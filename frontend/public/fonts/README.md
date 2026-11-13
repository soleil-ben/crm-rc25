# Self-hosted web fonts

These files are served from this application's own origin. Nothing in the portal or on
the public tracking page requests a font, a stylesheet, or any other resource from a
third party.

## Why they are here

A tracking reference is privacy-sensitive (`CRM.md` section 10, `Design.md` section 14).
A font requested from `fonts.gstatic.com` tells that server, from the request alone, that
a browser at a given address opened a Solaris tracking page. That is a small disclosure,
and it is not one a customer checking on a parcel agreed to.

Both shells are served from one HTML entry, so a `<link>` in `index.html` loads on every
route. Route-scoped prevention would have meant splitting the build purely to keep one
external request, so the external requests were removed globally instead (DEC-0046). The
staff portal gets the same benefit.

## Provenance

Downloaded on 2026-09-09 from the Google Fonts CSS2 API, which is the same source the
previous `<link rel="stylesheet">` used:

```text
https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Poppins:wght@500;600&display=swap
```

Requested with a current Chrome user agent so the API returned `woff2` rather than the
`truetype` fallback it serves to unknown clients. Only the `latin`, `latin-ext`, and
`vietnamese` subsets were kept; the Cyrillic, Greek, and Devanagari subsets are not used
by this product.

Every `unicode-range` in `src/styles/fonts.css` is copied verbatim from that CSS, so a
browser downloads the Vietnamese face only when a page actually contains a Vietnamese
glyph.

## Files

| File | Bytes | SHA-256 |
|---|---:|---|
| `inter-latin-ext.woff2` | 85,068 | `34b9c504cab7a73e37b746343a449132e56cf7b5481af2cb81dc74dcff25c956` |
| `inter-latin.woff2` | 48,256 | `3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62` |
| `inter-vietnamese.woff2` | 10,252 | `5c66f9e07e90c6d4ac4922cc68d60de26c17b1858e677fb5e603fce3952b3ff2` |
| `poppins-500-latin-ext.woff2` | 5,484 | `af5fda16a19169e029a132374616728e1bf326d90bef5a552395c5053e21cd0f` |
| `poppins-500-latin.woff2` | 7,748 | `cd36de204aca2d5fa263a731f7c20009b5e3d754ba1f1e03c33e93a48f3e7446` |
| `poppins-600-latin-ext.woff2` | 5,524 | `bb1f2d582e7fba586ab70c91ef062d3becaf78b887654953863521b73665d171` |
| `poppins-600-latin.woff2` | 8,000 | `f4e80d9dfd374d02989b87a27b5ed4cb78fbb177c27f1478e9a8b0afb7513149` |

180 KB in total, and a browser fetches only the subsets a page needs — typically the two
Latin faces, plus the Vietnamese one when the page is in Vietnamese.

**Inter is a variable font.** The API returned the *same file* for weights 400, 500, and
600 (identical SHA-256), so one file per subset is stored and the `@font-face` rule
declares `font-weight: 100 900` against it.

**Poppins is static**, so 500 and 600 are separate files.

## Licence

Both families are under the **SIL Open Font License 1.1**, which permits redistribution,
modification, and web embedding, including as part of a larger work. The full text is in
`OFL.txt` beside these files.

- Inter — Copyright the Inter Project Authors (<https://github.com/rsms/inter>)
- Poppins — Copyright the Indian Type Foundry and Jonny Pinhorn

The OFL's only substantive conditions here are that the licence travels with the files
(it does, in `OFL.txt`) and that a derived font not be sold on its own or use a reserved
font name. Neither applies: these are the unmodified released binaries.

## Poppins has no Vietnamese subset

Google Fonts serves Poppins in `devanagari`, `latin`, and `latin-ext` only. Vietnamese
precomposed characters live in `U+1EA0–1EF9`, which is the `vietnamese` subset, so a
Poppins heading in Vietnamese renders its accented letters from whatever face the browser
falls back to — producing a heading in two typefaces.

The public shell therefore sets **headings in Inter**, which covers Vietnamese fully
(DEC-0047). The staff portal is English-first and keeps Poppins headings unchanged.

`Design.md` section 3 calls Poppins and Inter "a provisional starting point ... verify
supplied assets before finalizing", so this is a reversible interim choice, not a
rejection of the brand direction. It is listed for business confirmation alongside the
logo.

## Replacing these

If the business confirms different brand faces:

1. Put the new `woff2` files here and update this table with their sizes and digests.
2. Update the `@font-face` blocks in `src/styles/fonts.css`.
3. Check the new face covers `U+1EA0–1EF9`. If it does not, keep a covering face ahead of
   it in the stack for the public shell, or the Vietnamese page will render in two fonts.
4. Confirm its licence permits web embedding, and replace `OFL.txt`.
5. Re-run `npm run build` and check the public page at 375 px in both languages.
