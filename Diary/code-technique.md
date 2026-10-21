## 2026-10-21T15:53:16Z | code-technique | score: 7

**Where:** `main.py` — `check_login` / `save_session` / `load_session` / `get_session`

**Pattern:** Session cache via persisted cookies + live expiry probe

**Why:** The BRAIN platform rate-limits `POST /authentication` (header `X-RateLimit-Limit-Minute: 5`, and Persona warns against more than 25 logins/day). Re-logging on every development run risks an account lockout. The JWT is issued as the session cookie `t`, and `GET /authentication` returns `{"token": {"expiry": <seconds_remaining>}}` for a live session (401 for a dead one) — so a cached cookie jar can be validated with a cheap GET instead of a full login.

**Reusable in:** Any script in this project that talks to the BRAIN API; the same `check_login` probe should gate every entry point before calling simulation endpoints.

**Sentiment:** 7 — non-obvious that the JWT lives in a cookie rather than the JSON body, and a reviewer would ask how lockout was avoided.

## 2026-10-21T16:08:34Z | code-technique | score: 8

**Where:** `main.py` — `start_session` (persona branch), `PERSONA_URL_PATH`

**Pattern:** Poll-based Persona verification with an out-of-band URL file

**Why:** The upstream `ace_lib.py` blocks on `input()` after printing the Persona inquiry URL, which forces the operator back to the terminal. Replaced with a `time.monotonic()`-based poll loop against the inquiry endpoint (`201` = verified) plus a 600 s deadline, so the script progresses unattended. Because a run may be detached (nohup/systemd/cron) or driven over SSH from a second machine, the inquiry URL is also written to `.brain_persona_url.txt` alongside the `print(..., flush=True)` — otherwise the link is lost to stdout buffering when no TTY is attached.

**Reusable in:** Any long-running BRAIN job that may need re-auth mid-run (simulation submits, data downloads) — the same "expose the link through a file, not just stdout" pattern applies to every interactive-auth step.

**Sentiment:** 8 — cross-cutting: it removes a hard human-in-the-loop block from every unattended run and is the only way the operator can verify from a different machine.

## 2026-10-21T16:15:16Z | code-technique | score: 6

**Where:** `Functions/login.py` — `class BrainLogin`

**Pattern:** Session-scoped class instead of module-level functions with globals

**Why:** The login logic needed per-instance state (`base_url`, `state_dir`, resolved file paths) that were previously module-level constants. `BrainLogin.__init__` resolves `state_dir` relative to the *package* (`Path(__file__).parent.parent / ".brain"`) rather than the CWD, so the script works regardless of where it is invoked from — relevant because the project is driven over SSH from arbitrary directories. The class also makes the `base_url` and `state_dir` overridable for tests without monkeypatching module globals.

**Reusable in:** Every future BRAIN module (simulation submit, data download) should take a `BrainLogin` instance rather than re-deriving the session — the session object is stateful and must be shared, not rebuilt per call.

**Sentiment:** 6 — a reviewer would ask why the state paths are not CWD-relative; the answer (SSH + arbitrary CWD) is not obvious from the diff.
