"""Local columnar cache of the BRAIN catalog: one .npz per (scope, field type).

Each scope gets its own folder named after the three varying scope parts
(region / delay / universe), holding one .npz per field type. The folder
boundary is what keeps scopes apart: the same field type is re-fetched whenever
the scope changes, and a flat cache directory would mix snapshots of different
scopes together.

np.load is lazy per archive member: a member is decompressed only when it is
first touched. Rows are therefore stored in blocks of CHUNK_ROWS and each
column is a separate member, so fetching a handful of rows touches only the
blocks and columns it needs instead of the whole catalog.

Each archive holds every field of one type for one scope, with the *raw* snapshot
columns kept intact. Eligibility is re-derived from those columns on every read,
so the coverage threshold can change without re-downloading the catalog.

The archive also carries what a run needs to be reproducible against it: the
scope it was fetched for, the fetch timestamp, and the frame id (content hash
of the field ids), which pins the catalog snapshot the cache holds.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Rows per stored block. Large enough that a full scan pays little per-member
# overhead, small enough that one sampled row does not drag in megabytes of
# unrelated text.
CHUNK_ROWS = 8192

# Field types cached separately. MATRIX and VECTOR feed different expression
# semantics; GROUP is not an alpha input at all, so the three are never mixed.
FIELD_TYPES = ("MATRIX", "VECTOR", "GROUP")

CACHE_DIR = Path(__file__).parent.parent / "cache"


def scope_key(scope: dict) -> str:
    """Folder name identifying one scope tuple.

    `instrumentType` is a platform constant (see `Functions/data.py`), so only
    the three varying parts identify a scope.
    """
    return "_".join(str(scope[k]) for k in ("region", "delay", "universe"))


def scope_dir(scope: dict, cache_dir: Path = CACHE_DIR) -> Path:
    """Folder holding the cached archives of one scope."""
    return cache_dir / scope_key(scope)


def cached_scope(scope: dict, cache_dir: Path = CACHE_DIR) -> dict[str, Path] | None:
    """Return the cached archive of every field type, or None if any is missing.

    The whole scope is present or none of it is: a partially fetched scope
    would silently mix a fresh catalog with a stale one.
    """
    folder = scope_dir(scope, cache_dir)
    paths = {ft: folder / f"{ft.lower()}.npz" for ft in FIELD_TYPES}
    if not all(p.exists() for p in paths.values()):
        return None
    return paths


def frame_id(field_ids) -> str:
    """Content hash of the field id set, so a run can name its catalog snapshot."""
    return hashlib.sha256("\n".join(sorted(str(i) for i in field_ids)).encode()).hexdigest()[:8]


def save_cache(
    scope: dict,
    frame: pd.DataFrame,
    field_type: str,
    catalog_total: int | None = None,
    catalog_frame_id: str | None = None,
    cache_dir: Path = CACHE_DIR,
) -> Path:
    """Write one (scope, field type) catalog snapshot to disk as a chunked .npz."""
    columns = list(frame.columns)
    n_chunks = max(1, (len(frame) + CHUNK_ROWS - 1) // CHUNK_ROWS)

    # Two dtype maps on purpose: `numpy` is what goes into the archive (pickle-free,
    # so allow_pickle=False stays valid), `pandas` is what `take()` restores, so a
    # round trip returns the original dtypes and not merely equal values.
    numpy_dtypes, pandas_dtypes = {}, {}
    arrays = {}
    for col in columns:
        series = frame[col]
        pandas_dtypes[col] = str(series.dtype)
        if pd.api.types.is_bool_dtype(series):
            numpy_dtypes[col] = "int8"
            encoded = series.to_numpy(dtype="int8")
        elif pd.api.types.is_numeric_dtype(series):
            numpy_dtypes[col] = "float64"
            encoded = series.to_numpy(dtype="float64", na_value=np.nan)
        else:
            numpy_dtypes[col] = "str"
            encoded = series.fillna("").astype(str).to_numpy(dtype="U")
        for k in range(n_chunks):
            arrays[f"c::{col}::{k}"] = encoded[k * CHUNK_ROWS : (k + 1) * CHUNK_ROWS]

    arrays["meta"] = np.array(
        json.dumps(
            {
                "scope": scope,
                "field_type": field_type,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "n_rows": len(frame),
                "chunk_rows": CHUNK_ROWS,
                "n_chunks": n_chunks,
                "columns": columns,
                "numpy_dtypes": numpy_dtypes,
                "pandas_dtypes": pandas_dtypes,
                "frame_id": frame_id(frame["fieldid"]) if "fieldid" in frame.columns else None,
                "catalog_frame_id": catalog_frame_id,
                "catalog_total": catalog_total,
            }
        )
    )

    folder = scope_dir(scope, cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{field_type.lower()}.npz"
    np.savez_compressed(path, **arrays)
    return path


class ScopeCache:
    """Read side of one cached (scope, field type) snapshot: rows by position, block by block."""

    def __init__(self, path: Path):
        self._npz = np.load(path, allow_pickle=False)
        meta = json.loads(self._npz["meta"].item())
        self.meta = meta
        self.columns = list(meta["columns"])
        self.numpy_dtypes = meta["numpy_dtypes"]
        self.pandas_dtypes = meta["pandas_dtypes"]
        self.chunk_rows = int(meta["chunk_rows"])
        self.n_rows = int(meta["n_rows"])
        self.field_type = meta["field_type"]
        self.scope = meta["scope"]
        self.catalog_total = meta.get("catalog_total")
        self.catalog_frame_id = meta.get("catalog_frame_id")
        self.fetched_at = meta.get("fetched_at")

    def close(self) -> None:
        self._npz.close()

    def _numpy_dtype(self, col: str) -> np.dtype:
        kind = self.numpy_dtypes[col]
        return np.dtype("O") if kind == "str" else np.dtype(kind)

    def column(self, col: str) -> np.ndarray:
        """Read one whole column back, joining its blocks."""
        blocks = [
            self._npz[f"c::{col}::{k}"]
            for k in range(int(self.meta["n_chunks"]))
        ]
        return np.concatenate(blocks) if blocks else np.array([])

    def eligible_positions(self, min_coverage: float) -> np.ndarray:
        """Row positions whose own coverage and dateCoverage both clear the threshold.

        Derived from the stored raw columns rather than saved as a member, so
        the threshold is a live parameter instead of a value frozen at save
        time. A missing dateCoverage is NaN and therefore fails the comparison.
        """
        coverage = self.column("coverage")
        date_coverage = self.column("dateCoverage")
        mask = (coverage > min_coverage) & (date_coverage > min_coverage)
        return np.flatnonzero(mask).astype(np.int64)

    def take(self, indices, columns=None) -> pd.DataFrame:
        """Return the rows at the given positions, touching only the blocks they fall in.

        `columns` narrows the read further: each column is a separate archive
        member, so reading only the columns a caller needs avoids decompressing
        the rest.
        """
        cols = list(self.columns) if columns is None else list(columns)
        idx = np.asarray(indices, dtype=np.int64)
        if idx.size == 0:
            return pd.DataFrame({c: pd.Series(dtype=self.pandas_dtypes[c]) for c in cols})

        # Rows are gathered block by block, so scatter back to caller's order.
        order = np.argsort(idx, kind="stable")
        sorted_idx = idx[order]
        blocks = sorted_idx // self.chunk_rows
        restore = np.argsort(order)

        data = {}
        for col in cols:
            values = np.empty(sorted_idx.size, dtype=self._numpy_dtype(col))
            for block in np.unique(blocks):
                mask = blocks == block
                local = sorted_idx[mask] - int(block) * self.chunk_rows
                values[mask] = self._npz[f"c::{col}::{int(block)}"][local]
            data[col] = values[restore]

        frame = pd.DataFrame(data)
        for col in cols:
            frame[col] = frame[col].astype(self.pandas_dtypes[col])
        return frame
