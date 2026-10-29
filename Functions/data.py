"""BRAIN catalog access, in three tiers.

`BrainAPI` owns the transport: the session, the per-second rate limit and the
OPTIONS negotiation that enumerates valid scopes. `BrainData` adds the catalog
endpoints themselves, turning their nested JSON into flat frames.
`CatalogBuilder` is the pipeline on top — fetch a scope, keep only the fields
dense enough to backtest on, write one archive per field type, then sample from
those archives. It reaches the platform through a `BrainData` handed to it by
the caller rather than owning one, because the login budget (5 per minute,
25 per day) is spent once for a run that may otherwise need no login at all.
"""

import os
import time
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd
import requests
import yaml

from Functions.cache import (
    CATALOG_MAX_AGE_SECONDS,
    FIELD_TYPES,
    CatalogCache,
    ScopeCache,
    frame_id,
)

BRAIN_API_URL = "https://api.worldquantbrain.com"

# The BRAIN catalog and simulation endpoints are scoped by
# (instrumentType, region, delay, universe), but `OPTIONS /simulations` publishes
# exactly one instrumentType ("EQUITY"), so it is a platform constant rather
# than a free parameter of the experiment.
INSTRUMENT_TYPE = "EQUITY"

# The per-second rate limit is shared across the whole session, so a catalog GET
# can return an HTML error body instead of JSON. Retry a non-JSON body a few
# times before giving up.
GET_MAX_ATTEMPTS = 5
GET_RETRY_INTERVAL_SECONDS = 2

# Every valid scope tuple, as enumerated in config/scopes.yaml. The list is a
# snapshot of OPTIONS /simulations, so a scope the platform has since dropped
# would fail the catalog request instead of being silently skipped.
SCOPES_PATH = Path(__file__).parent.parent / "config" / "scopes.yaml"


class BrainAPI:
    """Transport-level access to BRAIN: session, rate limit, OPTIONS negotiation.

    Every catalog endpoint is scoped by (instrumentType, region, delay, universe).
    `instrumentType` is a platform constant (INSTRUMENT_TYPE), so a scope only
    varies in region / delay / universe — and "how much data exists" is only
    meaningful per scope.
    """

    def __init__(self, session: requests.Session, base_url: str = BRAIN_API_URL):
        self.session = session
        self.base_url = base_url

    def _get(self, url: str) -> dict:
        """GET a catalog endpoint, respecting the per-second rate limit.

        The rate limit is enforced per second across the whole session, so a
        request can come back with an HTML error body instead of JSON. Retry
        on a non-JSON body until the attempt budget is exhausted.
        """
        for attempt in range(1, GET_MAX_ATTEMPTS + 1):
            r = self.session.get(url)
            if int(r.headers.get("X-RateLimit-Remaining-Second", 1)) <= 1:
                time.sleep(1)
            try:
                return r.json()
            except requests.exceptions.JSONDecodeError:
                if attempt == GET_MAX_ATTEMPTS:
                    raise
                time.sleep(GET_RETRY_INTERVAL_SECONDS)

    def settings(self) -> dict:
        """Return the valid simulation settings: instrumentType, region, delay, universe.

        Reads the OPTIONS payload of /simulations. The nesting differs per
        setting: instrumentType is a flat list, while region/delay/universe
        nest under instrumentType -> region.
        """
        children = self.session.options(self.base_url + "/simulations").json()[
            "actions"
        ]["POST"]["settings"]["children"]
        return {
            "instrumentType": children["instrumentType"]["choices"],
            "region": children["region"]["choices"]["instrumentType"],
            "delay": children["delay"]["choices"]["instrumentType"],
            "universe": children["universe"]["choices"]["instrumentType"],
        }

    def combinations(self) -> Iterator[dict]:
        """Yield every valid (region, delay, universe) scope."""
        s = self.settings()
        for region in s["region"][INSTRUMENT_TYPE]:
            for delay in s["delay"][INSTRUMENT_TYPE]["region"][region["value"]]:
                for universe in s["universe"][INSTRUMENT_TYPE]["region"][region["value"]]:
                    yield {
                        "region": region["value"],
                        "delay": delay["value"],
                        "universe": universe["value"],
                    }

    def _scope_query(self, scope: dict) -> str:
        return (
            f"instrumentType={INSTRUMENT_TYPE}&region={scope['region']}"
            f"&delay={scope['delay']}&universe={scope['universe']}"
        )


class BrainData(BrainAPI):
    """The catalog itself: which datasets and data fields a scope offers.

    The endpoint responses nest, so every record is flattened into its own
    column before it becomes a frame.
    """

    @staticmethod
    def _flatten(obj: Any, prefix: str = "") -> dict:
        """Flatten nested dict/list values into `prefix_sub` columns."""
        out: dict = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.update(BrainData._flatten(v, f"{prefix}{k}"))
        elif isinstance(obj, list):
            out[prefix] = ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in obj)
        else:
            out[prefix] = obj
        return out

    @staticmethod
    def _to_frame(records: list[dict]) -> pd.DataFrame:
        """Build a DataFrame with every nested key flattened into its own column."""
        if not records:
            return pd.DataFrame()
        flat = [dict(BrainData._flatten(r)) for r in records]
        return pd.DataFrame(flat)

    def datasets(self, scope: dict) -> pd.DataFrame:
        """Return every dataset available in one scope, all columns flattened."""
        j = self._get(f"{self.base_url}/data-sets?{self._scope_query(scope)}")
        return self._to_frame(j["results"])

    def datafields(self, scope: dict) -> pd.DataFrame:
        """Return every data field available in one scope, all columns flattened."""
        j = self._get(f"{self.base_url}/data-fields?{self._scope_query(scope)}")
        return self._to_frame(j["results"])

    def summary(self, scopes: list[dict]) -> pd.DataFrame:
        """Count datasets and data fields per scope, with the data field type breakdown.

        One row per scope. `fields_by_type` holds the MATRIX/VECTOR/GROUP/... counts
        so a scope can be compared without re-downloading the field list.
        """
        rows = []
        for scope in scopes:
            ds = self.datasets(scope)
            fs = self.datafields(scope)
            by_type = fs["type"].value_counts().to_dict() if "type" in fs else {}
            rows.append(
                {
                    "region": scope["region"],
                    "delay": scope["delay"],
                    "universe": scope["universe"],
                    "n_datasets": len(ds),
                    "n_datafields": len(fs),
                    "fields_by_type": by_type,
                    "n_dataset_categories": ds["categoryid"].nunique()
                    if "categoryid" in ds
                    else 0,
                    "n_datasets_with_fields": ds["fieldCount"].gt(0).sum()
                    if "fieldCount" in ds
                    else 0,
                }
            )
        return pd.DataFrame(rows)


class CatalogBuilder:
    """Cache every enumerated scope's field catalog and report its eligibility.

    Auth is not this class's business: the platform caps logins (5 per minute,
    25 per day), so `BrainData` arrives from the caller and one session serves
    every scope. `run(None)` is the no-auth path, valid only when every scope is
    already cached. That is why `BrainData` is composed in rather than
    inherited from — this class has to be constructible with no session at all.

    `refetch_stale` is the one decision that does belong here rather than in the
    caller, because both `stale_scopes` and `needs_auth` must agree on it: with it
    off, an aged-out snapshot is reused as it is instead of being replaced, and
    the session is then needed only for scopes absent from disk.
    """

    def __init__(
        self,
        min_coverage: float,
        refetch_stale: bool = True,
        scopes_path: Path = SCOPES_PATH,
        max_value_score: float | None = None,
    ):
        self.min_coverage = min_coverage
        self.max_value_score = max_value_score
        self.refetch_stale = refetch_stale
        self.scopes = yaml.safe_load(scopes_path.read_text(encoding="utf-8"))["scopes"]
        self.cache = CatalogCache()

    def needs_download(self) -> bool:
        """True when some scope is absent from disk, i.e. the run will need auth."""
        return any(self.cache.cached(scope) is None for scope in self.scopes)

    def stale_scopes(self) -> list[dict]:
        """Scopes whose cached snapshot has outlived CATALOG_MAX_AGE_SECONDS.

        The BRAIN catalog gains, loses and re-scores fields continuously, so a
        snapshot older than the cadence is re-fetched rather than sampled. This
        is what makes a long-lived cache safe to keep on disk: the directory
        persists, but its contents do not go stale indefinitely.

        Empty when `refetch_stale` is off: an aged-out snapshot is then pinned and
        reused as it is, which is what keeps a run that may not log in from
        reaching the platform at all.
        """
        if not self.refetch_stale:
            return []
        stale = []
        for scope in self.scopes:
            paths = self.cache.cached(scope)
            if paths is None:
                continue
            if self.cache.age_seconds(paths) > CATALOG_MAX_AGE_SECONDS:
                stale.append(scope)
        return stale

    def needs_auth(self) -> bool:
        """True when this run will have to talk to the platform.

        A scope is missing from disk entirely, or present but older than the
        catalog cadence. Both mean the snapshot has to be fetched again, and
        fetching needs a session. With `refetch_stale` off the second case cannot
        occur, so this reduces to `needs_download`.
        """
        return self.needs_download() or bool(self.stale_scopes())

    def fetch_scope(self, data: BrainData, scope: dict) -> dict[str, Path]:
        """Download the whole catalog of one scope and cache it per field type.

        Returns the cached archive path of every field type.
        """
        datasets = data.datasets(scope)
        datafields = data.datafields(scope)

        # One row per data field. /data-fields already carries the dataset context
        # (datasetid, datasetname, category, subcategory, region, delay, universe,
        # pyramidMultiplier) with values identical to the dataset record, so only
        # the dataset-only columns are joined in. coverage and dateCoverage exist
        # at both levels with *different* values (field-level is the field's own
        # value), so both are kept.
        dataset_meta = datasets.rename(
            columns={
                "id": "datasetid",
                "description": "dataset_description",
                "valueScore": "dataset_valueScore",
                "dateUpdated": "dataset_dateUpdated",
                "coverage": "dataset_coverage",
                "dateCoverage": "dataset_dateCoverage",
            }
        )[
            [
                "datasetid",
                "dataset_description",
                "dataset_valueScore",
                "dataset_dateUpdated",
                "dataset_coverage",
                "dataset_dateCoverage",
            ]
        ]
        fields = datafields.merge(dataset_meta, on="datasetid", how="left")
        fields = fields[
            [
                "dateCreated",
                "dataset_dateUpdated",
                "region",
                "delay",
                "universe",
                "id",
                "description",
                "type",
                "datasetid",
                "datasetname",
                "dataset_description",
                "categoryid",
                "categoryname",
                "subcategoryid",
                "subcategoryname",
                "dataset_valueScore",
                "coverage",
                "dateCoverage",
                "pyramidMultiplier",
            ]
        ].rename(columns={"id": "fieldid", "description": "field_description"})

        # Only fields dense enough to backtest on are kept: the field's own
        # coverage (fraction of the universe it is defined for) and its
        # dateCoverage (fraction of the history it spans) must both clear the
        # threshold. A missing dateCoverage is NaN and fails the comparison.
        # Filtering here, before the type split, is what makes every archive
        # hold eligible rows only.
        catalog_total = len(fields)
        eligible = (fields["coverage"] > self.min_coverage) & (
            fields["dateCoverage"] > self.min_coverage
        )
        fields = fields[eligible].reset_index(drop=True)

        # Cache each field type separately: MATRIX and VECTOR feed different
        # expression semantics, GROUP is not an alpha input at all, so keeping the
        # three archives apart stops them being mixed in a backtest.
        #
        # The frame id hashes the rows actually stored, so it pins the snapshot
        # an archive really holds. `catalog_total` keeps the pre-filter count, so
        # the archives stay auditable: it records how many fields the scope
        # offered before the coverage filter rejected any.
        catalog_frame_id = frame_id(fields["fieldid"])
        paths = {}
        for field_type in FIELD_TYPES:
            subset = fields[fields["type"] == field_type].reset_index(drop=True)
            paths[field_type] = self.cache.save(
                scope,
                subset,
                field_type,
                catalog_total=catalog_total,
                catalog_frame_id=catalog_frame_id,
            )
        return paths

    def drawable_positions(self, cache: ScopeCache, theme: tuple[str, ...] | list[str] = ()) -> np.ndarray:
        """Row positions of an archive a draw may pick.

        `theme` keeps rows whose `categoryid` is in it (empty keeps all rows).
        `max_value_score` keeps rows whose dataset `dataset_valueScore` is
        strictly below it (None keeps all rows). The score filter is applied
        here, on the stored column, rather than at fetch time, so it takes
        effect on snapshots already on disk. A missing score is NaN and fails
        the comparison.
        """
        mask = np.ones(cache.n_rows, dtype=bool)
        if len(theme):
            mask &= np.isin(cache.column("categoryid"), theme)
        if self.max_value_score is not None:
            mask &= cache.column("dataset_valueScore") < self.max_value_score
        return np.flatnonzero(mask)

    def sample_field_ids(
        self,
        region: str,
        delay: int,
        universe: str,
        data_type: str,
        n: int,
        seed: int | None = None,
        theme: tuple[str, ...] | list[str] = (),
    ) -> pd.DataFrame:
        """Draw `n` distinct fields at random from one scope's stored catalog.

        Returns one row per drawn field, carrying every column the archive
        holds — the field id, its type, description, category, dataset and the
        numeric coverage / value-score columns. The row order is the draw
        order, so the caller can pop fields off the front and still know which
        metadata belongs to which field.

        Every stored row already clears the coverage filter (`fetch_scope`
        applies it before writing); the `max_value_score` cut, if set, is
        applied here by `drawable_positions`. Positions are drawn with `replace=False`; asking for
        more than the archive holds returns the whole archive instead of raising,
        because a smaller sample is still a valid answer.

        `theme` is a collection of `categoryid` values. Empty keeps the draw
        uniform over the whole archive, bit-exact with the draw before `theme`
        existed. Non-empty restricts the draw to rows whose `categoryid` is in
        the theme, still uniform over those rows: a category with more fields in
        the scope is drawn proportionally more often. A theme category absent
        from this scope and type matches no row and is skipped.

        `seed=None` draws fresh entropy from the OS CSPRNG, so the sample is not
        anchored to any fixed constant; the seed actually used is returned with
        the draw (see `main`) and replays it bit-exact. The archive's `frame_id`
        is what pins the catalog the draw applies to: the same seed against a
        different snapshot selects different fields.
        """
        scope = {"region": region, "delay": delay, "universe": universe}
        cache = self.cache.open(scope, data_type)
        if seed is None:
            seed = int.from_bytes(os.urandom(8), "big")
        positions = self.drawable_positions(cache, theme)
        picked = positions[
            np.random.default_rng(seed).choice(
                positions.size, size=min(n, positions.size), replace=False
            )
        ]
        frame = cache.take(picked)
        cache.close()
        return frame

    def run(self, data: BrainData | None) -> list[tuple[str, int, int]]:
        """Bring every scope onto disk, fetching the missing and the expired ones.

        Returns one (scope key, eligible fields, pre-filter total) triple per scope,
        so the caller decides how to report it.
        """
        totals = []

        # Resolved once: every scope past the cadence is treated as a miss, so the
        # age is not re-read from disk once per scope per field type.
        stale = {CatalogCache.key(s) for s in self.stale_scopes()}

        for scope in self.scopes:
            key = self.cache.key(scope)
            paths = None if key in stale else self.cache.cached(scope)
            if paths is None:
                paths = self.fetch_scope(data, scope)

            n_eligible = 0
            catalog_total = 0

            for field_type in FIELD_TYPES:
                cache = ScopeCache(paths[field_type])
                n_eligible += cache.n_rows
                catalog_total = cache.catalog_total
                cache.close()

            totals.append((key, n_eligible, catalog_total))

        return totals