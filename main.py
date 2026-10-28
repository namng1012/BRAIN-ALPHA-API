import re
import sys
import json
from collections import Counter

import numpy as np
import pandas as pd
from Functions.cache import CATALOG_MAX_AGE_SECONDS
from Functions.data import BrainData, CatalogBuilder
from Functions.login import RELOGIN_THRESHOLD_SECONDS, BrainLogin
from Functions.operators import OPERATORS_CSV_PATH, MatrixBinary, MatrixUnary, Vector, Group, OperatorProfile, OperatorTable, Variadic
from Functions.random import IntegerSampler


class ExpressionBuilder:
    # Operator calls allowed in one FASTEXPR. Counted on the rendered text:
    # nested calls count, and an operator that repeats its argument multiplies
    # the cost of everything below it (sqrt^3(f) = 5 + 4*25 = 105).
    OPERATOR_LIMIT = 64
    OPERATOR_CALL = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(")

    # One pool per bucket of Docs/all-operators.md §3 that has a builder.
    # `divide` and `power` are left out: a zero denominator or a negative base
    # with a fractional exponent fails at simulation time and costs a slot.
    BINARY_POOL = [
        "add", "if_else", "multiply", "signed_power", "subtract",
        "ts_corr", "ts_covariance", "ts_regression", "vector_neut",
    ]
    UNARY_POOL = [
        "abs", "days_from_last_change", "hump", "inverse", "kth_element",
        "last_diff_value", "log", "normalize", "pasteurize", "quantile", "rank",
        "reverse", "scale", "sign", "sqrt", "tail", "trade_when", "ts_arg_max",
        "ts_arg_min", "ts_av_diff", "ts_backfill", "ts_count_nans",
        "ts_decay_linear", "ts_delay", "ts_delta", "ts_ir", "ts_kurtosis",
        "ts_max_diff", "ts_mean", "ts_product", "ts_quantile", "ts_rank",
        "ts_returns", "ts_scale", "ts_std_dev", "ts_sum", "ts_target_tvr_decay",
        "ts_target_tvr_hump", "ts_zscore", "winsorize", "zscore",
    ]
    VECTOR_POOL = [
        "vec_avg", "vec_count", "vec_max", "vec_min", "vec_range", "vec_stddev",
        "vec_sum",
    ]
    GROUP_POOL = [
        "group_backfill", "group_count", "group_mean", "group_neutralize",
        "group_rank", "group_scale", "group_std_dev", "group_sum", "group_zscore",
    ]

    # The VARIADIC operators take any number of operands in one call, so one
    # `max(a, b, c)` replaces a chain of two binary joins. The platform asks
    # for at least two inputs.
    VARIADIC_POOL = ["max", "min"]

    # The largest operand count one VARIADIC call is given. The platform leaves
    # the count open-ended, so the cap is a budget choice, not a platform limit.
    VARIADIC_MAX_OPERANDS = 4

    # The chance a join round uses a VARIADIC call instead of a binary one,
    # when at least three nodes are waiting to be joined.
    VARIADIC_PROBABILITY = 0.35

    # The number of wrappers applied on top of the joined tree, drawn from
    # 0..POST_WRAPPERS. A wrapper here transforms the combined signal, which
    # is a position no leaf-level wrapper can reach.
    POST_WRAPPERS = 2

    # Swapping the operands changes the value, so a join may swap them.
    NON_COMMUTATIVE = {
        "if_else", "signed_power", "subtract", "ts_corr", "ts_covariance",
        "ts_regression", "vector_neut",
    }

    # Joins whose result depends on the operands' magnitudes: a field of scale
    # 1e9 swamps one of scale 1e-2. Each operand is mapped to [0, 1] by a
    # cross-sectional rank() first, which costs 2 extra operators per join.
    # ts_corr is scale-free and if_else already rank-wraps its operands.
    # max and min compare magnitudes too, so they rank-wrap each operand the
    # same way a scale-sensitive binary join does.
    SCALE_SENSITIVE = {"add", "subtract", "multiply", "signed_power", "max", "min"}
    JOIN_COST = 3

    # Operators that render their argument more than once (measured on the
    # rendered text): sqrt 4x, trade_when 3x, if_else and most group_* 2x.
    REPEATING = {
        "sqrt", "trade_when", "if_else",
        "group_backfill", "group_count", "group_neutralize", "group_scale",
        "group_std_dev", "group_sum", "group_zscore",
    }

    # A pool below its minimum counts as empty: USA_delay1_SP500 has a single
    # GROUP field, so group_* is switched off there instead of reusing one id.
    MIN_POOL_SIZE = {"MATRIX": 1, "VECTOR": 3, "GROUP": 3}

    def __init__(self, catalog, scope, theme):
        self.catalog = catalog
        self.scope = scope
        self.theme = theme
        self.pools = {
            field_type: self._pool_size(field_type)
            for field_type in ("MATRIX", "VECTOR", "GROUP")
        }
        self.empty = [
            field_type
            for field_type, size in self.pools.items()
            if size < self.MIN_POOL_SIZE[field_type]
        ]
        # The GROUP field is sampled on its own, because the group operators
        # need it even when the expression itself uses no MATRIX or VECTOR
        # field. The row is kept whole: its metadata belongs in the profile.
        self.group_frame = None if "GROUP" in self.empty else self._sample("GROUP", 1)
        self.group_id = (
            None if self.group_frame is None else self.group_frame["fieldid"].iloc[0]
        )

        # Operator pools per level, richest first. `build` falls to the next
        # level when no expression of the current one fits the operator limit.
        # Each level is (binary, unary, group, variadic); a level with no
        # variadic pool joins with binary operators only.
        calm = tuple(
            [name for name in pool if name not in self.REPEATING]
            for pool in (self.BINARY_POOL, self.UNARY_POOL, self.GROUP_POOL)
        )
        self.levels = (
            (self.BINARY_POOL, self.UNARY_POOL, self.GROUP_POOL, self.VARIADIC_POOL),
            (self.BINARY_POOL, self.UNARY_POOL, self.GROUP_POOL, []),
            calm + ([],),
            (["add"], self.UNARY_POOL, self.GROUP_POOL, []),
            (["add"], [], [], []),
        )

    @classmethod
    def operator_count(cls, expression):
        return len(cls.OPERATOR_CALL.findall(expression))

    @staticmethod
    def _pick(pool):
        return pool[IntegerSampler.sample((0, len(pool) - 1))]

    def _sample(self, field_type, count):
        return self.catalog.sample_field_ids(
            self.scope["region"], self.scope["delay"], self.scope["universe"],
            field_type, count, theme=self.theme,
        )

    def _pool_size(self, field_type):
        snapshot = self.catalog.cache.open(self.scope, field_type)
        if self.theme:
            size = int(np.isin(snapshot.column("categoryid"), self.theme).sum())
        else:
            size = snapshot.n_rows
        snapshot.close()
        return size

    def draw_fields(self, n):
        """Draw `n` distinct fields and their types, MATRIX and VECTOR as one pool.

        Each type is asked for a random share, capped by what its pool holds (a
        pool below its minimum gives nothing); the shortfall goes to whichever
        type still has fields. MATRIX, VECTOR and GROUP ids are pairwise
        disjoint (measured), so the ids of one expression are distinct.

        Returns the list of drawn field types, the drawn field ids, and the
        drawn rows as a frame carrying every column the archive holds, in draw
        order.
        """
        types = ("MATRIX", "VECTOR")
        wanted = [types[IntegerSampler.sample((0, 1))] for _ in range(n)]
        available = {t: 0 if t in self.empty else self.pools[t] for t in types}
        take = {t: min(wanted.count(t), available[t]) for t in types}
        shortfall = n - sum(take.values())
        for t in types:
            extra = min(shortfall, available[t] - take[t])
            take[t] += extra
            shortfall -= extra
        queues = {t: self._sample(t, take[t]) for t in types}

        field_types, field_ids, rows = [], [], []
        for wanted_type in wanted:
            # The recorded type is where the id came from: it decides whether
            # the leaf needs a vec_* reduction.
            source = wanted_type if not queues[wanted_type].empty else next(
                t for t in types if t != wanted_type
            )
            if queues[source].empty:
                print(
                    f"No MATRIX and no VECTOR field available in "
                    f"{self.catalog.cache.key(self.scope)} (theme={self.theme}) "
                    f"— cannot sample fields."
                )
                break
            field_types.append(source)
            row = queues[source].iloc[0]
            field_ids.append(row["fieldid"])
            rows.append(row)
            queues[source] = queues[source].iloc[1:]
        drawn = pd.DataFrame(rows)
        return field_types, field_ids, drawn

    def build(self, field_ids, field_types, max_wrappers=2, field_meta=None):
        """Build one FASTEXPR from `field_ids` that fits OPERATOR_LIMIT.

        Layers: a VECTOR field is reduced by one vec_* operator; each leaf gets
        0..max_wrappers MATRIX_UNARY/GROUP wrappers; the leaves are then
        shuffled and joined — by a MATRIX_BINARY operator, or by one VARIADIC
        call over three or more operands — until one expression is left. N=1 is
        the leaf stage alone. Every draw takes fresh OS entropy.

        On top of the joined tree, 0..POST_WRAPPERS more wrappers are applied.
        Those transform the combined signal, which the leaf stage cannot
        reach: it only ever wraps a single field.

        The expression is rebuilt with a halving per-leaf wrapper allowance, then
        with poorer pools (see `levels`), until its rendered operator count fits.

        Returns a tuple of (expression, profile). `profile` describes the whole
        expression: the data fields it reads, the operators at each level, and
        the counts that follow from them. `field_meta` is the metadata frame of
        the drawn fields (see `draw_fields`); when it is None the profile lists
        the field ids without their metadata.
        """
        n = len(field_ids)
        if n == 0:
            raise ValueError(
                "build needs at least one field id: the scope has no MATRIX "
                "and no VECTOR field above the pool minimum."
            )
        # n leaves need n-1 joins even when each is a plain `add` of two rank()s.
        if self.JOIN_COST * (n - 1) > self.OPERATOR_LIMIT:
            raise ValueError(
                f"{n} fields need at least {self.JOIN_COST * (n - 1)} operators, over the "
                f"platform's limit of {self.OPERATOR_LIMIT}."
            )

        # The smallest expression the pools allow, kept as the fallback when no
        # level fits the limit.
        smallest = None
        for pools in self.levels:
            allowance = max(1, (self.OPERATOR_LIMIT - self.JOIN_COST * (n - 1)) // n)
            while True:
                tree = self._tree(field_ids, field_types, max_wrappers, allowance, pools)
                expression = tree["expression"]
                if self.operator_count(expression) <= self.OPERATOR_LIMIT:
                    # The post-join wrappers transform the combined signal, a
                    # position the leaf stage cannot reach. They are charged
                    # against whatever the tree left over, so they never push
                    # the expression past the limit.
                    expression, post = self._post_wrap(tree, pools[1], pools[2])
                    return expression, self._profile(
                        expression, post, field_ids, field_types, field_meta
                    )
                if smallest is None or self.operator_count(expression) < self.operator_count(smallest):
                    smallest = expression
                if allowance == 1:
                    break
                allowance //= 2
        return smallest, self._profile(
            smallest, None, field_ids, field_types, field_meta
        )

    def _profile(self, expression, tree, field_ids, field_types, field_meta):
        """Assemble the profile of one built expression.

        The profile has three parts:

        - `data`: the fields the expression reads, each with its full metadata
          from the catalog. A MATRIX or VECTOR field is a leaf of the
          expression; the GROUP field is the one every group operator groups by.
        - `levels`: the operators of each stage of the tree — the leaf stage,
          the join stage and the stage on top of the joined tree. Each level
          maps an operator name to the profiles of the calls that used it.
        - `counts`: what follows from the two parts above.

        The tree is walked rather than the rendered text parsed, so the profile
        holds exactly the operators that were built, with the configuration
        each call was drawn with.
        """
        operators_by_level = {"leaf": {}, "join": {}, "post": {}}
        fields = []
        if tree is not None:
            self._walk(tree, operators_by_level, fields)

        return {
            "expression": expression,
            "operator_count": self.operator_count(expression),
            "data": {
                "fields": self._field_metadata(fields, field_meta),
                "group": self._group_metadata(),
            },
            "levels": {
                level: {name: calls for name, calls in calls_by_name.items()}
                for level, calls_by_name in operators_by_level.items()
            },
            "counts": self._counts(operators_by_level, fields),
        }

    def _walk(self, node, operators_by_level, fields):
        """Collect the operators and the fields of one subtree into the profile.

        An operator's own implicit calls — the `densify` and `bucket` the
        platform's definition of a group operator brings along — are recorded
        at the level of the operator that carries them, so a level's operators
        sum to what that level actually put into the expression.
        """
        for operator in node["operators"]:
            calls = operators_by_level[node["level"]].setdefault(operator["name"], [])
            calls.append(dict(operator))
            for implicit in operator.get("implicit", []):
                implicit_calls = operators_by_level[node["level"]].setdefault(
                    implicit["name"], []
                )
                implicit_calls.append(dict(implicit))
        if node.get("field") is not None:
            fields.append(dict(node["field"]))
        for child in node["children"]:
            self._walk(child, operators_by_level, fields)

    def _counts(self, operators_by_level, fields):
        """Summarize the profile: operators per level and per category."""
        per_level = {
            level: sum(len(calls) for calls in calls_by_name.values())
            for level, calls_by_name in operators_by_level.items()
        }
        per_category = Counter()
        for calls_by_name in operators_by_level.values():
            for calls in calls_by_name.values():
                for call in calls:
                    per_category[call["category"]] += 1
        return {
            "operators_per_level": per_level,
            "operators_per_category": dict(per_category),
            "n_data_fields": len(fields),
            "n_distinct_operators": sum(
                len(calls_by_name) for calls_by_name in operators_by_level.values()
            ),
        }

    def _group_metadata(self):
        """The catalog metadata of the GROUP field, or None when there is none."""
        if self.group_frame is None or len(self.group_frame) == 0:
            return None
        return self.group_frame.iloc[0].to_dict()

    def _field_metadata(self, fields, frame):
        """Attach the catalog metadata to each drawn field.

        `fields` are the leaves of the expression, each a field id and its
        type. `frame` is the catalog metadata of the drawn fields; a field
        missing from it keeps only its id and type.
        """
        lookup = {}
        if frame is not None and len(frame) > 0:
            lookup = {
                row["fieldid"]: row.to_dict()
                for _, row in frame.iterrows()
            }
        out = []
        for field in fields:
            metadata = lookup.get(field["fieldid"], {})
            out.append({**metadata, "type": field["type"]})
        return out

    def _tree(self, field_ids, field_types, max_wrappers, allowance, pools):
        binary_pool, unary_pool, group_pool, variadic_pool = pools
        nodes = [
            self._leaf(field_id, field_type, max_wrappers, allowance, unary_pool, group_pool)
            for field_id, field_type in zip(field_ids, field_types)
        ]
        while len(nodes) > 1:
            nodes = self._join_round(nodes, binary_pool, variadic_pool)
        return nodes[0]

    def _post_wrap(self, node, unary_pool, group_pool):
        """Apply 0..POST_WRAPPERS wrappers on top of the joined tree.

        A wrapper here transforms the combined signal. The leaf stage cannot
        produce that position: it only ever wraps a single field, so the
        combined value of two or more fields never reaches a transform.
        """
        expression = node["expression"]
        operators = []
        for _ in range(IntegerSampler.sample((0, self.POST_WRAPPERS))):
            if self.group_id is not None and group_pool and IntegerSampler.sample((0, 1)) == 0:
                wrapped, operator = Group.get(self._pick(group_pool), expression, self.group_id)
            elif unary_pool:
                wrapped, operator = MatrixUnary.get(self._pick(unary_pool), expression)
            else:
                break
            # A repeating wrapper renders its argument several times, so it can
            # push the whole expression past the operator limit.
            if self.operator_count(wrapped) > self.OPERATOR_LIMIT:
                break
            expression = wrapped
            operators.append(operator)
        return expression, {
            "expression": expression,
            "level": "post",
            "operators": operators,
            "children": [node],
        }

    def _leaf(self, field_id, field_type, max_wrappers, allowance, unary_pool, group_pool):
        leaf = field_id
        operators = []
        if field_type == "VECTOR":
            leaf, operator = Vector.get(self._pick(self.VECTOR_POOL), field_id)
            operators.append(operator)

        for _ in range(IntegerSampler.sample((0, max_wrappers))):
            if self.group_id is not None and group_pool and IntegerSampler.sample((0, 1)) == 0:
                wrapped, operator = Group.get(self._pick(group_pool), leaf, self.group_id)
            elif unary_pool:
                wrapped, operator = MatrixUnary.get(self._pick(unary_pool), leaf)
            else:
                break
            # A repeating wrapper can blow a tiny leaf past its allowance.
            if self.operator_count(wrapped) > allowance:
                break
            leaf = wrapped
            operators.append(operator)
        return {
            "expression": leaf,
            "level": "leaf",
            "field": {"fieldid": field_id, "type": field_type},
            "operators": operators,
            "children": [],
        }

    def _join_round(self, nodes, binary_pool, variadic_pool):
        # Fisher-Yates, so each round pairs the nodes in a different order.
        order = list(range(len(nodes)))
        for position in range(len(order) - 1, 0, -1):
            swap = IntegerSampler.sample((0, position))
            order[position], order[swap] = order[swap], order[position]
        nodes = [nodes[i] for i in order]

        # Draw without replacement within this round; the bag is refilled when
        # it runs dry and starts full again at the next round.
        bag = []
        joined = []
        index = 0
        while index < len(nodes):
            remaining = len(nodes) - index
            # A VARIADIC call pays one operator for the call itself, so it only
            # beats a chain of binary joins from three operands on.
            if (
                variadic_pool
                and remaining >= 3
                and IntegerSampler.sample((0, 99)) < self.VARIADIC_PROBABILITY * 100
            ):
                count = IntegerSampler.sample(
                    (3, min(self.VARIADIC_MAX_OPERANDS, remaining))
                )
                operands = nodes[index:index + count]
                joined.append(self._variadic_join(self._pick(variadic_pool), operands))
                index += count
                continue
            if remaining < 2:
                joined.append(nodes[index])
                index += 1
                continue
            left, right = nodes[index], nodes[index + 1]
            if not bag:
                bag = list(binary_pool)
            name = bag.pop(IntegerSampler.sample((0, len(bag) - 1)))
            if name in self.NON_COMMUTATIVE and IntegerSampler.sample((0, 1)) == 0:
                left, right = right, left
            operators = []
            if name in self.SCALE_SENSITIVE:
                # The scale fix is a plain `rank(x)` with no argument, so it
                # carries no configuration of its own.
                left, right = self._rank_wrap(left), self._rank_wrap(right)
            expression, operator = MatrixBinary.get(name, left["expression"], right["expression"])
            operators.append(operator)
            joined.append({
                "expression": expression,
                "level": "join",
                "operators": operators,
                "children": [left, right],
            })
            index += 2
        return joined

    def _rank_wrap(self, node):
        """Wrap one subtree in the plain `rank(x)` the scale fix needs.

        The wrapper is a `rank` with no argument, so it carries no configuration
        of its own. It is scaffolding the generator inserts to keep the operands
        on one scale, not a choice the profile records: it is present in every
        scale-sensitive join, so counting it would drown the operators the
        profile is meant to describe.
        """
        return {
            "expression": f"rank({node['expression']})",
            "level": "join",
            "operators": [],
            "children": [node],
        }

    def _variadic_join(self, name, operands):
        """Join `operands` with one VARIADIC call.

        Each operand is rank-wrapped first, as a scale-sensitive binary join
        does: max and min compare magnitudes, so a field of scale 1e9 would
        otherwise decide the result on its own.

        The wrap is per operand, not one rank over the whole call. The two are
        not interchangeable: rank is a cross-sectional transform, so it mixes
        stocks, and rank(max(a, b)) ranks the maximum value across the
        cross-section while max(rank(a), rank(b)) takes the larger of two
        already-ranked values. They order the cross-section differently.
        """
        operators = []
        if name in self.SCALE_SENSITIVE:
            operands = [self._rank_wrap(operand) for operand in operands]
        expression, operator = Variadic.get(name, [o["expression"] for o in operands])
        operators.append(operator)
        return {
            "expression": expression,
            "level": "join",
            "operators": operators,
            "children": operands,
        }


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

    # categoryid values the field draws are restricted to (see
    # Docs/categoryid.md). Empty keeps the draw uniform over the whole catalog.
    THEME = []

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
    scope = builder.scopes[-3]

    expressions = ExpressionBuilder(builder, scope, THEME)
    print(f"\nPool in {builder.cache.key(scope)} (theme={THEME}): {expressions.pools}")
    if expressions.empty:
        print(
            f"Empty pool: {expressions.empty} — these types cannot be drawn "
            f"(min {ExpressionBuilder.MIN_POOL_SIZE})."
        )

    # n leaves need n-1 joins, which eats the operator budget: at n=60 only
    # 5 operators remain and the expression degenerates into a bare `add` chain.
    FIELD_COUNTS = (2,)
    for n in FIELD_COUNTS:
        field_types, field_ids, drawn = expressions.draw_fields(n)
        if not field_ids:
            print(f"\nN={n}  skipped: no field available in this scope.")
            continue
        expression, profile = expressions.build(field_ids, field_types, field_meta=drawn)
        print(f"\nN={n}  types={field_types}")
        for field_id in field_ids:
            print(f"  field: {field_id}")
        print(f"  drawn fields ({len(drawn)} rows, {len(drawn.columns)} columns):")
        print(drawn[["fieldid", "type", "categoryid", "coverage"]].to_string(index=False))
        print(f"  expression ({len(expression)} chars, {profile['operator_count']} operators):")
        print(f"  {expression}")
        print(" profile:")
        print(json.dumps(profile, indent=2, default=str))


if __name__ == "__main__":
    main()
