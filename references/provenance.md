# Compatibility provenance

This portable skill adapts the Quick, Full, Turbo, and Turbo Append workflows from the locally maintained Neta Studio Source Import extension (package version 0.3.2). The original workflows used browser-generated attachments and Studio/Cohub sessions; this edition uses generic agent input tools, isolated local drafts, and one final export writer.

`studio-world-import-v1.schema.json` is preserved byte-for-byte from that source package. Deterministic semantic checks follow its section-to-type mapping and source-grounded, non-placeholder output requirements. The portable Python validator additionally applies the full JSON Schema rather than treating the old JavaScript semantic checker as a schema implementation.

This extraction was packaged on 2026-10-14. The profile is pinned to the bundled V1 schema. No live Neta import was performed as part of packaging. Future platform changes require a separately verified compatibility update, not an undocumented schema relaxation.

The short Bellweather story in `examples/source.md` and its illustrative payload are synthetic examples authored for this package. The example payload demonstrates fields and custom sections; it is not a complete Full-mode extraction or a required template for entity selection.
