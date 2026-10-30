import io

import pandas as pd
import pytest

from warehouse_optimizer.data.column_mapping import (apply_mapping, canonical, duplicate_sources, mapping_from_json,
                                                     mapping_to_json, missing_required, resolve_with_profile,
                                                     suggest_mapping, suggest_sheet, unit_hints)
from warehouse_optimizer.data.loaders import Dataset, excel_sheet_names, read_table
from warehouse_optimizer.data.validators import parse_numbers, validate_dataset
from warehouse_optimizer.pipeline import run_pipeline
from warehouse_optimizer.settings import load_settings

ERP_PRODUCTS = pd.DataFrame({
    "Stok Kodu": ["U001", "U002", "U003"], "Stok Adı": ["Ürün 1", "Ürün 2", "Ürün 3"],
    "Boy (cm)": ["30", "25,5", "40"], "En (cm)": ["20", "18", "30"], "Yükseklik (cm)": ["20", "6", "25"],
    "Brüt Ağırlık (kg)": ["2,5", "1", "1.250,0"], "Kategori": ["A", "B", "A"], "Satış Fiyatı": ["10", "20", "30"],
})
ERP_ORDERS = pd.DataFrame({
    "Sipariş No": ["S1", "S1", "S2", "S3"], "Sipariş Tarihi": ["01.09.2026", "01.09.2026", "02.09.2026", "03.09.2026"],
    "Stok Kodu": ["U001", "U002", "U001", "U003"], "Miktar": ["3", "1", "2", "1"],
})
ERP_LOCATIONS = pd.DataFrame({
    "Lokasyon Kodu": ["A-01-1", "A-02-1", "B-01-1", "B-02-1"], "Koridor": ["A", "A", "B", "B"],
    "X": ["1", "1", "7", "7"], "Y": ["2", "5", "2", "5"],
    "Max Ağırlık": ["5000", "5000", "5000", "5000"], "Max Hacim (lt)": ["800", "800", "800", "800"],
    "Max Uzunluk": ["120", "120", "120", "120"], "Max Genişlik": ["80", "80", "80", "80"],
    "Max Yükseklik": ["90", "90", "90", "90"],
})
ERP_STOCK = pd.DataFrame({"Stok Kodu": ["U001", "U002", "U003"], "Lokasyon": ["B-02-1", "A-02-1", "A-01-1"],
                          "Eldeki Miktar": ["5", "4", "1"]})


def _workbook() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        ERP_PRODUCTS.to_excel(w, sheet_name="Ürünler", index=False)
        ERP_ORDERS.to_excel(w, sheet_name="Siparişler", index=False)
        ERP_LOCATIONS.to_excel(w, sheet_name="Lokasyonlar", index=False)
        ERP_STOCK.to_excel(w, sheet_name="Lokasyon Stok", index=False)
    return buf.getvalue()


def test_canonical_folds_turkish_and_punctuation():
    assert canonical("Brüt Ağırlık (kg)") == "brut_agirlik_kg"
    assert canonical("  SİPARİŞ  No ") == "siparis_no"


def test_suggests_turkish_erp_headers():
    m = suggest_mapping("products", list(ERP_PRODUCTS.columns))
    assert m["sku"] == "Stok Kodu" and m["product_name"] == "Stok Adı"
    assert (m["length_m"], m["width_m"], m["height_m"]) == ("Boy (cm)", "En (cm)", "Yükseklik (cm)")
    assert m["weight_kg"] == "Brüt Ağırlık (kg)" and m["product_family"] == "Kategori"
    assert "Satış Fiyatı" not in m.values()  # unrelated columns are not guessed
    assert missing_required("products", m) == []
    o = suggest_mapping("order_lines", list(ERP_ORDERS.columns))
    assert o == {"order_id": "Sipariş No", "order_date": "Sipariş Tarihi", "sku": "Stok Kodu", "quantity": "Miktar",
                 "movement_type": None}
    inv = suggest_mapping("inventory", list(ERP_STOCK.columns))
    assert inv == {"sku": "Stok Kodu", "location_id": "Lokasyon", "current_quantity": "Eldeki Miktar"}


def test_exact_schema_names_win_and_sources_are_used_once():
    m = suggest_mapping("inventory", ["miktar", "current_quantity", "sku", "location_id"])
    assert m["current_quantity"] == "current_quantity"
    m2 = suggest_mapping("order_lines", ["Miktar", "Adet"])
    assert m2["quantity"] == "Miktar"
    assert list(m2.values()).count("Miktar") == 1


def test_missing_required_and_duplicates():
    m = suggest_mapping("locations", ["Lokasyon Kodu", "Koridor"])
    assert set(missing_required("locations", m)) == {"x", "y"}
    assert duplicate_sources({"x": "A", "y": "A", "z": None}) == {"A": ["x", "y"]}


def test_sheet_suggestion():
    names = ["Ürünler", "Siparişler", "Lokasyonlar", "Lokasyon Stok", "Notlar"]
    assert [suggest_sheet(t, names) for t in ("products", "order_lines", "locations", "inventory", "aisles")] == \
        ["Ürünler", "Siparişler", "Lokasyonlar", "Lokasyon Stok", None]


def test_unit_hints_from_column_names():
    m = suggest_mapping("locations", list(ERP_LOCATIONS.columns))
    hints = unit_hints("locations", m)
    assert any("litre" in h for h in hints)
    assert unit_hints("locations", m, {"volume": "dm3"}) == []  # already selected -> no hint
    p = suggest_mapping("products", list(ERP_PRODUCTS.columns))
    assert len(unit_hints("products", p)) == 1 and "cm" in unit_hints("products", p)[0]
    assert unit_hints("products", p, {"dimension": "cm"}) == []


def test_apply_mapping_keeps_file_row_numbers():
    raw = pd.DataFrame({"Sipariş No": ["S1", "S2"], "Sipariş Tarihi": ["2026-01-01", "bozuk"], "Stok Kodu": ["P", "P"],
                        "Miktar": ["1", "1"], "Not": ["x", "y"]})
    mapped = apply_mapping(raw, suggest_mapping("order_lines", list(raw.columns)))
    assert list(mapped.columns) == ["order_id", "order_date", "sku", "quantity"]
    report = validate_dataset(Dataset(tables={
        "products": pd.DataFrame({"sku": ["P"], "length_m": ["1"], "width_m": ["1"], "height_m": ["1"],
                                  "weight_kg": ["1"]}),
        "order_lines": mapped}))
    bad = report.issues[(report.issues["table"] == "order_lines") & (report.issues["field"] == "order_date")]
    assert list(bad["row"]) == [3]


def test_profile_json_roundtrip_and_priority():
    m = {"order_lines": {"order_id": "Belge", "order_date": "Tarih", "sku": "Kod", "quantity": "Adet",
                         "movement_type": None}}
    text = mapping_to_json(m, {"order_lines": "Satış"}, {"dimension": "cm", "weight": "kg", "volume": "dm3"})
    profile = mapping_from_json(text)
    assert profile["tables"]["order_lines"]["order_id"] == "Belge"
    assert profile["sheets"] == {"order_lines": "Satış"} and profile["units"]["volume"] == "dm3"
    # Profile wins over the automatic suggestion ("Miktar" would otherwise be chosen).
    resolved = resolve_with_profile("order_lines", ["Belge", "Tarih", "Kod", "Adet", "Miktar"], profile)
    assert resolved["quantity"] == "Adet"
    with pytest.raises(ValueError):
        mapping_from_json('{"foo": 1}')


def test_parse_numbers_formats():
    out = parse_numbers(pd.Series(["12.5", "12,5", "1.234,5", "1,234.5", "1 234", "abc"])).tolist()
    assert out[:5] == [12.5, 12.5, 1234.5, 1234.5, 1234.0]
    assert pd.isna(out[5])


def test_erp_workbook_end_to_end_with_mapping_and_units():
    data = _workbook()
    sheets = excel_sheet_names(data)
    tables = {}
    for table in ("products", "order_lines", "locations", "inventory"):
        raw = read_table(data, "erp.xlsx", sheet_name=suggest_sheet(table, sheets), normalize_columns=False)
        tables[table] = apply_mapping(raw, suggest_mapping(table, list(raw.columns)))
    report = validate_dataset(Dataset(tables=tables), dimension_unit="cm", weight_unit="kg", volume_unit="dm3")
    assert report.error_count == 0, report.issues
    p = report.tables["products"].set_index("sku")
    assert p.at["U002", "length_m"] == pytest.approx(0.255)
    assert p.at["U003", "weight_kg"] == pytest.approx(1250.0)
    loc = report.tables["locations"].set_index("location_id")
    assert loc.at["A-01-1", "max_volume_m3"] == pytest.approx(0.8)
    assert loc.at["A-01-1", "max_length_m"] == pytest.approx(1.2)
    assert report.tables["order_lines"]["order_date"].min() == pd.Timestamp("2026-09-01")

    s = load_settings()
    s["units"].update(dimension="cm", weight="kg", volume="dm3")
    res = run_pipeline(Dataset(tables=tables, dock_xy=(0.0, 0.0)), s)
    assert res.ok
    assert res.comparisons["hybrid"].summary["orders_compared"] == 3
