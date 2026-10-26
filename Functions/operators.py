"""The FASTEXPR operator table: the operators the platform publishes, typed by
the data field they consume.

`/operators` is the one BRAIN endpoint that is not scope-scoped, so the table is
fetched once and cached as a CSV in the cache folder; a later run finds the file
and spends neither a request nor a login.
"""

import os
import re
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd

from Functions.cache import CACHE_DIR
from Functions.data import BrainData
from Functions.random import FloatSampler, IntegerSampler

# The operator table sits next to the scope snapshots in the cache folder.
OPERATORS_CSV_PATH=CACHE_DIR / "operators.csv"


# The profile of one built operator call: category, name, and the config
# (arguments that are not matrix fields, drawn at random).
OperatorProfile=TypedDict(
    "OperatorProfile",
    {
        "category": str,
        "name": str,
        "config": dict[str, int | bool],
    },
)
OperatorProfile.__doc__="""One built operator call: what it is and how it is configured.

`category` is the bucket the operator belongs to, `name` the operator's own
name, and `config` the arguments that are not matrix fields with the values
the platform receives (the window `d`, the `lag`, the `rettype`). Arguments
fixed by the operator itself are not listed: they do not change with the seed,
so they are not needed to replay the call.
"""

# The data-field arguments of an operator call. The numeric and keyword
# arguments (d, k, lag, rettype, filter, std) are not matrix fields, so
# ts_corr(x, y, d) counts as two inputs and ts_mean(x, d) as one.
DATA_ARGS={"x", "y", "z", "input", "input1", "input2", "input3"}

# The buckets, in the order a FASTEXPR walks through the data flow. The order
# is the order the rows appear in the CSV.
BUCKETS=(
    "MATRIX_BINARY",
    "MATRIX_UNARY",
    "MATRIX_GENERATED",
    "VARIADIC",
    "SELECT",
    "BOOLEAN",
    "VECTOR",
    "GROUP",
    "GROUPING",
)


class OperatorTable:
    """The operator table: fetched from /operators, typed, and cached as a CSV.

    `load` reads the cached table from disk; `fetch` asks the platform and
    writes the answer back. The typing rules are read off the live catalog:
    every operator falls into exactly one bucket.
    """

    def __init__(self, data: BrainData, path: Path=OPERATORS_CSV_PATH):
        self.data=data
        self.path=path

    @staticmethod
    def load(path: Path=OPERATORS_CSV_PATH) -> pd.DataFrame:
        """Read the cached table from disk.

        `category` comes back as an ordered categorical so it sorts in the same
        bucket order a freshly fetched table has.
        """
        table=pd.read_csv(path, encoding="utf-8")
        table["category"]=pd.Categorical(
            table["category"], categories=BUCKETS, ordered=True
        )
        return table

    @staticmethod
    def arg_names(definition: str) -> list[str]:
        """Top-level argument names of the first balanced call in a definition.

        Keyword defaults are stripped. Nested calls like bucket(rank(x), ...) are
        not arguments of their own, so the result is only a lower bound on arity.
        """
        start=definition.find("(")
        if start < 0:
            return []

        depth, parts, current=0, [], ""
        for char in definition[start + 1 :]:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current)
                current=""
            else:
                current += char
        parts.append(current)

        return [
            re.match(
                r"[A-Za-z0-9_]*", p.split("=")[0].strip().rsplit("(", 1)[-1]
            ).group()
            for p in parts
        ]

    @staticmethod
    def bucket_of(name: str, definition: str, category: str, args: list[str]) -> str:
        """The one bucket an operator falls into.

        The buckets follow the data flow a FASTEXPR walks through: MATRIX takes
        matrix fields and returns a matrix, MATRIX_GENERATED returns a matrix
        without taking one (ts_step counts the days), VECTOR operators are the
        only ones that consume a vector field and reduce it to a matrix, GROUP
        operators take a matrix plus a group field, GROUPING operators consume or
        produce a grouping field themselves, VARIADIC takes an open-ended number
        of matrix fields, SELECT takes three matrix fields where one is a
        condition rather than a value, and BOOLEAN returns a 0/1 mask rather than
        a value. Every operator falls in exactly one.
        """
        is_select=len(args) >= 3 and all(n in DATA_ARGS for n in args)
        # bucket and densify are named explicitly: their typing is stated only in
        # their prose description, and matching on that wording would silently
        # reclassify them the day WorldQuant rewords it. group_cartesian_product
        # falls out structurally instead — it is the one group_ operator that never
        # names a group argument.
        is_grouping=name in ("bucket", "densify") or (
            name.startswith("group_") and not re.search(r"\bgroup\b", definition)
        )

        if is_grouping:
            return "GROUPING"
        if name.startswith("group_"):
            return "GROUP"
        if name.startswith("vec_"):
            return "VECTOR"
        # BOOLEAN is the platform's own Logical category minus the select shape:
        # if_else is graded Logical yet is a value selector, not a mask.
        if category == "Logical" and not is_select:
            return "BOOLEAN"
        # A select operator is one whose arguments are all data fields and number
        # three or more; checked against the live catalog, that selects exactly
        # if_else and trade_when.
        if is_select:
            return "SELECT"
        # The platform ships two variadic markers: `..` (two dots) and `...`
        # (three dots). Only the two-dot marker counts as variadic here, so
        # `multiply` — whose definition spells it `...` — is classified by its
        # two matrix arguments like `add` and `subtract` are.
        if ".." in definition and "..." not in definition:
            return "VARIADIC"
        # ts_step is the one operator that takes no matrix field at all: it is a
        # day counter, so it is not a unary transform of a field and cannot be
        # ranked or z-scored on its own.
        if name == "ts_step":
            return "MATRIX_GENERATED"
        n_matrix=sum(1 for n in args if n in DATA_ARGS)
        return "MATRIX_BINARY" if n_matrix == 2 else "MATRIX_UNARY"

    def fetch(self) -> pd.DataFrame:
        """Fetch /operators, classify it, write the CSV, and return the table."""
        payload=self.data._get(self.data.base_url + "/operators")
        if isinstance(payload, dict):
            raise RuntimeError(f"/operators returned an error: {payload}")

        operators=pd.DataFrame(payload).explode("scope")
        regular=(
            operators[operators["scope"] == "REGULAR"].reset_index(drop=True).copy()
        )

        # bucket ships a multi-line definition, which would break a one-line
        # reading of the table.
        regular["definition"]=(
            regular["definition"].str.replace(r"\s+", " ", regex=True).str.strip()
        )
        # The platform ships some descriptions with CRLF line endings and the CSV
        # writer keeps them verbatim, so they are normalised to keep the file's
        # line endings uniform.
        regular["description"]=regular["description"].str.replace(
            "\r\n", "\n", regex=False
        )

        table=pd.DataFrame(
            {
                "name": regular["name"],
                "category": [
                    self.bucket_of(
                        name, definition, category, self.arg_names(definition)
                    )
                    for name, definition, category in zip(
                        regular["name"], regular["definition"], regular["category"]
                    )
                ],
                "expression": regular["definition"],
                "description": regular["description"],
            }
        )
        # Rows are grouped by category in the order the buckets are declared, not
        # alphabetically: the declaration order follows the data flow a FASTEXPR
        # walks through, so reading the CSV top to bottom walks the same path.
        table["category"]=pd.Categorical(
            table["category"], categories=BUCKETS, ordered=True
        )
        table=table.sort_values(["category", "name"])
        table.to_csv(self.path, index=False, encoding="utf-8")
        return table


class MatrixBinary:
    """The MATRIX_BINARY operators: two matrix fields in, one matrix out.

    Every operator in this bucket consumes exactly two matrix fields and
    returns a matrix, so one class holds all of them.

    The numeric arguments the platform takes alongside the two fields are
    drawn at random when the caller leaves them out, and each draw sits on
    its own entropy stream so adding an argument later never shifts the value
    an existing draw produces.
    """

    # The rolling window the time-series operators run over, in days. 252 is
    # the longest lookback a year of trading days covers.
    WINDOW_DAYS=(1, 252)

    # The lag ts_regression shifts x by before the fit.
    LAG=(0, 5)

    # The ts_regression output types: 0 residual, 1 beta, 2 alpha, 3 predicted
    # value, 4 correlation, 5 R-squared, 6-9 t-statistics and standard errors.
    RETTYPE=(0, 9)

    @staticmethod
    def get(
        name: str,
        x: str,
        y: str,
        *,
        distribution: Literal["uniform", "balanced"]="uniform",
    ) -> tuple[str, OperatorProfile]:
        """Build the named MATRIX_BINARY operator.

        `name` is the operator name as the platform spells it, `x` and `y` are
        two matrix field ids. The two fields reach the platform in the order
        they are given here: the platform's own parameter names differ between
        operators (ts_corr names them x, y while ts_covariance and
        ts_regression name them y, x), but every builder in this class already
        maps its arguments onto the platform's slots.

        The numeric arguments the platform takes alongside the two fields are
        drawn at random, so two calls with the same name differ in their
        window.

        `distribution` picks how the window is drawn: "uniform" gives every
        length the same probability, "balanced" gives each of the five horizon
        buckets the same probability instead. Operators that take no window
        ignore it.

        Returns a tuple of (expression, profile) where expression is the
        FASTEXPR string and profile contains category, name, and config.
        """
        builders={
            "add": MatrixBinary.add,
            "divide": MatrixBinary.divide,
            "if_else": MatrixBinary.if_else,
            "multiply": MatrixBinary.multiply,
            "power": MatrixBinary.power,
            "signed_power": MatrixBinary.signed_power,
            "subtract": MatrixBinary.subtract,
            "ts_corr": MatrixBinary.ts_corr,
            "ts_covariance": MatrixBinary.ts_covariance,
            "ts_regression": MatrixBinary.ts_regression,
            "vector_neut": MatrixBinary.vector_neut,
        }
        builder=builders[name]
        # Only the ts_* and if_else operators take a distribution, so only they take a
        # distribution; the rest would reject the keyword.
        if name.startswith("ts_") or name=="if_else":
            return builder(x, y, distribution=distribution)
        return builder(x, y)

    @staticmethod
    def _profile(
        name: str,
        config: dict[str, int | bool],
        expression: str,
    ) -> tuple[str, OperatorProfile]:
        """Assemble the expression and profile of one built operator call.

        `config` holds the arguments that are not matrix fields and that the
        draw produced — the window `d`, the `lag` and the `rettype`. The
        arguments fixed by the operator itself are not listed: they do not
        change with the seed, so they are not needed to replay the call.

        Returns a tuple of (expression, profile).
        """
        profile: OperatorProfile={
            "category": "MATRIX_BINARY",
            "name": name,
            "config": config,
        }
        return (expression, profile)

    @staticmethod
    def add(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `add` FASTEXPR over two matrix field ids.

        `filter=true` treats NaN as 0 before summing.
        """
        return MatrixBinary._profile(
            "add",
            {},
            f"add({x}, {y}, filter=true)",
        )

    @staticmethod
    def divide(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `divide` FASTEXPR over two matrix field ids.

        The platform's `divide` takes no `filter` argument, so NaN propagates and a
        zero denominator raises — the caller guards it with an epsilon instead.
        """
        return MatrixBinary._profile(
            "divide",
            {},
            f"divide({x}, {y})",
        )

    @staticmethod
    def multiply(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `multiply` FASTEXPR over two matrix field ids.

        `filter=true` treats NaN as 1 before multiplying.
        """
        return MatrixBinary._profile(
            "multiply",
            {},
            f"multiply({x}, {y}, filter=true)",
        )

    @staticmethod
    def power(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `power` FASTEXPR over two matrix field ids.

        The platform's `power` takes no `filter` argument.
        """
        return MatrixBinary._profile(
            "power",
            {},
            f"power({x}, {y})",
        )

    @staticmethod
    def signed_power(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `signed_power` FASTEXPR over two matrix field ids.

        The platform's `signed_power` takes no `filter` argument.
        """
        return MatrixBinary._profile(
            "signed_power",
            {},
            f"signed_power({x}, {y})",
        )

    @staticmethod
    def subtract(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `subtract` FASTEXPR over two matrix field ids.

        `filter=true` treats NaN as 0 before subtracting.
        """
        return MatrixBinary._profile(
            "subtract",
            {},
            f"subtract({x}, {y}, filter=true)",
        )

    @staticmethod
    def ts_corr(
        x: str,
        y: str,
        d: int | None=None,
        seed: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced",
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_corr` FASTEXPR: rolling Pearson correlation of x and y over d days.

        `d` is the window in days, an integer argument to the platform. `d=None`
        draws the window at random from (WINDOW_DAYS_MIN, WINDOW_DAYS_MAX).

        `distribution` picks how the window is drawn: "uniform" gives every
        length the same probability, "balanced" gives each of the five horizon
        buckets the same probability instead.

        The same `seed` yields the same window for every operator that shares it,
        so two operators are always compared over the same window.
        """
        if d is None:
            d=IntegerSampler.sample(
                MatrixBinary.WINDOW_DAYS, seed, 1, distribution=distribution
            )
        return MatrixBinary._profile(
            "ts_corr",
            {"d": d},
            f"ts_corr({x}, {y}, {d})",
        )

    @staticmethod
    def ts_covariance(
        y: str,
        x: str,
        d: int | None=None,
        seed: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced",
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_covariance` FASTEXPR: rolling covariance of y and x over d days.

        The platform's own signature puts `y` first, so the argument order is `y, x`
        — the reverse of `ts_corr`.

        `d` is the window in days, an integer argument to the platform. `d=None`
        draws the window at random from (WINDOW_DAYS_MIN, WINDOW_DAYS_MAX). The same
        `seed` yields the same window for every operator that shares it.

        `distribution` picks how the window is drawn: "uniform" gives every
        length the same probability, "balanced" gives each of the five horizon
        buckets the same probability instead.
        """
        if d is None:
            d=IntegerSampler.sample(
                MatrixBinary.WINDOW_DAYS, seed, 1, distribution=distribution
            )
        return MatrixBinary._profile(
            "ts_covariance",
            {"d": d},
            f"ts_covariance({y}, {x}, {d})",
        )

    @staticmethod
    def ts_regression(
        y: str,
        x: str,
        d: int | None=None,
        lag: int | None=None,
        rettype: int | None=None,
        seed: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced",
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_regression` FASTEXPR: rolling OLS of y on x over d days.

        `y` is the regressand and `x` the predictor. `lag` shifts x before the fit;
        `lag=None` draws it uniformly from 0-5, so a run exercises a different lag
        each time.

        `rettype` selects the output: 0 residual, 1 beta, 2 alpha, 3 predicted
        value, 4 correlation, 5 R-squared, 6-9 t-statistics and standard errors.
        `rettype=None` draws it uniformly from 0-9, so a run exercises a different
        regression output each time.

        `d` is the window in days, an integer argument to the platform. `d=None`
        draws the window at random from (WINDOW_DAYS_MIN, WINDOW_DAYS_MAX). The same
        `seed` yields the same window, lag and rettype for every operator that
        shares it.

        `distribution` picks how the window is drawn: "uniform" gives every
        length the same probability, "balanced" gives each of the five horizon
        buckets the same probability instead. It applies to the window only —
        the lag and the rettype are always drawn uniformly.
        """
        if seed is None:
            seed=int.from_bytes(os.urandom(8), "big")
        if d is None:
            d=IntegerSampler.sample(
                MatrixBinary.WINDOW_DAYS, seed, 1, distribution=distribution
            )
        if lag is None:
            # Entropy stream 3, separate from the window's stream 1 and rettype's
            # stream 2, so the draw of one does not shift the others.
            lag=IntegerSampler.sample(MatrixBinary.LAG, seed, 3, distribution="uniform")
        if rettype is None:
            # Entropy stream 2, separate from the window's stream 1, so the draw of
            # one does not shift the other.
            rettype=IntegerSampler.sample(MatrixBinary.RETTYPE, seed, 2, distribution="uniform")
        return MatrixBinary._profile(
            "ts_regression",
            {"d": d, "lag": lag, "rettype": rettype},
            f"ts_regression({y}, {x}, {d}, lag={lag}, rettype={rettype})",
        )

    @staticmethod
    def vector_neut(x: str, y: str) -> tuple[str, OperatorProfile]:
        """Build the `vector_neut` FASTEXPR: the component of x orthogonal to y.

        Cross-sectional: it strips the linear projection of x onto y, leaving x* with
        x* . y=0. "Vector" is the alpha position vector, not a VECTOR-type field.
        """
        return MatrixBinary._profile(
            "vector_neut",
            {},
            f"vector_neut({x}, {y})",
        )

    @staticmethod
    def if_else(
        x: str,
        y: str,
        s1: float | None=None,
        s2: float | None=None,
        dx: int | None=None,
        dy: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `if_else` expression: conditional selection based on weighted comparison.

        Transforms x and y with ts_rank(*, dx) and ts_rank(*, dy) if not already starting
        with rank operators.
        Rank operators: ts_rank(, rank(, scale(, ts_scale(

        Args:
            x, y: operand expressions
            s1, s2: weighting coefficients. If None, samples from [1.0, 2.0] with given distribution.
            dx, dy: ts_rank windows wrapping x and y. If None, sampled independently from
                [60, 252] with given distribution; unused when the operand is already ranked.
            distribution: sampling strategy for s1, s2, dx, dy when None.

        Condition: s1 * _x > s2 * _y
        Returns _x if condition is truthy, else _y.
        """
        if s1 is None:
            s1=FloatSampler.sample((1.0, 2.0), None, 1, distribution=distribution)
        if s2 is None:
            s2=FloatSampler.sample((1.0, 2.0), None, 2, distribution=distribution)

        rank_ops=("ts_rank(", "rank(", "scale(", "ts_scale(")
        config={"s1": s1, "s2": s2}
        if x.startswith(rank_ops):
            _x=x
        else:
            if dx is None:
                dx=IntegerSampler.sample((60, 252), None, 3, distribution=distribution)
            _x=f"ts_rank({x}, {dx})"
            config["dx"]=dx
        if y.startswith(rank_ops):
            _y=y
        else:
            if dy is None:
                dy=IntegerSampler.sample((60, 252), None, 4, distribution=distribution)
            _y=f"ts_rank({y}, {dy})"
            config["dy"]=dy

        condition=f"{s1} * {_x} > {s2} * {_y}"
        expression=f"if_else({condition}, {_x}, {_y})"

        return MatrixBinary._profile(
            "if_else",
            config,
            expression,
        )


class MatrixUnary:
    """The MATRIX_UNARY operators: one matrix field in, one matrix out.

    Every operator in this bucket consumes exactly one matrix field and
    returns a matrix, so one class holds all of them.

    The numeric arguments the platform takes alongside the field are drawn
    at random when the caller leaves them out, and each draw sits on its
    own entropy stream so adding an argument later never shifts the value
    an existing draw produces.
    """

    # The rolling window the time-series operators run over, in days. 252 is the
    # longest lookback a year of trading days covers.
    WINDOW_DAYS=(1, 252)

    # The entropy streams the drawn arguments sit on. Each kind of argument gets
    # its own stream, so drawing one never shifts the value another produces.
    WINDOW_STREAM=1
    KTH_ELEMENT_K_STREAM=2
    WINSORIZE_STD_STREAM=3
    DRIVER_STREAM=4
    DENSE_STREAM=5
    HUMP_STREAM=6
    NORMALIZE_USE_STD_STREAM=7
    NORMALIZE_LIMIT_STREAM=8
    QUANTILE_SIGMA_STREAM=9
    RANK_RATE_STREAM=10
    SCALE_BOOK_STREAM=11
    SCALE_LONG_STREAM=12
    SCALE_SHORT_STREAM=13
    TAIL_LOWER_STREAM=14
    TAIL_UPPER_STREAM=15
    TAIL_NEWVAL_STREAM=16
    TS_BACKFILL_K_STREAM=17
    TS_RETURNS_MODE_STREAM=18
    TS_TARGET_TVR_LAMBDA_MIN_STREAM=19
    TS_TARGET_TVR_LAMBDA_MAX_STREAM=20
    TS_TARGET_TVR_TARGET_STREAM=21
    WINSORIZE_WINDOW_STREAM=22

    # The probability distributions `quantile` and `ts_quantile` map the ranks onto.
    DRIVERS=("gaussian", "cauchy", "uniform")

    # The ranks `kth_element` takes, and the values each rank makes it ignore.
    KTH_ELEMENT_KS=(1, 2)
    KTH_ELEMENT_IGNORE={1: "NaN", 2: "NaN 0"}

    # The book sizes `scale` targets, in platform units.
    SCALE_BOOK_SIZES=(1, 10)

    @staticmethod
    def get(
        name: str,
        x: str,
        *,
        distribution: Literal["uniform", "balanced"]="uniform",
    ) -> tuple[str, OperatorProfile]:
        """Build the named MATRIX_UNARY operator.

        `name` is the operator name as the platform spells it, `x` is one
        matrix field id.

        The numeric arguments the platform takes alongside the field are
        drawn at random, so two calls with the same name differ in their
        parameters.

        `distribution` picks how windowed parameters are drawn: "uniform"
        gives every length the same probability, "balanced" gives each of
        the five horizon buckets the same probability instead.

        Returns a tuple of (expression, profile) where expression is the
        FASTEXPR string and profile contains category, name, and config.
        """
        builders={
            "abs": MatrixUnary.abs_,
            "days_from_last_change": MatrixUnary.days_from_last_change,
            "hump": MatrixUnary.hump,
            "inverse": MatrixUnary.inverse,
            "kth_element": MatrixUnary.kth_element,
            "last_diff_value": MatrixUnary.last_diff_value,
            "log": MatrixUnary.log,
            "normalize": MatrixUnary.normalize,
            "pasteurize": MatrixUnary.pasteurize,
            "quantile": MatrixUnary.quantile,
            "rank": MatrixUnary.rank,
            "reverse": MatrixUnary.reverse,
            "scale": MatrixUnary.scale,
            "sign": MatrixUnary.sign,
            "sqrt": MatrixUnary.sqrt,
            "tail": MatrixUnary.tail,
            "trade_when": MatrixUnary.trade_when,
            "ts_arg_max": MatrixUnary.ts_arg_max,
            "ts_arg_min": MatrixUnary.ts_arg_min,
            "ts_av_diff": MatrixUnary.ts_av_diff,
            "ts_backfill": MatrixUnary.ts_backfill,
            "ts_count_nans": MatrixUnary.ts_count_nans,
            "ts_decay_linear": MatrixUnary.ts_decay_linear,
            "ts_delay": MatrixUnary.ts_delay,
            "ts_delta": MatrixUnary.ts_delta,
            "ts_ir": MatrixUnary.ts_ir,
            "ts_kurtosis": MatrixUnary.ts_kurtosis,
            "ts_max_diff": MatrixUnary.ts_max_diff,
            "ts_mean": MatrixUnary.ts_mean,
            "ts_product": MatrixUnary.ts_product,
            "ts_quantile": MatrixUnary.ts_quantile,
            "ts_rank": MatrixUnary.ts_rank,
            "ts_returns": MatrixUnary.ts_returns,
            "ts_scale": MatrixUnary.ts_scale,
            "ts_std_dev": MatrixUnary.ts_std_dev,
            "ts_sum": MatrixUnary.ts_sum,
            "ts_target_tvr_decay": MatrixUnary.ts_target_tvr_decay,
            "ts_target_tvr_hump": MatrixUnary.ts_target_tvr_hump,
            "ts_zscore": MatrixUnary.ts_zscore,
            "winsorize": MatrixUnary.winsorize,
            "zscore": MatrixUnary.zscore,
        }
        builder=builders[name]
        # Operators that take a window parameter accept distribution; others ignore it.
        if name.startswith("ts_") or name in ("kth_element", "last_diff_value", "tail", "trade_when", "winsorize"):
            return builder(x, distribution=distribution)
        return builder(x)

    @staticmethod
    def _profile(
        name: str,
        config: dict[str, int | bool | float | str],
        expression: str,
    ) -> tuple[str, OperatorProfile]:
        """Assemble the expression and profile of one built operator call.

        `config` holds the arguments that are not matrix fields and that the
        draw produced — the window `d`, boolean flags, and numeric parameters.
        The arguments fixed by the operator itself are not listed: they do not
        change with the seed, so they are not needed to replay the call.

        Returns a tuple of (expression, profile).
        """
        profile: OperatorProfile={
            "category": "MATRIX_UNARY",
            "name": name,
            "config": config,
        }
        return (expression, profile)

    @staticmethod
    def abs_(x: str) -> tuple[str, OperatorProfile]:
        """Build the `abs` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("abs", {}, f"abs({x})")

    @staticmethod
    def days_from_last_change(x: str) -> tuple[str, OperatorProfile]:
        """Build the `days_from_last_change` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile(
            "days_from_last_change", {}, f"days_from_last_change({x})"
        )

    @staticmethod
    def hump(
        x: str,
        hump: float | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `hump` FASTEXPR over one matrix field id."""
        if hump is None:
            hump=FloatSampler.sample(seed=None, stream=MatrixUnary.HUMP_STREAM, distribution=distribution)
        return MatrixUnary._profile(
            "hump", {"hump": hump}, f"hump({x}, hump={hump:.4f})"
        )

    @staticmethod
    def inverse(x: str) -> tuple[str, OperatorProfile]:
        """Build the `inverse` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("inverse", {}, f"inverse({x})")

    @staticmethod
    def kth_element(
        x: str,
        d: int | None=None,
        k: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `kth_element` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        if k is None:
            k=IntegerSampler.sample(
                MatrixUnary.KTH_ELEMENT_KS, None, MatrixUnary.KTH_ELEMENT_K_STREAM, distribution="uniform"
            )
        ignore=MatrixUnary.KTH_ELEMENT_IGNORE[k]
        return MatrixUnary._profile(
            "kth_element",
            {"d": d, "k": k, "ignore": ignore},
            f"kth_element({x}, {d}, k={k}, ignore='{ignore}')",
        )

    @staticmethod
    def last_diff_value(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `last_diff_value` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile(
            "last_diff_value", {"d": d}, f"last_diff_value({x}, {d})"
        )

    @staticmethod
    def log(x: str) -> tuple[str, OperatorProfile]:
        """Build the `log` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("log", {}, f"log({x})")

    @staticmethod
    def normalize(
        x: str,
        use_std: bool | None=None,
        limit: float | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `normalize` FASTEXPR over one matrix field id."""
        if use_std is None:
            use_std=bool(
                IntegerSampler.sample((0, 1), None, MatrixUnary.NORMALIZE_USE_STD_STREAM, distribution="uniform")
            )
        if limit is None:
            limit=FloatSampler.sample(seed=None, stream=MatrixUnary.NORMALIZE_LIMIT_STREAM, distribution=distribution)
        return MatrixUnary._profile(
            "normalize",
            {"useStd": use_std, "limit": limit},
            f"normalize({x}, useStd={'true' if use_std else 'false'}, limit={limit:.4f})",
        )

    @staticmethod
    def pasteurize(x: str) -> tuple[str, OperatorProfile]:
        """Build the `pasteurize` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("pasteurize", {}, f"pasteurize({x})")

    @staticmethod
    def quantile(
        x: str,
        driver: str | None=None,
        sigma: float | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `quantile` FASTEXPR over one matrix field id."""
        if driver is None:
            driver=MatrixUnary.DRIVERS[
                IntegerSampler.sample(
                    (0, len(MatrixUnary.DRIVERS) - 1), None, MatrixUnary.DRIVER_STREAM, distribution="uniform"
                )
            ]
        if sigma is None:
            sigma=FloatSampler.sample(seed=None, stream=MatrixUnary.QUANTILE_SIGMA_STREAM, distribution=distribution)
        return MatrixUnary._profile(
            "quantile",
            {"driver": driver, "sigma": sigma},
            f"quantile({x}, driver='{driver}', sigma={sigma:.4f})",
        )

    @staticmethod
    def rank(
        x: str,
        rate: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="uniform"
    ) -> tuple[str, OperatorProfile]:
        """Build the `rank` FASTEXPR over one matrix field id."""
        if rate is None:
            rate=IntegerSampler.sample((0, 2), None, MatrixUnary.RANK_RATE_STREAM, distribution=distribution)
        return MatrixUnary._profile("rank", {"rate": rate}, f"rank({x}, rate={rate})")

    @staticmethod
    def reverse(x: str) -> tuple[str, OperatorProfile]:
        """Build the `reverse` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("reverse", {}, f"reverse({x})")

    @staticmethod
    def scale(
        x: str,
        book_size: int | None=None,
        long_scale: int | None=None,
        short_scale: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="uniform"
    ) -> tuple[str, OperatorProfile]:
        """Build the `scale` FASTEXPR over one matrix field id."""
        if book_size is None:
            book_size=IntegerSampler.sample(
                MatrixUnary.SCALE_BOOK_SIZES, None, MatrixUnary.SCALE_BOOK_STREAM, distribution=distribution
            )
        if long_scale is None:
            long_scale=IntegerSampler.sample(
                MatrixUnary.SCALE_BOOK_SIZES, None, MatrixUnary.SCALE_LONG_STREAM, distribution=distribution
            )
        if short_scale is None:
            short_scale=IntegerSampler.sample(
                MatrixUnary.SCALE_BOOK_SIZES, None, MatrixUnary.SCALE_SHORT_STREAM, distribution=distribution
            )
        return MatrixUnary._profile(
            "scale",
            {"scale": book_size, "longscale": long_scale, "shortscale": short_scale},
            f"scale({x}, scale={book_size}, longscale={long_scale}, shortscale={short_scale})",
        )

    @staticmethod
    def sign(x: str) -> tuple[str, OperatorProfile]:
        """Build the `sign` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("sign", {}, f"sign({x})")

    @staticmethod
    def sqrt(x: str) -> tuple[str, OperatorProfile]:
        """Build the `sqrt` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile(
            "sqrt", {}, f"if_else({x} >= 0, sqrt({x}), sign({x})*sqrt(abs({x})))"
        )

    @staticmethod
    def tail(
        x: str,
        d: int | None=None,
        lower: float | None=None,
        upper: float | None=None,
        newval: float | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `tail` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        if lower is None:
            lower=FloatSampler.sample((0.0, 0.7), None, MatrixUnary.TAIL_LOWER_STREAM, distribution=distribution)
        if upper is None:
            upper=FloatSampler.sample((0.3, 1.0), None, MatrixUnary.TAIL_UPPER_STREAM, distribution=distribution)
        if newval is None:
            newval=FloatSampler.sample((0.0, 1.0), None, MatrixUnary.TAIL_NEWVAL_STREAM, distribution=distribution)
        lower, upper=min(lower, upper), max(lower, upper)
        return MatrixUnary._profile(
            "tail",
            {"d": d, "lower": lower, "upper": upper, "newval": newval},
            f"tail(ts_rank({x}, {d}), lower={lower:.4f}, upper={upper:.4f}, newval={newval:.4f})",
        )

    @staticmethod
    def trade_when(
        x: str,
        t1: float | None=None,
        t2: float | None=None,
        d1: int | None=None,
        d2: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced",
    ) -> tuple[str, OperatorProfile]:
        """Build the `trade_when` expression over one matrix field id.

        Trigger is `ts_rank(x, d1) > t1`, value is `x`, exit is `abs(ts_zscore(x, d2)) < t2`.
        Any of t1, t2, d1, d2 left as None is drawn with `distribution`: t1 and t2 from
        [0, 0.1], d1 and d2 independently from [60, 252].
        """
        if t1 is None:
            t1=FloatSampler.sample((0.0, 0.1), None, 1, distribution=distribution)
        if t2 is None:
            t2=FloatSampler.sample((0.0, 0.1), None, 2, distribution=distribution)
        if d1 is None:
            d1=IntegerSampler.sample((60, 252), None, 3, distribution=distribution)
        if d2 is None:
            d2=IntegerSampler.sample((60, 252), None, 4, distribution=distribution)
        return MatrixUnary._profile(
            "trade_when",
            {"t1": t1, "t2": t2, "d1": d1, "d2": d2},
            f"trade_when(ts_rank({x}, {d1}) > {t1}, {x}, abs(ts_zscore({x}, {d2})) < {t2})",
        )

    @staticmethod
    def ts_arg_max(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_arg_max` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_arg_max", {"d": d}, f"ts_arg_max({x}, {d})")

    @staticmethod
    def ts_arg_min(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_arg_min` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_arg_min", {"d": d}, f"ts_arg_min({x}, {d})")

    @staticmethod
    def ts_av_diff(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_av_diff` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_av_diff", {"d": d}, f"ts_av_diff({x}, {d})")

    @staticmethod
    def ts_backfill(
        x: str,
        d: int | None=None,
        k: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_backfill` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        if k is None:
            k=IntegerSampler.sample((1, 5), None, MatrixUnary.TS_BACKFILL_K_STREAM, distribution=distribution)
        return MatrixUnary._profile(
            "ts_backfill", {"lookback": d, "k": k}, f"ts_backfill({x}, lookback={d}, k={k})"
        )

    @staticmethod
    def ts_count_nans(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_count_nans` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile(
            "ts_count_nans", {"d": d}, f"ts_count_nans({x}, {d})"
        )

    @staticmethod
    def ts_decay_linear(
        x: str,
        d: int | None=None,
        dense: bool | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_decay_linear` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        if dense is None:
            dense=bool(IntegerSampler.sample((0, 1), None, MatrixUnary.DENSE_STREAM, distribution="uniform"))
        return MatrixUnary._profile(
            "ts_decay_linear",
            {"d": d, "dense": dense},
            f"ts_decay_linear({x}, {d}, dense={'true' if dense else 'false'})",
        )

    @staticmethod
    def ts_delay(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_delay` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_delay", {"d": d}, f"ts_delay({x}, {d})")

    @staticmethod
    def ts_delta(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_delta` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_delta", {"d": d}, f"ts_delta({x}, {d})")

    @staticmethod
    def ts_ir(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_ir` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_ir", {"d": d}, f"ts_ir({x}, {d})")

    @staticmethod
    def ts_kurtosis(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_kurtosis` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_kurtosis", {"d": d}, f"ts_kurtosis({x}, {d})")

    @staticmethod
    def ts_max_diff(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_max_diff` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_max_diff", {"d": d}, f"ts_max_diff({x}, {d})")

    @staticmethod
    def ts_mean(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_mean` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_mean", {"d": d}, f"ts_mean({x}, {d})")

    @staticmethod
    def ts_product(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_product` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_product", {"d": d}, f"ts_product({x}, {d})")

    @staticmethod
    def ts_quantile(
        x: str,
        d: int | None=None,
        driver: str | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_quantile` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        if driver is None:
            driver=MatrixUnary.DRIVERS[
                IntegerSampler.sample(
                    (0, len(MatrixUnary.DRIVERS) - 1), None, MatrixUnary.DRIVER_STREAM, distribution="uniform"
                )
            ]
        return MatrixUnary._profile(
            "ts_quantile",
            {"d": d, "driver": driver},
            f"ts_quantile({x}, {d}, driver='{driver}')",
        )

    @staticmethod
    def ts_rank(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_rank` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_rank", {"d": d}, f"ts_rank({x}, {d})")

    @staticmethod
    def ts_returns(
        x: str,
        d: int | None=None,
        mode: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_returns` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        if mode is None:
            mode=IntegerSampler.sample((1, 2), None, MatrixUnary.TS_RETURNS_MODE_STREAM, distribution="uniform")
        return MatrixUnary._profile(
            "ts_returns", {"d": d, "mode": mode}, f"ts_returns({x}, {d}, mode={mode})"
        )

    @staticmethod
    def ts_scale(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_scale` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_scale", {"d": d}, f"ts_scale({x}, {d})")

    @staticmethod
    def ts_std_dev(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_std_dev` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_std_dev", {"d": d}, f"ts_std_dev({x}, {d})")

    @staticmethod
    def ts_sum(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_sum` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_sum", {"d": d}, f"ts_sum({x}, {d})")

    @staticmethod
    def ts_target_tvr_decay(
        x: str,
        lambda_min: float | None=None,
        lambda_max: float | None=None,
        target_tvr: float | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_target_tvr_decay` FASTEXPR over one matrix field id."""
        if lambda_min is None:
            lambda_min=FloatSampler.sample(
                (0.0, 0.7), None, MatrixUnary.TS_TARGET_TVR_LAMBDA_MIN_STREAM, distribution=distribution
            )
        if lambda_max is None:
            lambda_max=FloatSampler.sample(
                (0.3, 1.0), None, MatrixUnary.TS_TARGET_TVR_LAMBDA_MAX_STREAM, distribution=distribution
            )
        if target_tvr is None:
            target_tvr=FloatSampler.sample(
                (0.1, 0.4), None, MatrixUnary.TS_TARGET_TVR_TARGET_STREAM, distribution=distribution
            )
        lambda_min, lambda_max=min(lambda_min, lambda_max), max(lambda_min, lambda_max)
        return MatrixUnary._profile(
            "ts_target_tvr_decay",
            {"lambda_min": lambda_min, "lambda_max": lambda_max, "target_tvr": target_tvr},
            f"ts_target_tvr_decay({x}, lambda_min={lambda_min:.4f}, lambda_max={lambda_max:.4f}, target_tvr={target_tvr:.4f})",
        )

    @staticmethod
    def ts_target_tvr_hump(
        x: str,
        lambda_min: float | None=None,
        lambda_max: float | None=None,
        target_tvr: float | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_target_tvr_hump` FASTEXPR over one matrix field id."""
        if lambda_min is None:
            lambda_min=FloatSampler.sample(
                (0.0, 0.7), None, MatrixUnary.TS_TARGET_TVR_LAMBDA_MIN_STREAM, distribution=distribution
            )
        if lambda_max is None:
            lambda_max=FloatSampler.sample(
                (0.3, 1.0), None, MatrixUnary.TS_TARGET_TVR_LAMBDA_MAX_STREAM, distribution=distribution
            )
        if target_tvr is None:
            target_tvr=FloatSampler.sample(
                (0.1, 0.6), None, MatrixUnary.TS_TARGET_TVR_TARGET_STREAM, distribution=distribution
            )
        lambda_min, lambda_max=min(lambda_min, lambda_max), max(lambda_min, lambda_max)
        return MatrixUnary._profile(
            "ts_target_tvr_hump",
            {"lambda_min": lambda_min, "lambda_max": lambda_max, "target_tvr": target_tvr},
            f"ts_target_tvr_hump({x}, lambda_min={lambda_min:.4f}, lambda_max={lambda_max:.4f}, target_tvr={target_tvr:.4f})",
        )

    @staticmethod
    def ts_zscore(
        x: str,
        d: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `ts_zscore` FASTEXPR over one matrix field id."""
        if d is None:
            d=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile("ts_zscore", {"d": d}, f"ts_zscore({x}, {d})")

    @staticmethod
    def winsorize(
        x: str,
        std: float | None=None,
        window: int | None=None,
        *,
        distribution: Literal["uniform", "balanced"]="balanced"
    ) -> tuple[str, OperatorProfile]:
        """Build the `winsorize` FASTEXPR over one matrix field id."""
        if std is None:
            std=FloatSampler.sample(
                (0.01, 0.2), None, MatrixUnary.WINSORIZE_STD_STREAM, distribution=distribution
            )
        if window is None:
            window=IntegerSampler.sample(
                MatrixUnary.WINDOW_DAYS,
                None,
                MatrixUnary.WINSORIZE_WINDOW_STREAM,
                distribution=distribution,
            )
        return MatrixUnary._profile(
            "winsorize",
            {"std": std, "window": window},
            f"winsorize(ts_rank({x},{window}), std={std:.4f})",
        )

    @staticmethod
    def zscore(x: str) -> tuple[str, OperatorProfile]:
        """Build the `zscore` FASTEXPR over one matrix field id."""
        return MatrixUnary._profile("zscore", {}, f"zscore({x})")


class Vector:
    """The VECTOR operators: one matrix field in, one scalar out.

    Every operator in this bucket consumes exactly one matrix field and
    returns a scalar by reducing cross-sectional. No sampled parameters.
    """

    @staticmethod
    def get(
        name: str,
        x: str,
    ) -> tuple[str, OperatorProfile]:
        """Build the named VECTOR operator.

        `name` is the operator name as the platform spells it, `x` is one
        matrix field id.

        Returns a tuple of (expression, profile) where expression is the
        FASTEXPR string and profile contains category, name, and config.
        """
        builders={
            "vec_avg": Vector.vec_avg,
            "vec_count": Vector.vec_count,
            "vec_max": Vector.vec_max,
            "vec_min": Vector.vec_min,
            "vec_range": Vector.vec_range,
            "vec_stddev": Vector.vec_stddev,
            "vec_sum": Vector.vec_sum,
        }
        if name not in builders:
            raise ValueError(f"Unknown VECTOR operator: {name}")
        return builders[name](x)

    @staticmethod
    def _profile(
        name: str,
        config: dict[str, int | bool | float | str],
        expression: str,
    ) -> tuple[str, OperatorProfile]:
        """Assemble the expression and profile of one built operator call.

        `config` holds the arguments that are not matrix fields and that the
        draw produced. For VECTOR, config is always empty since no parameters
        are sampled.

        Returns a tuple of (expression, profile).
        """
        profile: OperatorProfile={
            "category": "VECTOR",
            "name": name,
            "config": config,
        }
        return (expression, profile)

    @staticmethod
    def vec_avg(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_avg` FASTEXPR over one matrix field."""
        return Vector._profile("vec_avg", {}, f"vec_avg({x})")

    @staticmethod
    def vec_count(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_count` FASTEXPR over one matrix field."""
        return Vector._profile("vec_count", {}, f"vec_count({x})")

    @staticmethod
    def vec_max(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_max` FASTEXPR over one matrix field."""
        return Vector._profile("vec_max", {}, f"vec_max({x})")

    @staticmethod
    def vec_min(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_min` FASTEXPR over one matrix field."""
        return Vector._profile("vec_min", {}, f"vec_min({x})")

    @staticmethod
    def vec_range(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_range` FASTEXPR over one matrix field."""
        return Vector._profile("vec_range", {}, f"vec_range({x})")

    @staticmethod
    def vec_stddev(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_stddev` FASTEXPR over one matrix field."""
        return Vector._profile("vec_stddev", {}, f"vec_stddev({x})")

    @staticmethod
    def vec_sum(x: str) -> tuple[str, OperatorProfile]:
        """Build the `vec_sum` FASTEXPR over one matrix field."""
        return Vector._profile("vec_sum", {}, f"vec_sum({x})")


class Group:
    """The GROUP operators: bucket and group aggregation operations.
    
    This class builds GROUP operators with randomized bucket parameters
    (min, max, step) and boolean flags (skipBoth, NaNGroup), each drawn on
    its own entropy stream for reproducibility.
    """
    
    # Entropy streams for bucket parameters and boolean flags
    BUCKET_MIN_STREAM = 13
    BUCKET_MAX_STREAM = 14
    BUCKET_STEP_STREAM = 15
    SKIP_BOTH_STREAM = 16
    NAN_GROUP_STREAM = 17
    
    # Range bounds for bucket parameters
    BUCKET_MIN_RANGE = (0.0, 0.8)
    BUCKET_MAX_RANGE = (0.2, 1.0)
    BUCKET_STEP_RANGE = (0.02, 0.15)
    
    @staticmethod
    def get(
        name: str,
        x: str,
        group: str,
        *,
        weight_mode: int | None = None,
        mode: int | None = None,
        d: int | None = None,
        std: float | None = None,
        window: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: Literal["uniform", "balanced"] = "balanced",
    ) -> tuple[str, OperatorProfile]:
        """Build the named GROUP operator.
        
        `name` is the operator name, `x` is the field, `group` is the grouping
        field. For `group_mean`, `weight_mode` controls the weight expression.
        Numeric parameters are drawn at random when left out, each on its own 
        entropy stream.
        
        Returns a tuple of (expression, profile).
        """
        builders = {
            "group_backfill": Group.group_backfill,
            "group_count": Group.group_count,
            "group_mean": Group.group_mean,
            "group_neutralize": Group.group_neutralize,
            "group_rank": Group.group_rank,
            "group_scale": Group.group_scale,
            "group_std_dev": Group.group_std_dev,
            "group_sum": Group.group_sum,
            "group_zscore": Group.group_zscore,
        }
        builder = builders[name]
        if name == "group_mean":
            return builder(
                x, group,
                mode=mode, weight_mode=weight_mode,
                bucket_range=bucket_range, skip_both=skip_both, nan_group=nan_group,
                distribution=distribution
            )
        else:
            return builder(
                x, group,
                mode=mode, d=d, std=std, window=window,
                bucket_range=bucket_range, skip_both=skip_both, nan_group=nan_group,
                distribution=distribution
            )
    
    @staticmethod
    def _profile(
        name: str,
        config: dict[str, int | float | bool],
        expression: str,
    ) -> tuple[str, OperatorProfile]:
        """Assemble the expression and profile of one built operator call."""
        profile: OperatorProfile = {
            "category": "GROUP",
            "name": name,
            "config": config,
        }
        return (expression, profile)
    
    @staticmethod
    def _sample_bucket_params(
        bucket_range: tuple[float, float, float] | None,
        distribution: str,
    ) -> tuple[float, float, float]:
        """Sample or unpack bucket range parameters.
        
        Returns (bucket_min, bucket_max, bucket_step) with min < max guaranteed.
        """
        if bucket_range is None:
            bucket_min = FloatSampler.sample(Group.BUCKET_MIN_RANGE, None, Group.BUCKET_MIN_STREAM, distribution=distribution)
            bucket_max = FloatSampler.sample(Group.BUCKET_MAX_RANGE, None, Group.BUCKET_MAX_STREAM, distribution=distribution)
            bucket_step = FloatSampler.sample(Group.BUCKET_STEP_RANGE, None, Group.BUCKET_STEP_STREAM, distribution=distribution)
            bucket_min, bucket_max = min(bucket_min, bucket_max), max(bucket_min, bucket_max)
        else:
            bucket_min, bucket_max, bucket_step = bucket_range
        return bucket_min, bucket_max, bucket_step
    
    @staticmethod
    def _sample_flags(
        skip_both: int | None,
        nan_group: int | None,
    ) -> tuple[str, str]:
        """Sample or unpack boolean flags and convert to string representation."""
        if skip_both is None:
            skip_both = IntegerSampler.sample((0, 1), None, Group.SKIP_BOTH_STREAM, distribution="uniform")
        if nan_group is None:
            nan_group = IntegerSampler.sample((0, 1), None, Group.NAN_GROUP_STREAM, distribution="uniform")
        
        skip_both_bool = "True" if skip_both == 1 else "False"
        nan_group_bool = "True" if nan_group == 1 else "False"
        return skip_both_bool, nan_group_bool
    
    @staticmethod
    def group_backfill(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        d: int | None = None,
        std: float | None = None,
        window: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_backfill` operator."""
        if d is None:
            d = IntegerSampler.sample((1, 252), None, 1, distribution=distribution)
        if std is None:
            std = FloatSampler.sample((0.01, 0.2), None, 2, distribution=distribution)
        if window is None:
            window = IntegerSampler.sample((1, 252), None, 12, distribution=distribution)
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 3, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        _x = f"ts_rank({x}, {window})"
        
        config = {"d": d, "std": f"{std:.2f}", "window": window, "mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_backfill({_x}, densify({group}), {d}, std = {std:.2f})"
        elif mode == 3:
            _group = f"bucket(rank({_x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_backfill({_x}, densify({_group}), {d}, std = {std:.2f})"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({_x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_backfill({_x}, densify({_group}), {d}, std = {std:.2f})"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({_x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_backfill({_x}, {_group}, {d}, std = {std:.2f})"
        else:
            expr = f"group_backfill({_x}, {group}, {d}, std = {std:.2f})"
        
        return Group._profile("group_backfill", config, expr)
    
    @staticmethod
    def group_count(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_count` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 4, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_count({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_count({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_count({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_count({x}, {_group})"
        else:
            expr = f"group_count({x}, {group})"
        
        return Group._profile("group_count", config, expr)
    
    @staticmethod
    def group_mean(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        weight_mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_mean` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 5, distribution="uniform")
        
        if weight_mode is None:
            weight_mode = IntegerSampler.sample((1, 5), None, 18, distribution="uniform")
        
        weight_map = {
            1: "1",
            2: "cap",
            3: "volume",
            4: "volume/cap",
            5: "ts_step(1)",
        }
        weight = weight_map[weight_mode]
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "weight_mode": weight_mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_mean({x}, {weight}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_mean({x}, {weight}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_mean({x}, {weight}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_mean({x}, {weight}, {_group})"
        else:
            expr = f"group_mean({x}, {weight}, {group})"
        
        return Group._profile("group_mean", config, expr)
    
    @staticmethod
    def group_neutralize(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_neutralize` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 6, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_neutralize({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_neutralize({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_neutralize({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_neutralize({x}, {_group})"
        else:
            expr = f"group_neutralize({x}, {group})"
        
        return Group._profile("group_neutralize", config, expr)
    
    @staticmethod
    def group_rank(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_rank` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 7, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_rank({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_rank({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_rank({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_rank({x}, {_group})"
        else:
            expr = f"group_rank({x}, {group})"
        
        return Group._profile("group_rank", config, expr)
    
    @staticmethod
    def group_scale(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_scale` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 8, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_scale({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_scale({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_scale({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_scale({x}, {_group})"
        else:
            expr = f"group_scale({x}, {group})"
        
        return Group._profile("group_scale", config, expr)
    
    @staticmethod
    def group_std_dev(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_std_dev` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 9, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_std_dev({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_std_dev({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_std_dev({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_std_dev({x}, {_group})"
        else:
            expr = f"group_std_dev({x}, {group})"
        
        return Group._profile("group_std_dev", config, expr)
    
    @staticmethod
    def group_sum(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_sum` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 10, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_sum({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_sum({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_sum({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_sum({x}, {_group})"
        else:
            expr = f"group_sum({x}, {group})"
        
        return Group._profile("group_sum", config, expr)
    
    @staticmethod
    def group_zscore(
        x: str,
        group: str,
        *,
        mode: int | None = None,
        bucket_range: tuple[float, float, float] | None = None,
        skip_both: int | None = None,
        nan_group: int | None = None,
        distribution: str = "balanced",
        **kwargs,
    ) -> tuple[str, OperatorProfile]:
        """Build the `group_zscore` operator."""
        if mode is None:
            mode = IntegerSampler.sample((1, 5), None, 11, distribution="uniform")
        
        bucket_min, bucket_max, bucket_step = Group._sample_bucket_params(bucket_range, distribution)
        skip_both_bool, nan_group_bool = Group._sample_flags(skip_both, nan_group)
        
        config = {"mode": mode, "skip_both": skip_both_bool, "nan_group": nan_group_bool}
        
        if mode == 2:
            expr = f"group_zscore({x}, densify({group}))"
        elif mode == 3:
            _group = f"bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool})"
            expr = f"group_zscore({x}, densify({_group}))"
        elif mode == 4:
            _group = f"group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group})"
            expr = f"group_zscore({x}, densify({_group}))"
        elif mode == 5:
            _group = f"densify(group_cartesian_product(bucket(rank({x}), range='{bucket_min:.4f}, {bucket_max:.4f}, {bucket_step:.4f}', skipBoth={skip_both_bool}, NaNGroup={nan_group_bool}), {group}))"
            expr = f"group_zscore({x}, {_group})"
        else:
            expr = f"group_zscore({x}, {group})"
        
        return Group._profile("group_zscore", config, expr)
