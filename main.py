import sys
from pathlib import Path

import numpy as np
import yaml

from Functions.cache import (
    FIELD_TYPES,
    ScopeCache,
    cached_scope,
    frame_id,
    save_cache,
    scope_key,
)
from Functions.data import BrainData
from Functions.login import BrainLogin

# Every valid scope tuple, as enumerated in config/scopes.yaml. The list is a
# snapshot of OPTIONS /simulations, so a scope the platform has since dropped
# would fail the catalog request instead of being silently skipped.
SCOPES_PATH = Path(__file__).parent / "config" / "scopes.yaml"


def load_scopes(path: Path = SCOPES_PATH) -> list[dict]:
    """Read the enumerated scope tuples from the YAML config."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))["scopes"]


def fetch_scope(data: BrainData, scope: dict) -> dict[str, Path]:
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

    # Cache each field type separately: MATRIX and VECTOR feed different
    # expression semantics, GROUP is not an alpha input at all, so keeping the
    # three archives apart stops them being mixed in a backtest.
    #
    # Each archive holds the *raw* snapshot for its type, so the eligibility
    # filter stays local and can be re-derived without re-downloading. Rows are
    # stored in blocks and each column is a separate archive member, so a later
    # lookup reads only the blocks and columns it needs instead of reparsing
    # 41 MB of JSON.
    catalog_frame_id = frame_id(fields["fieldid"])
    paths = {}
    for field_type in FIELD_TYPES:
        subset = fields[fields["type"] == field_type].reset_index(drop=True)
        paths[field_type] = save_cache(
            scope,
            subset,
            field_type,
            catalog_total=len(fields),
            catalog_frame_id=catalog_frame_id,
        )
    return paths


def main():
    # Field descriptions contain non-cp1252 characters (e.g. U+2011), so any
    # printout of the catalog would abort on the default Windows console
    # encoding.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Keep only fields that are populated enough to backtest on: the field's own
    # coverage (fraction of the universe the field is defined for) and its
    # dateCoverage (fraction of the history the field spans) must both clear
    # the threshold. dateCoverage is missing on ~4 % of records, and those rows
    # fail the comparison.
    MIN_COVERAGE = 0.7

    # Every valid scope tuple, enumerated in config/scopes.yaml. Only region /
    # delay / universe vary: instrumentType is a platform constant (see
    # Functions/data.py INSTRUMENT_TYPE).
    scopes = load_scopes()

    # The catalog is a moving target, so a scope is downloaded once and reused
    # from disk afterwards: an existing cache folder means the snapshot is
    # already pinned, and re-downloading it would only replace a reproducible
    # snapshot with a different one.
    paths_by_scope = {scope_key(scope): cached_scope(scope) for scope in scopes}

    # One session serves every scope: logging in per scope would burn the
    # platform's login budget (5 per minute, 25 per day) for no reason.
    data = None
    if any(paths is None for paths in paths_by_scope.values()):
        login = BrainLogin()
        s = login.get_session()
        if s is None:
            return
        print("Login successful. JWT:")
        print(login.get_token(s))
        data = BrainData(s, login.base_url)

    display_cols = ["fieldid", "datasetid", "coverage", "dateCoverage"]
    rng = np.random.default_rng()
    totals = []

    for scope in scopes:
        paths = paths_by_scope[scope_key(scope)]
        if paths is None:
            paths = fetch_scope(data, scope)
        else:
            print(f"Cache hit for scope {scope_key(scope)}: reusing the cached catalog.")

        n_eligible = 0
        catalog_total = 0

        for field_type in FIELD_TYPES:
            path = paths[field_type]
            cache = ScopeCache(path)
            eligible = cache.eligible_positions(MIN_COVERAGE)
            n_eligible += eligible.size
            catalog_total = cache.catalog_total
            print(
                f"{scope_key(scope)} {field_type}: {cache.n_rows} rows, "
                f"{eligible.size} eligible "
                f"({eligible.size / max(cache.n_rows, 1):.1%}) -> "
                f"cache/{path.parent.name}/{path.name} "
                f"({path.stat().st_size / 1e6:.1f} MB, catalog_frame_id={cache.catalog_frame_id})"
            )

            # Draw five fields at random from the eligible positions, then read back
            # only those rows and only the columns actually displayed — narrowing the
            # column set avoids decompressing the other 15.
            picked = np.sort(rng.choice(eligible, size=min(5, eligible.size), replace=False))
            sampled = cache.take(picked, columns=display_cols)
            print(sampled.to_string(index=False))
            cache.close()

        print(
            f"{scope_key(scope)}: fields with coverage > {MIN_COVERAGE} and "
            f"dateCoverage > {MIN_COVERAGE}: {n_eligible} / {catalog_total} "
            f"({n_eligible / catalog_total:.1%})\n"
        )
        totals.append((scope_key(scope), n_eligible, catalog_total))

    grand_eligible = sum(n for _, n, _ in totals)
    grand_total = sum(t for _, _, t in totals)
    print(
        f"Scopes cached: {len(totals)} / {len(scopes)}; "
        f"eligible fields across scopes: {grand_eligible} / {grand_total} "
        f"({grand_eligible / grand_total:.1%})"
    )


if __name__ == "__main__":
    main()
