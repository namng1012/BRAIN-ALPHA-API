import sys

from Functions.cache import CATALOG_MAX_AGE_SECONDS
from Functions.data import BrainData, CatalogBuilder
from Functions.login import RELOGIN_THRESHOLD_SECONDS, BrainLogin
from Functions.operators import OPERATORS_CSV_PATH, MatrixBinary, OperatorTable


def main():
    # Field descriptions contain non-cp1252 characters (e.g. U+2011), so any
    # printout of the catalog would abort on the default Windows console
    # encoding.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Keep only fields that are populated enough to backtest on: the field's own
    # coverage (fraction of the universe the field is defined for) and its
    # dateCoverage (fraction of the history the field spans) must both clear the
    # threshold. dateCoverage is missing on ~4 % of records, and those rows
    # fail the comparison.
    MIN_COVERAGE = 0.7

    # Master switch for reaching the platform. True may log in and refetch; False
    # keeps the run entirely on disk, reusing snapshots even after they age out.
    LOGIN_ALLOW = False
    print(f"LOGIN_ALLOW = {LOGIN_ALLOW}")

    builder = CatalogBuilder(MIN_COVERAGE, refetch_stale=LOGIN_ALLOW)

    # One session serves every scope: logging in per scope would burn the
    # platform's login budget (5 per minute, 25 per day) for no reason.
    login = BrainLogin()
    data = None
    if LOGIN_ALLOW:
        # Two independent reasons to reach the platform, and they are kept apart:
        # the catalog may need refetching, and the token may be close to expiry.
        # The session is obtained whenever the platform is reachable, and
        # get_session() decides on its own whether the cached token still has
        # more than RELOGIN_THRESHOLD_SECONDS left — so a run that only reads
        # /operators still gets a guaranteed token window, and a run whose
        # catalog is still fresh still re-logs in before the token dies.
        s = login.get_session()
        if s is None:
            return
        data = BrainData(s, login.base_url)
    else:
        # Reporting the countdown costs no login: check_login only reads the cached
        # session, so it tells the user how much run time the current token still
        # guarantees without spending any of the 25-logins/day budget.
        s = login.load_session()
        if s is not None:
            expiry = login.check_login(s)
            print(
                f"Session valid for {expiry}s "
                f"({expiry / 60:.1f} min); "
                f"re-login at {RELOGIN_THRESHOLD_SECONDS}s remaining."
            )

    # /operators is not scope-scoped and its table changes far more slowly than
    # the field catalog, so it is cached as a single CSV: the file on disk is
    # the answer, and the platform is only asked when the file is absent.
    #
    # Three cases, in this order:
    #   - the CSV exists: load it, no request, no login spent;
    #   - no CSV but a session is open: fetch it and cache it;
    #   - no CSV and no session: neither load nor fetch is possible.
    if OPERATORS_CSV_PATH.exists():
        operators = OperatorTable.load()
        print(f"Loaded {len(operators)} operators from {OPERATORS_CSV_PATH}")
    elif data is not None:
        operators = OperatorTable(data).fetch()
        print(f"Wrote {len(operators)} operators to {OPERATORS_CSV_PATH}")
    else:
        print(
            f"Error: no operator table at {OPERATORS_CSV_PATH} and LOGIN_ALLOW "
            "is False, so it cannot be fetched."
        )
        return

    # run() fetches whatever it considers a miss, and with LOGIN_ALLOW off the
    # only misses left are absent scopes. Completing that fetch would need a
    # session this branch deliberately never opened.
    if not LOGIN_ALLOW and builder.needs_download():
        print("LOGIN_ALLOW is False and the cache is incomplete; nothing fetched.")
        return

    builder.run(data)

    # Which cache expires first decides whether the next run needs a login, so the
    # countdown is reported for the soonest-to-expire scope rather than all 41 — the
    # run itself prints the one it actually samples.
    soonest = None
    for scope in builder.scopes:
        paths = builder.cache.cached(scope)
        if paths is None:
            continue
        left = builder.cache.expires_in_seconds(paths)
        if soonest is None or left < soonest[0]:
            soonest = (left, builder.cache.key(scope))
    if soonest is not None:
        left, key = soonest
        state = "expired" if left <= 0 else "expires in"
        print(
            f"Cache ({len(builder.scopes)} scopes, {CATALOG_MAX_AGE_SECONDS / 86400:.0f}d max age): "
            f"{key} {state} {abs(left):.0f}s ({abs(left) / 86400:.2f} d)"
        )
    # Expression builder examples: two real MATRIX field ids from one cached
    # scope, run through every builder so the printed FASTEXPR is exactly what
    # the platform would receive. The snapshot id is printed because
    # frame_id + scope is what pins the two field ids to one catalog snapshot.
    scope = builder.scopes[-1]
    x, y = builder.sample_field_ids(
        scope["region"], scope["delay"], scope["universe"], "MATRIX", 2
    )
    # The window is left to each operator to draw: d=None makes it pick from
    # (WINDOW_DAYS_MIN, WINDOW_DAYS_MAX). No seed is passed, so each operator
    # draws its own window from fresh OS entropy — to compare two operators over
    # the same window, call the builders directly with a shared seed.
    snapshot = builder.cache.open(scope, "MATRIX")
    frame = snapshot.frame_id
    snapshot.close()
    print(f"\nExpression examples [{builder.cache.key(scope)}, frame {frame}")
    # The ts_* operators take the window as their third argument, and the
    # platform's argument order differs per operator (ts_corr is x, y while
    # ts_covariance and ts_regression are y, x), so each call is written out.
    for name in (
        "add",
        "divide",
        "multiply",
        "power",
        "signed_power",
        "subtract",
        "ts_corr",
        "ts_covariance",
        "ts_regression",
        "vector_neut",
    ):
        profile = MatrixBinary.get(name, x, y)
        print(f"  {name:14s} {profile['expression']}")


if __name__ == "__main__":
    main()
