# Neta-compatible export profile

The bundled `studio-world-import-v1.schema.json` is the existing Studio source-import V1 schema, copied unchanged; see [provenance.md](provenance.md). It is a pinned export contract, not a live platform capability probe. All four modes emit the same shape. Runtime IDs, timestamps, materials paths, relation objects, extraction evidence, and agent state are excluded.

## World fields

`worldConfig` requires `name`, `overview`, `language`, `creationMode`, and `sections`.

- `name`: 1–200 characters; `overview`: meaningful, source-grounded text.
- `language`: exactly `zh` or `en`; match reader-facing language. Other input languages can be translated after selecting one of these outputs.
- `creationMode`: exactly `book-import`, including when the supplied scope is an excerpt or worldbuilding pack. Actual scope is recorded in the separate report.
- `sections`: 1–50 ordered `{key, label}` entries. Key: 1–50 characters, label: 1–80.
- Optional fields: `genre`, `tone`, `era`, `rules` (string array), `prologue`, `coreConflict`, `visualStyle`, `sectionBodies`, `sectionTitles`, `backgroundPresetId`, `worldCover`. See schema for exact types and lengths. Omit fields the source or user does not support. Covers and preset IDs need real supplied/verified values, not generated URLs or guessed IDs.

`sectionBodies` and `sectionTitles`, when supplied, refer to declared section keys. No empty sections, duplicate section keys, or multiple sections resolving to the same Atom type.

## Atom fields

Each Atom requires exactly `type`, `name`, `description`, `content`, and `tags`:

- `type`: open non-empty string, up to 50 characters. Use one stable singular machine key per category.
- `name`: concise canonical name, up to 100 characters. Merge aliases, except genuinely different namesakes distinguished by source-supported context.
- `description`: specific non-empty summary, up to 500 characters.
- `content`: non-empty array of `{key, value}` strings. Keys are readable section names; values add concrete information. Keys are unique within an Atom; content values have no schema maximum length.
- `tags`: array of distinct non-empty strings; `[]` is valid when no labels help.

Built-in section mappings:

| Section key | Atom type |
| --- | --- |
| `characters` or `character` | `character` |
| `locations` or `location` | `location` |
| `events` or `event` | `event` |
| `secrets` or `secret` | `secret` |
| `perspectives` or `perspective` | `perspective` |
| `lore` | `lore` |

For custom categories the section key equals the type exactly: section `{key: "faction", label: "Factions"}` matches Atom `type: "faction"`. Do not assume plural English keys such as `factions` singularize automatically. Display labels may be translated or plural. Types express meaning, not a desired card appearance.

## Separate evidence

Maintain an entity ledger outside the payload. For each canonical entity keep its aliases, type, source file/hash, normalized line ranges or original page locations, supported facts, chronology, unresolved conflicts, and reasons for material omissions. This is a working record, not another Neta import format. Do not put it into Atom tags/content or add extra root keys.

## What validation proves

`scripts/validate_world.py` checks the pinned schema and deterministic consistency rules. It reads without modifying the input and exits nonzero on errors. Structural success does not prove completeness, factual accuracy, good prose, absence of semantic duplicates, or live Neta acceptance. Review those separately and describe the actual verification performed.

When a live Neta destination rejects the pinned profile, preserve the export and inspect the destination's actual contract. Report the incompatibility; do not quietly delete rejected fields or call an empty world successful.
