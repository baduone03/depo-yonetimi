"""End-to-end regression on the ERP-style imaginary warehouse in examples/ (Turkish headers, values and units)."""
from pathlib import Path

import pandas as pd
import pytest

from warehouse_optimizer.data.column_mapping import apply_mapping, missing_required, suggest_mapping, suggest_sheet
from warehouse_optimizer.data.loaders import Dataset, excel_sheet_names, read_table
from warehouse_optimizer.data.value_normalization import normalize_codes
from warehouse_optimizer.pipeline import run_pipeline
from warehouse_optimizer.settings import load_settings

WORKBOOK = Path(__file__).resolve().parents[1] / "examples" / "hayali_depo.xlsx"


@pytest.fixture(scope="module")
def result():
    data = WORKBOOK.read_bytes()
    sheets = excel_sheet_names(data)
    tables = {}
    for table in ("products", "order_lines", "locations", "inventory", "aisles"):
        raw = read_table(data, WORKBOOK.name, sheet_name=suggest_sheet(table, sheets), normalize_columns=False)
        mapping = suggest_mapping(table, list(raw.columns))
        assert missing_required(table, mapping) == []
        assert set(mapping.values()) - {None} == set(raw.columns)  # every column recognised
        tables[table] = apply_mapping(raw, mapping)
    s = load_settings()
    s["units"].update(dimension="cm", weight="kg", volume="dm3")
    return run_pipeline(Dataset(tables=tables, dock_xy=(20.0, -2.0), source_label="Hayali depo"), s)


def test_turkish_codes_are_normalised():
    out, translated = normalize_codes(pd.Series(["Elle", "palet", "", "Forklift", "vinç"]), "handling")
    assert out.tolist() == ["manual", "pallet", "", "forklift", "vinç"]
    assert translated == {"Elle": "manual", "palet": "pallet"}  # case-only changes are not reported
    storage, _ = normalize_codes(pd.Series(["Soğuk", "STANDART", ""]), "storage", "standard")
    assert storage.tolist() == ["cold", "standard", "standard"]


def test_all_deliberate_problems_are_reported(result):
    issues = result.validation.issues
    text = " | ".join(issues["message"] + " " + issues["value"].astype(str))
    for expected in ("31.02.2026", "Miktar sıfır veya negatif", "S-9999", "Fiziksel olarak imkânsız boyut",
                     "K03-D-12-1", "yinelenen satır", "K09-S-01-1", "tek SKU kuralı", "Ağırlık kapasitesi aşılıyor",
                     "18 iade ve 7 iptal", "soğuk → cold", "elle → manual", "raf → shelf"):
        assert expected in text, expected
    assert not (issues["message"].str.contains("ayarlarda tanımlı değil")).any()


def test_imaginary_warehouse_produces_valid_plan(result):
    assert result.ok and result.geometry.source == "file" and result.geometry.dock_source == "file"
    for method in ("hybrid", "class_based"):
        slot = result.slotting[method]
        assert slot.move_count > 0
        assert set(slot.unassignable["sku"]) == {"S-1041"}  # the over-stocked SKU fits nowhere
        plan = result.move_plans[method]
        assert (plan["constraint_check"] == "Geçti").all()
        assert result.comparisons[method].summary["orders_compared"] > 400


def test_unknown_handling_type_is_warned():
    from warehouse_optimizer.data.demo_generator import generate_demo_dataset

    ds = generate_demo_dataset()
    ds.tables["products"].loc[0, "handling_type"] = "vinç"
    res = run_pipeline(ds, load_settings())
    msgs = res.validation.issues["message"]
    assert msgs.str.contains("Elleçleme tipi 'vinç' ayarlarda tanımlı değil").any()
