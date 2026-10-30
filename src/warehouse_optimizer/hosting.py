"""Where is the app running? Used to keep data-privacy statements truthful.

Detection order:
    1. WAREHOUSE_HOSTING env var: "cloud" / "hosted" or "local" (explicit override)
    2. Streamlit Community Cloud markers: HOSTNAME == "streamlit" or the code living under /mount/src/
    3. otherwise: local
"""
from __future__ import annotations

import os
from pathlib import Path

LOCAL_SHORT = "Yerel çalışır · dosyalar bu bilgisayarda işlenir · WMS'e yazmaz"
LOCAL_LONG = ("Uygulama bu bilgisayarda çalışıyor; yüklenen dosyalar dışarı gönderilmez ve hiçbir WMS'e değişiklik "
              "yazılmaz.")
HOSTED_SHORT = "Bulut sürümü · dosyalar Streamlit sunucularında işlenir · WMS'e yazmaz"
HOSTED_LONG = ("Bu, uygulamanın bulutta (Streamlit Community Cloud) çalışan sürümüdür: yüklenen dosyalar Streamlit "
               "sunucularında işlenir. Uygulama dosyaları diske kaydetmez, oturum kapanınca bellekten silinir ve "
               "hiçbir WMS'e değişiklik yazmaz. Gizli müşteri verisi için uygulamayı yerel bilgisayarda çalıştırın "
               "(README → Kurulum).")


def is_hosted(environ: dict | None = None, module_path: str | None = None) -> bool:
    env = os.environ if environ is None else environ
    override = env.get("WAREHOUSE_HOSTING", "").strip().lower()
    if override in ("cloud", "hosted"):
        return True
    if override == "local":
        return False
    if env.get("HOSTNAME") == "streamlit":
        return True
    path = module_path or Path(__file__).resolve().as_posix()
    return path.startswith("/mount/src/")


def privacy_notice(short: bool = False, hosted: bool | None = None) -> str:
    hosted = is_hosted() if hosted is None else hosted
    if hosted:
        return HOSTED_SHORT if short else HOSTED_LONG
    return LOCAL_SHORT if short else LOCAL_LONG
