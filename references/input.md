# Input preparation

## Local files

Run `python3 "$SKILL_DIR/scripts/prepare_source.py" --help` for current flags. The helper accepts explicit paths in argument order and writes a new directory with normalized `source.txt` and `source-manifest.json`. Its parent directory must already exist: for `--output-dir ./run/work/source`, first create `./run/work`, but not `source` itself. File hashes identify original bytes; line ranges point into normalized text. Do not edit the normalized source after recording its hash.

Supported inputs:

- TXT / Markdown: preserve text order, decode strictly. UTF-8 and BOM-marked Unicode are handled; supply a known legacy encoding explicitly. Do not guess a broken encoding or insert replacement characters.
- HTML: extract text with the helper; inspect navigation, layout, and meaningful images before deciding the result covers the intended source.
- DOCX: preserve document paragraph/table order. Text-only extraction does not prove images, embedded objects, notes, tracked changes, or complex layouts were read; consult the manifest and inspect the original when those carry meaning.
- EPUB: read the package's spine order, not filename order. Missing, encrypted, corrupt, or unreadable chapters fail. Image-only narrative requires another extraction path such as OCR. Do not skip failed spine entries.
- Text PDF: the helper uses an installed `pdftotext` on a POSIX system (macOS/Linux). On other systems, use the host's PDF tool and preserve its extracted text and page evidence. Check page order, columns, tables, and extraction gaps. OCR is required for scanned or mixed unreadable pages; a text-layer conversion alone does not establish complete reading.

For folders or ZIP collections, inventory first and build an explicit ordered file list. Use an index/TOC or the user's order; a lexical sort that places chapter 10 before chapter 2 is not source order. Resolve ambiguity before extraction. Do not blindly recurse into unrelated files or execute archive contents. The helper processes document ZIP containers (EPUB/DOCX), not arbitrary chapter ZIP archives.

```bash
python3 "$SKILL_DIR/scripts/prepare_source.py" chapter-01.md chapter-02.md --output-dir ./book-source
```

Multiple inputs may be chapters of one book or complementary material for one world. Record that distinction. Duplicate editions, translations, and contradictory reference packs require explicit scope and precedence, not accidental merging.

The helper has explicit resource limits: 64 MiB per input, 32 MiB combined UTF-8 text, and 128 MiB expanded ZIP contents. It fails instead of truncating. Larger works need an explicitly partitioned preparation plan whose manifest still accounts for every part; splitting preparation does not reduce the declared reading scope.

## Pasted text and tool-provided attachments

Save the exact supplied text as a UTF-8 local source, label its origin and scope honestly, then run the helper. When an attachment tool exposes only an excerpt, report that scope; retrieve the full attachment if the user requested complete-book processing. Tool output truncation is a missing-source condition, not the end of the book.

## URLs and other formats

Use the host's authorized browsing/document tools to fetch user-selected URLs or read other formats. This skill does not ship a network downloader, browser integration, login flow, or universal binary converter. Preserve an inspectable local copy and provenance: URL/document identifier, retrieval time, converter/tool, page/chapter coverage, and extraction limitations. Normalize the resulting text with the helper and keep the acquisition record beside its manifest. Never substitute search snippets for the actual linked work or claim access to a paywalled/unreadable page.

For scanned PDF, images, audio, or video, use the host's appropriate OCR/transcription tools if available and suitable for the request. Retain page/time locations and confidence issues outside the world payload. Inspect representative renderings and all extraction anomalies; no tool availability means an explicit unsupported-input result, not fabricated text. Full-book completeness requires all narrative-bearing pages or segments, not just a sample.

## Extraction review

Before reading for entities, check the manifest, beginning/end, chapter transitions, source order, and anomalies. Verify that meaningful footnotes, captions, tables, equations, and diagram-dependent facts survived if the work relies on them. Disclose text-only omissions. An empty page may be legitimately blank, but confirm against the original; never classify unexamined extraction gaps as harmless.

If a source is malformed, preserve the original and diagnose it. Any supported normalization must be narrow, documented in a new derived file, and revalidated; do not silently switch parsers to get plausible text. If only part of the source is usable, get agreement to a narrower scope before calling that run complete.
