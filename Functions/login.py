import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

BRAIN_API_URL = os.environ.get("BRAIN_API_URL", "https://api.worldquantbrain.com")

# Same guard as ace_lib.check_session_and_relogin: re-auth before the session
# dies rather than after, so a dead session is never observed mid-run.
RELOGIN_THRESHOLD_SECONDS = 2000

# Persona verification is completed in the browser; the script polls the
# inquiry endpoint instead of waiting for a keypress.
PERSONA_POLL_INTERVAL_SECONDS = 5
PERSONA_TIMEOUT_SECONDS = 600


class BrainLogin:
    """Authentication against the WorldQuant BRAIN platform.

    The JWT is issued as the session cookie "t" on successful authentication.
    """

    def __init__(
        self,
        base_url: str = BRAIN_API_URL,
        state_dir: Path | None = None,
    ):
        self.base_url = base_url
        # Runtime state (session cache, persona URL) lives in one folder so
        # nothing is scattered across the project root.
        self.state_dir = state_dir or Path(__file__).parent.parent / ".brain"
        self.session_cache_path = self.state_dir / "session.json"
        # The persona inquiry URL is written here as well as printed, so a run
        # that is detached from any terminal (nohup, systemd, cron) still
        # exposes the link.
        self.persona_url_path = self.state_dir / "persona_url.txt"

    def credentials(self) -> tuple[str, str]:
        """Read [email, password] from the BRAIN_CREDENTIALS entry of .env."""
        load_dotenv()
        email, password = json.loads(os.environ["BRAIN_CREDENTIALS"])
        return email, password

    def check_login(self, s: requests.Session) -> int:
        """Return the seconds left on the session, or 0 when not logged in.

        Mirrors ace_lib.check_session_timeout: GET /authentication answers with
        {"token": {"expiry": ...}} for a live session and 401 for a dead one.
        """
        try:
            expiry = s.get(self.base_url + "/authentication").json()["token"]["expiry"]
        except Exception:
            return 0
        return int(expiry)

    def save_session(self, s: requests.Session) -> None:
        """Persist the session cookies so the next run can skip the login call."""
        self.state_dir.mkdir(exist_ok=True)
        self.session_cache_path.write_text(
            json.dumps(
                [
                    {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                    for c in s.cookies
                ]
            )
        )

    def load_session(self) -> requests.Session | None:
        """Rebuild a session from the cached cookies, or None if nothing is cached."""
        if not self.session_cache_path.exists():
            return None
        s = requests.Session()
        s.auth = self.credentials()
        for c in json.loads(self.session_cache_path.read_text()):
            s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        return s

    def start_session(self, email: str, password: str) -> requests.Session | None:
        """Authenticate against /authentication, following the persona biometric flow."""
        s = requests.Session()
        s.auth = (email, password)
        r = s.post(self.base_url + "/authentication")

        if r.status_code == requests.status_codes.codes.unauthorized:
            if r.headers.get("WWW-Authenticate") == "persona":
                inquiry_url = urljoin(r.url, r.headers["Location"])
                self.state_dir.mkdir(exist_ok=True)
                self.persona_url_path.write_text(inquiry_url + "\n")
                print(
                    "Complete biometrics authentication in the browser: \n"
                    + inquiry_url
                    + "\nWaiting for verification...\n"
                    f"(also saved to {self.persona_url_path})\n",
                    flush=True,
                )
                deadline = time.monotonic() + PERSONA_TIMEOUT_SECONDS
                while True:
                    if s.post(inquiry_url).status_code == 201:
                        break
                    if time.monotonic() > deadline:
                        print(
                            "\nBiometrics authentication timed out after "
                            f"{PERSONA_TIMEOUT_SECONDS}s\n"
                        )
                        return None
                    time.sleep(PERSONA_POLL_INTERVAL_SECONDS)
            else:
                print("\nIncorrect email or password\n")
                return None

        return s

    def get_session(self) -> requests.Session | None:
        """Return a live session, reusing the cached JWT whenever it is still valid.

        Only a missing, expired or nearly expired session triggers a fresh login
        against /authentication, which is what the platform rate-limits.
        """
        s = self.load_session()
        if s is not None:
            expiry = self.check_login(s)
            if expiry > RELOGIN_THRESHOLD_SECONDS:
                print(f"Reusing cached session, valid for {expiry}s")
                self.persona_url_path.unlink(missing_ok=True)
                return s

        email, password = self.credentials()
        s = self.start_session(email, password)
        if s is None:
            return None
        self.save_session(s)
        self.persona_url_path.unlink(missing_ok=True)
        return s

    def get_token(self, s: requests.Session) -> str:
        """Return the JWT of the authenticated session (session cookie "t")."""
        return s.cookies["t"]
