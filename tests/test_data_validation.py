import io

import pandas as pd

from conftest import make_dataset, product, small_locations
from warehouse_optimizer.data.loaders import Dataset, read_table
from warehouse_optimizer.data.validators import validate_dataset


def _issues(report, table=None, severity=None):
    df = report.issues
    if table:
        df = df[df["table"] == table]
    if severity:
        df = df[df["severity"] == severity]
    return df


def test_empty_dataset_reports_missing_tables():
    report = validate_dataset(Dataset())
    assert set(report.missing_tables()) == {"products", "order_lines", "locations", "inventory"}
    assert not report.is_usable()
    assert report.error_count == 4


def test_missing_required_column_makes_table_unusable():
    ds = make_dataset([{"sku": "P1", "length_m": 1}], [], small_locations(), [])
    report = validate_dataset(ds)
    assert "products" in report.missing_tables()
    missing = _issues(report, "products", "hata")
    assert set(missing["field"]) >= {"width_m", "height_m", "weight_kg"}


def test_duplicate_product_keeps_first_and_reports_row():
    ds = make_dataset([product("P1"), product("P1", weight=9.0)], [], small_locations(), [])
    report = validate_dataset(ds)
    assert len(report.tables["products"]) == 1
    assert report.tables["products"]["weight_kg"].iloc[0] == 2.0
    dup = _issues(report, "products", "hata")
    assert list(dup["row"]) == [3]  # header is row 1, second data row is row 3
    assert "Yinelenen" in dup["message"].iloc[0]


def test_duplicate_order_lines_are_merged():
    orders = [{"order_id": "O1", "order_date": "2026-01-01", "sku": "P1", "quantity": 2},
              {"order_id": "O1", "order_date": "2026-01-01", "sku": "P1", "quantity": 3}]
    report = validate_dataset(make_dataset([product("P1")], orders, small_locations(), []))
    lines = report.tables["order_lines"]
    assert len(lines) == 1 and lines["quantity"].iloc[0] == 5
    assert (_issues(report, "order_lines")["action"] == "birleştirildi").any()


def test_invalid_date_and_negative_quantity_are_excluded_with_row_numbers():
    orders = [{"order_id": "O1", "order_date": "2026-13-45", "sku": "P1", "quantity": 1},
              {"order_id": "O2", "order_date": "2026-01-02", "sku": "P1", "quantity": -4},
              {"order_id": "O3", "order_date": "2026-01-03", "sku": "P1", "quantity": "abc"},
              {"order_id": "O4", "order_date": "2026-01-04", "sku": "P1", "quantity": 1}]
    report = validate_dataset(make_dataset([product("P1")], orders, small_locations(), []))
    assert list(report.tables["order_lines"]["order_id"]) == ["O4"]
    errors = _issues(report, "order_lines", "hata").sort_values("row")
    assert list(errors["row"]) == [2, 3, 4]
    assert list(errors["field"]) == ["order_date", "quantity", "quantity"]


def test_unknown_sku_and_unmatched_location():
    orders = [{"order_id": "O1", "order_date": "2026-01-01", "sku": "NOPE", "quantity": 1}]
    inventory = [{"sku": "P1", "location_id": "XX-1", "current_quantity": 3},
                 {"sku": "GHOST", "location_id": "A1-2", "current_quantity": 3}]
    report = validate_dataset(make_dataset([product("P1")], orders, small_locations(), inventory))
    assert report.tables["order_lines"].empty
    assert report.tables["inventory"].empty
    msgs = " ".join(report.issues["message"])
    assert "Bilinmeyen SKU" in msgs and "Eşleşmeyen lokasyon" in msgs


def test_physically_impossible_dimensions_excluded():
    report = validate_dataset(make_dataset([product("P1", length=0), product("P2", height=120), product("P3")],
                                           [], small_locations(), []))
    assert list(report.tables["products"]["sku"]) == ["P3"]
    assert len(_issues(report, "products", "hata")) == 2


def test_missing_capacity_is_warned():
    locs = small_locations(**{"A1-2": {"max_weight_kg": ""}, "A1-5": {"max_volume_m3": -1}})
    report = validate_dataset(make_dataset([product("P1")], [], locs, []))
    warnings = _issues(report, "locations", "uyarı")
    assert any("kapasite bilgisi eksik" in m for m in warnings["message"])
    assert pd.isna(report.tables["locations"].set_index("location_id").at["A1-5", "max_volume_m3"])


def test_mixed_location_and_current_placement_violation_are_warned():
    inventory = [{"sku": "P1", "location_id": "A1-2", "current_quantity": 1},
                 {"sku": "P2", "location_id": "A1-2", "current_quantity": 1},
                 {"sku": "P3", "location_id": "A1-5", "current_quantity": 1}]
    products = [product("P1"), product("P2"), product("P3", weight=500)]
    report = validate_dataset(make_dataset(products, [], small_locations(), inventory))
    msgs = " ".join(_issues(report, "inventory", "uyarı")["message"])
    assert "tek SKU kuralı" in msgs
    assert "Ağırlık kapasitesi" in msgs


def test_returns_and_cancellations_are_separated():
    orders = [{"order_id": "O1", "order_date": "2026-01-01", "sku": "P1", "quantity": 1, "movement_type": "çıkış"},
              {"order_id": "O1", "order_date": "2026-01-02", "sku": "P1", "quantity": 1, "movement_type": "iade"},
              {"order_id": "O2", "order_date": "2026-01-02", "sku": "P1", "quantity": 1, "movement_type": "iptal"},
              {"order_id": "O3", "order_date": "2026-01-02", "sku": "P1", "quantity": 1, "movement_type": "??"}]
    report = validate_dataset(make_dataset([product("P1")], orders, small_locations(), []))
    types = report.tables["order_lines"]["movement_type"].value_counts().to_dict()
    assert types == {"outbound": 1, "return": 1, "cancel": 1}
    assert (_issues(report, "order_lines", "hata")["field"] == "movement_type").all()


def test_unit_conversion_cm_and_g():
    ds = make_dataset([product("P1", length=30, width=20, height=10, weight=500)], [], small_locations(), [])
    report = validate_dataset(ds, dimension_unit="cm", weight_unit="g")
    p = report.tables["products"].iloc[0]
    assert abs(p["length_m"] - 0.3) < 1e-12 and abs(p["weight_kg"] - 0.5) < 1e-12


def test_read_table_csv_semicolon_and_xlsx_roundtrip(tmp_path):
    csv_bytes = "SKU;Product Name;Length M\nP1;A;0,5\n".encode("utf-8")
    df = read_table(csv_bytes, "p.csv")
    assert list(df.columns) == ["sku", "product_name", "length_m"]
    assert df.iloc[0]["length_m"] == "0,5"
    buf = io.BytesIO()
    pd.DataFrame({"sku": ["P1"], "quantity": [3]}).to_excel(buf, index=False)
    xdf = read_table(buf.getvalue(), "x.xlsx")
    assert xdf.iloc[0]["sku"] == "P1" and xdf.iloc[0]["quantity"] == "3"


def test_shipped_templates_load_and_validate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "templates"
    tables = {t: read_table(root / f"{t}_template.csv") for t in
              ("products", "order_lines", "locations", "inventory", "aisles")}
    report = validate_dataset(Dataset(tables=tables))
    assert report.is_usable()
    assert report.error_count == 0 and report.warning_count == 0, report.issues
