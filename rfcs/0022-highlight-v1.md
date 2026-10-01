# RFC 0022 — payload profile `highlight/v1`

Status: draft · 2026-10-01 · comment period: two weeks

One mark the owner made in something they read: a passage highlighted in a book, a note written against
it, a bookmark dropped on a page. The line records what the reading app stored — the book, the passage,
the owner's words, where in the book and when — and never what it means: no theme, no tag, no "key
idea". A highlight is the one moment of reading the record can see; what the owner thought of the whole
book belongs in a `note/v1` line.

## Line

`kind` MUST be `highlight`. `tier` SHOULD be 2: a highlight shows what the owner read and what caught
them, and a note is their own words (SPEC §4 puts notes under tier 2). An adapter MAY let the owner
change it (`logbook add --tier`). `at` is when the mark was made (the store's creation date, UTC);
`end` is `null`. `tz` is the record's zone unless the store keeps one. `source` is the adapter:
`apple-books`, `kindle`, ….

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"highlight/v1"` | MUST | |
| `raw_id` | string | MUST | the store's own id for the mark (Books' annotation UUID, Kindle's annotation id). The `(source, raw_id)` dedupe key: re-importing the same store appends nothing |
| `type` | string | MUST | `highlight` (a passage marked, with or without a note) or `bookmark` (a place marked, no passage) |
| `title` | string | SHOULD | the book's title as the library spells it; absent when the store does not know the book |
| `author` | string | MAY | the author as the library spells it |
| `asset_id` | string | SHOULD | the library's id for the book (Books' asset id, an ASIN), so marks in one book can be grouped without the title |
| `quote` | string | `highlight` only | the passage, verbatim as the store kept it |
| `note` | string | MAY | the owner's words on the passage, verbatim |
| `location` | string | SHOULD | where in the book, as the source spells it: an EPUB CFI (`epubcfi(/6/14!/4/2/8,/1:0,/1:143)`), a Kindle location (`loc 1234`), a PDF page reference. Kept as text; never parsed |
| `page` | integer | MAY | the page, when the source gives one as a number |
| `modified_at` | RFC3339 UTC | MAY | when the mark was last edited, when later than `at` |
| `extra` | object | MAY | anything else the source keeps: Books' `style` (its colour index) and `underline`, Kindle's `color` |

## Rules

1. **One mark, one line.** Every highlight and every bookmark in the store is a line. A highlight that carries a note is still one line: the note is on the passage.
2. **A reading position is not a mark.** Books keeps where the owner last stopped as an annotation row of its own type; Kindle keeps a last-read location per book. Those are the app's state, not the owner's act, and are skipped and counted (`skipped_reading_position`).
3. **A deleted mark stays deleted.** A store that keeps tombstones for marks the owner removed (Books' `deleted` flag) gives no line for them; they are skipped and counted (`skipped_deleted`). A mark removed after an import is not retracted by the adapter; the owner can (RFC 0003).
4. **The book is looked up, not guessed.** `title` and `author` come from the app's own library store (Books' `BKLibrary`, Kindle's book data) by the mark's asset id. When the library does not have the book — a sample, a deleted book, a PDF the owner dropped in — the line carries `asset_id` and no title, counted (`no_title`). An adapter never derives a title from the quote or the file name.
5. **Verbatim.** `quote` and `note` are the store's text with surrounding whitespace trimmed and nothing else changed: no truncation, no normalisation of quotes or dashes.
6. **Timestamps are the source's.** `at` is the mark's creation date converted to UTC; a mark whose date is missing or a placeholder (before 1900) is skipped and counted (`skipped_no_date`, `skipped_placeholder_date`).

## Example (synthetic)

```json
{"at":"2026-03-02T20:14:07Z","end":null,"tz":"Europe/Oslo","source":"apple-books","kind":"highlight","tier":2,
 "payload":{"schema":"highlight/v1","raw_id":"6F1A2B3C-0000-4000-8000-000000000001","type":"highlight",
 "title":"The Long Ships","author":"Frans G. Bengtsson","asset_id":"A1B2C3D4E5F60718293A4B5C6D7E8F90",
 "quote":"They sailed west until the coast was a line and then was nothing.",
 "note":"the moment the book turns","location":"epubcfi(/6/14!/4/2/8,/1:0,/1:66)",
 "extra":{"style":3,"underline":false}}}
```

## JSON Schema

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"highlight/v1","type":"object",
 "required":["schema","raw_id","type"],
 "properties":{
  "schema":{"const":"highlight/v1"},
  "raw_id":{"type":"string","minLength":1},
  "type":{"enum":["highlight","bookmark"]},
  "title":{"type":"string","minLength":1},
  "author":{"type":"string","minLength":1},
  "asset_id":{"type":"string","minLength":1},
  "quote":{"type":"string","minLength":1},
  "note":{"type":"string","minLength":1},
  "location":{"type":"string","minLength":1},
  "page":{"type":"integer","minimum":0},
  "modified_at":{"type":"string","format":"date-time"},
  "extra":{"type":"object"}},
 "if":{"properties":{"type":{"const":"highlight"}}},"then":{"required":["quote"]},
 "additionalProperties":false}
```

## Notes

- **Why a profile and not `note/v1`.** A note is the owner's text on a day; a highlight is a pointer into someone else's text, with the passage carried along so the line stands on its own when the book is gone. Readers show them differently: a note as its first line, a highlight as a quotation with the book's name.
- **Why the quote is in the line and not an attachment.** A passage is a few hundred characters, the size of a message; SPEC §1.1 is for content too large or binary to inline. A highlight of a whole chapter would be unusual; an adapter MAY move a quote over a few kilobytes into the store and leave the reference under `quote_content`, but none does yet.
- **Why titles and not resolution.** A book is not a person or a place; it is named by its title and author as the library spells them, and two libraries that spell them differently are two spellings, which a reader can group by `asset_id` within a library. No entity is minted (RFC 0006 is for people).
- **Sources.** `apple-books` reads an iPhone's or Mac's `AEAnnotation*.sqlite` with the `BKLibrary*.sqlite` beside it. A Kindle adapter is wanted: the phone app's annotation store (`com.amazon.Lassen`, `Library/KSDK/cid/annotation.db`) holds the marks only when the app has synced them down, and a `My Clippings.txt` or a Kindle notebook export is the other way in.
