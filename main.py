import sys

import pandas as pd

from Functions.data import BrainData
from Functions.login import BrainLogin


def main():
    # Field descriptions contain non-cp1252 characters (e.g. U+2011), so any
    # printout of the catalog would abort on the default Windows console
    # encoding.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    login = BrainLogin()
    s = login.get_session()
    if s is None:
        return
    print("Login successful. JWT:")
    print(login.get_token(s))

    data = BrainData(s, login.base_url)
    scope = {"instrumentType": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
    datasets = data.datasets(scope)
    datafields = data.datafields(scope)

    # Keep only fields that are populated enough to backtest on: the field's own
    # coverage (fraction of the universe the field is defined for) and its
    # dateCoverage (fraction of the history the field spans) must both clear
    # the threshold. dateCoverage is missing on ~4 % of records, and those rows
    # fail the comparison.
    MIN_COVERAGE = 0.7

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

    n_before = len(fields)
    fields = fields[(fields["coverage"] > MIN_COVERAGE) & (fields["dateCoverage"] > MIN_COVERAGE)]
    print(
        f"\nFields with coverage > {MIN_COVERAGE} and dateCoverage > {MIN_COVERAGE}: "
        f"{len(fields)} / {n_before} ({len(fields) / n_before:.1%})"
    )

    # One CSV per field type, because MATRIX and VECTOR feed different
    # expression semantics and GROUP fields are not usable as alpha inputs at
    # all — keeping them in one file invites mixing them in a backtest.
    for field_type in ("MATRIX", "VECTOR", "GROUP"):
        subset = fields[fields["type"] == field_type]
        path = f"datafields_{field_type.lower()}.csv"
        subset.head(100).to_csv(path, index=False)
        print(f"{field_type}: {len(subset)} fields eligible -> {path} ({min(len(subset), 100)} rows written)")


if __name__ == "__main__":
    main()
