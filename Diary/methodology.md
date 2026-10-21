## 2026-10-21T15:53:16Z | methodology | score: 7

**Decision:** Re-authenticate only when the cached session has less than 2000 seconds of validity left; reuse the cached JWT otherwise.

**Alternatives considered:**
- Re-login on every run — rejected, hits the 5 logins/minute rate limit and risks an account lockout.
- Persist the JWT with an absolute expiry timestamp read from the token payload — rejected, the `exp` claim is not the same clock as the server-side session expiry, and a stale-but-unexpired JWT would still 401 mid-run.
- Trust the cached cookie without probing — rejected, a dead session would surface as a confusing 401 on the first real API call instead of at the login gate.

**Rationale:** The 2000-second threshold is the same constant used by `ace_lib.check_session_and_relogin` in `ACE_API__Gold_/ace_lib.py`, so re-auth happens while the session is still alive rather than after it dies. The probe itself is a cheap `GET /authentication` and does not count against the login rate limit.

**Impact on reported results:** None — this affects only session lifecycle, not any simulation or metric. It does mean a run started more than ~4 hours after the last login will trigger one persona flow, which is the intended behaviour.

**Sentiment:** 7 — defensible via the existing ACE convention, and it prevents a silent account lockout.
