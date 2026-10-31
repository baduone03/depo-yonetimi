"""Normalise categorical codes written in Turkish or in different spellings.

ERP exports say "elle", "palet", "raf", "soğuk", "standart" where the
constraint engine uses manual / pallet / shelf / cold / standard. Without this
step every product would be "incompatible" with every location. Unknown
values are kept as written (lower-cased) and reported by the pipeline.
"""
from __future__ import annotations

import pandas as pd

from .column_mapping import canonical

HANDLING = {
    "manual": ["manual", "manuel", "elle", "el", "el_ile", "elden", "hand", "koli", "parca", "adet"],
    "pallet": ["pallet", "palet", "paletli", "tam_palet"],
    "forklift": ["forklift", "istif_makinesi", "reach_truck", "transpalet"],
}
LOCATION_TYPE = {
    "shelf": ["shelf", "raf", "rafli", "hafif_raf", "shelving"],
    "pallet": ["pallet", "palet", "palet_rafi", "palet_gozu", "selektif"],
    "floor": ["floor", "zemin", "yer", "blok", "blok_istif"],
    "bin": ["bin", "goz", "kutu", "kasa", "bolme"],
    "flow_rack": ["flow_rack", "akisli_raf", "akiskan_raf", "dinamik_raf", "flow"],
}
STORAGE = {
    "standard": ["standard", "standart", "normal", "ortam", "ambient", "kuru"],
    "cold": ["cold", "soguk", "sogutmali", "chilled", "serin", "plus_4"],
    "frozen": ["frozen", "donuk", "dondurulmus", "derin_dondurucu", "eksi_18"],
    "hazmat": ["hazmat", "tehlikeli", "tehlikeli_madde", "adr", "kimyasal"],
}
KINDS = {"handling": HANDLING, "location_type": LOCATION_TYPE, "storage": STORAGE}


def _lookup(kind: str) -> dict[str, str]:
    return {canonical(alias): code for code, aliases in KINDS[kind].items() for alias in aliases}


def normalize_codes(values: pd.Series, kind: str, empty_default: str = "") -> tuple[pd.Series, dict[str, str]]:
    """Return (normalised series, {original value: code} for values that were translated)."""
    lookup = _lookup(kind)
    translated: dict[str, str] = {}
    out = []
    for value in values.astype(str):
        text = value.strip()
        if text == "":
            out.append(empty_default)
            continue
        code = lookup.get(canonical(text))
        if code is None:
            out.append(text.lower())
            continue
        if code != text.lower():
            translated[text] = code
        out.append(code)
    return pd.Series(out, index=values.index, dtype=object), translated
