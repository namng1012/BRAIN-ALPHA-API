import re
import sys
from pathlib import Path

import pandas as pd

from Functions.cache import CATALOG_MAX_AGE_SECONDS, FIELD_TYPES
from Functions.data import BrainData, CatalogBuilder
from Functions.login import RELOGIN_THRESHOLD_SECONDS, BrainLogin

# The operator table is written next to the other CSV artifacts of the project.
OPERATORS_CSV_PATH = Path(__file__).parent / "operators.csv"


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
    LOGIN_ALLOW = True
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
        # run() fetches whatever it considers a miss, and with LOGIN_ALLOW off the
        # only misses left are absent scopes. Completing that fetch would need a
        # session this branch deliberately never opened.
        if builder.needs_download():
            print("LOGIN_ALLOW is False and the cache is incomplete; nothing fetched.")
            return
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

    builder.run(data)

    # # Which cache expires first decides whether the next run needs a login, so the
    # # countdown is reported for the soonest-to-expire scope rather than all 41 — the
    # # run itself prints the one it actually samples.
    # soonest = None
    # for scope in builder.scopes:
    #     paths = builder.cache.cached(scope)
    #     if paths is None:
    #         continue
    #     left = builder.cache.expires_in_seconds(paths)
    #     if soonest is None or left < soonest[0]:
    #         soonest = (left, builder.cache.key(scope))
    # if soonest is not None:
    #     left, key = soonest
    #     state = "expired" if left <= 0 else "expires in"
    #     print(
    #         f"Cache ({len(builder.scopes)} scopes, {CATALOG_MAX_AGE_SECONDS / 86400:.0f}d max age): "
    #         f"{key} {state} {abs(left):.0f}s ({abs(left) / 86400:.2f} d)"
    #     )

    # scope = builder.scopes[-1]
    # # A fresh seed per run keeps the draw from being anchored to a fixed
    # # constant, and printing it with the snapshot id keeps the run reproducible:
    # # seed + frame_id + scope replays this exact sample.
    # for field_type in FIELD_TYPES:
    #     sample = builder.sample_field_ids(
    #         scope["region"], scope["delay"], scope["universe"], field_type, 2
    #     )
    #     print(
    #         f"{field_type}: {sample}\n"
    #     )

    # /operators needs auth, but unlike the catalog it is neither scope-scoped nor
    # cached, so one read per run is enough. Any session this run already holds
    # serves it — the cached cookies when nothing was refetched, which spends no
    # login against the 25/day budget.
    if s is not None:
        payload = BrainData(s, login.base_url)._get(login.base_url + "/operators")
        operators = pd.DataFrame(payload).explode("scope")
        regular = operators[operators["scope"] == "REGULAR"].copy()

        # bucket ships a multi-line definition, which would break the column
        # alignment; level is null on the 18 operators the platform has not
        # graded, which is a real value in the payload rather than a missing one.
        regular["definition"] = (
            regular["definition"].str.replace(r"\s+", " ", regex=True).str.strip()
        )
        regular["level"] = regular["level"].fillna("-")

        # The data field types an alpha expression moves through.
        # MATRIX takes matrix fields and returns a matrix. VECTOR operators are
        # the only ones that consume a vector field and reduce it to a matrix.
        # GROUP operators take a matrix plus a group field and return a matrix,
        # so they need both kinds of data field at once. GROUPING operators
        # consume or produce a grouping field itself, so no matrix comes out.
        #
        # VARIADIC operators take an open-ended number of matrix fields.
        # SELECT operators take three matrix fields where one plays the role of
        # a condition rather than a value. BOOLEAN operators return a 0/1 mask
        # rather than a value, so they are not interchangeable with MATRIX even
        # though both are matrix fields on the wire.
        #
        # bucket and densify are named explicitly: their input/output typing is
        # stated only in their prose description, and matching on that wording
        # would silently reclassify them the day WorldQuant rewords it.
        # group_cartesian_product is found structurally instead — it is the one
        # group_ operator that never names a group argument.
        # The variadic and select operators are found structurally too: ".."
        # in the definition is the platform's own variadic marker, and an
        # operator whose arguments are all data fields with three or more of
        # them is the platform's select shape. Both rules were checked against
        # the live catalog and select exactly max/min/multiply and
        # if_else/trade_when.
        #
        # BOOLEAN is the platform's own Logical category minus the select shape.
        # Select wins over Logical because if_else is graded Logical by the
        # platform yet is a value selector, not a mask — classifying it as a
        # mask would put it in the wrong bucket of the typing graph.
        #
        # MATRIX is split by how many matrix fields the operator consumes. The
        # count comes from the data-field arguments only (x, y, z, input...);
        # the numeric and keyword arguments (d, k, lag, rettype, filter, std)
        # are not matrix fields, so ts_corr(x, y, d) counts as two inputs and
        # ts_mean(x, d) as one. The binary subset matters on its own: those
        # operators are the only ones where two independent fields meet, so
        # they are where a pairwise relationship can be expressed at all.
        DATA_ARGS = {"x", "y", "z", "input", "input1", "input2", "input3"}

        def arg_names(definition: str) -> list[str]:
            # Top-level argument names of the first balanced call in the
            # definition, with the default value of each keyword argument
            # stripped. Nested calls like bucket(rank(x), ...) contribute their
            # own arguments, so the result is only a lower bound on arity.
            start = definition.find("(")
            if start < 0:
                return []
            depth = 0
            inner = ""
            for i in range(start, len(definition)):
                if definition[i] == "(":
                    depth += 1
                elif definition[i] == ")":
                    depth -= 1
                    if depth == 0:
                        inner = definition[start + 1 : i]
                        break
            if not inner:
                return []
            parts = []
            depth = 0
            current = ""
            for char in inner:
                if char in "([{":
                    depth += 1
                elif char in ")]}":
                    depth -= 1
                if char == "," and depth == 0:
                    parts.append(current.strip())
                    current = ""
                else:
                    current += char
            parts.append(current.strip())
            names = []
            for part in parts:
                part = part.split("=")[0].strip()
                if part.endswith(")"):
                    part = part[part.rfind("(") + 1 :]
                names.append(re.sub(r"[^A-Za-z0-9_].*$", "", part))
            return names

        args = regular["definition"].map(arg_names)
        is_vec = regular["name"].str.startswith("vec_")
        names_group = regular["name"].str.startswith("group_")
        is_grouping = regular["name"].isin(["bucket", "densify"]) | (
            names_group & ~regular["definition"].str.contains(r"\bgroup\b")
        )
        is_variadic = regular["definition"].str.contains(r"\.\.")
        is_select = args.map(
            lambda a: len(a) >= 3 and all(name in DATA_ARGS for name in a)
        )
        is_boolean = (regular["category"] == "Logical") & ~is_select
        is_matrix = (
            ~is_vec
            & ~names_group
            & ~is_grouping
            & ~is_variadic
            & ~is_select
            & ~is_boolean
        )
        # ts_step is the one operator that takes no matrix field at all: it is a
        # constant day counter, so it is not a unary transform of a field and
        # cannot be ranked or z-scored on its own.
        is_step = regular["name"] == "ts_step"
        # The number of matrix fields consumed, counting only the data-field
        # arguments and ignoring numeric / keyword ones.
        n_matrix_inputs = args.map(lambda a: sum(1 for name in a if name in DATA_ARGS))
        is_binary_matrix = is_matrix & (n_matrix_inputs == 2)
        is_unary_matrix = is_matrix & ~is_binary_matrix & ~is_step

        buckets = [
            (
                "MATRIX_BINARY",
                "MATRIX BINARY — args take exactly two matrix fields (x, y)",
                regular[is_binary_matrix],
            ),
            (
                "MATRIX_UNARY",
                "MATRIX UNARY — args take one matrix field (x)",
                regular[is_unary_matrix],
            ),
            (
                "MATRIX_CONSTANT",
                "MATRIX CONSTANT — takes no matrix field, produces a day counter",
                regular[is_step],
            ),
            (
                "VARIADIC",
                "VARIADIC — args take an open-ended number of matrix fields",
                regular[is_variadic],
            ),
            (
                "SELECT",
                "SELECT — args take matrix fields, one of them a condition",
                regular[is_select],
            ),
            (
                "BOOLEAN",
                "BOOLEAN — returns a 0/1 mask instead of a value",
                regular[is_boolean],
            ),
            (
                "VECTOR",
                "VECTOR -> MATRIX — name starts with vec_",
                regular[is_vec],
            ),
            (
                "GROUP",
                "GROUP — args take a matrix field and a group field",
                regular[names_group & ~is_grouping],
            ),
            (
                "GROUPING",
                "GROUPING — args take or return a grouping field, not a matrix",
                regular[is_grouping],
            ),
        ]

        print(
            f"FASTEXPR operators: {operators['name'].nunique()} published, "
            f"{len(regular)} REGULAR split by data field type\n"
        )
        for _, title, rows in buckets:
            print(f"{title} ({len(rows)})")
            for name, definition, level in zip(
                rows.sort_values("name")["name"],
                rows.sort_values("name")["definition"],
                rows.sort_values("name")["level"],
            ):
                print(f"  {name:26s} {definition}  [{level}]")
            print()

        # The operator table as data: one row per REGULAR operator, with the
        # bucket it was classified into, the platform's own call representation
        # and its prose description. The buckets are disjoint — every operator
        # falls in exactly one — so the category column is a partition of the
        # 84 rows, not a set of overlapping tags.
        #
        # Rows are grouped by category in the order the buckets are declared
        # above, not alphabetically: the declaration order follows the data flow
        # a FASTEXPR walks through, so reading the CSV top to bottom walks the
        # same path as reading the console printout. Sorting the category column
        # alphabetically would scramble that into an order with no meaning
        # (BOOLEAN before MATRIX_*), and rows of the same category would no
        # longer be contiguous.
        category_of = {}
        category_rank = {}
        for rank, (key, _, rows) in enumerate(buckets):
            for name in rows["name"]:
                category_of[name] = key
                category_rank[name] = rank
        table = pd.DataFrame(
            {
                "name": regular["name"],
                "category": regular["name"].map(category_of),
                "expression": regular["definition"],
                "description": regular["description"],
            }
        )
        table["_rank"] = table["name"].map(category_rank)
        table = table.sort_values(["_rank", "name"]).drop(columns="_rank")
        table.to_csv(OPERATORS_CSV_PATH, index=False, encoding="utf-8")
        print(f"Wrote {len(table)} operators to {OPERATORS_CSV_PATH}")


if __name__ == "__main__":
    main()