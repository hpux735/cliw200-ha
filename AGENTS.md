# AGENTS.md

## Project intent

This repository is the product of an **LLM-driven reverse engineering effort**.
The Savant CLI-W220/CLI-W200 thermostat integration under
`custom_components/savant_cli/` was reconstructed and implemented by an AI
coding agent (opencode / `deepseek-v4-pro`) working from a series of user
prompts — **not** from vendor documentation, firmware, or source code.

The canonical, chronological record of those prompts and the exact steps taken
is [`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md). Treat it as the source
of truth for how and why the code came to be, and keep it up to date.

## Auditing rule: every change must be paired with a prompt

Because the code was produced by prompting an LLM, provenance is essential.
When you add or modify code in this repository:

1. **Pair every change with its prompt.** The user prompt that drove the change
   must be quoted (verbatim) in the commit message, the PR description, or an
   entry in `REVERSE_ENGINEERING.md`. A change without a recorded prompt is
   untraceable and is not acceptable as-is.
2. **Flag unprompted code.** Any code that cannot be paired with a prompt must
   be flagged — annotate it in source with `# NOTE: unprompted change — needs
   review`, and record it in the "Flagged changes" section of
   `REVERSE_ENGINEERING.md` with the reason and the author (model vs. human).
3. **Audit on review.** When reviewing a change, verify each file/hunk maps to
   a documented prompt. Reject or flag orphaned changes before merging.

## Reverse-engineering constraints

The device was investigated using only **read-only, passive techniques**:

- TCP port scanning,
- mDNS queries (multicast and unicast),
- HTTP(S) probing of the device's own web UI,

No firmware may be modified, no credentials may be brute-forced beyond trivial
guesses against the device's own login endpoint, and no destructive action was
taken against the device. Extensions should prefer the read-only telemetry
stream and must document any newly discovered endpoint or protocol detail in
`REVERSE_ENGINEERING.md`.

## Conventions for future agents

- Read `REVERSE_ENGINEERING.md` and this file before changing anything.
- Do not commit code that is not traceable to a user prompt.
- Do not invent device behavior; verify against the live device
  (`192.168.3.45`) or document assumptions explicitly.
- Keep the transcript updated whenever a new prompt meaningfully changes the
  code.
- Commit and push at the end of each prompt.
