"""Reading an untrusted CSV file safely (CRM.md section 13).

An uploaded CSV is the least trustworthy input the CRM accepts. It arrives from a
spreadsheet somebody else built, it is full of personal data, and the operator uploading it
usually cannot say what is inside. This module is the only place a file is turned into
rows, and it is deliberately unfriendly:

* every dimension is bounded — bytes, rows, columns, cell length, and parsing time;
* an archive, a compressed file, a spreadsheet binary, or a PDF is refused by inspection
  of its leading bytes, not by trusting the filename;
* a NUL byte anywhere means the file is not text and is refused;
* only UTF-8 is accepted, with or without a byte-order mark, and anything else is refused
  with an instruction rather than being guessed at;
* quoting is parsed strictly, so a malformed file fails loudly instead of silently
  producing shifted columns;
* headers are normalized, and two headers that normalize to the same field are refused as
  ambiguous rather than resolved by picking one.

What this module never does: evaluate a formula, resolve a path, fetch a URL, run SQL, or
interpret markup. A cell is text. The one transformation applied anywhere is normalization
of the *header* row, and header names are matched against a fixed allowlist.
"""

from __future__ import annotations

import csv
import io
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import NoReturn

from app.services.errors import ValidationError

# --- Bounds ------------------------------------------------------------------
#
# Sized for the job: a launch-scale customer list, not a data warehouse. Every one of
# these is a refusal, never a truncation — a truncated import silently loses people.

#: 2 MiB. A 5,000-row customer CSV is roughly 500 kB.
MAX_FILE_BYTES = 2 * 1024 * 1024
#: Data rows, excluding the header.
MAX_ROWS = 5_000
#: Columns in the header row. A wider file is a spreadsheet, not a customer list.
MAX_COLUMNS = 60
#: Characters in one cell. Longer than any name, email, or address the model stores.
MAX_CELL_CHARS = 1_000
#: Wall-clock budget for parsing. A pathological file that parses slowly is refused
#: rather than allowed to occupy a worker.
MAX_PARSE_SECONDS = 10.0

#: Leading byte sequences that mean "this is not a CSV". Checked against the content,
#: never against the filename, because a filename is chosen by whoever uploaded it.
BINARY_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "a ZIP archive or an .xlsx workbook"),
    (b"PK\x05\x06", "an empty ZIP archive"),
    (b"PK\x07\x08", "a spanned ZIP archive"),
    (b"\x1f\x8b", "a gzip-compressed file"),
    (b"BZh", "a bzip2-compressed file"),
    (b"\xfd7zXZ\x00", "an xz-compressed file"),
    (b"7z\xbc\xaf\x27\x1c", "a 7-Zip archive"),
    (b"Rar!\x1a\x07", "a RAR archive"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "a legacy .xls workbook"),
    (b"%PDF-", "a PDF"),
    (b"\x89PNG\r\n\x1a\n", "a PNG image"),
    (b"\xff\xd8\xff", "a JPEG image"),
    (b"SQLite format 3\x00", "a SQLite database"),
)

#: Byte-order marks for encodings that are *not* accepted. Detected so the operator gets
#: "save it as UTF-8" rather than a decode error full of hex.
REJECTED_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "UTF-32 (little-endian)"),
    (b"\x00\x00\xfe\xff", "UTF-32 (big-endian)"),
    (b"\xff\xfe", "UTF-16 (little-endian)"),
    (b"\xfe\xff", "UTF-16 (big-endian)"),
)

UTF8_BOM_BYTES = b"\xef\xbb\xbf"

_WHITESPACE = re.compile(r"\s+")
_NON_KEY = re.compile(r"[^a-z0-9]+")


@dataclass
class ParsedRow:
    """One data row, as text. Nothing here has been interpreted."""

    #: 1-based row number as the operator sees it in their spreadsheet: the header is row
    #: 1, so the first data row is row 2. Getting this wrong makes every error message
    #: point at the wrong line.
    row_number: int
    values: dict[str, str]


@dataclass
class ParsedFile:
    headers: list[str]
    #: Original header text, in file order, so the interface can show what was mapped.
    raw_headers: list[str]
    rows: list[ParsedRow]
    #: Headers present in the file that no known field claims. Reported, not silently
    #: dropped, so the operator can see what was ignored.
    unmapped_headers: list[str] = field(default_factory=list)


def normalize_header(value: str) -> str:
    """Fold a header into a comparison key.

    ``"Full Name"``, ``"full_name"``, ``" FULL  NAME "`` and ``"Full-Name"`` are the same
    column. Accents are folded too, so a header typed with Vietnamese diacritics still
    matches. This is the *only* normalization performed anywhere in the import: cell values
    are never rewritten.
    """
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _WHITESPACE.sub(" ", text).strip().lower()
    text = _NON_KEY.sub("_", text)
    return text.strip("_")


def _reject(message: str, *, field_name: str = "file") -> NoReturn:
    """Always raises. Declared ``NoReturn`` so callers need no unreachable guard."""
    raise ValidationError(message, field=field_name)


def inspect_bytes(content: bytes, *, max_bytes: int = MAX_FILE_BYTES) -> str:
    """Validate the raw upload and decode it. Refuses rather than guesses."""
    if not content:
        _reject("The file is empty.")

    if len(content) > max_bytes:
        _reject(
            f"The file is {len(content) // 1024} kB, which is larger than the "
            f"{max_bytes // 1024} kB limit. Split it into smaller files and import each."
        )

    for signature, description in BINARY_SIGNATURES:
        if content.startswith(signature):
            _reject(
                f"This looks like {description}, not a CSV file. Export or save the "
                "sheet as CSV UTF-8 and upload that."
            )

    for bom, description in REJECTED_BOMS:
        if content.startswith(bom):
            _reject(
                f"This file is encoded as {description}. Save it as CSV UTF-8 and upload it again."
            )

    if b"\x00" in content:
        # A NUL means the file is binary, or that a UTF-16 file lost its byte-order mark.
        # Either way it is not the CSV it claims to be.
        _reject(
            "The file contains NUL bytes, so it is not a plain-text CSV. Save it as "
            "CSV UTF-8 and upload it again."
        )

    if content.startswith(UTF8_BOM_BYTES):
        content = content[len(UTF8_BOM_BYTES) :]

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "The file is not valid UTF-8 text, so some characters could not be read. "
            "Save it as CSV UTF-8 — that is the only encoding that reliably preserves "
            "Vietnamese names — and upload it again.",
            field="file",
        ) from exc


def parse(
    content: bytes,
    *,
    known_fields: dict[str, str],
    required_headers: tuple[str, ...] = (),
    max_bytes: int = MAX_FILE_BYTES,
    max_rows: int = MAX_ROWS,
    max_columns: int = MAX_COLUMNS,
    max_cell_chars: int = MAX_CELL_CHARS,
    max_seconds: float = MAX_PARSE_SECONDS,
) -> ParsedFile:
    """Parse an uploaded CSV into rows of text.

    ``known_fields`` maps a normalized header key to the canonical field name. A header
    the mapping does not know is reported in ``unmapped_headers`` and its values are
    dropped: an import must only ever write the documented fields, and accepting an
    unknown column would be the mechanism by which it stopped doing that.
    """
    started = time.monotonic()
    text = inspect_bytes(content, max_bytes=max_bytes)

    # ``strict=True`` makes a malformed quote an exception instead of a silent
    # re-interpretation that shifts every subsequent column.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)

    try:
        raw_headers = next(reader)
    except StopIteration:
        _reject("The file has no header row.")
    except csv.Error as exc:
        raise ValidationError(
            f"The header row could not be read: {_describe_csv_error(exc)}", field="file"
        ) from exc

    if len(raw_headers) > max_columns:
        _reject(
            f"The file has {len(raw_headers)} columns, more than the {max_columns} "
            "allowed. Remove the columns the import does not use and try again."
        )

    headers, unmapped = _map_headers(raw_headers, known_fields)

    missing = [name for name in required_headers if name not in headers]
    if missing:
        _reject(
            "The file is missing required column(s): "
            + ", ".join(sorted(missing))
            + ". Download the template to see the expected header row."
        )

    rows: list[ParsedRow] = []
    row_number = 1  # the header occupies row 1
    while True:
        if time.monotonic() - started > max_seconds:
            _reject(
                "The file took too long to read and was stopped. Split it into smaller "
                "files and import each."
            )
        try:
            raw = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise ValidationError(
                f"Row {row_number + 1} could not be read: {_describe_csv_error(exc)}",
                field="file",
            ) from exc

        row_number += 1
        if not any(cell.strip() for cell in raw):
            # A blank line is skipped rather than rejected: spreadsheets add trailing
            # ones, and refusing the file for that would be unhelpful.
            continue

        if len(rows) >= max_rows:
            _reject(
                f"The file has more than {max_rows} rows. Split it into smaller files "
                "and import each. Nothing has been imported."
            )

        if len(raw) > len(raw_headers):
            _reject(
                f"Row {row_number} has {len(raw)} values but the header has "
                f"{len(raw_headers)} columns. A stray comma or an unclosed quote is the "
                "usual cause."
            )

        values: dict[str, str] = {}
        for index, canonical in enumerate(headers):
            if canonical is None:
                continue
            cell = raw[index] if index < len(raw) else ""
            if len(cell) > max_cell_chars:
                _reject(
                    f"Row {row_number}, column '{raw_headers[index]}' holds "
                    f"{len(cell)} characters, more than the {max_cell_chars} allowed."
                )
            values[canonical] = cell
        rows.append(ParsedRow(row_number=row_number, values=values))

    return ParsedFile(
        headers=[name for name in headers if name is not None],
        raw_headers=list(raw_headers),
        rows=rows,
        unmapped_headers=unmapped,
    )


def _map_headers(
    raw_headers: list[str], known_fields: dict[str, str]
) -> tuple[list[str | None], list[str]]:
    """Map each file column to a canonical field, or to nothing.

    Two headers that normalize to the same field are refused. Picking one and ignoring the
    other would mean the operator's file said one thing and the import did another, and
    which column won would depend on column order.
    """
    mapped: list[str | None] = []
    seen: dict[str, str] = {}
    unmapped: list[str] = []
    blank_columns = 0

    for raw in raw_headers:
        key = normalize_header(raw)
        if not key:
            blank_columns += 1
            mapped.append(None)
            continue
        canonical = known_fields.get(key)
        if canonical is None:
            unmapped.append(raw)
            mapped.append(None)
            continue
        if canonical in seen:
            _reject(
                f"Columns '{seen[canonical]}' and '{raw}' both map to the same field "
                f"('{canonical}'). Remove or rename one of them so the mapping is "
                "unambiguous.",
                field_name="headers",
            )
        seen[canonical] = raw
        mapped.append(canonical)

    if not seen:
        _reject(
            "None of the columns in this file match a field the import understands. "
            "Download the template and compare the header row.",
            field_name="headers",
        )
    return mapped, unmapped


def _describe_csv_error(exc: csv.Error) -> str:
    """A CSV parse failure, said in words an operator can act on.

    Python's own wording is accurate and unhelpful: ``"',' expected after '\\"'"`` and
    ``"unexpected end of data"`` describe the parser's state, not what is wrong with the
    spreadsheet. These are the two failures that actually occur, and both have the same
    cause and the same fix.
    """
    message = str(exc).lower()
    if "end of data" in message:
        return (
            "a quotation mark is opened and never closed, so the file ends in the middle "
            'of a value. Every opening " needs a matching closing ".'
        )
    if "quote" in message or '"' in message:
        return (
            "there is an unclosed or misplaced quotation mark. A value containing a "
            'comma must be wrapped in quotes, and any quote inside it doubled ("").'
        )
    if "newline" in message:
        return "a value contains a line break that is not inside quotation marks."
    return "the row is not valid CSV. Check the quotation marks and commas."
