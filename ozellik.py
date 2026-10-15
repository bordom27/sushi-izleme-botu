"""
v6.1 islemlerinin GIRIS anindaki piyasa konumlanmasi / hacim ozellikleri ve sonuca etkisi.
Kaynaklar: Binance spot mumlari (taker alim hacmi), data.binance.vision arsivi
(vadeli funding orani, open interest, long/short oranlari).
Cikti: arastirma_cikti/ozellik*.txt
"""
from __future__ import annotations

import io
import multiprocessing as mp
import os
import time
import zipfile

import numpy as np
import pandas as pd
import requests

import arastirma as A
import veri
from coin_listesi import COINLER

OUT = "arastirma_cikti"
ARSIV = "https://data.binance.vision/data/futures/um"
S = requests.Session()
S.headers.update(veri.HEADERS)


def zip_csv(url):
    for _ in range(3):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            return pd.read_csv(z.open(z.namelist()[0]))
        except Exception:
            time.sleep(1)
    return None


def vadeli_ad(sym):
    for ad in (sym, "1000" + sym, "1000000" + sym):
        if zip_csv(f"{ARSIV}/monthly/fundingRate/{ad}/{ad}-fundingRate-2025-08.zip") is not None:
            return ad
    return None


def funding_tablosu(ad):
    parcalar = []
    for ay in pd.period_range("2024-05", "2026-09", freq="M"):
        d = zip_csv(f"{ARSIV}/monthly/fundingRate/{ad}/{ad}-fundingRate-{ay}.zip")
        if d is not None and len(d):
            if "calc_time" not in d.columns:  # basliksiz dosya
                d.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"][:len(d.columns)]
            parcalar.append(d)
    if not parcalar:
        return None
    f = pd.concat(parcalar)
    f["t"] = pd.to_datetime(pd.to_numeric(f["calc_time"], errors="coerce"), unit="ms")
    f["fr"] = pd.to_numeric(f["last_funding_rate"], errors="coerce")
    return f.dropna(subset=["t"]).sort_values("t")[["t", "fr"]]


def metrik_gun(ad, gun):
    d = zip_csv(f"{ARSIV}/daily/metrics/{ad}/{ad}-metrics-{gun}.zip")
    if d is None or d.empty:
        return None
    d["t"] = pd.to_datetime(d["create_time"])
    return d


def taker_mumlar(sym):
    """4s mumlar + taker alim hacmi (spot)."""
    rows = []
    start = int(pd.Timestamp("2024-05-01", tz="UTC").timestamp() * 1000)
    while True:
        data = veri._get("/api/v3/klines", {"symbol": sym, "interval": "4h", "startTime": start, "limit": 1000})
        if not data:
            break
        rows += data
        if len(data) < 1000:
            break
        start = data[-1][0] + 4 * 3600_000
    df = pd.DataFrame(rows).iloc[:, [0, 5, 9]]
    df.columns = ["open_time", "vol", "taker"]
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df[["vol", "taker"]] = df[["vol", "taker"]].astype(float)
    return df.set_index("open_time")


def sembol_ozellikleri(args):
    sym, tr = args
    out = []
    try:
        km = taker_mumlar(sym)
    except Exception:
        km = None
    ad = vadeli_ad(sym)
    fund = funding_tablosu(ad) if ad else None
    gun_cache = {}
    for _, r in tr.iterrows():
        g = pd.Timestamp(r.giris_zaman)          # kirilim mumunun acilisi
        giris_t = g + pd.Timedelta(hours=4)       # giris ani = mum kapanisi
        y = r.yon
        o = {"idx": r.name}
        if km is not None and g in km.index:
            i = km.index.get_loc(g)
            v = km["vol"].to_numpy()
            tk = km["taker"].to_numpy()
            if i >= 25 and v[i] > 0:
                alim = tk[i] / v[i]
                o["taker_yon"] = alim if y == 1 else 1 - alim             # yon lehine agresif hacim payi
                o["hacim_ivme"] = v[i] / max(np.mean(v[i - 3:i]), 1e-12)  # son mum / onceki 3
                o["hacim_3_20"] = np.mean(v[i - 2:i + 1]) / max(np.mean(v[i - 23:i - 3]), 1e-12)
                ort = np.mean(v[i - 20:i])
                o["hacim_x"] = v[i] / max(ort, 1e-12)
        if fund is not None:
            f = fund[fund.t <= giris_t]
            if len(f):
                fr = f.fr.iloc[-1]
                o["funding_yon"] = fr * y          # +: yon kalabalik tarafta (long'da pozitif funding)
                o["funding_3g"] = f.fr.iloc[-9:].mean() * y
        if ad:
            gun = giris_t.strftime("%Y-%m-%d")
            dun = (giris_t - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            for gg in (gun, dun):
                if gg not in gun_cache:
                    gun_cache[gg] = metrik_gun(ad, gg)
            m = pd.concat([x for x in (gun_cache[dun], gun_cache[gun]) if x is not None]) if any(
                gun_cache[x] is not None for x in (gun, dun)) else None
            if m is not None and len(m):
                m = m.sort_values("t")
                simdi = m[m.t <= giris_t]
                once = m[m.t <= giris_t - pd.Timedelta(hours=24)]
                if len(simdi):
                    s_ = simdi.iloc[-1]
                    for k_, col in (("ls_hesap", "count_long_short_ratio"), ("ls_top", "sum_toptrader_long_short_ratio"),
                                    ("taker_ls", "sum_taker_long_short_vol_ratio")):
                        if col in s_ and pd.notna(s_[col]):
                            val = float(s_[col])
                            o[k_ + "_yon"] = val if y == 1 else (1 / val if val > 0 else np.nan)
                    if len(once) and "sum_open_interest" in s_:
                        oi0 = float(once.iloc[-1]["sum_open_interest"])
                        if oi0 > 0:
                            o["oi_24s"] = float(s_["sum_open_interest"]) / oi0 - 1
        out.append(o)
    return out


def tercil_raporu(tr, kol):
    t = tr.dropna(subset=[kol])
    if len(t) < 60:
        return f"{kol}: yetersiz veri ({len(t)})\n"
    IS = t[t.donem == "IS"]
    if len(IS) < 30:
        return f"{kol}: IS yetersiz\n"
    q1, q2 = IS[kol].quantile([1 / 3, 2 / 3])
    t = t.assign(dilim=np.where(t[kol] <= q1, "1-dusuk", np.where(t[kol] <= q2, "2-orta", "3-yuksek")))
    g = t.groupby(["donem", "grup", "dilim"])["sonuc_r"].agg(n="size", R="sum", ort="mean",
                                                              isabet=lambda x: (x > 0).mean()).round(3)
    return f"\n=== {kol}  (IS tercil sinirlari {q1:.4g} / {q2:.4g}) ===\n{g.unstack('dilim').to_string()}\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    tick = veri._get("/api/v3/ticker/24hr", {})
    haric = set(COINLER) | A.STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                          "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                          "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
    aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
            and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
    aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    yeni = [d["symbol"] for d in aday[:70]]
    A.DATA["btc_d"] = veri.mumlar_onbellekli("BTCUSDT", "1d", "2019-06-01")
    A.DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", A.VERI_BAS)
    A.DATA["4h"] = A.yukle(COINLER + yeni)
    yeni = [s for s in yeni if s in A.DATA["4h"]]
    with mp.Pool(4) as hv:
        tr = A.calistir({}, COINLER + yeni, "4h", hv)
    tr = tr.reset_index(drop=True)
    tr["donem"] = np.where(pd.to_datetime(tr.giris_zaman) >= pd.Timestamp(A.OOS_BAS), "OOS", "IS")
    tr["grup"] = np.where(tr.symbol.isin(COINLER), "46", "YENI")
    print("islem", len(tr), round(time.time() - t0), flush=True)

    # arsiv erisim testi
    test = zip_csv(f"{ARSIV}/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-08.zip")
    print("arsiv erisimi:", "OK" if test is not None else "YOK", flush=True)

    isler = [(s, g) for s, g in tr.groupby("symbol")]
    with mp.Pool(8) as hv:
        sonuc = hv.map(sembol_ozellikleri, isler)
    oz = pd.DataFrame([x for lst in sonuc for x in lst]).set_index("idx")
    tr = tr.join(oz)
    tr.to_csv(f"{OUT}/ozellik_islemler.csv", index=False)
    print("ozellik hazir", round(time.time() - t0), flush=True)

    kolonlar = [k for k in ["hacim_x", "hacim_ivme", "hacim_3_20", "taker_yon", "funding_yon", "funding_3g",
                            "oi_24s", "ls_hesap_yon", "ls_top_yon", "taker_ls_yon"] if k in tr.columns]
    rapor = [f"Toplam islem {len(tr)} | dolu oranlari: " +
             ", ".join(f"{k} %{100 * tr[k].notna().mean():.0f}" for k in kolonlar)]
    for k in kolonlar:
        rapor.append(tercil_raporu(tr, k))
        for yon, ad in ((1, "LONG"), (-1, "SHORT")):
            rapor.append(tercil_raporu(tr[tr.yon == yon], k).replace(f"=== {k}", f"=== {k} [{ad}]"))
    with open(f"{OUT}/ozellik.txt", "w") as f:
        f.write("\n".join(rapor))
    print("bitti", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
