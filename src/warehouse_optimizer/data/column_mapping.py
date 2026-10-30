"""Map arbitrary ERP / WMS export columns onto the application schema.

Users rarely have files with our column names. This module
    * suggests a source column for every schema column (exact name, known
      Turkish / English aliases, with unit suffixes like _cm / _kg ignored),
    * suggests which workbook sheet holds which table,
    * applies a mapping (renames, keeps the original row index so validation
      still reports the original file row numbers),
    * serialises mappings to JSON so a recurring export can be re-used.

Suggestions are only suggestions: the UI shows them for confirmation and
nothing is mapped silently when no confident match exists.
"""
from __future__ import annotations

import json
import re
import unicodedata

import pandas as pd

from .schemas import SCHEMAS

NONE_OPTION = "— yok —"
MAPPING_VERSION = 1

_TR_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "İ": "i", "I": "i"})
_UNIT_SUFFIX = re.compile(r"_(m|cm|mm|kg|gr|g|ton|t|m3|dm3|cm3|lt|l|litre|metre|adet)$")

_SKU = ["sku", "stok_kodu", "stok_kod", "urun_kodu", "malzeme_kodu", "malzeme", "malzeme_no", "item_code", "item_id",
        "item", "product_code", "product_id", "material", "article", "artikel", "kod", "stok_no", "urun_no"]
_LOCATION = ["location_id", "lokasyon", "lokasyon_kodu", "lokasyon_id", "adres", "raf_adresi", "adres_kodu",
             "location", "location_code", "bin", "bin_code", "goz", "goz_kodu", "hucre"]

ALIASES: dict[str, dict[str, list[str]]] = {
    "products": {
        "sku": _SKU,
        "product_name": ["urun_adi", "stok_adi", "malzeme_adi", "malzeme_tanimi", "aciklama", "tanim", "description",
                         "item_name", "product_name", "name", "urun"],
        "length_m": ["length", "uzunluk", "boy", "derinlik_uzunluk"],
        "width_m": ["width", "genislik", "en"],
        "height_m": ["height", "yukseklik"],
        "weight_kg": ["weight", "agirlik", "brut_agirlik", "gross_weight", "birim_agirlik", "net_agirlik"],
        "stackable": ["stackable", "istiflenebilir", "istif"],
        "product_family": ["product_family", "kategori", "category", "urun_grubu", "grup", "family", "product_group",
                           "malzeme_grubu"],
        "storage_requirements": ["storage_requirements", "depolama_kosulu", "depolama_sartlari", "storage",
                                 "sicaklik_sinifi"],
        "handling_type": ["handling_type", "ellecleme_tipi", "ellecleme", "handling"],
    },
    "order_lines": {
        "order_id": ["order_id", "siparis_no", "siparis_numarasi", "siparis", "order_no", "order_number", "order",
                     "belge_no", "fis_no", "irsaliye_no", "sevk_no"],
        "order_date": ["order_date", "tarih", "siparis_tarihi", "date", "belge_tarihi", "sevk_tarihi", "fis_tarihi"],
        "sku": _SKU,
        "quantity": ["quantity", "miktar", "adet", "qty", "sevk_miktari", "cikis_miktari", "siparis_miktari"],
        "movement_type": ["movement_type", "hareket_tipi", "hareket_turu", "islem_tipi", "islem_turu", "fis_tipi"],
    },
    "locations": {
        "location_id": _LOCATION,
        "zone": ["zone", "bolge", "alan", "depo_alani"],
        "aisle_id": ["aisle_id", "koridor", "koridor_no", "aisle", "reyon", "sira"],
        "x": ["x", "x_koordinat", "x_koordinati", "koordinat_x", "pos_x"],
        "y": ["y", "y_koordinat", "y_koordinati", "koordinat_y", "pos_y"],
        "z": ["z", "z_koordinat", "kat_yuksekligi", "seviye_yuksekligi", "pos_z"],
        "location_type": ["location_type", "lokasyon_tipi", "raf_tipi", "adres_tipi", "goz_tipi"],
        "max_weight_kg": ["max_weight_kg", "max_agirlik", "agirlik_kapasitesi", "max_weight", "tasima_kapasitesi",
                          "maksimum_agirlik"],
        "max_volume_m3": ["max_volume_m3", "max_hacim", "hacim_kapasitesi", "max_volume", "hacim", "maksimum_hacim"],
        "max_length_m": ["max_length_m", "max_uzunluk", "max_length", "maksimum_uzunluk", "goz_uzunlugu"],
        "max_width_m": ["max_width_m", "max_genislik", "max_derinlik", "max_width", "maksimum_genislik",
                        "goz_derinligi", "goz_genisligi"],
        "max_height_m": ["max_height_m", "max_yukseklik", "max_height", "maksimum_yukseklik", "goz_yuksekligi"],
        "is_pickable": ["is_pickable", "toplanabilir", "toplama_lokasyonu", "toplama_gozu", "pickable"],
        "is_available": ["is_available", "kullanilabilir", "aktif", "available", "active"],
        "is_fixed": ["is_fixed", "sabit", "sabit_lokasyon", "fixed"],
        "storage_class": ["storage_class", "depolama_sinifi", "depolama_kosulu", "sicaklik_sinifi"],
    },
    "inventory": {
        "sku": _SKU,
        "location_id": _LOCATION,
        "current_quantity": ["current_quantity", "miktar", "stok", "stok_miktari", "mevcut_miktar", "mevcut_stok",
                             "eldeki_miktar", "qty", "quantity", "adet", "bakiye"],
    },
    "aisles": {
        "aisle_id": ["aisle_id", "koridor", "koridor_no", "aisle"],
        "x_center": ["x_center", "x", "x_orta", "koridor_x"],
        "y_start": ["y_start", "y_baslangic", "baslangic_y"],
        "y_end": ["y_end", "y_bitis", "bitis_y"],
    },
}

SHEET_ALIASES = {
    "products": ["products", "urunler", "urun", "stok_kartlari", "malzemeler", "malzeme", "items", "urun_listesi"],
    "order_lines": ["order_lines", "siparisler", "siparis_satirlari", "siparis", "orders", "satislar", "sevkiyatlar",
                    "cikislar", "hareketler"],
    "locations": ["locations", "lokasyonlar", "lokasyon", "adresler", "gozler", "raflar"],
    "inventory": ["inventory", "stok", "stoklar", "lokasyon_stok", "lokasyon_stoklari", "envanter"],
    "aisles": ["aisles", "koridorlar", "koridor"],
}


def canonical(name: object) -> str:
    """Lower-case, Turkish characters folded to ASCII, non-alphanumerics -> '_'."""
    text = str(name).strip().translate(_TR_FOLD).lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^0-9a-z]+", "_", text).strip("_")
    return text


def _score(target: str, source: str, aliases: list[str]) -> int:
    src = canonical(source)
    stripped = _UNIT_SUFFIX.sub("", src)
    if src == target:
        return 4
    if stripped == _UNIT_SUFFIX.sub("", target):
        return 3
    if src in aliases:
        return 2
    if stripped in aliases:
        return 1
    return 0


def suggest_mapping(table: str, columns: list[str]) -> dict[str, str | None]:
    """Return {schema column: source column or None}. Each source column is used at most once."""
    aliases = ALIASES.get(table, {})
    candidates = []
    for order, spec in enumerate(SCHEMAS[table]):
        names = [canonical(a) for a in aliases.get(spec.name, [])]
        for col_order, col in enumerate(columns):
            score = _score(spec.name, col, names)
            if score:
                alias_rank = names.index(canonical(col)) if canonical(col) in names else len(names)
                # Higher score first, required columns first, earlier alias first, stable on order.
                candidates.append((-score, 0 if spec.required else 1, alias_rank, order, col_order, spec.name, col))
    candidates.sort()
    mapping: dict[str, str | None] = {spec.name: None for spec in SCHEMAS[table]}
    used: set[str] = set()
    for *_, target, col in candidates:
        if mapping[target] is None and col not in used:
            mapping[target] = col
            used.add(col)
    return mapping


def suggest_sheet(table: str, sheet_names: list[str]) -> str | None:
    aliases = [canonical(a) for a in SHEET_ALIASES.get(table, [])]
    for alias in aliases:
        for sheet in sheet_names:
            if canonical(sheet) == alias:
                return sheet
    return None


def missing_required(table: str, mapping: dict[str, str | None]) -> list[str]:
    return [s.name for s in SCHEMAS[table] if s.required and not mapping.get(s.name)]


def duplicate_sources(mapping: dict[str, str | None]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for target, source in mapping.items():
        if source:
            seen.setdefault(source, []).append(target)
    return {src: targets for src, targets in seen.items() if len(targets) > 1}


def apply_mapping(raw: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Rename mapped source columns to schema names; unmapped columns are dropped. Index is preserved."""
    data = {target: raw[source] for target, source in mapping.items() if source and source in raw.columns}
    return pd.DataFrame(data, index=raw.index)


def unit_hints(table: str, mapping: dict[str, str | None], selected: dict | None = None) -> list[str]:
    """Hints derived from source column names (e.g. a length column called 'Boy (cm)').

    Hints that already match the selected units (`selected`: dimension / weight / volume) are omitted.
    """
    selected = selected or {}
    dims = {"products": ["length_m", "width_m", "height_m"],
            "locations": ["max_length_m", "max_width_m", "max_height_m"]}.get(table, [])
    weights = {"products": ["weight_kg"], "locations": ["max_weight_kg"]}.get(table, [])
    found: dict[tuple[str, str, str], list[str]] = {}

    def add(kind: str, unit: str, label: str, column: str) -> None:
        if selected.get(kind) != unit:
            columns = found.setdefault((kind, unit, label), [])
            if column not in columns:
                columns.append(column)

    for target in dims:
        src = canonical(mapping.get(target) or "")
        for unit in ("mm", "cm"):
            if re.search(rf"(^|_){unit}($|_)", src):
                add("dimension", unit, unit, mapping[target])
    vol = canonical(mapping.get("max_volume_m3") or "") if table == "locations" else ""
    for pattern, unit, label in ((r"(^|_)(lt|l|litre|liter|dm3)($|_)", "dm3", "litre (dm³)"),
                                 (r"(^|_)cm3($|_)", "cm3", "cm³"), (r"(^|_)mm3($|_)", "mm3", "mm³")):
        if vol and re.search(pattern, vol):
            add("volume", unit, label, mapping["max_volume_m3"])
    for target in weights:
        src = canonical(mapping.get(target) or "")
        if re.search(r"(^|_)(g|gr|gram)($|_)", src):
            add("weight", "g", "g", mapping[target])
    return [f"{', '.join(repr(c) for c in cols)} kolon(lar)ı {label} görünüyor; {_UNIT_KIND[kind]} birimini "
            f"{label} seçin." for (kind, _, label), cols in found.items()]


_UNIT_KIND = {"dimension": "boyut", "weight": "ağırlık", "volume": "hacim"}


def mapping_to_json(mappings: dict[str, dict[str, str | None]], sheets: dict[str, str | None] | None = None,
                    units: dict | None = None) -> str:
    payload = {"version": MAPPING_VERSION,
               "tables": {t: {k: v for k, v in m.items() if v} for t, m in mappings.items()},
               "sheets": {t: s for t, s in (sheets or {}).items() if s},
               "units": units or {}}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def mapping_from_json(text: str | bytes) -> dict:
    payload = json.loads(text)
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("Geçerli bir eşleştirme dosyası değil (tables alanı yok)")
    tables = {}
    for table, mapping in payload["tables"].items():
        if table not in SCHEMAS or not isinstance(mapping, dict):
            continue
        known = {s.name for s in SCHEMAS[table]}
        tables[table] = {k: str(v) for k, v in mapping.items() if k in known and v}
    return {"tables": tables, "sheets": payload.get("sheets", {}), "units": payload.get("units", {})}


def resolve_with_profile(table: str, columns: list[str], profile: dict | None) -> dict[str, str | None]:
    """Saved profile entries win when their source column exists; the rest falls back to suggestions."""
    mapping = suggest_mapping(table, columns)
    saved = (profile or {}).get("tables", {}).get(table, {})
    for target, source in saved.items():
        if source in columns:
            for other, src in list(mapping.items()):
                if src == source and other != target:
                    mapping[other] = None
            mapping[target] = source
    return mapping
