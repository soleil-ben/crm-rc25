"""Zip-level guard for an intake workbook (Phase 13H review, DEC-0214).

Two jobs, both done on the ``.xlsx`` container **before** openpyxl, the importer or any
store sees the file:

1. **Refuse an archive bomb.** More than ``MAX_MEMBERS`` members, more than
   ``MAX_UNCOMPRESSED`` bytes uncompressed in total, an overall compression ratio above
   ``MAX_RATIO``, or one large member (over 1 MiB) compressed more than ``MAX_RATIO`` times:
   ``WorkbookRefused``. Sizes are read from the central directory; nothing is inflated.
2. **Strip the vendor's staff directory without reading it.** A worksheet whose name starts
   with ``DS SDT`` (``kango_workbook.NEVER_READ_SHEET_PREFIXES``) is removed at the zip level.
   Only ``xl/workbook.xml`` (sheet names and relationship ids), ``xl/_rels/workbook.xml.rels``,
   ``[Content_Types].xml``, the dropped sheets' relationship lists (to drop their comments,
   drawings and tables unread), the shared-string table and the **kept** sheets are read.
   The dropped sheet part is never read. Its ``<sheet>`` element, relationship, content-type
   override, sheet-scoped and sheet-referencing ``definedName`` entries and the calculation
   chain are removed; a shared string that no kept sheet uses is blanked in place (indexes
   are unchanged, so no kept cell moves). The result is written with the original members'
   timestamps, so the same input always gives the same bytes and the same SHA-256.

A workbook without such a sheet is returned unchanged, byte for byte.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from html import unescape
from xml.etree import ElementTree as ET

from app.pricing.kango_workbook import NEVER_READ_SHEET_PREFIXES

MAX_MEMBERS = 2000
MAX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_RATIO = 100
_LARGE_MEMBER = 1024 * 1024

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

_DTD = re.compile(rb"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_SHARED_CELL = re.compile(rb'<c\b[^>]*?\bt="s"[^>]*>\s*<v>\s*(\d+)\s*</v>')
_SI = re.compile(r"<si\b[^>]*/>|<si\b[^>]*>.*?</si>", re.DOTALL)
_DEFINED_NAME = re.compile(r"<definedName\b([^>]*)>(.*?)</definedName>", re.DOTALL)


class WorkbookRefused(ValueError):
    """The container is outside the safe bounds (an archive bomb, a DTD)."""


class WorkbookUnreadable(ValueError):
    """The bytes are not a readable ``.xlsx`` container."""


def _check_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise WorkbookRefused(f"the workbook has more than {MAX_MEMBERS} parts")
    total = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos)
    if total > MAX_UNCOMPRESSED:
        raise WorkbookRefused(
            f"the workbook expands to more than {MAX_UNCOMPRESSED // (1024 * 1024)} MB"
        )
    if packed and total / packed > MAX_RATIO:
        raise WorkbookRefused("the workbook is compressed implausibly well (archive bomb?)")
    for info in infos:
        if info.file_size > _LARGE_MEMBER and info.file_size > MAX_RATIO * max(
            info.compress_size, 1
        ):
            raise WorkbookRefused("a workbook part is compressed implausibly well (archive bomb?)")


def _xml(archive: zipfile.ZipFile, name: str) -> bytes:
    data = archive.read(name)
    if _DTD.search(data):
        raise WorkbookRefused("the workbook declares a document type; refused")
    return data


def _parse(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise WorkbookUnreadable("a workbook part is not well-formed XML") from error


def _resolve(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(base_dir, target))


def _rels_name(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _remove_relationships(text: str, ids: set[str]) -> str:
    for rid in ids:
        text = re.sub(rf'<Relationship\b[^>]*\bId="{re.escape(rid)}"[^>]*/>', "", text)
    return text


def _blank_unused_strings(
    archive: zipfile.ZipFile, sst_name: str, kept_parts: list[str], names: set[str]
) -> bytes:
    """Blank (in place, keeping every index) each shared string no kept sheet uses."""
    used: set[int] = set()
    for part in kept_parts:
        if part in names:
            used.update(int(m.group(1)) for m in _SHARED_CELL.finditer(archive.read(part)))
    position = iter(range(10**9))

    def keep_or_blank(match: re.Match) -> str:
        return match.group(0) if next(position) in used else "<si><t></t></si>"

    return _SI.sub(keep_or_blank, _xml(archive, sst_name).decode("utf-8")).encode("utf-8")


def check_and_strip(content: bytes) -> tuple[bytes, list[str]]:
    """Guard the container and drop any staff-directory sheet. Returns (bytes, dropped names)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, ValueError, OSError) as error:
        raise WorkbookUnreadable("the attachment is not a readable .xlsx workbook") from error
    with archive:
        _check_archive(archive)
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise WorkbookUnreadable("the attachment has no workbook part")
        workbook_xml = _xml(archive, "xl/workbook.xml")
        root = _parse(workbook_xml)
        sheets = [
            (el.get("name") or "", el.get(f"{{{NS_R}}}id") or "")
            for el in root.iter(f"{{{NS_MAIN}}}sheet")
        ]
        drop_index = [
            i
            for i, (name, _) in enumerate(sheets)
            if name.upper().startswith(NEVER_READ_SHEET_PREFIXES)
        ]
        if not drop_index:
            return content, []
        drop_names = [sheets[i][0] for i in drop_index]
        drop_rids = {sheets[i][1] for i in drop_index}

        rels_xml = _xml(archive, "xl/_rels/workbook.xml.rels")
        relationships = {
            rel.get("Id"): (rel.get("Target") or "", rel.get("Type") or "")
            for rel in _parse(rels_xml).iter(f"{{{NS_PKG}}}Relationship")
        }
        drop_parts = {
            _resolve("xl", relationships[rid][0]) for rid in drop_rids if rid in relationships
        }
        # The dropped sheets' own parts (comments, drawings, tables), by their rels list only.
        for part in list(drop_parts):
            rels_name = _rels_name(part)
            if rels_name in names:
                drop_parts.add(rels_name)
                for rel in _parse(_xml(archive, rels_name)).iter(f"{{{NS_PKG}}}Relationship"):
                    if rel.get("TargetMode") == "External":
                        continue
                    target = _resolve(posixpath.dirname(part), rel.get("Target") or "")
                    if target in names and not target.startswith("xl/media/"):
                        drop_parts.add(target)
        remove_rids = set(drop_rids)
        # The calculation chain names cells by sheet index; Excel rebuilds it.
        for rid, (target, kind) in relationships.items():
            if kind.endswith("/calcChain"):
                remove_rids.add(rid)
                drop_parts.add(_resolve("xl", target))

        replaced: dict[str, bytes] = {}

        # workbook.xml: the <sheet> elements, definedNames, the active and first tab.
        text = workbook_xml.decode("utf-8")
        for rid in drop_rids:
            text = re.sub(rf'<(?:\w+:)?sheet\b[^>]*?\b\w+:id="{re.escape(rid)}"[^>]*/>', "", text)

        def defined_name(match: re.Match) -> str:
            attrs, body = match.group(1), match.group(2)
            local = re.search(r'localSheetId="(\d+)"', attrs)
            if local:
                index = int(local.group(1))
                if index in drop_index:
                    return ""
                shifted = index - sum(1 for d in drop_index if d < index)
                attrs = attrs.replace(local.group(0), f'localSheetId="{shifted}"')
            reference = unescape(body)
            if any(f"'{n}'!" in reference or f"{n}!" in reference for n in drop_names):
                return ""
            return f"<definedName{attrs}>{body}</definedName>"

        text = _DEFINED_NAME.sub(defined_name, text)
        text = re.sub(r'\b(activeTab|firstSheet)="\d+"', r'\1="0"', text)
        replaced["xl/workbook.xml"] = text.encode("utf-8")
        replaced["xl/_rels/workbook.xml.rels"] = _remove_relationships(
            rels_xml.decode("utf-8"), remove_rids
        ).encode("utf-8")

        # [Content_Types].xml: the dropped parts' overrides.
        if "[Content_Types].xml" in names:
            types = _xml(archive, "[Content_Types].xml").decode("utf-8")
            for part in drop_parts:
                types = re.sub(
                    rf'<Override\b[^>]*\bPartName="/{re.escape(part)}"[^>]*/>', "", types
                )
            replaced["[Content_Types].xml"] = types.encode("utf-8")

        # Shared strings: blank every entry no kept sheet uses (the dropped sheets' text).
        kept_parts = [
            _resolve("xl", relationships[rid][0])
            for _, rid in sheets
            if rid not in drop_rids and rid in relationships
        ]
        sst_names = [
            _resolve("xl", target)
            for target, kind in relationships.values()
            if kind.endswith("/sharedStrings")
        ]
        for sst_name in sst_names:
            if sst_name in names:
                replaced[sst_name] = _blank_unused_strings(archive, sst_name, kept_parts, names)

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for info in archive.infolist():
                if info.filename in drop_parts:
                    continue  # never read
                data = replaced.get(info.filename)
                if data is None:
                    data = archive.read(info.filename)
                member = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                member.compress_type = zipfile.ZIP_DEFLATED
                member.external_attr = info.external_attr
                target_zip.writestr(member, data)
        return out.getvalue(), drop_names
