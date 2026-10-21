# Rules Index

Quick reference for all rules in `.cursor/rules/`. Read this first; load a specific rule only when you need its detail.

## Precedence (highest → lowest)

1. **Correctness** — `04-scientific-ml`, `09-research-paper` (merged content)
2. **Safety** — `13-no-silent-control-flow`
3. **Output style** — `15-no-yapping` > `07-output-format` > `12-do-only-what-asked`
4. **Scope** — `12-do-only-what-asked` (default for new work)
5. **Logging** — `14-diary-logging` (opt-in only)

## All rules

| # | File | Scope | One-line |
|---|---|---|---|
| 01 | `01-language.mdc` | always | Tiếng Việt for prose, English in code; keep technical terms in English |
| 02 | `02-research-behavior.mdc` | always | Investigate first, think before coding, default to action |
| 03 | `03-code-quality.mdc` | always | Minimalism, no over-engineering, single-responsibility functions |
| 04 | `04-scientific-ml.mdc` | always | Scientific operations & reproducibility (merged into 09; kept for back-compat) |
| 05 | `05-refactoring.mdc` | always | Read first, surgical changes, snapshot before modify |
| 06 | `06-performance.mdc` | always | Vectorize first, scale when justified |
| 07 | `07-output-format.mdc` | always | Concise, grounded, structured only when it helps |
| 08 | `08-tool-usage.mdc` | always | Explicit action, parallel calls when independent |
| 09 | `09-research-paper.mdc` | always | Research-paper hygiene; absorbed scientific-ml content |
| 10 | `10-tooling-uv.mdc` | always | uv replaces pip; always `uv run` |
| 11 | `11-main-py-style.mdc` | globs `main.py` | Research-code clarity, no parser abstraction |
| 12 | `12-do-only-what-asked.mdc` | always | Default priority: do exactly what is asked |
| 13 | `13-no-silent-control-flow.mdc` | always | No try/except/print/raise without instruction |
| 14 | `14-diary-logging.mdc` | always | Append to `Diary/<chat-id>.md` only on opt-in trigger |
| 15 | `15-no-yapping.mdc` | always | No yap; short, dense, complete replies |
| 16 | `16-reference-code-readonly.mdc` | globs `ACE_API__Gold_/**` | Reference code is read-only; never edit, never copy verbatim |

## Loading discipline

- Read this INDEX first (cheap).
- Load a specific rule only when the current task touches its scope (e.g. edit `main.py` → load 11; touch tensor math → load 04+09; write chat prose → load 15).
- Don't load all 15 into context upfront — each one costs tokens.

## How rules interact

- **Conflict**: higher precedence wins for its domain. See precedence table above.
- **Scope**: rules with `globs` only apply when matching files are open (rule 11). All others are `alwaysApply`.
- **Override**: if the user explicitly contradicts a rule, the user wins — but the agent must surface the conflict in chat, not silently override.
