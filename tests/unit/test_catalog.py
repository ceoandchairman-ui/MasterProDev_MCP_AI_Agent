import pytest

from mpd_assistant.business.catalog import CatalogError, load_catalog


def write(tmp_path, text):
    p = tmp_path / "catalog.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_valid_catalog(tmp_path):
    cat = load_catalog(write(tmp_path, "items:\n  - {sku: dev-hour, name: Development hour, unit: hour, unit_price_cents: 15000}\n"))
    assert cat["dev-hour"].unit_price_cents == 15000


@pytest.mark.parametrize(
    "text",
    [
        "",
        "items: []",
        "items:\n  - {sku: a, name: A, unit: parsec, unit_price_cents: 1}",
        "items:\n  - {sku: a, name: A, unit: hour, unit_price_cents: 0}",
        "items:\n  - {sku: a, name: A, unit: hour}",
        "items:\n  - {sku: a, name: A, unit: hour, unit_price_cents: 5}\n  - {sku: a, name: B, unit: hour, unit_price_cents: 6}",
    ],
)
def test_rejects_invalid_catalogs(tmp_path, text):
    with pytest.raises(CatalogError):
        load_catalog(write(tmp_path, text))
