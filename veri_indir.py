"""Gelistirme verisi: kripto + BIST + ABD mumlarini indirip veri.npz yapar (ucgen-veri dalina konur).
Anahtar: PIYASA__SEMBOL__aralik, sutunlar t,o,h,l,c,v (float32). Kullanim: ARALIKLAR=1w,3d,1d,4h python veri_indir.py"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import ucgen_istatistik as st
import ucgen_tarayici as u

st.BAR.update({"4h": 1000, "1d": 1000})          # kripto: 4s ~166 gun, gunluk ~2,7 yil (hisse gunluk 5 yil)
# 4hL: uzun 4 saatlik (kripto ~1000 gun, hisse Yahoo 1s'ten ~2 yil) — gunluk kirilimin 4s icindeki seyri testi
st.ARALIK_MS["4hL"] = 4 * 3600_000
st.BINANCE_AD["4hL"] = "4h"
st.BAR["4hL"] = 6000
st.MIN_VERI["4hL"] = 300


def al(is_):
    p, s, a = is_
    try:
        if p == "KRIPTO":
            return st.binance_uzun(s, a)
        ys = s + ".IS" if p == "BIST" else s
        return st.yahoo_4s(ys) if a in ("4h", "4hL") else st.yahoo_uzun(ys, a)
    except Exception:  # noqa: BLE001
        return None


def main():
    araliklar = [a.strip() for a in (os.environ.get("ARALIKLAR") or "1w,3d,1d,4h").split(",") if a.strip()]
    kripto = u.kripto_listesi()
    isler = []
    for a in araliklar:
        isler += [("KRIPTO", s, a) for s in kripto]
        if a not in ("4h", "8h"):
            isler += [("BIST", s, a) for s in dict.fromkeys(u.BIST)] + [("ABD", s, a) for s in u.ABD]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        veriler = list(ex.map(al, isler))
    cikti = {f"{p}__{s}__{a}": np.column_stack([d[k] for k in ("t", "o", "h", "l", "c", "v")]).astype(np.float32)
             for (p, s, a), d in zip(isler, veriler) if d is not None}
    np.savez_compressed("veri.npz", **cikti)
    print(f"{len(cikti)} seri / {len(isler)} is, {time.time() - t0:.0f} sn, {os.path.getsize('veri.npz') / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
