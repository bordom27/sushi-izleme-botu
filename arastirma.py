"""
Kirilim69 v6 - kripto iyilestirme arastirmasi (GitHub Actions'ta calisir).
Her ayar degisikligi IS (2024-07..2025-06) ve OOS (2025-07..) icin ayri olculur.
Cikti: arastirma_cikti/*.txt / *.csv
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np
import pandas as pd

import kirilim_v6 as k
import veri
from coin_listesi import COINLER

OUT = "arastirma_cikti"
IS_BAS, IS_BIT, OOS_BAS = "2024-07-01", "2025-06-30 23:59", "2025-07-01"
VERI_BAS = "2023-09-01"

DATA: dict = {}


def yukle(semboller, interval="4h"):
    d = {}
    for s in semboller:
        try:
            df = veri.mumlar_onbellekli(s, interval, VERI_BAS)
            gd = veri.mumlar_onbellekli(s, "1d", "2019-06-01")
            wd = veri.mumlar_onbellekli(s, "1w", "2019-06-01")
            if len(df) > 300:
                d[s] = (df, gd, wd)
        except Exception as exc:
            print("veri yok", s, exc, flush=True)
        time.sleep(0.1)
    return d


def _tek(args):
    s, prm, interval = args
    df, gd, wd = DATA[interval][s]
    btc_d = DATA["btc_d"]
    btc = DATA["btc_" + interval]
    r = k.simule_et(s, df, gd, btc_d, btc, haftalik=wd, params=prm, giris_bas=pd.Timestamp(IS_BAS))
    return r.islemler


def calistir(prm, semboller, interval="4h", havuz=None):
    isler = [(s, prm, interval) for s in semboller if s in DATA[interval]]
    sonuc = havuz.map(_tek, isler) if havuz else list(map(_tek, isler))
    tr = pd.DataFrame([x for lst in sonuc for x in lst])
    return tr


def metrik(tr, bas, bit=None):
    if tr.empty:
        return dict(n=0, wr=np.nan, R=0.0, Rpt=np.nan, L=0.0, S=0.0, dd=0.0)
    t = tr[(tr["giris_zaman"] >= pd.Timestamp(bas)) & ((tr["giris_zaman"] <= pd.Timestamp(bit)) if bit else True)]
    if t.empty:
        return dict(n=0, wr=np.nan, R=0.0, Rpt=np.nan, L=0.0, S=0.0, dd=0.0)
    eq = t.sort_values("cikis_zaman")["sonuc_r"].cumsum()
    return dict(n=len(t), wr=round(100 * (t.sonuc_r > 0).mean(), 1), R=round(t.sonuc_r.sum(), 2),
                Rpt=round(t.sonuc_r.mean(), 3), L=round(t[t.yon == 1].sonuc_r.sum(), 2),
                S=round(t[t.yon == -1].sonuc_r.sum(), 2), dd=round((eq.cummax().clip(lower=0) - eq).max(), 1))


def satir(ad, tr):
    a, b = metrik(tr, IS_BAS, IS_BIT), metrik(tr, OOS_BAS)
    return {"ayar": ad, **{f"IS_{k_}": v for k_, v in a.items()}, **{f"OOS_{k_}": v for k_, v in b.items()}}


SENARYOLAR = [
    ("TEMEL", {}),
    ("long: kapali filtre", {"long_sart": "Kapali"}),
    ("long: coin>200", {"long_sart": "Coin > EMA200"}),
    ("long: btc ve coin>200", {"long_sart": "BTC ve coin > EMA200"}),
    ("sadece short", {"yon": "Sadece Short"}),
    ("sadece long", {"yon": "Sadece Long"}),
    ("tp1 %50", {"tp1_pct": 50.0}),
    ("tp1 %60", {"tp1_pct": 60.0}),
    ("tp1 %80", {"tp1_pct": 80.0}),
    ("trail 2.0", {"trail_atr_mult": 2.0}),
    ("trail 3.0", {"trail_atr_mult": 3.0}),
    ("trail 3.5", {"trail_atr_mult": 3.5}),
    ("zaman stop 12", {"time_stop_bars": 12}),
    ("zaman stop 30", {"time_stop_bars": 30}),
    ("zaman stop yok", {"use_time_stop": False}),
    ("be +0", {"be_buf_r": 0.0}),
    ("be +0.2", {"be_buf_r": 0.2}),
    ("tp1 0.6R", {"tp1_r": 0.6, "tp1_min_r": 0.5, "tp1_max_r": 0.9}),
    ("tp1 1.0R", {"tp1_r": 1.0, "tp1_min_r": 0.8, "tp1_max_r": 1.3}),
    ("tp2 tabani 2.0", {"def_tp2_r": 2.0, "use_auto_params": False}),
    ("tp2 tabani 3.0", {"def_tp2_r": 3.0, "use_auto_params": False}),
    ("sembol tablosu kapali", {"use_auto_params": False}),
    ("hacim 1.5x", {"vol_mult": 1.5}),
    ("hacim 2.5x", {"vol_mult": 2.5}),
    ("direnc 50", {"resistance_len": 50}),
    ("direnc 120", {"resistance_len": 120}),
    ("adx 20", {"adx_min": 20.0}),
    ("adx 30", {"adx_min": 30.0}),
    ("yumusak 3/4", {"min_yumusak": 3}),
    ("giris: kirilim kapanisi", {"entry_mode": "Kirilim kapanisi"}),
    ("giris: sadece retest", {"entry_mode": "Sadece retest"}),
    ("teyit kapali", {"use_teyit": False}),
    ("max stop 2.5 ATR", {"max_stop_atr": 2.5}),
    ("max stop 4 ATR", {"max_stop_atr": 4.0}),
    ("seviye stop 1.0", {"seviye_stop_atr": 1.0}),
    ("seviye stop 2.0", {"seviye_stop_atr": 2.0}),
    ("seviye stop kapali", {"seviye_stop_atr": 0.0}),
    ("engel 0.3R", {"min_room_r": 0.3}),
    ("engel 0.8R", {"min_room_r": 0.8}),
    ("engel kontrolu yok", {"use_room": False}),
    ("panik %3", {"panic_pct": 3.0}),
    ("panik %6", {"panic_pct": 6.0}),
    ("panik yok", {"use_panic": False}),
    ("piyasa EMA 20", {"mkt_ema_len": 20}),
    ("piyasa EMA 100", {"mkt_ema_len": 100}),
    ("piyasa MACD de", {"mkt_macd_req": True}),
    ("fib kapali", {"use_fib": False}),
    ("ana trend acik", {"use_ana_trend": True}),
    ("haftalik MACD acik", {"use_w_macd": True}),
    ("gunluk MACD acik", {"use_d_macd": True}),
    ("yuksek isabet profili", {"yuksek_isabet": True}),
    ("cooldown 0", {"cooldown_bars": 0}),
    ("cooldown 6", {"cooldown_bars": 6}),
    ("min kalite B", {"min_kalite": "B"}),
    ("RSI ust 80", {"def_rsi_max": 80.0, "use_auto_params": False}),
    ("RSI orta 55", {"rsi_min": 55.0}),
    ("erken BE 0.5R", {"erken_be_r": 0.5}),
    ("max oynaklik %5", {"max_atr_pct": 5.0}),
    ("komisyon %0.05 (vadeli)", {"komisyon_pct": 0.05}),
]

KOMBOLAR = [
    ("TEMEL", {}),
    ("C1 kirilim kapanisi", {"entry_mode": "Kirilim kapanisi"}),
    ("C2 C1+zaman30", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30}),
    ("C3 C2+trail3", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "trail_atr_mult": 3.0}),
    ("C4 C3+tp1%80", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "trail_atr_mult": 3.0, "tp1_pct": 80.0}),
    ("C5 C1+zamanyok", {"entry_mode": "Kirilim kapanisi", "use_time_stop": False}),
    ("C6 C2+tp1 1.0R", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "tp1_r": 1.0, "tp1_min_r": 0.8, "tp1_max_r": 1.3}),
    ("C7 C2 sadece short", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "yon": "Sadece Short"}),
    ("C8 C2+direnc120", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "resistance_len": 120}),
    ("C9 C2+engel0.8", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "min_room_r": 0.8}),
    ("C10 C2+adx30", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "adx_min": 30.0}),
    ("C11 C2+long coin>200", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "long_sart": "BTC ve coin > EMA200"}),
    ("C12 C2+trail3+tp1 1.0R", {"entry_mode": "Kirilim kapanisi", "time_stop_bars": 30, "trail_atr_mult": 3.0, "tp1_r": 1.0, "tp1_min_r": 0.8, "tp1_max_r": 1.3}),
]
STOK_HARIC = {"UUSDT", "INTCBUSDT", "CRCLBUSDT", "MUBUSDT", "SKHYBUSDT", "QQQBUSDT", "SNDKBUSDT", "SPCXBUSDT"}


def tavanli(tr, cap):
    """Ayni yonde ayni anda en fazla 'cap' pozisyon: fazla sinyaller atlanir."""
    if tr.empty or cap is None:
        return tr
    t = tr.sort_values(["giris_zaman", "symbol"]).reset_index(drop=True)
    acik = []
    keep = []
    for i, r in t.iterrows():
        acik = [(c, y) for c, y in acik if c > r.giris_zaman]
        if sum(1 for _, y in acik if y == r.yon) < cap:
            keep.append(i)
            acik.append((r.cikis_zaman, r.yon))
    return t.loc[keep]

FORM_SENARYO = []
for F in ["CIFT", "OBO", "TREND", "UCGEN", "BAYRAK"]:
    FORM_SENARYO += [
        (f"{F} tek basina", {"formasyonlar": (F,), "sadece_formasyon": True}),
        (f"{F} tek, hacim sartsiz", {"formasyonlar": (F,), "sadece_formasyon": True, "form_vol_mult": 0.0}),
        (f"v6.1 + {F}", {"formasyonlar": (F,)}),
    ]
    if F in ("CIFT", "OBO"):
        FORM_SENARYO.append((f"{F} tek, trend serbest", {"formasyonlar": (F,), "sadece_formasyon": True, "form_trend_serbest": True}))
FORM_SENARYO = [("v6.1 TEMEL", {})] + FORM_SENARYO + [
    ("v6.1 + TUM formasyonlar", {"formasyonlar": ("CIFT", "OBO", "TREND", "UCGEN", "BAYRAK")}),
    ("TUM formasyonlar tek", {"formasyonlar": ("CIFT", "OBO", "TREND", "UCGEN", "BAYRAK"), "sadece_formasyon": True}),
    ("sikisma filtresi 6 ATR", {"use_base": True, "max_base_atr": 6.0}),
    ("sikisma filtresi 8 ATR", {"use_base": True, "max_base_atr": 8.0}),
    ("sikisma filtresi 10 ATR", {"use_base": True, "max_base_atr": 10.0}),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    mod = sys.argv[1] if len(sys.argv) > 1 else "grid"
    t0 = time.time()
    DATA["btc_d"] = veri.mumlar_onbellekli("BTCUSDT", "1d", "2019-06-01")

    if mod == "grid":
        DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", VERI_BAS)
        DATA["4h"] = yukle(COINLER)
        print("veri hazir", len(DATA["4h"]), round(time.time() - t0), flush=True)
        with mp.Pool(4) as hv:
            rows = []
            temel = None
            for ad, prm in SENARYOLAR:
                tr = calistir(prm, COINLER, "4h", hv)
                if ad == "TEMEL":
                    temel = tr
                    tr.to_csv(f"{OUT}/temel_islemler.csv", index=False)
                rows.append(satir(ad, tr))
                print(rows[-1], flush=True)
        res = pd.DataFrame(rows)
        res.to_csv(f"{OUT}/grid.csv", index=False)
        with open(f"{OUT}/grid.txt", "w") as f:
            f.write(res.to_string(index=False))

        # TEMEL islemlerin kirilimi
        t = temel.copy()
        t["donem"] = np.where(t.giris_zaman >= pd.Timestamp(OOS_BAS), "OOS", "IS")
        t["yonA"] = t.yon.map({1: "L", -1: "S"})
        with open(f"{OUT}/kirilim_analizi.txt", "w") as f:
            for col in ["tip", "kalite", "neden", "yonA"]:
                g = t.groupby(["donem", "yonA", col] if col != "yonA" else ["donem", col])["sonuc_r"].agg(
                    ["size", "sum", "mean", lambda x: (x > 0).mean()]).round(3)
                f.write(f"\n=== {col} ===\n{g.to_string()}\n")
            t["ay"] = pd.to_datetime(t.giris_zaman).dt.to_period("M")
            f.write("\n=== aylik ===\n" + t.groupby(["ay", "yonA"])["sonuc_r"].agg(["size", "sum"]).round(2).unstack().to_string())
            # eszamanli pozisyon
            ev = []
            for _, r in t.iterrows():
                ev += [(r.giris_zaman, 1, r.yon), (r.cikis_zaman, -1, r.yon)]
            ev.sort()
            acik = {1: 0, -1: 0}
            mx = {1: 0, -1: 0}
            for _, d, y in ev:
                acik[y] += d
                mx[y] = max(mx[y], acik[y])
            f.write(f"\n=== max eszamanli acik: long {mx[1]}, short {mx[-1]} ===\n")
        print("bitti", round(time.time() - t0), flush=True)

    elif mod == "tf":
        rows = []
        for iv in ["4h", "6h", "8h", "12h"]:
            DATA["btc_" + iv] = veri.mumlar_onbellekli("BTCUSDT", iv, VERI_BAS)
            DATA[iv] = yukle(COINLER, iv)
            with mp.Pool(4) as hv:
                tr = calistir({}, COINLER, iv, hv)
            rows.append(satir(f"zaman dilimi {iv}", tr))
            print(rows[-1], flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/tf.csv", index=False)
        with open(f"{OUT}/tf.txt", "w") as f:
            f.write(pd.DataFrame(rows).to_string(index=False))

    elif mod == "evren":
        tick = veri._get("/api/v3/ticker/24hr", {})
        haric = set(COINLER) | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "PAXGUSDT", "EURIUSDT", "USDEUSDT"}
        aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
                and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
        aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
        yeni = [d["symbol"] for d in aday[:70]]
        DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", VERI_BAS)
        DATA["4h"] = yukle(yeni)
        print("yeni coin", len(DATA["4h"]), list(DATA["4h"]), flush=True)
        with mp.Pool(4) as hv:
            tr = calistir({}, list(DATA["4h"]), "4h", hv)
            tr2 = calistir({"yon": "Sadece Short"}, list(DATA["4h"]), "4h", hv)
        rows = [satir("YENI 70 coin - temel", tr), satir("YENI 70 coin - sadece short", tr2)]
        tr.to_csv(f"{OUT}/evren_islemler.csv", index=False)
        g = tr.groupby("symbol")["sonuc_r"].agg(["size", "sum"]).round(2).sort_values("sum")
        with open(f"{OUT}/evren.txt", "w") as f:
            f.write(pd.DataFrame(rows).to_string(index=False) + "\n\n" + g.to_string())
        print(rows, flush=True)

    elif mod == "kombo":
        tick = veri._get("/api/v3/ticker/24hr", {})
        haric = set(COINLER) | STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
        aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
                and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
        aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
        yeni = [d["symbol"] for d in aday[:70]]
        DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", VERI_BAS)
        DATA["4h"] = yukle(COINLER + yeni)
        yeni = [s_ for s_ in yeni if s_ in DATA["4h"]]
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in KOMBOLAR:
                tr = calistir(prm, COINLER + yeni, "4h", hv)
                a46 = tr[tr.symbol.isin(COINLER)]
                ay = tr[tr.symbol.isin(yeni)]
                for etiket, x in (("46", a46), ("YENI", ay), ("HEPSI", tr)):
                    rows.append(satir(f"{ad} [{etiket}]", x))
                for cap in (5, 8, 12):
                    rows.append(satir(f"{ad} [HEPSI, tavan {cap}/yon]", tavanli(tr, cap)))
                print(ad, flush=True)
                if ad.startswith("C2 "):
                    tr.to_csv(f"{OUT}/c2_islemler.csv", index=False)
        res = pd.DataFrame(rows)
        res.to_csv(f"{OUT}/kombo.csv", index=False)
        with open(f"{OUT}/kombo.txt", "w") as f:
            f.write(res.to_string(index=False))

    elif mod == "formasyon":
        tick = veri._get("/api/v3/ticker/24hr", {})
        haric = set(COINLER) | STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
        aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
                and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
        aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
        yeni = [d["symbol"] for d in aday[:70]]
        DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", VERI_BAS)
        DATA["4h"] = yukle(COINLER + yeni)
        yeni = [s_ for s_ in yeni if s_ in DATA["4h"]]
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in FORM_SENARYO:
                tr = calistir(prm, COINLER + yeni, "4h", hv)
                for etiket, x in (("46", tr[tr.symbol.isin(COINLER)] if len(tr) else tr),
                                  ("YENI", tr[tr.symbol.isin(yeni)] if len(tr) else tr), ("HEPSI", tr)):
                    rows.append(satir(f"{ad} [{etiket}]", x))
                if len(tr) and "formasyonlar" in prm:
                    ft = tr[~tr.tip.isin(["KIRILIM", "GUCLU KIRILIM", "RETEST", "TEYIT"])]
                    for tip, g in ft.groupby("tip"):
                        rows.append(satir(f"   {ad} :: sadece {tip} islemleri [HEPSI]", g))
                print(ad, flush=True)
        res = pd.DataFrame(rows)
        res.to_csv(f"{OUT}/formasyon.csv", index=False)
        with open(f"{OUT}/formasyon.txt", "w") as f:
            f.write(res.to_string(index=False))


if __name__ == "__main__":
    main()
