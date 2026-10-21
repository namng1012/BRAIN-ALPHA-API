import time
from typing import Any, Iterator

import pandas as pd
import requests

BRAIN_API_URL = "https://api.worldquantbrain.com"


def _flatten(obj: Any, prefix: str = "") -> dict:
    """Flatten nested dict/list values into `prefix_sub` columns."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}"))
    elif isinstance(obj, list):
        out[prefix] = ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in obj)
    else:
        out[prefix] = obj
    return out


def _to_frame(records: list[dict]) -> pd.DataFrame:
    """Build a DataFrame with every nested key flattened into its own column."""
    if not records:
        return pd.DataFrame()
    flat = [dict(_flatten(r)) for r in records]
    return pd.DataFrame(flat)


class BrainData:
    """Read-only access to the BRAIN catalog: datasets, data fields, settings.

    Every catalog endpoint is scoped by (instrumentType, region, delay, universe),
    so "how much data exists" is only meaningful per scope.
    """

    def __init__(self, session: requests.Session, base_url: str = BRAIN_API_URL):
        self.session = session
        self.base_url = base_url

    def _get(self, url: str) -> dict:
        """GET a catalog endpoint, respecting the per-second rate limit."""
        while True:
            r = self.session.get(url)
            if int(r.headers.get("X-RateLimit-Remaining-Second", 1)) <= 1:
                time.sleep(1)
            return r.json()

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
        """Yield every valid (instrumentType, region, delay, universe) scope."""
        s = self.settings()
        for inst in s["instrumentType"]:
            for region in s["region"][inst["value"]]:
                for delay in s["delay"][inst["value"]]["region"][region["value"]]:
                    for universe in s["universe"][inst["value"]]["region"][region["value"]]:
                        yield {
                            "instrumentType": inst["value"],
                            "region": region["value"],
                            "delay": delay["value"],
                            "universe": universe["value"],
                        }

    def _scope_query(self, scope: dict) -> str:
        return (
            f"instrumentType={scope['instrumentType']}&region={scope['region']}"
            f"&delay={scope['delay']}&universe={scope['universe']}"
        )

    def datasets(self, scope: dict) -> pd.DataFrame:
        """Return every dataset available in one scope, all columns flattened."""
        j = self._get(f"{self.base_url}/data-sets?{self._scope_query(scope)}")
        return _to_frame(j["results"])

    def datafields(self, scope: dict) -> pd.DataFrame:
        """Return every data field available in one scope, all columns flattened."""
        j = self._get(f"{self.base_url}/data-fields?{self._scope_query(scope)}")
        return _to_frame(j["results"])

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
                    "instrumentType": scope["instrumentType"],
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
