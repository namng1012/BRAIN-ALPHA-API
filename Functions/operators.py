"""The FASTEXPR operator table: the operators the platform publishes, typed by
the data field they consume.

`/operators` is the one BRAIN endpoint that is not scope-scoped, so the table is
fetched once and cached as a CSV in the cache folder; a later run finds the file
and spends neither a request nor a login.
"""

import itertools
import os
import re
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np
import pandas as pd

from Functions.cache import CACHE_DIR
from Functions.data import BrainData

# The operator table sits next to the scope snapshots in the cache folder.
OPERATORS_CSV_PATH = CACHE_DIR / "operators.csv"


# The profile of one built operator call. The functional form is used because
# the `inputs matrics` key carries a space, which the class syntax cannot
# express.
OperatorProfile = TypedDict(
    "OperatorProfile",
    {
        "category": str,
        "name": str,
        "config": dict[str, int | bool],
        "inputs matrics": list[str],
        "expression": str,
    },
)
OperatorProfile.__doc__ = """One built operator call: what it is, how it is configured, what it reads.

`category` is the bucket the operator belongs to, `name` the operator's own
name, `config` the arguments that are not matrix fields with the values the
platform receives, `inputs matrics` the matrix fields in the order they reach
the platform, and `expression` the FASTEXPR itself.
"""

# The data-field arguments of an operator call. The numeric and keyword
# arguments (d, k, lag, rettype, filter, std) are not matrix fields, so
# ts_corr(x, y, d) counts as two inputs and ts_mean(x, d) as one.
DATA_ARGS = {"x", "y", "z", "input", "input1", "input2", "input3"}

# The buckets, in the order a FASTEXPR walks through the data flow. The order
# is the order the rows appear in the CSV.
BUCKETS = (
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

    def __init__(self, data: BrainData, path: Path = OPERATORS_CSV_PATH):
        self.data = data
        self.path = path

    @staticmethod
    def load(path: Path = OPERATORS_CSV_PATH) -> pd.DataFrame:
        """Read the cached table from disk.

        `category` comes back as an ordered categorical so it sorts in the same
        bucket order a freshly fetched table has.
        """
        table = pd.read_csv(path, encoding="utf-8")
        table["category"] = pd.Categorical(
            table["category"], categories=BUCKETS, ordered=True
        )
        return table

    @staticmethod
    def arg_names(definition: str) -> list[str]:
        """Top-level argument names of the first balanced call in a definition.

        Keyword defaults are stripped. Nested calls like bucket(rank(x), ...) are
        not arguments of their own, so the result is only a lower bound on arity.
        """
        start = definition.find("(")
        if start < 0:
            return []

        depth, parts, current = 0, [], ""
        for char in definition[start + 1 :]:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current)
                current = ""
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
        is_select = len(args) >= 3 and all(n in DATA_ARGS for n in args)
        # bucket and densify are named explicitly: their typing is stated only in
        # their prose description, and matching on that wording would silently
        # reclassify them the day WorldQuant rewords it. group_cartesian_product
        # falls out structurally instead — it is the one group_ operator that never
        # names a group argument.
        is_grouping = name in ("bucket", "densify") or (
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
        n_matrix = sum(1 for n in args if n in DATA_ARGS)
        return "MATRIX_BINARY" if n_matrix == 2 else "MATRIX_UNARY"

    def fetch(self) -> pd.DataFrame:
        """Fetch /operators, classify it, write the CSV, and return the table."""
        payload = self.data._get(self.data.base_url + "/operators")
        if isinstance(payload, dict):
            raise RuntimeError(f"/operators returned an error: {payload}")

        operators = pd.DataFrame(payload).explode("scope")
        regular = (
            operators[operators["scope"] == "REGULAR"].reset_index(drop=True).copy()
        )

        # bucket ships a multi-line definition, which would break a one-line
        # reading of the table.
        regular["definition"] = (
            regular["definition"].str.replace(r"\s+", " ", regex=True).str.strip()
        )
        # The platform ships some descriptions with CRLF line endings and the CSV
        # writer keeps them verbatim, so they are normalised to keep the file's
        # line endings uniform.
        regular["description"] = regular["description"].str.replace(
            "\r\n", "\n", regex=False
        )

        table = pd.DataFrame(
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
        table["category"] = pd.Categorical(
            table["category"], categories=BUCKETS, ordered=True
        )
        table = table.sort_values(["category", "name"])
        table.to_csv(self.path, index=False, encoding="utf-8")
        return table


class IntegerSampler:
    """Draws integers from an inclusive range, uniformly or in balanced buckets.

    The balanced distribution splits the range into five buckets cut at fixed
    *fractions* of the range rather than at fixed day counts: the range size is
    not fixed (a rolling window may be 252 days, a lag may be 5), so the cut
    points scale with it.

    The fractions are the quintiles of a 252-trading-day year, so a 252-day
    window splits into 1-5, 6-22, 23-66, 67-126 and 127-252. Any other range
    keeps the same proportions.
    """

    # The cut points of the five buckets, as fractions of the range size.
    BUCKET_FRACTIONS = (5 / 252, 22 / 252, 66 / 252, 126 / 252)

    # The number of buckets a balanced draw splits the range into.
    BUCKET_COUNT = len(BUCKET_FRACTIONS) + 1

    @classmethod
    def buckets(cls, min_value: int, max_value: int) -> list[tuple[int, int]]:
        """Partition an inclusive integer range into five nonempty buckets.

        The cuts are the range's quintiles: a 252-value range splits into
        1-5, 6-22, 23-66, 67-126 and 127-252, and a smaller range keeps the same
        proportions.
        """
        count = max_value - min_value + 1
        if count < cls.BUCKET_COUNT:
            # Too few integers to split: each bucket is a single value.
            return [(value, value) for value in range(min_value, max_value + 1)]

        # Bucket boundaries are end-exclusive offsets from min_value.
        cuts = [0]
        for index, fraction in enumerate(cls.BUCKET_FRACTIONS, start=1):
            scaled_cut = round(count * fraction)
            # Every bucket must hold at least one integer, so a cut may not fall
            # below the previous one nor above the room left for the later buckets.
            lower_bound = cuts[-1] + 1
            upper_bound = count - (cls.BUCKET_COUNT - index)
            cuts.append(max(lower_bound, min(scaled_cut, upper_bound)))
        cuts.append(count)

        return [
            (min_value + left, min_value + right - 1)
            for left, right in itertools.pairwise(cuts)
        ]

    @classmethod
    def sample(
        cls,
        value_range: tuple[int, int],
        seed: int | None = None,
        stream: int = 0,
        *,
        distribution: Literal["uniform", "balanced"] = "uniform",
    ) -> int:
        """Draw one integer from the inclusive range `value_range`.

        `distribution="uniform"` (default): every integer is equally likely.

        `distribution="balanced"`: one of the five buckets is drawn uniformly,
        then an integer inside that bucket is drawn uniformly. The buckets are the
        range's quintiles, so a 252-value range splits into 1-5, 6-22, 23-66,
        67-126 and 127-252, each with probability 20%. Every integer stays
        possible, but the probability of any single integer is not equal across
        the range.

        `seed=None` draws fresh entropy from the OS CSPRNG, so the draw is not
        anchored to any fixed constant.

        `stream` picks the entropy sub-stream: draws that share a seed but sit on
        different streams are independent, so adding a new draw for another
        category never shifts the value an existing draw produces. The same seed
        and stream replay the same integer bit-exact.
        """
        min_value, max_value = value_range
        if min_value > max_value:
            raise ValueError("value_range must be an inclusive (min, max) pair")
        if distribution not in ("uniform", "balanced"):
            raise ValueError("distribution must be 'uniform' or 'balanced'")

        if seed is None:
            seed = int.from_bytes(os.urandom(8), "big")
        rng = np.random.default_rng([seed, stream])

        if distribution == "uniform":
            return int(rng.integers(min_value, max_value + 1))

        buckets = cls.buckets(min_value, max_value)
        bucket = buckets[int(rng.integers(0, len(buckets)))]
        return int(rng.integers(bucket[0], bucket[1] + 1))


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
    WINDOW_DAYS = (1, 252)

    # The lag ts_regression shifts x by before the fit.
    LAG = (0, 5)

    # The ts_regression output types: 0 residual, 1 beta, 2 alpha, 3 predicted
    # value, 4 correlation, 5 R-squared, 6-9 t-statistics and standard errors.
    RETTYPE = (0, 9)

    @staticmethod
    def get(
        name: str,
        x: str,
        y: str,
        *,
        distribution: Literal["uniform", "balanced"] = "uniform",
    ) -> OperatorProfile:
        """Build the profile of the named MATRIX_BINARY operator.

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
        """
        builders = {
            "add": MatrixBinary.add,
            "divide": MatrixBinary.divide,
            "multiply": MatrixBinary.multiply,
            "power": MatrixBinary.power,
            "signed_power": MatrixBinary.signed_power,
            "subtract": MatrixBinary.subtract,
            "ts_corr": MatrixBinary.ts_corr,
            "ts_covariance": MatrixBinary.ts_covariance,
            "ts_regression": MatrixBinary.ts_regression,
            "vector_neut": MatrixBinary.vector_neut,
        }
        builder = builders[name]
        # Only the ts_* operators take a window, so only they take a
        # distribution; the rest would reject the keyword.
        if name.startswith("ts_"):
            return builder(x, y, distribution=distribution)
        return builder(x, y)

    @staticmethod
    def _profile(
        name: str,
        config: dict[str, int | bool],
        inputs: list[str],
        expression: str,
    ) -> OperatorProfile:
        """Assemble the profile of one built operator call.

        `config` holds the arguments that are not matrix fields and that the
        draw produced — the window `d`, the `lag` and the `rettype`. The
        arguments fixed by the operator itself are not listed: they do not
        change with the seed, so they are not needed to replay the call.
        `inputs` holds the matrix fields in the order they reach the platform.
        """
        return {
            "category": "MATRIX_BINARY",
            "name": name,
            "config": config,
            "inputs matrics": inputs,
            "expression": expression,
        }

    @staticmethod
    def add(x: str, y: str) -> OperatorProfile:
        """Build the `add` FASTEXPR over two matrix field ids.

        `filter = true` treats NaN as 0 before summing.
        """
        return MatrixBinary._profile(
            "add",
            {},
            [x, y],
            f"add({x}, {y}, filter = true)",
        )

    @staticmethod
    def divide(x: str, y: str) -> OperatorProfile:
        """Build the `divide` FASTEXPR over two matrix field ids.

        The platform's `divide` takes no `filter` argument, so NaN propagates and a
        zero denominator raises — the caller guards it with an epsilon instead.
        """
        return MatrixBinary._profile(
            "divide",
            {},
            [x, y],
            f"divide({x}, {y})",
        )

    @staticmethod
    def multiply(x: str, y: str) -> OperatorProfile:
        """Build the `multiply` FASTEXPR over two matrix field ids.

        `filter = true` treats NaN as 1 before multiplying.
        """
        return MatrixBinary._profile(
            "multiply",
            {},
            [x, y],
            f"multiply({x}, {y}, filter = true)",
        )

    @staticmethod
    def power(x: str, y: str) -> OperatorProfile:
        """Build the `power` FASTEXPR over two matrix field ids.

        The platform's `power` takes no `filter` argument.
        """
        return MatrixBinary._profile(
            "power",
            {},
            [x, y],
            f"power({x}, {y})",
        )

    @staticmethod
    def signed_power(x: str, y: str) -> OperatorProfile:
        """Build the `signed_power` FASTEXPR over two matrix field ids.

        The platform's `signed_power` takes no `filter` argument.
        """
        return MatrixBinary._profile(
            "signed_power",
            {},
            [x, y],
            f"signed_power({x}, {y})",
        )

    @staticmethod
    def subtract(x: str, y: str) -> OperatorProfile:
        """Build the `subtract` FASTEXPR over two matrix field ids.

        `filter = true` treats NaN as 0 before subtracting.
        """
        return MatrixBinary._profile(
            "subtract",
            {},
            [x, y],
            f"subtract({x}, {y}, filter = true)",
        )

    @staticmethod
    def ts_corr(
        x: str,
        y: str,
        d: int | None = None,
        seed: int | None = None,
        *,
        distribution: Literal["uniform", "balanced"] = "balanced",
    ) -> OperatorProfile:
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
            d = IntegerSampler.sample(
                MatrixBinary.WINDOW_DAYS, seed, 1, distribution=distribution
            )
        return MatrixBinary._profile(
            "ts_corr",
            {"d": d},
            [x, y],
            f"ts_corr({x}, {y}, {d})",
        )

    @staticmethod
    def ts_covariance(
        y: str,
        x: str,
        d: int | None = None,
        seed: int | None = None,
        *,
        distribution: Literal["uniform", "balanced"] = "balanced",
    ) -> OperatorProfile:
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
            d = IntegerSampler.sample(
                MatrixBinary.WINDOW_DAYS, seed, 1, distribution=distribution
            )
        return MatrixBinary._profile(
            "ts_covariance",
            {"d": d},
            [y, x],
            f"ts_covariance({y}, {x}, {d})",
        )

    @staticmethod
    def ts_regression(
        y: str,
        x: str,
        d: int | None = None,
        lag: int | None = None,
        rettype: int | None = None,
        seed: int | None = None,
        *,
        distribution: Literal["uniform", "balanced"] = "balanced",
    ) -> OperatorProfile:
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
            seed = int.from_bytes(os.urandom(8), "big")
        if d is None:
            d = IntegerSampler.sample(
                MatrixBinary.WINDOW_DAYS, seed, 1, distribution=distribution
            )
        if lag is None:
            # Entropy stream 3, separate from the window's stream 1 and rettype's
            # stream 2, so the draw of one does not shift the others.
            lag = IntegerSampler.sample(MatrixBinary.LAG, seed, 3)
        if rettype is None:
            # Entropy stream 2, separate from the window's stream 1, so the draw of
            # one does not shift the other.
            rettype = IntegerSampler.sample(MatrixBinary.RETTYPE, seed, 2)
        return MatrixBinary._profile(
            "ts_regression",
            {"d": d, "lag": lag, "rettype": rettype},
            [y, x],
            f"ts_regression({y}, {x}, {d}, lag = {lag}, rettype = {rettype})",
        )

    @staticmethod
    def vector_neut(x: str, y: str) -> OperatorProfile:
        """Build the `vector_neut` FASTEXPR: the component of x orthogonal to y.

        Cross-sectional: it strips the linear projection of x onto y, leaving x* with
        x* . y = 0. "Vector" is the alpha position vector, not a VECTOR-type field.
        """
        return MatrixBinary._profile(
            "vector_neut",
            {},
            [x, y],
            f"vector_neut({x}, {y})",
        )
