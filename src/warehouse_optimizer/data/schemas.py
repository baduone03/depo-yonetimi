"""Table schemas and the data dictionary shown to users.

Every input table is described by a list of ColumnSpec objects. The loaders
and validators use these specs; the UI renders them as the data dictionary.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    dtype: str  # "str" | "float" | "int" | "bool" | "date"
    required: bool
    description: str  # Turkish, user facing
    example: str = ""


PRODUCTS = [
    ColumnSpec("sku", "str", True, "Benzersiz ürün kodu", "SKU-0001"),
    ColumnSpec("product_name", "str", False, "Ürün adı", "Deterjan 5L"),
    ColumnSpec("length_m", "float", True, "Birim uzunluğu (elleçleme birimi), metre", "0.40"),
    ColumnSpec("width_m", "float", True, "Birim genişliği, metre", "0.30"),
    ColumnSpec("height_m", "float", True, "Birim yüksekliği, metre", "0.25"),
    ColumnSpec("weight_kg", "float", True, "Birim ağırlığı, kilogram", "5.2"),
    ColumnSpec("stackable", "bool", False, "Üst üste istiflenebilir mi (evet/hayır). Boşsa: evet", "evet"),
    ColumnSpec("product_family", "str", False, "Ürün ailesi / kategori", "Temizlik"),
    ColumnSpec("storage_requirements", "str", False,
               "Özel depolama koşulu (standard, cold, hazmat ...). Boşsa: standard", "standard"),
    ColumnSpec("handling_type", "str", False, "Elleçleme tipi (manual, pallet ...). Boşsa: kısıt yok", "manual"),
]

ORDER_LINES = [
    ColumnSpec("order_id", "str", True, "Sipariş numarası", "SO-10001"),
    ColumnSpec("order_date", "date", True, "Sipariş tarihi (YYYY-AA-GG önerilir)", "2026-07-01"),
    ColumnSpec("sku", "str", True, "Ürün kodu (ürün listesinde bulunmalı)", "SKU-0001"),
    ColumnSpec("quantity", "float", True, "Miktar (pozitif)", "3"),
    ColumnSpec("movement_type", "str", False,
               "Hareket türü: outbound/çıkış, return/iade, cancel/iptal. Boşsa: outbound", "outbound"),
]

LOCATIONS = [
    ColumnSpec("location_id", "str", True, "Benzersiz lokasyon kodu", "A01-01-1"),
    ColumnSpec("zone", "str", False, "Bölge", "Z1"),
    ColumnSpec("aisle_id", "str", True, "Lokasyonun erişildiği koridor", "A01"),
    ColumnSpec("x", "float", True, "X koordinatı, metre", "3.5"),
    ColumnSpec("y", "float", True, "Y koordinatı, metre", "12.0"),
    ColumnSpec("z", "float", False, "Seviye yüksekliği, metre (yürüme mesafesine katılmaz)", "0.0"),
    ColumnSpec("location_type", "str", False, "Lokasyon tipi (shelf, pallet ...)", "shelf"),
    ColumnSpec("max_weight_kg", "float", False, "Maksimum ağırlık, kg. Boşsa: hedef olarak kullanılmaz", "300"),
    ColumnSpec("max_volume_m3", "float", False, "Maksimum hacim (birimi ayrıca seçilir: m³, litre, cm³). Boşsa: hedef olarak kullanılmaz", "0.8"),
    ColumnSpec("max_length_m", "float", False, "Maksimum uzunluk, metre", "1.2"),
    ColumnSpec("max_width_m", "float", False, "Maksimum genişlik (derinlik), metre", "0.8"),
    ColumnSpec("max_height_m", "float", False, "Maksimum yükseklik, metre", "0.9"),
    ColumnSpec("is_pickable", "bool", False, "Toplama lokasyonu mu. Boşsa: evet", "evet"),
    ColumnSpec("is_available", "bool", False, "Kullanılabilir mi. Boşsa: evet", "evet"),
    ColumnSpec("is_fixed", "bool", False, "Sabit lokasyon: içeriği taşınmaz, başka ürün atanmaz. Boşsa: hayır", "hayır"),
    ColumnSpec("storage_class", "str", False, "Depolama koşulu (standard, cold ...). Boşsa: standard", "standard"),
]

INVENTORY = [
    ColumnSpec("sku", "str", True, "Ürün kodu", "SKU-0001"),
    ColumnSpec("location_id", "str", True, "Lokasyon kodu", "A01-01-1"),
    ColumnSpec("current_quantity", "float", True, "Lokasyondaki mevcut stok (birim)", "40"),
]

AISLES = [
    ColumnSpec("aisle_id", "str", True, "Koridor kodu (locations.aisle_id ile eşleşmeli)", "A01"),
    ColumnSpec("x_center", "float", True, "Koridor orta hattının X koordinatı, metre", "3.0"),
    ColumnSpec("y_start", "float", True, "Koridorun ön ucu (ön ara koridora bağlandığı Y), metre", "0.0"),
    ColumnSpec("y_end", "float", True, "Koridorun arka ucu (arka ara koridora bağlandığı Y), metre", "30.0"),
]

SCHEMAS: dict[str, list[ColumnSpec]] = {
    "products": PRODUCTS,
    "order_lines": ORDER_LINES,
    "locations": LOCATIONS,
    "inventory": INVENTORY,
    "aisles": AISLES,
}

TABLE_LABELS = {
    "products": "Ürünler",
    "order_lines": "Sipariş satırları",
    "locations": "Lokasyonlar",
    "inventory": "Stok / mevcut yerleşim",
    "aisles": "Koridorlar (opsiyonel geometri)",
}

REQUIRED_TABLES = ("products", "order_lines", "locations", "inventory")

# Default values applied to missing optional columns / empty cells.
DEFAULTS = {
    "products": {"stackable": True, "storage_requirements": "standard", "product_family": "",
                 "handling_type": "", "product_name": ""},
    "order_lines": {"movement_type": "outbound"},
    "locations": {"is_pickable": True, "is_available": True, "is_fixed": False, "storage_class": "standard",
                  "z": 0.0, "zone": "", "location_type": ""},
}

MOVEMENT_TYPE_ALIASES = {
    "outbound": "outbound", "out": "outbound", "pick": "outbound", "sale": "outbound",
    "çıkış": "outbound", "cikis": "outbound", "satış": "outbound", "satis": "outbound",
    "return": "return", "iade": "return",
    "cancel": "cancel", "cancelled": "cancel", "canceled": "cancel", "iptal": "cancel",
}

TRUE_VALUES = {"true", "1", "yes", "y", "evet", "e", "doğru", "dogru", "t", "x"}
FALSE_VALUES = {"false", "0", "no", "n", "hayır", "hayir", "h", "yanlış", "yanlis", "f", ""}


def data_dictionary_rows() -> list[dict]:
    rows = []
    for table, specs in SCHEMAS.items():
        for spec in specs:
            rows.append({
                "Tablo": table,
                "Kolon": spec.name,
                "Tip": spec.dtype,
                "Zorunlu": "Evet" if spec.required else "Hayır",
                "Açıklama": spec.description,
                "Örnek": spec.example,
            })
    return rows
