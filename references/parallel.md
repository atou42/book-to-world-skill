# Portable Turbo workflows

Turbo requires the current host's authorized parallel agent capability. No platform-specific tool names, models, accounts, or native World writes are required. If parallel agents are unavailable, say so and ask whether to use Full; do not silently relabel sequential processing as Turbo. A user selecting Turbo authorizes this local decomposition workflow subject to the host's normal execution permissions, not creation of paid cloud sessions or external messages.

## Partition and ownership

After input preparation, record a plan with source hash, mode, output language, declared scope, and ordered inclusive line ranges covering the whole source exactly once. Prefer chapter/paragraph boundaries. Use up to four simultaneous workers by default, bounded by host capacity and source size. More ranges may be queued when the book exceeds worker context; never drop remaining ranges to fit a fixed worker count. Give workers necessary adjacent context, but count coverage only by assigned nonoverlapping ranges.

Each worker owns one `work/workers/<worker-id>/` directory. Workers write local findings and candidate drafts only. The coordinator alone assembles `world.json`; shared writes or live Neta mutations are not part of this workflow.

Dispatch all available slots before waiting. Pass each worker:

- The immutable source path/hash, exact assigned range, output language, mode, and already-confirmed extraction limitations.
- Shared source discipline and schema requirements, provisional category map, private output directory, and expected result path.
- Instructions to read its full assigned range, track aliases and chronology, and retain evidence for substantive facts. Cross-range questions remain unresolved findings, not guesses from model knowledge.

Require durable worker results with source hash, assigned/completed ranges, candidate entities, evidence locations, local aliases, conflicts, and explicit completion/failure status. Candidate drafts are not a complete world and need not pass the final whole-world schema before merging. Save tool/task IDs so retries can be distinguished from original workers.

## Observe and reconcile

Check actual agent completion and inspect saved files; a chat saying “done” is not sufficient. A missing range, stale hash, truncated read, invalid evidence reference, failed worker, or missing result blocks completion. Preserve partial files. Stop or await active workers before retrying an affected range in a new attempt directory. Bound retries to a diagnosed recoverable cause; do not endlessly restart or mix unresolved attempts.

The coordinator merges after all contributing workers are terminal and every range is accounted for. Resolve aliases and types globally; integrate later revelations; reread disputed passages and boundary-crossing sequences as needed. Reconcile all candidate facts, including cross-range additions to entities already created elsewhere. Record which facts were incorporated, excluded with reasons, or remain unresolved. Do not choose one worker's shorter version merely because its result arrived first.

Then finalize taxonomy, world fields, and Atoms. Apply the shared final validation and source-review gates. Turbo is a parallel execution choice with Full-equivalent coverage, not permission to reduce detail or declare an unmeasured speedup.

## Turbo Append: enrich while reading

Workers maintain a local entity key/alias map. On the first substantive evidence, create a meaningful draft. On later revelations, revise that same entity draft into a coherent synthesis of prior and new facts, retaining evidence and revision history. Do not make a new card per mention, concatenate disconnected bullet fragments, overwrite richer text with a summary, or write name-only shells. This applies to evolving organizations, places, and rules as well as characters.

After merging all ranges, review **every extracted character**, including minor ones. Consider only source-supported dimensions: identity/background, appearance and speech, choices and traits, motives and fears, capabilities and limits, relationships, and pivotal development. These are review questions, not mandatory blank sections or minimum lengths.

Save `work/character-audit.json` with canonical type/name, contributing worker/entity keys, evidence references, material facts incorporated into output fields, omissions with reasons, unresolved gaps, and a hash of the final reviewed Atom. A short source-limited character needs an evidence-backed reason. “Worker wrote little” is not evidence that the source contains little. Reread relevant passages for real gaps. Unresolved meaningful omissions fail this audit even when the schema passes; do not fabricate detail to close them. Include the audit outcome in `report.md`.
