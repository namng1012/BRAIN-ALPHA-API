"""The FASTEXPR operator table: the operators the platform publishes, typed by
the data field they consume.

`/operators` is the one BRAIN endpoint that is not scope-scoped, so the table is
fetched once and cached as a CSV in the cache folder; a later run finds the file
and spends neither a request nor a login.
"""

import re
from pathlib import Path

import pandas as pd

from Functions.cache import CACHE_DIR
from Functions.data import BrainData

# The operator table sits next to the scope snapshots in the cache folder.
OPERATORS_CSV_PATH = CACHE_DIR / "operators.csv"

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
            re.match(r"[A-Za-z0-9_]*", p.split("=")[0].strip().rsplit("(", 1)[-1]).group()
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
        # ".." in the definition is the platform's own variadic marker. A select
        # operator is one whose arguments are all data fields and number three or
        # more; checked against the live catalog, that selects exactly if_else
        # and trade_when.
        if is_select:
            return "SELECT"
        if ".." in definition:
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
        regular = operators[operators["scope"] == "REGULAR"].reset_index(drop=True).copy()

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
                    self.bucket_of(name, definition, category, self.arg_names(definition))
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
