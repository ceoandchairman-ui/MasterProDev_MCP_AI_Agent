"""Loads the service catalog from YAML. Prices are owned by the business, never by code or the model."""

from pathlib import Path
from typing import Dict

import yaml

from mpd_assistant.business.quoting import CatalogItem

UNITS = {"hour", "fixed", "month"}


class CatalogError(ValueError):
    pass


def load_catalog(path: str | Path) -> Dict[str, CatalogItem]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise CatalogError("catalog needs a non-empty 'items' list")
    catalog: Dict[str, CatalogItem] = {}
    for raw in items:
        try:
            item = CatalogItem(str(raw["sku"]), str(raw["name"]), str(raw["unit"]), int(raw["unit_price_cents"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogError(f"invalid catalog item: {raw!r}") from exc
        if item.unit not in UNITS or item.unit_price_cents <= 0:
            raise CatalogError(f"invalid unit or price for {item.sku}")
        if item.sku in catalog:
            raise CatalogError(f"duplicate sku {item.sku}")
        catalog[item.sku] = item
    return catalog
