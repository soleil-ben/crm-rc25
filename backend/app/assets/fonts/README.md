# Vendored label font

`Roboto-Regular.ttf` and `Roboto-Bold.ttf` are embedded into every generated 4 × 6 label
PDF so Vietnamese diacritics render correctly. This is a hard requirement: ReportLab's
bundled Bitstream Vera face is missing 14 of the codepoints in a name like
*Nguyễn Thị Bích Hạnh Đặng*, and a PDF font that lacks a glyph prints a blank box.

| Item | Value |
|---|---|
| Family | Roboto |
| Version | 2.138 (2017) |
| Designer | Christian Robertson / Google |
| License | **Apache License 2.0** — full text in `LICENSE-Roboto-Apache-2.0.txt` |
| Upstream source | <https://github.com/google/roboto> |
| Obtained from | PyPI package [`font-roboto` 0.0.1](https://pypi.org/project/font-roboto/), which repackages the Google release (<https://github.com/pimoroni/fonts-python>) |
| `Roboto-Regular.ttf` SHA-256 | `797e35f7f5d6020a5c6ea13b42ecd668bcfb3bbc4baa0e74773527e5b6cb3174` |
| `Roboto-Bold.ttf` SHA-256 | `36f3709dea3e3ce3c6aedc058079e55980825f898f1e901d091c73c40de8bab1` |

Apache 2.0 permits redistribution and embedding, including in a commercial product, so
committing the files here and embedding them in generated PDFs is allowed. The license
text travels with them.

## Coverage verified

Both faces cover the complete Vietnamese repertoire that the label needs:
`Đ`/`đ`, `Ơ`/`ơ`, `Ư`/`ư`, and the whole Latin Extended Additional block
`U+1EA0`–`U+1EF9`. `backend/tests/test_labels.py` asserts this so a future font swap
cannot silently regress it.

## Why the font is vendored rather than installed

Committing the exact bytes means label output is deterministic, reviewable, and does not
depend on a small third-party PyPI package staying available. `docs/DECISIONS.md`
DEC-0033 records the trade-off.
