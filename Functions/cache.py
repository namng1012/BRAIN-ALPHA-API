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

Each archive holds every *eligible* field of one type for one scope: the
coverage filter is applied when the catalog is fetched, before the type split,
so a field too sparse to backtest on is never written to disk. The stored
coverage / dateCoverage columns stay in the snapshot and `catalog_total` keeps
the pre-filter count, so how many fields the filter rejected is still
recoverable from the archive.

The archive also carries what a run needs to be reproducible against it: the
scope it was fetched for, the fetch timestamp, and the frame id (content hash
of the field ids), which pins the catalog snapshot the cache holds.

Two levels, split by what each one owns. `CatalogCache` is the folder level: it
knows where a scope's archives live, whether they are there, how old they are,
and how to write one. `ScopeCache` is the archive level: it opens one .npz and
hands back rows by position. `frame_id` stays a plain function — it is a pure
content hash with no cache state behind it.
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

# The BRAIN catalog is a moving target: fields are added, deprecated and have
# their coverage revised continuously. A cached .npz is a fixed snapshot, so once
# it is older than this it is re-fetched rather than sampled. Same shape as
# RELOGIN_THRESHOLD_SECONDS in login.py — a deadline measured from when the
# resource was obtained, checked before it is used rather than after it turns
# out to be wrong. 15 days is the platform's catalog update cadence.
CATALOG_MAX_AGE_SECONDS = 15 * 24 * 3600


def frame_id(field_ids) -> str:
    """Content hash of the field id set, so a run can name its catalog snapshot."""
    return hashlib.sha256("\n".join(sorted(str(i) for i in field_ids)).encode()).hexdigest()[:8]


class CatalogCache:
    """The folder level of the cache: where a scope's archives live and how they age.

    One instance owns one cache root, so the root is threaded through a single
    object instead of a `cache_dir` argument repeated on every call. `ScopeCache`
    reads a single archive; this class is everything above that — locating the
    archives, deciding whether a scope is usable, and writing new ones.
    """

    def __init__(self, root: Path = CACHE_DIR):
        self.root = root

    @staticmethod
    def key(scope: dict) -> str:
        """Folder name identifying one scope tuple.

        `instrumentType` is a platform constant (see `Functions/data.py`), so only
        the three varying parts identify a scope.
        """
        return "_".join(str(scope[k]) for k in ("region", "delay", "universe"))

    def dir(self, scope: dict) -> Path:
        """Folder holding the cached archives of one scope."""
        return self.root / self.key(scope)

    def paths(self, scope: dict) -> dict[str, Path]:
        """Archive path of every field type of one scope, whether or not it exists."""
        folder = self.dir(scope)
        return {ft: folder / f"{ft.lower()}.npz" for ft in FIELD_TYPES}

    def cached(self, scope: dict) -> dict[str, Path] | None:
        """Return the cached archive of every field type, or None if any is missing.

        The whole scope is present or none of it is: a partially fetched scope
        would silently mix a fresh catalog with a stale one.
        """
        paths = self.paths(scope)
        if not all(p.exists() for p in paths.values()):
            return None
        return paths

    def age_seconds(self, paths: dict[str, Path]) -> float:
        """Seconds since the oldest archive of one scope was fetched.

        Takes the paths of an already-confirmed scope rather than a scope dict,
        so it cannot be pointed at archives that were never written. Age is taken
        from the oldest member rather than the newest: the field types of a scope
        are fetched together and are meant to be one snapshot, so the scope is only
        as fresh as its least fresh part.
        """
        fetched = []
        for path in paths.values():
            with np.load(path, allow_pickle=False) as npz:
                fetched.append(
                    datetime.fromisoformat(json.loads(npz["meta"].item())["fetched_at"])
                )
        return (datetime.now(timezone.utc) - min(fetched)).total_seconds()

    def expires_in_seconds(self, paths: dict[str, Path]) -> float:
        """Seconds until the snapshot goes stale, negative once it already is.

        The same deadline as the one `CatalogBuilder.stale_scopes` compares
        against, expressed as a countdown instead of an age, so a caller
        reporting cache health cannot disagree with the run decision about
        whether to refetch.
        """
        return CATALOG_MAX_AGE_SECONDS - self.age_seconds(paths)

    def open(self, scope: dict, field_type: str) -> "ScopeCache":
        """Open the cached archive of one (scope, field type) for reading."""
        return ScopeCache(self.paths(scope)[field_type])

    def save(
        self,
        scope: dict,
        frame: pd.DataFrame,
        field_type: str,
        catalog_total: int | None = None,
        catalog_frame_id: str | None = None,
    ) -> Path:
        """Write one (scope, field type) catalog snapshot to disk as a chunked .npz."""
        columns = list(frame.columns)
        n_chunks = max(1, (len(frame) + CHUNK_ROWS - 1) // CHUNK_ROWS)

        # Two dtype maps on purpose: `numpy` is what goes into the archive (pickle-free,
        # so allow_pickle=False stays valid), `pandas` is what `ScopeCache.take()`
        # restores, so a round trip returns the original dtypes and not merely
        # equal values.
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

        folder = self.dir(scope)
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
        self.frame_id = meta.get("frame_id")
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

        Rows are stored already filtered, so on a snapshot written by
        `CatalogBuilder.fetch_scope` this returns every position. It stays a live
        derivation from the stored columns rather than a member saved at write
        time, so a threshold looser than the one used at fetch still selects the
        right subset. A missing dateCoverage is NaN and fails the comparison.
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