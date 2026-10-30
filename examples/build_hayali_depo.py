"""Hayali "Marmara Dağıtım Deposu" test veri seti (SENTETİK).

Bir ERP'den alınmış gibi görünen çalışma kitabı üretir: Türkçe sayfa/kolon adları, cm / kg / litre birimleri,
gg.aa.yyyy tarihleri, Türkçe ondalık virgül ve Türkçe kategori değerleri (elle, palet, raf, soğuk, standart).
Kolon eşleştirme, birim çevirme, kod normalizasyonu ve doğrulamanın birlikte sınanması içindir.

Kasıtlı veri hataları (doğrulama raporunda görünmeli):
    1. Geçersiz tarih (31.02.2026)            6. Yinelenen 2 sipariş satırı (birleştirilir)
    2. Negatif miktar (-2)                     7. Olmayan lokasyonda stok (K09-S-01-1)
    3. Ürün listesinde olmayan ürün (S-9999)   8. Aynı lokasyonda iki ürün
    4. Boyu 0 olan ürün (S-1149)               9. Kapasitesini aşan stok (60 adet)
    5. Ağırlık kapasitesi boş lokasyon (K03-D-12-1)
Ayrıca 18 iade + 7 iptal satırı, 5 sabit ve 12 pasif lokasyon, rezerv (toplanamaz) üst katlar vardır.

Kullanım:  python examples/build_hayali_depo.py examples/hayali_depo.xlsx
Uygulamada birimler: boyut cm, ağırlık kg, hacim litre; sevkiyat noktası X=20, Y=-2.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from warehouse_optimizer.optimization.constraints import max_units_fitting  # noqa: E402

DOCK_XY = (20.0, -2.0)


def build(OUT) -> None:
    rng = np.random.default_rng(2026)

    # ---------------- geometry ----------------
    aisles, locs = [], []
    FRONT, BACK = 1.0, 20.0
    for a in range(8):
        kod = f"K{a+1:02d}"
        xc = 5.0 + a * 5.0
        aisles.append({"Koridor": kod, "X Orta": xc, "Y Başlangıç": FRONT, "Y Bitiş": BACK})
        if a == 6:   kind, levels, bays, cls = "palet", [0.0], 10, "standart"
        elif a == 7: kind, levels, bays, cls = "raf", [0.0, 1.0], 10, "soğuk"
        else:        kind, levels, bays, cls = "raf", [0.0, 1.0, 2.0], 12, "standart"
        for side, sx in (("S", -1), ("D", 1)):   # sol / sağ
            for b in range(bays):
                for li, z in enumerate(levels):
                    if kind == "palet":
                        cap = (130, 110, 180, 1000)
                    elif li == 2:
                        cap = (120, 60, 80, 300)      # üst kat: rezerv
                    else:
                        cap = (120, 60, 45, 200 if li == 0 else 150)
                    L, W, H, kg = cap
                    locs.append({
                        "Lokasyon Kodu": f"{kod}-{side}-{b+1:02d}-{li+1}",
                        "Bölge": "SOĞUK" if cls == "soğuk" else ("PALET" if kind == "palet" else "ANA"),
                        "Koridor": kod, "X (m)": xc + sx * 1.6, "Y (m)": 3.0 + b * 1.35, "Kat Yüksekliği (m)": z,
                        "Raf Tipi": kind, "Max Ağırlık (kg)": kg, "Max Hacim (lt)": L * W * H / 1000,
                        "Max Uzunluk (cm)": L, "Max Genişlik (cm)": W, "Max Yükseklik (cm)": H,
                        "Toplama Gözü": "hayır" if li == 2 else "evet", "Aktif": "evet", "Sabit": "hayır",
                        "Depolama Sınıfı": cls,
                    })
    locs = pd.DataFrame(locs)
    locs.loc[rng.choice(len(locs), 12, replace=False), "Aktif"] = "hayır"

    # ---------------- products ----------------
    fams = ["Temizlik", "Gıda", "Kozmetik", "İçecek", "Kırtasiye", "Ev Gereçleri", "Elektronik"]
    prods = []
    for i in range(150):
        if i < 10:   el, dep, dims, kg = "palet", "standart", (120, 100, rng.uniform(100, 160)), rng.uniform(150, 700)
        elif i < 22: el, dep, dims, kg = "elle", "soğuk", rng.uniform(12, 40, 3), rng.uniform(0.3, 6)
        else:        el, dep, dims, kg = "elle", "standart", rng.uniform(8, 50, 3), rng.uniform(0.2, 20)
        prods.append({"Stok Kodu": f"S-{1001+i}", "Stok Adı": f"Ürün {i+1}", "Boy (cm)": round(float(dims[0]), 1),
                      "En (cm)": round(float(dims[1]), 1), "Yükseklik (cm)": round(float(dims[2]), 1),
                      "Brüt Ağırlık (kg)": round(float(kg), 2), "Kategori": fams[int(rng.integers(len(fams)))],
                      "İstiflenebilir": "evet" if (el == "palet" or rng.random() > 0.15) else "hayır",
                      "Depolama Koşulu": dep, "Elleçleme Tipi": el})
    prods = pd.DataFrame(prods)

    # ---------------- stock (historic, unsorted placement) ----------------
    def to_m(p):
        return pd.Series({"length_m": p["Boy (cm)"]/100, "width_m": p["En (cm)"]/100, "height_m": p["Yükseklik (cm)"]/100,
                          "weight_kg": p["Brüt Ağırlık (kg)"], "stackable": p["İstiflenebilir"] == "evet"})
    def loc_m(l):
        return pd.Series({"max_length_m": l["Max Uzunluk (cm)"]/100, "max_width_m": l["Max Genişlik (cm)"]/100,
                          "max_height_m": l["Max Yükseklik (cm)"]/100, "max_weight_kg": l["Max Ağırlık (kg)"],
                          "max_volume_m3": l["Max Hacim (lt)"]/1000})
    free = set(locs.loc[locs["Aktif"] == "evet", "Lokasyon Kodu"])
    stock = []
    def place(p, pool_mask, n=1):
        pool = locs[pool_mask & locs["Lokasyon Kodu"].isin(free)]
        ok = [r for _, r in pool.iterrows() if max_units_fitting(to_m(p), loc_m(r)) >= 1]
        if not ok: return []
        chosen = [ok[k] for k in rng.choice(len(ok), size=min(n, len(ok)), replace=False)]
        out = []
        for r in chosen:
            mu = max_units_fitting(to_m(p), loc_m(r))
            q = int(rng.integers(max(1, int(mu*0.3)), max(2, int(mu*0.85)) + 1)); q = max(1, min(q, mu))
            out.append({"Stok Kodu": p["Stok Kodu"], "Lokasyon Kodu": r["Lokasyon Kodu"], "Eldeki Miktar": q})
            free.discard(r["Lokasyon Kodu"])
        return out
    pick = locs["Toplama Gözü"] == "evet"
    for _, p in prods.sample(frac=1, random_state=7).iterrows():
        if p["Elleçleme Tipi"] == "palet":   m = pick & (locs["Raf Tipi"] == "palet")
        elif p["Depolama Koşulu"] == "soğuk": m = pick & (locs["Depolama Sınıfı"] == "soğuk")
        else: m = pick & (locs["Raf Tipi"] == "raf") & (locs["Depolama Sınıfı"] == "standart")
        stock += place(p, m)
        if rng.random() < 0.15 and p["Elleçleme Tipi"] == "elle" and p["Depolama Koşulu"] == "standart":
            stock += place(p, ~pick)  # üst katta rezerv stok
    stock = pd.DataFrame(stock)
    fixed = rng.choice(stock["Lokasyon Kodu"].unique(), 5, replace=False)
    locs.loc[locs["Lokasyon Kodu"].isin(fixed), "Sabit"] = "evet"

    # ---------------- orders (6 months) ----------------
    skus = prods["Stok Kodu"].to_numpy()
    w = 1.0 / (rng.permutation(len(skus)) + 1) ** 1.05
    w[rng.choice(len(skus), 8, replace=False)] = 0; w /= w.sum()
    start = pd.Timestamp("2026-04-01")
    orders = []
    for o in range(900):
        d = start + pd.Timedelta(days=int(rng.integers(0, 183)))
        for s in rng.choice(skus, size=int(min(1 + rng.geometric(0.4), 9)), replace=False, p=w):
            orders.append({"Sipariş No": f"SP-{50001+o}", "Sipariş Tarihi": d.strftime("%d.%m.%Y"), "Stok Kodu": s,
                           "Miktar": int(rng.integers(1, 13)), "Hareket Tipi": "Satış"})
    orders = pd.DataFrame(orders)
    ret = orders.sample(25, random_state=3).copy(); ret["Hareket Tipi"] = ["İade"] * 18 + ["İptal"] * 7

    # ---------------- deliberate data problems ----------------
    bad_orders = pd.DataFrame([
        {"Sipariş No": "SP-60001", "Sipariş Tarihi": "15.07.2026", "Stok Kodu": "S-9999", "Miktar": 2, "Hareket Tipi": "Satış"},
        {"Sipariş No": "SP-60002", "Sipariş Tarihi": "31.02.2026", "Stok Kodu": "S-1030", "Miktar": 1, "Hareket Tipi": "Satış"},
        {"Sipariş No": "SP-60003", "Sipariş Tarihi": "16.07.2026", "Stok Kodu": "S-1031", "Miktar": -2, "Hareket Tipi": "Satış"},
    ])
    orders = pd.concat([orders, ret, orders.iloc[[10, 11]], bad_orders], ignore_index=True)   # 2 yinelenen satır
    prods.loc[prods["Stok Kodu"] == "S-1149", "Boy (cm)"] = 0            # imkânsız boyut
    locs.loc[locs["Lokasyon Kodu"] == "K03-D-12-1", "Max Ağırlık (kg)"] = None  # eksik kapasite
    stock = pd.concat([stock, pd.DataFrame([
        {"Stok Kodu": "S-1040", "Lokasyon Kodu": "K09-S-01-1", "Eldeki Miktar": 5},          # olmayan lokasyon
    ])], ignore_index=True)
    shared = stock[stock["Lokasyon Kodu"].str.startswith("K02")].iloc[0]["Lokasyon Kodu"]
    other = prods[(prods["Elleçleme Tipi"] == "elle") & (prods["Depolama Koşulu"] == "standart")
                  & ~prods["Stok Kodu"].isin(stock["Stok Kodu"])]
    extra_sku = other.iloc[0]["Stok Kodu"] if len(other) else "S-1050"
    stock = pd.concat([stock, pd.DataFrame([{"Stok Kodu": extra_sku, "Lokasyon Kodu": shared, "Eldeki Miktar": 2}])],
                      ignore_index=True)                                                     # karışık lokasyon
    heavy = stock.merge(prods, on="Stok Kodu").query("`Brüt Ağırlık (kg)` > 10 and `Elleçleme Tipi` == 'elle'").iloc[0]
    stock.loc[stock["Stok Kodu"] == heavy["Stok Kodu"], "Eldeki Miktar"] = 60                # kapasite aşımı

    def tr(x):  # Türkçe ondalık biçim
        return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",") if isinstance(x, float) else x
    with pd.ExcelWriter(OUT, engine="openpyxl") as wr:
        prods.map(tr).to_excel(wr, sheet_name="Ürünler", index=False)
        orders.to_excel(wr, sheet_name="Siparişler", index=False)
        locs.map(tr).to_excel(wr, sheet_name="Lokasyonlar", index=False)
        stock.to_excel(wr, sheet_name="Lokasyon Stok", index=False)
        pd.DataFrame(aisles).map(tr).to_excel(wr, sheet_name="Koridorlar", index=False)
    return {"products": len(prods), "order_lines": len(orders), "locations": len(locs), "inventory": len(stock),
            "overstock_sku": heavy["Stok Kodu"], "mixed_location": shared}


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "hayali_depo.xlsx"))
