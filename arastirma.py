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
    s1 = DATA.get("1h", {}).get(s) if prm.get("ltf_giris") else None
    r = k.simule_et(s, df, gd, btc_d, btc, haftalik=wd, params=prm, giris_bas=pd.Timestamp(IS_BAS), saatlik=s1)
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

KOVALAMA = [("v6.1 TEMEL", {})]
for v in (0.5, 1.0, 1.5):
    KOVALAMA.append((f"kirilim mesafesi <= {v} ATR", {"max_kirilim_atr": v}))
for v in (4.0, 6.0, 8.0):
    KOVALAMA.append((f"onceki 10 mum hareket <= {v} ATR", {"max_onceki_atr": v}))
for v in (6.0, 8.0, 10.0):
    KOVALAMA.append((f"stop <= %{v:g}", {"max_risk_pct": v}))
for v in (2.0, 2.5):
    KOVALAMA.append((f"mum boyu <= {v} ATR", {"max_candle_range_atr": v}))
for v in (2.0, 2.5):
    KOVALAMA.append((f"EMA21 uzaklik <= {v} ATR", {"max_ext_atr": v}))
KOVALAMA.append(("kapanis gucu >= 0.7", {"min_close_pos": 0.7}))

LIMIT = [("v6.1 TEMEL (kapanista giris)", {})]
for lm in ("seviye", "orta", "seviye_atr"):
    for nb in (3, 6, 10):
        LIMIT.append((f"limit {lm} / {nb} mum", {"limit_mod": lm, "limit_bar": nb}))
LIMIT.append(("limit seviye+0.6ATR / 6 mum", {"limit_mod": "seviye_atr", "limit_atr": 0.6, "limit_bar": 6}))

PROFESYONEL = [
    ("v6.1 TEMEL", {}),
    ("1s giris: 0.382 geri cekilme, 3 mum4", {"ltf_giris": "geri_cekilme", "ltf_max_bar4": 3}),
    ("1s giris: 0.382 geri cekilme, 6 mum4", {"ltf_giris": "geri_cekilme", "ltf_max_bar4": 6}),
    ("1s giris: ilk kirmizi mum, 3 mum4", {"ltf_giris": "ilk_dusus", "ltf_max_bar4": 3}),
    ("1s giris: ilk kirmizi mum, 6 mum4", {"ltf_giris": "ilk_dusus", "ltf_max_bar4": 6}),
    ("1s giris: geri cekilme, min stop 0.8 ATR", {"ltf_giris": "geri_cekilme", "ltf_max_bar4": 3, "ltf_min_stop": 0.8}),
    ("1s giris: geri cekilme, min stop 0.3 ATR", {"ltf_giris": "geri_cekilme", "ltf_max_bar4": 3, "ltf_min_stop": 0.3}),
    ("v6.1 + trend ici geri cekilme", {"geri_cekilme": True}),
    ("SADECE trend ici geri cekilme", {"geri_cekilme": True, "sadece_formasyon": True}),
    ("trend ici geri cekilme taze 5", {"geri_cekilme": True, "sadece_formasyon": True, "gc_taze_bar": 5}),
]

BASARISIZ = [("v6.1 TEMEL", {})]
for bb in (3, 6, 0):
    for xa in (0.0, 0.3, 0.6):
        BASARISIZ.append((f"basarisiz kirilim cikisi: {bb if bb else 'TP1e kadar'} mum, seviye-{xa} ATR",
                          {"basarisiz_cikis": True, "bc_bar": bb, "bc_atr": xa}))

_B = {"basarisiz_cikis": True, "bc_bar": 3, "bc_atr": 0.3}
SEVIYE = [("v6.2 TEMEL (fitil, 80 mum)", dict(_B)),
          ("govde kapanisi seviyesi", dict(_B, seviye_tipi="kapanis")),
          ("en az 2 kez test edilmis", dict(_B, min_test=2)),
          ("en az 3 kez test edilmis", dict(_B, min_test=3)),
          ("en az 2 test, tolerans 0.3 ATR", dict(_B, min_test=2, test_tol_atr=0.3)),
          ("govde + en az 2 test", dict(_B, seviye_tipi="kapanis", min_test=2)),
          ("gunluk 20 gun seviyesi", dict(_B, gunluk_seviye=20)),
          ("gunluk 30 gun seviyesi", dict(_B, gunluk_seviye=30)),
          ("gunluk 14 gun seviyesi", dict(_B, gunluk_seviye=14))]

_B2 = {"basarisiz_cikis": True, "bc_bar": 3, "bc_atr": 0.3}
FIKIR = [("v6.2 TEMEL", dict(_B2)),
         ("TP2 yok, trail 2.5", dict(_B2, tp2_yok=True)),
         ("TP2 yok, trail 3.0", dict(_B2, tp2_yok=True, trail_atr_mult=3.0)),
         ("TP2 yok, trail 4.0", dict(_B2, tp2_yok=True, trail_atr_mult=4.0)),
         ("TP2 yok, trail 3.0, TP1 %50", dict(_B2, tp2_yok=True, trail_atr_mult=3.0, tp1_pct=50.0)),
         ("gunluk EMA20 onayi", dict(_B2, gunluk_ema_onay=20)),
         ("gunluk EMA10 onayi", dict(_B2, gunluk_ema_onay=10)),
         ("gunluk EMA50 onayi", dict(_B2, gunluk_ema_onay=50)),
         ("BTC yuksek oynaklik rejimi", dict(_B2, btc_vol_rejim="yuksek")),
         ("BTC dusuk oynaklik rejimi", dict(_B2, btc_vol_rejim="dusuk"))]

YAS = [("v6.2 TEMEL", dict(_B2))] + [(f"seviye en az {n} mum yasli", dict(_B2, min_seviye_yas=n)) for n in (2, 3, 5, 8, 12, 20)]
UZUN = [("v6.2 TEMEL (80 mum)", dict(_B2))] + [(f"direnc {n} mum", dict(_B2, resistance_len=n)) for n in (30, 50, 60, 100, 120, 160, 200, 300)]
_GRID = [(a_, b_) for a_, b_ in SENARYOLAR if not a_.startswith("giris:") and a_ != "TEMEL"]
_GRID += [("hacim 1.25x", {"vol_mult": 1.25}), ("hacim 1.75x", {"vol_mult": 1.75}), ("hacim 3x", {"vol_mult": 3.0}),
          ("kirilim tamponu 0", {"break_buf_atr": 0.0}), ("kirilim tamponu 0.2", {"break_buf_atr": 0.2}),
          ("kirilim tamponu 0.3", {"break_buf_atr": 0.3}), ("kapanis gucu 0.5", {"min_close_pos": 0.5}),
          ("kapanis gucu 0.7", {"min_close_pos": 0.7}), ("basarisiz cikis 0.2 ATR", {"bc_atr": 0.2}),
          ("basarisiz cikis 0.5 ATR", {"bc_atr": 0.5}), ("basarisiz cikis 2 mum", {"bc_bar": 2}),
          ("basarisiz cikis 5 mum", {"bc_bar": 5})]
KALIB = [[("v6.2 TEMEL", dict(_B2))] + [(a_, dict(_B2, **b_)) for a_, b_ in _GRID[j::3]] for j in range(3)]
EK = [("v6.2 TEMEL", dict(_B2)),
      ("goreli guc 30 mum > 0", dict(_B2, rs_bar=30)),
      ("goreli guc 60 mum > 0", dict(_B2, rs_bar=60)),
      ("goreli guc 120 mum > 0", dict(_B2, rs_bar=120)),
      ("goreli guc 60 mum > %5", dict(_B2, rs_bar=60, rs_min=0.05)),
      ("goreli guc 120 mum > %10", dict(_B2, rs_bar=120, rs_min=0.10)),
      ("yeniden giris 3 mum", dict(_B2, yeniden_giris=3)),
      ("yeniden giris 6 mum", dict(_B2, yeniden_giris=6)),
      ("yeniden giris 12 mum", dict(_B2, yeniden_giris=12)),
      ("yeniden giris 6 mum, tampon 0.3 ATR", dict(_B2, yeniden_giris=6, yeniden_buf_atr=0.3))]
K2 = [("v6.2 TEMEL", dict(_B2))]
for ms in (3.0, 3.5, 4.0, 4.5):
    for tp in (70.0, 75.0, 80.0, 85.0):
        for bc in (0.15, 0.2, 0.25, 0.3):
            K2.append((f"stop{ms} tp1%{tp:.0f} bc{bc}", dict(_B2, max_stop_atr=ms, tp1_pct=tp, bc_atr=bc)))
K2S = [K2[:1] + K2[1 + j::4] for j in range(4)]
K3 = [("v6.2 TEMEL", dict(_B2))] + [(f"stop3.5 tp1%{tp:.0f} bc{bc}", dict(_B2, max_stop_atr=3.5, tp1_pct=tp, bc_atr=bc))
                                   for tp in (80.0, 85.0, 90.0, 95.0, 100.0) for bc in (0.0, 0.05, 0.1, 0.15, 0.2)]
V63 = [("v6.3", dict(_B2, max_stop_atr=3.5, tp1_pct=90.0, bc_atr=0.15))]
_B3 = dict(V63[0][1])
YENI6 = [("v6.3 TEMEL", dict(_B3)),
         ("RSI dinamik ust (BB200 ust bandi)", dict(_B3, rsi_dinamik="ust")),
         ("RSI dinamik orta (RSI > BB200 ortasi)", dict(_B3, rsi_dinamik="orta")),
         ("RSI dinamik ikisi", dict(_B3, rsi_dinamik="ikisi")),
         ("z-skor20 < 2.5", dict(_B3, z_max=2.5)),
         ("z-skor20 < 3.0", dict(_B3, z_max=3.0)),
         ("z-skor50 < 2.5", dict(_B3, z_max=2.5, z_len=50)),
         ("z-skor50 < 3.0", dict(_B3, z_max=3.0, z_len=50)),
         ("verimlilik orani20 >= 0.2", dict(_B3, er_min=0.2)),
         ("verimlilik orani20 >= 0.3", dict(_B3, er_min=0.3)),
         ("verimlilik orani20 >= 0.4", dict(_B3, er_min=0.4)),
         ("choppiness < 61.8", dict(_B3, chop_max=61.8)),
         ("choppiness < 55", dict(_B3, chop_max=55.0)),
         ("choppiness < 50", dict(_B3, chop_max=50.0)),
         ("ters FVG 1 ATR icinde ise red", dict(_B3, fvg_atr=1.0)),
         ("ters FVG 2 ATR icinde ise red", dict(_B3, fvg_atr=2.0)),
         ("ters FVG 3 ATR icinde ise red", dict(_B3, fvg_atr=3.0)),
         ("BTC korelasyon30 >= 0", dict(_B3, kor_min=0.0)),
         ("BTC korelasyon30 >= 0.3", dict(_B3, kor_min=0.3)),
         ("BTC korelasyon60 >= 0.3", dict(_B3, kor_min=0.3, kor_len=60)),
         ("BTC korelasyon30 >= 0.5", dict(_B3, kor_min=0.5))]
YENI6S = [YENI6[:1] + YENI6[1 + j::3] for j in range(3)]
MR = []
for rj in ("", "adx", "chop", "trend"):
    MR += [(f"BB20 2.0 | rejim {rj or 'yok'}", {"sinyal": "bb", "bb_k": 2.0, "rejim": rj}),
           (f"BB20 2.5 | rejim {rj or 'yok'}", {"sinyal": "bb", "bb_k": 2.5, "rejim": rj}),
           (f"RSI2 10/90 | rejim {rj or 'yok'}", {"sinyal": "rsi2", "rsi_alt": 10.0, "rsi_ust": 90.0, "rejim": rj}),
           (f"RSI2 5/95 | rejim {rj or 'yok'}", {"sinyal": "rsi2", "rsi_alt": 5.0, "rsi_ust": 95.0, "rejim": rj}),
           (f"Z50 2.0 | rejim {rj or 'yok'}", {"sinyal": "z", "z_len": 50, "z_esik": 2.0, "rejim": rj}),
           (f"Z50 2.5 | rejim {rj or 'yok'}", {"sinyal": "z", "z_len": 50, "z_esik": 2.5, "rejim": rj})]
MRS = [MR[j::4] for j in range(4)]
MR2 = []
for tf in ("4h", "1d"):
    for st in (3.0, 6.0):
        for zm in (5, 15):
            MR2 += [(f"{tf} RSI2 10/90 trend | stop {st} ATR, {zm} mum", {"tf": tf, "sinyal": "rsi2", "rejim": "trend", "stop_atr": st, "zaman": zm}),
                    (f"{tf} BB20 2.5 trend | stop {st} ATR, {zm} mum", {"tf": tf, "sinyal": "bb", "bb_k": 2.5, "rejim": "trend", "stop_atr": st, "zaman": zm}),
                    (f"{tf} BB20 2.5 chop | stop {st} ATR, {zm} mum", {"tf": tf, "sinyal": "bb", "bb_k": 2.5, "rejim": "chop", "stop_atr": st, "zaman": zm})]
MRS += [MR2[j::4] for j in range(4)]


def _mr_tek(args):
    import ortalama
    s_, prm = args
    df, gd, wd = DATA["4h"][s_]
    prm = dict(prm)
    if prm.pop("tf", "4h") == "1d":
        df = gd
    return ortalama.simule(s_, df, DATA["btc_d"], prm, giris_bas=pd.Timestamp(IS_BAS))


def mr_calistir(mod, liste):
    tick = veri._get("/api/v3/ticker/24hr", {})
    haric = set(COINLER) | STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                            "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                            "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
    aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
            and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
    aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    yeni = [d["symbol"] for d in aday[:70]]
    DATA["4h"] = yukle(COINLER + yeni)
    sem = list(DATA["4h"])
    kir = None
    try:
        kir = pd.read_csv(f"{OUT}/v63_islemler.csv", parse_dates=["cikis_zaman"])
        kir = kir[kir.cikis_zaman >= pd.Timestamp(IS_BAS)].groupby(kir.cikis_zaman.dt.to_period("M"))["sonuc_r"].sum()
    except Exception as exc:
        print("v63 yok", exc)
    rows = []
    with mp.Pool(4) as hv:
        for ad, prm in liste:
            sonuc = hv.map(_mr_tek, [(s_, prm) for s_ in sem])
            tr = pd.DataFrame([x for lst in sonuc for x in lst])
            row = satir(ad, tr)
            if len(tr) and kir is not None:
                ay = tr[tr.cikis_zaman >= pd.Timestamp(IS_BAS)].groupby(pd.to_datetime(tr.cikis_zaman).dt.to_period("M"))["sonuc_r"].sum()
                j = pd.concat([kir.rename("kir"), ay.rename("mr")], axis=1).fillna(0)
                row["ay_kor"] = round(j.kir.corr(j.mr), 2)
                kotu = j[j.kir < 0]
                row["kir_kotu_ay_mr"] = round(kotu.mr.sum(), 1)
                row["kir_kotu_ay_n"] = len(kotu)
                birlikte = j.kir + j.mr
                eq = birlikte.cumsum()
                row["birlikte_dd_ay"] = round((eq.cummax() - eq).max(), 1)
                eqk = j.kir.cumsum()
                row["kir_dd_ay"] = round((eqk.cummax() - eqk).max(), 1)
            rows.append(row)
            print(ad, flush=True)
    pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)


K2S += [K3[:1] + K3[1::2], K3[:1] + K3[2::2]]
BTCF = [("v6.2 TEMEL (long: BTC > gunluk EMA200)", dict(_B2)),
        ("long: BTC EMA200 sarti yok (sadece EMA50)", dict(_B2, long_sart="Kapali")),
        ("long: coin > EMA200", dict(_B2, long_sart="Coin > EMA200")),
        ("long: BTC ve coin > EMA200", dict(_B2, long_sart="BTC ve coin > EMA200")),
        ("long: BTC veya coin > EMA200", dict(_B2, long_sart="BTC veya coin > EMA200")),
        ("long: BTC > EMA100", dict(_B2, btc_long_ema=100)),
        ("long: BTC > EMA150", dict(_B2, btc_long_ema=150)),
        ("long: BTC > EMA250", dict(_B2, btc_long_ema=250)),
        ("long: BTC > EMA300", dict(_B2, btc_long_ema=300)),
        ("piyasa EMA 30 (iki yon)", dict(_B2, mkt_ema_len=30)),
        ("piyasa EMA 20 (iki yon)", dict(_B2, mkt_ema_len=20)),
        ("piyasa EMA 100 (iki yon)", dict(_B2, mkt_ema_len=100)),
        ("short: BTC < EMA200", dict(_B2, short_sart="BTC < EMA200")),
        ("short: coin < EMA200", dict(_B2, short_sart="Coin < EMA200")),
        ("long BTC veya coin + short coin<200", dict(_B2, long_sart="BTC veya coin > EMA200", short_sart="Coin < EMA200"))]
ODA = [("v6.2 TEMEL (engel 0.5R, pivot 10)", dict(_B2)),
       ("engel 0.8R", dict(_B2, min_room_r=0.8)),
       ("engel 1.0R", dict(_B2, min_room_r=1.0)),
       ("engel 1.5R", dict(_B2, min_room_r=1.5)),
       ("pivot 5, engel 0.5R", dict(_B2, room_pivot_len=5)),
       ("pivot 5, engel 1.0R", dict(_B2, room_pivot_len=5, min_room_r=1.0)),
       ("pivot 20, engel 1.0R", dict(_B2, room_pivot_len=20, min_room_r=1.0))]


def teshis(sembol, bas):
    df, gd, wd = DATA["4h"][sembol]
    r = k.simule_et(sembol, df, gd, DATA["btc_d"], DATA["btc_4h"], haftalik=wd, params=dict(_B2),
                    giris_bas=pd.Timestamp(IS_BAS))
    with open(f"{OUT}/teshis_{sembol}.txt", "w") as f:
        for o in r.olaylar:
            if o.zaman >= pd.Timestamp(bas):
                f.write(f"{o.zaman} {o.tur} {o.yon} {o.veri}\n")
        f.write("\nfiltre: " + str(r.filtre) + "\n\nmumlar:\n")
        f.write(df[df.open_time >= pd.Timestamp(bas)].to_string() + "\n")
        ph = k.pivot(df["high"].values, 10, True)
        f.write("\npivot10 tepeler (son 400 mum):\n")
        for j in range(len(df) - 400, len(df)):
            if not np.isnan(ph[j]):
                f.write(f"  {df.open_time.iloc[j]} {ph[j]}\n")


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
        if mod == "profesyonel":
            DATA["1h"] = {}
            for s_ in list(DATA["4h"]):
                try:
                    DATA["1h"][s_] = veri.mumlar_onbellekli(s_, "1h", "2024-05-15")
                except Exception as exc:
                    print("1s veri yok", s_, exc, flush=True)
            print("1s veri hazir", len(DATA["1h"]), flush=True)
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in KOMBOLAR:
                tr = calistir(prm, COINLER + yeni, "4h", hv)
                if mod == "v63":
                    tr.to_csv(f"{OUT}/v63_islemler.csv", index=False)
                if mod == "ek" and ad == "v6.2 TEMEL":
                    tr.to_csv(f"{OUT}/ek_temel_islemler.csv", index=False)
                if mod == "ek" and len(tr) and (tr.tip == "YENIDEN").any():
                    rows.append(satir(f"   {ad} :: sadece YENIDEN [HEPSI]", tr[tr.tip == "YENIDEN"]))
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

    elif mod == "genislik":
        tick = veri._get("/api/v3/ticker/24hr", {})
        haric = set(COINLER) | STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
        aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
                and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
        aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
        evren = COINLER + [d["symbol"] for d in aday[:70]]
        kap, ust50, kir_u, kir_a = {}, {}, {}, {}
        for s_ in evren:
            try:
                df = veri.mumlar_onbellekli(s_, "4h", VERI_BAS)
            except Exception:
                continue
            if len(df) < 300 or s_ in ("PAXGUSDT",):
                continue
            ix = pd.to_datetime(df["open_time"])
            c_ = df["close"].to_numpy(float); h_ = df["high"].to_numpy(float); l_ = df["low"].to_numpy(float)
            e50 = k.ema(c_, 50)
            ok = np.arange(len(c_)) >= 60
            ust50[s_] = pd.Series(np.where(ok, (c_ > e50).astype(float), np.nan), index=ix)
            hh = pd.Series(h_).rolling(80).max().shift(1).to_numpy(); ll = pd.Series(l_).rolling(80).min().shift(1).to_numpy()
            kir_u[s_] = pd.Series(np.where(ok, (c_ > hh).astype(float), np.nan), index=ix)
            kir_a[s_] = pd.Series(np.where(ok, (c_ < ll).astype(float), np.nan), index=ix)
            kap[s_] = pd.Series(c_, index=ix)
        U = pd.DataFrame(ust50); KU = pd.DataFrame(kir_u); KA = pd.DataFrame(kir_a)
        oran50 = U.mean(axis=1)                      # % coin EMA50 ustunde
        oran50_deg = oran50 - oran50.shift(6)         # 1 gunluk degisim
        ku6 = KU.rolling(6, min_periods=1).sum().mean(axis=1) * 100   # son 1 gunde yukari kirilim yapan coin % (tekrarlar dahil)
        ka6 = KA.rolling(6, min_periods=1).sum().mean(axis=1) * 100
        tr = pd.read_csv(f"{OUT}/v63_islemler.csv", parse_dates=["giris_zaman"])
        tr = tr[tr.giris_zaman >= pd.Timestamp(IS_BAS)].copy()
        t_ = tr.giris_zaman
        d_ = tr.yon.to_numpy()
        tr["genislik"] = np.where(d_ == 1, oran50.reindex(t_).to_numpy(), 1 - oran50.reindex(t_).to_numpy())
        tr["genislik_deg"] = d_ * oran50_deg.reindex(t_).to_numpy()
        tr["ayni_yon_kirilim"] = np.where(d_ == 1, ku6.reindex(t_).to_numpy(), ka6.reindex(t_).to_numpy())
        tr["ters_yon_kirilim"] = np.where(d_ == 1, ka6.reindex(t_).to_numpy(), ku6.reindex(t_).to_numpy())
        tr["donem"] = np.where(tr.giris_zaman >= pd.Timestamp(OOS_BAS), "OOS", "IS")
        tr.to_csv(f"{OUT}/genislik_islemler.csv", index=False)
        out = []
        for f_ in ("genislik", "genislik_deg", "ayni_yon_kirilim", "ters_yon_kirilim"):
            q = tr[f_].rank(pct=True)
            tr["_k"] = pd.cut(q, [0, .2, .4, .6, .8, 1.0], labels=["1-en dusuk", "2", "3", "4", "5-en yuksek"], include_lowest=True)
            g = tr.groupby(["_k", "donem"], observed=True).agg(n=("sonuc_r", "size"), R=("sonuc_r", "sum"), Rpt=("sonuc_r", "mean"),
                                                               wr=("sonuc_r", lambda x: (x > 0).mean() * 100),
                                                               ort=(f_, "mean")).round(3).reset_index()
            g.insert(0, "ozellik", f_)
            out.append(g)
            print(g.to_string(index=False), flush=True)
        pd.concat(out).to_csv(f"{OUT}/genislik.csv", index=False)
        oran50.to_csv(f"{OUT}/genislik_seri.csv")
    elif mod.startswith("gen2") or mod.startswith("gen3") or mod in ("gen4", "gen5") or mod.startswith("ek3") or mod.startswith("opt") or mod == "secici" or mod.startswith("konf"):
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
        yeni = [x for x in yeni if x in DATA["4h"]]
        ku, ka = {}, {}
        for s_, (df, gd, wd) in DATA["4h"].items():
            if s_ == "PAXGUSDT":
                continue
            ix = pd.to_datetime(df["open_time"])
            h_ = df["high"].to_numpy(float); l_ = df["low"].to_numpy(float); c_ = df["close"].to_numpy(float)
            hh = pd.Series(h_).rolling(80).max().shift(1).to_numpy(); ll = pd.Series(l_).rolling(80).min().shift(1).to_numpy()
            ok = np.arange(len(c_)) >= 80
            ku[s_] = pd.Series(np.where(ok, (c_ > hh).astype(float), np.nan), index=ix)
            ka[s_] = pd.Series(np.where(ok, (c_ < ll).astype(float), np.nan), index=ix)
        KU = pd.DataFrame(ku).fillna(0); KA = pd.DataFrame(ka).fillna(0)
        senaryo = [("v6.3 TEMEL", dict(_B3))]
        if mod.startswith("konf"):
            GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
                     "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
                     "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
                     "APTUSDT", "HBARUSDT", "XLMUSDT"]
            up6 = (KU[GEN30].rolling(6, min_periods=1).max() > 0).sum(axis=1)
            B5 = dict(_B3, ters_s=up6, ters_max=0, vol_mult=2.5)
            senaryo = [("SU ANKI (v6.4 secici)", dict(B5))]
            for kf in ("fib300", "zirve180", "zirve360", "eski_pivot", "herhangi"):
                for tol in (0.3, 0.6, 1.0):
                    senaryo.append((f"cakisma {kf} (tol {tol} ATR)", dict(B5, konf=kf, konf_tol=tol)))
            parca = int(mod.split("-")[1])
            senaryo = senaryo[:1] + senaryo[1 + parca::3]
            DON = [("A", "2024-07-01", "2025-06-30 23:59"), ("B", "2025-07-01", "2026-02-28 23:59"), ("C", "2026-03-01", None)]
            rows = []
            with mp.Pool(4) as hv:
                for ad, prm in senaryo:
                    tr = calistir(prm, COINLER + yeni, "4h", hv)
                    row = {"ayar": ad}
                    for dk, b_, e_ in DON:
                        for kk, vv in metrik(tr, b_, e_).items():
                            row[f"{dk}_{kk}"] = vv
                    rows.append(row)
                    print(ad, flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
            return
        if mod == "secici":
            GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
                     "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
                     "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
                     "APTUSDT", "HBARUSDT", "XLMUSDT"]
            up6 = (KU[GEN30].rolling(6, min_periods=1).max() > 0).sum(axis=1)
            B4 = dict(_B3, ters_s=up6, ters_max=0)
            DON = [("A", "2024-07-01", "2025-06-30 23:59"), ("B", "2025-07-01", "2026-02-28 23:59"), ("C", "2026-03-01", None)]
            rows = []
            with mp.Pool(4) as hv:
                for vm in (2.0, 2.25, 2.5, 2.75, 3.0):
                    tr = calistir(dict(B4, vol_mult=vm), COINLER + yeni, "4h", hv)
                    tr.to_csv(f"{OUT}/secici_{vm}.csv", index=False)
                    for etiket, x in (("46", tr[tr.symbol.isin(COINLER)]), ("YENI", tr[tr.symbol.isin(yeni)]), ("HEPSI", tr)):
                        row = {"ayar": f"hacim {vm}x [{etiket}]"}
                        for dk, b_, e_ in DON:
                            for kk, vv in metrik(x, b_, e_).items():
                                row[f"{dk}_{kk}"] = vv
                        rows.append(row)
                    print(vm, flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/secici.csv", index=False)
            return
        if mod.startswith("opt"):
            GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
                     "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
                     "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
                     "APTUSDT", "HBARUSDT", "XLMUSDT"]
            up6 = (KU[GEN30].rolling(6, min_periods=1).max() > 0).sum(axis=1)
            B4 = dict(_B3, ters_s=up6, ters_max=0)
            UZAY = {"resistance_len": [60, 70, 80, 90, 100, 120], "vol_mult": [1.5, 1.75, 2.0, 2.25, 2.5],
                    "min_close_pos": [0.5, 0.6, 0.7], "break_buf_atr": [0.0, 0.05, 0.1, 0.2],
                    "tp1_r": [0.6, 0.8, 1.0, 1.2], "use_fib_tp": [True, False], "tp1_pct": [70.0, 80.0, 90.0, 100.0],
                    "trail_atr_mult": [2.0, 2.5, 3.0], "bc_atr": [0.1, 0.15, 0.2, 0.3], "bc_bar": [2, 3, 4],
                    "max_stop_atr": [3.0, 3.5, 4.0, 5.0], "time_stop_bars": [12, 20, 30], "adx_min": [15.0, 20.0, 25.0]}
            j_ = int(mod.split("-")[1])
            rng = np.random.default_rng(1000 + j_)
            senaryo = [("TEMEL v6.4", dict(B4))] if j_ == 0 else []
            for q in range(20):
                ch_ = {k_: v_[rng.integers(len(v_))] for k_, v_ in UZAY.items()}
                senaryo.append((json.dumps({k_: (float(v_) if not isinstance(v_, bool) else v_) for k_, v_ in ch_.items()}), dict(B4, **ch_)))
            rows = []
            DON = [("A", "2024-07-01", "2025-06-30 23:59"), ("B", "2025-07-01", "2026-02-28 23:59"), ("C", "2026-03-01", None)]
            with mp.Pool(4) as hv:
                for ad, prm in senaryo:
                    tr = calistir(prm, COINLER + yeni, "4h", hv)
                    row = {"ayar": ad}
                    for dk, b_, e_ in DON:
                        m_ = metrik(tr, b_, e_)
                        for kk, vv in m_.items():
                            row[f"{dk}_{kk}"] = vv
                    rows.append(row)
                    print(len(rows), flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
            return
        if mod.startswith("ek3"):
            GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
                     "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
                     "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
                     "APTUSDT", "HBARUSDT", "XLMUSDT"]
            up6 = (KU[GEN30].rolling(6, min_periods=1).max() > 0).sum(axis=1)
            B4 = dict(_B3, ters_s=up6, ters_max=0)
            import requests as rq
            # FOMC karar gunu 14:00 ET, CPI 08:30 ET  (ET -> UTC: yaz +4, kis +5)
            fomc = ["2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
                    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
                    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16"]
            cpi = ["2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14", "2024-09-11",
                   "2024-10-10", "2024-11-13", "2024-12-11", "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
                   "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24", "2025-12-18", "2026-01-13", "2026-02-13",
                   "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14"]
            def et2utc(gun, saat, dk):
                t = pd.Timestamp(gun) + pd.Timedelta(hours=saat, minutes=dk)
                return t.tz_localize("America/New_York").tz_convert("UTC").tz_localize(None)
            olaylar_ = [et2utc(g, 14, 0) for g in fomc] + [et2utc(g, 8, 30) for g in cpi]
            fg = None
            try:
                j = rq.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]
                fg = pd.Series({pd.to_datetime(int(x["timestamp"]), unit="s").normalize(): float(x["value"]) for x in j}).sort_index()
                fg = fg.shift(1, freq="D")      # bir gun gecikmeli: o gunun degeri ancak ertesi gun kullanilir
                print("F&G", len(fg), fg.index.min(), fg.index.max(), flush=True)
            except Exception as exc:
                print("F&G alinamadi", exc, flush=True)
            senaryo = [("v6.4 TEMEL", dict(B4))]
            for once, sonra in ((4, 4), (8, 8), (0, 12), (12, 24)):
                senaryo.append((f"makro: FOMC/CPI {once}s once - {sonra}s sonra giris yok", dict(B4, olay_zaman=olaylar_, olay_once=once, olay_sonra=sonra)))
            senaryo.append(("makro: sadece FOMC 8s/8s", dict(B4, olay_zaman=olaylar_[:len(fomc)], olay_once=8, olay_sonra=8)))
            if fg is not None:
                senaryo += [("F&G: asiri acgozlulukte (>75) long yok", dict(B4, fg_seri=fg, fg_l_max=75)),
                            ("F&G: >80 long yok", dict(B4, fg_seri=fg, fg_l_max=80)),
                            ("F&G: asiri korkuda (<25) short yok", dict(B4, fg_seri=fg, fg_s_min=25)),
                            ("F&G: <20 short yok", dict(B4, fg_seri=fg, fg_s_min=20)),
                            ("F&G: >75 long yok + <25 short yok", dict(B4, fg_seri=fg, fg_l_max=75, fg_s_min=25)),
                            ("F&G: long sadece >=50, short sadece <=50", dict(B4, fg_seri=fg, fg_l_min=50, fg_s_max=50)),
                            ("F&G: long sadece <=60 (kalabalik yok)", dict(B4, fg_seri=fg, fg_l_max=60))]
            for hm in (0.5, 0.55):
                for hl in (100, 200):
                    senaryo.append((f"Hurst({hl}) >= {hm}", dict(B4, hurst_min=hm, hurst_len=hl)))
            parca = int(mod.split("-")[1])
            senaryo = senaryo[:1] + senaryo[1 + parca::3]
            rows = []
            with mp.Pool(4) as hv:
                for ad, prm in senaryo:
                    tr = calistir(prm, COINLER + yeni, "4h", hv)
                    for etiket, x in (("46", tr[tr.symbol.isin(COINLER)]), ("YENI", tr[tr.symbol.isin(yeni)]), ("HEPSI", tr)):
                        rows.append(satir(f"{ad} [{etiket}]", x))
                    print(ad, flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
            return
        if mod == "gen5":
            GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
                     "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
                     "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
                     "APTUSDT", "HBARUSDT", "XLMUSDT"]
            up6 = (KU[GEN30].rolling(6, min_periods=1).max() > 0).sum(axis=1)
            B4 = dict(_B3, ters_s=up6, ters_max=0)        # v6.4 temel
            u50 = {}
            for s_ in GEN30:
                df_ = DATA["4h"][s_][0]
                c_ = df_["close"].to_numpy(float)
                u50[s_] = pd.Series(np.where(np.arange(len(c_)) >= 60, (c_ > k.ema(c_, 50)).astype(float), np.nan),
                                    index=pd.to_datetime(df_["open_time"]))
            U = pd.DataFrame(u50).reindex(KU.index)
            oran = U.mean(axis=1) * 100
            senaryo = [("v6.4 TEMEL", dict(B4))]
            for N in (6, 12):
                up = (KU[GEN30].rolling(N, min_periods=1).max() > 0).sum(axis=1)
                for mn in (1, 2, 3, 5):
                    senaryo.append((f"long: son {N} mumda en az {mn} buyuk coin yukari kirmis", dict(B4, l_seri=up, l_min=mn)))
            for mn in (40, 50, 60, 70, 80):
                senaryo.append((f"long: buyuk coinlerin en az %{mn}'i EMA50 ustunde", dict(B4, l_seri=oran, l_min=mn)))
            dn6 = (KA[GEN30].rolling(6, min_periods=1).max() > 0).sum(axis=1)
            senaryo.append(("long: son 6 mumda asagi kiran buyuk coin yok (ayna)", dict(B4, ters_l=dn6)))
            parca = int(mod.split("-")[1]) if "-" in mod else 0
            rows = []
            with mp.Pool(4) as hv:
                for ad, prm in senaryo:
                    tr = calistir(prm, COINLER + yeni, "4h", hv)
                    for etiket, x in (("46", tr[tr.symbol.isin(COINLER)]), ("YENI", tr[tr.symbol.isin(yeni)]), ("HEPSI", tr)):
                        rows.append(satir(f"{ad} [{etiket}]", x))
                    print(ad, flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/gen5.csv", index=False)
            return
        if mod == "gen4":
            GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
                     "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
                     "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
                     "APTUSDT", "HBARUSDT", "XLMUSDT"]
            eksik = [x for x in GEN30 if x not in KU.columns]
            for x in eksik:
                df_ = veri.mumlar_onbellekli(x, "4h", VERI_BAS)
                ix = pd.to_datetime(df_["open_time"]); h_ = df_["high"].to_numpy(float); c_ = df_["close"].to_numpy(float)
                hh = pd.Series(h_).rolling(80).max().shift(1).to_numpy()
                KU[x] = pd.Series(np.where(np.arange(len(c_)) >= 80, (c_ > hh).astype(float), 0.0), index=ix).reindex(KU.index).fillna(0)
            print("eksik eklendi:", eksik, flush=True)
            for N in (3, 6, 9):
                up = (KU[GEN30].rolling(N, min_periods=1).max() > 0).sum(axis=1)
                senaryo.append((f"GEN30 | {N} mum <= 0 | sadece short", dict(_B3, ters_s=up, ters_max=0)))
            rows = []
            with mp.Pool(4) as hv:
                for ad, prm in senaryo:
                    tr = calistir(prm, COINLER + yeni, "4h", hv)
                    tr.to_csv(f"{OUT}/gen4_{ad.split('|')[0].strip().replace(' ', '')}_{ad.split('|')[1].strip().replace(' ', '').replace('<=', 'le') if '|' in ad else 'temel'}.csv", index=False)
                    for etiket, x in (("46", tr[tr.symbol.isin(COINLER)]), ("YENI", tr[tr.symbol.isin(yeni)]), ("HEPSI", tr)):
                        rows.append(satir(f"{ad} [{etiket}]", x))
                    tt = tr[tr.giris_zaman >= pd.Timestamp(IS_BAS)].copy()
                    tt["yariyil"] = tt.giris_zaman.dt.year.astype(str) + "-" + np.where(tt.giris_zaman.dt.month <= 6, "1", "2")
                    print(ad, tt.groupby("yariyil")["sonuc_r"].agg(["size", "sum"]).round(1).T.to_string(), flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
            return
        if mod.startswith("gen3"):
            hacim = {d["symbol"]: float(d["quoteVolume"]) for d in tick}
            sirali = sorted(KU.columns, key=lambda x: -hacim.get(x, 0))
            for M in (20, 30, 40, 116):
                cols = sirali[:M]
                for N in (3, 6):
                    up = (KU[cols].rolling(N, min_periods=1).max() > 0).sum(axis=1)
                    dn = (KA[cols].rolling(N, min_periods=1).max() > 0).sum(axis=1)
                    for mx in (0, 1):
                        senaryo.append((f"evren {M} | {N} mum <= {mx} | sadece short", dict(_B3, ters_s=up, ters_max=mx)))
                        senaryo.append((f"evren {M} | {N} mum <= {mx} | iki yon", dict(_B3, ters_l=dn, ters_s=up, ters_max=mx)))
            parca = int(mod.split("-")[1])
            senaryo = senaryo[:1] + senaryo[1 + parca::4]
            rows = []
            with mp.Pool(4) as hv:
                for ad, prm in senaryo:
                    tr = calistir(prm, COINLER + yeni, "4h", hv)
                    tr.to_csv(f"{OUT}/gen3_{ad.replace(' ', '').replace('|', '_').replace('<=', 'le')}.csv", index=False)
                    for etiket, x in (("46", tr[tr.symbol.isin(COINLER)]), ("YENI", tr[tr.symbol.isin(yeni)]), ("HEPSI", tr)):
                        rows.append(satir(f"{ad} [{etiket}]", x))
                    print(ad, flush=True)
            pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
            print("ilk30:", sirali[:30], flush=True)
            return
        for N in (3, 6, 12):
            up = (KU.rolling(N, min_periods=1).max() > 0).sum(axis=1)
            dn = (KA.rolling(N, min_periods=1).max() > 0).sum(axis=1)
            for mx in (0, 1, 2, 3):
                senaryo.append((f"ters kirilim son {N} mum <= {mx} coin (iki yon)", dict(_B3, ters_l=dn, ters_s=up, ters_max=mx)))
                senaryo.append((f"ters kirilim son {N} mum <= {mx} coin (sadece short)", dict(_B3, ters_s=up, ters_max=mx)))
        parca = int(mod.split("-")[1])
        senaryo = senaryo[:1] + senaryo[1 + parca::3]
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in senaryo:
                tr = calistir(prm, COINLER + yeni, "4h", hv)
                for etiket, x in (("46", tr[tr.symbol.isin(COINLER)] if len(tr) else tr),
                                  ("YENI", tr[tr.symbol.isin(yeni)] if len(tr) else tr), ("HEPSI", tr)):
                    rows.append(satir(f"{ad} [{etiket}]", x))
                print(ad, flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
    elif mod == "rot":
        import rotasyon as ro
        tick = veri._get("/api/v3/ticker/24hr", {})
        haric = set(COINLER) | STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT", "PAXGUSDT", "XAUTUSDT"}
        aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
                and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR")) and not d["symbol"].endswith("BUSDT")]
        aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
        yeni = [d["symbol"] for d in aday[:70]]
        evren = [x for x in COINLER + yeni if x not in ("PAXGUSDT",)]
        gunluk = {}
        for s_ in evren:
            try:
                gunluk[s_] = veri.mumlar_onbellekli(s_, "1d", "2019-06-01")
            except Exception as exc:
                print("yok", s_, exc)
        kap = ro.kapanis_matrisi(gunluk)
        btc = kap["BTCUSDT"].ffill()
        kir = None
        try:
            kt = pd.read_csv(f"{OUT}/v63_islemler.csv", parse_dates=["cikis_zaman"])
            kt = kt[kt.cikis_zaman >= pd.Timestamp(IS_BAS)]
            kir = kt.groupby(kt.cikis_zaman.dt.to_period("M"))["sonuc_r"].sum() * 0.005
        except Exception as exc:
            print("v63 yok", exc)
        sen = []
        for bak in (14, 30, 60, 90):
            for n_ in (5, 10, 20):
                for bf in (False, True):
                    sen.append((f"long en guclu {n_}, {bak}g, haftalik" + (", BTC>EMA50" if bf else ""),
                                dict(bak=bak, n=n_, btc_filtre=bf)))
        sen += [("long/short 10, 30g", dict(bak=30, n=10, ls=True)), ("long/short 10, 60g", dict(bak=60, n=10, ls=True)),
                ("long/short 5, 30g", dict(bak=30, n=5, ls=True)),
                ("BTC'ye gore guclu 10, 30g, BTC>EMA50", dict(bak=30, n=10, goreli=True, btc_filtre=True)),
                ("long en guclu 10, 30g, 2 haftalik, BTC>EMA50", dict(bak=30, n=10, tut=14, btc_filtre=True)),
                ("KIYAS: tum evren esit agirlik", dict(bak=30, n=60)),
                ("KIYAS: tum evren esit agirlik, BTC>EMA50", dict(bak=30, n=60, btc_filtre=True))]
        rows = []
        for ad, prm in sen:
            r = ro.simule(kap, btc, **prm)
            tut = prm.get("tut", 7)
            a1, a2 = ro.ozet(r, IS_BAS, IS_BIT, tut), ro.ozet(r, OOS_BAS, None, tut)
            row = {"ayar": ad, **{f"IS_{x}": v for x, v in a1.items()}, **{f"OOS_{x}": v for x, v in a2.items()}}
            if kir is not None:
                ay = (1 + r).groupby(r.index.to_period("M")).prod() - 1
                j = pd.concat([kir.rename("kir"), ay.rename("rot")], axis=1).fillna(0)
                row["ay_kor"] = round(j.kir.corr(j.rot), 2)
                row["kir_zarar_ay_rot_%"] = round(100 * j[j.kir < 0].rot.sum(), 1)
            rows.append(row)
        bh = btc.reindex(r.index)
        rb = bh.pct_change().dropna()
        rows.append({"ayar": "KIYAS: BTC al-tut", **{f"IS_{x}": v for x, v in ro.ozet(rb, IS_BAS, IS_BIT, 7).items()},
                     **{f"OOS_{x}": v for x, v in ro.ozet(rb, OOS_BAS, None, 7).items()}})
        if kir is not None:
            for ad_, b_, e_ in (("IS", IS_BAS, IS_BIT), ("OOS", OOS_BAS, None)):
                kk = kir[(kir.index.to_timestamp() >= pd.Timestamp(b_)) & ((kir.index.to_timestamp() <= pd.Timestamp(e_)) if e_ else True)]
                print("KIRILIM %0.5 risk", ad_, "toplam %", round(100 * kk.sum(), 1))
        pd.DataFrame(rows).to_csv(f"{OUT}/rot.csv", index=False)
        print("evren", kap.shape, flush=True)
    elif mod.startswith("mr-"):
        mr_calistir(mod, MRS[int(mod.split("-")[1])])
    elif mod == "aday":
        YENI_ = ['XRPUSDT', 'WLDUSDT', 'STRKUSDT', 'TAOUSDT', 'PUMPUSDT', 'ZROUSDT', 'SANDUSDT', 'QNTUSDT', 'EPICUSDT', 'ONDOUSDT', 'GTCUSDT', 'PROMUSDT', 'AMPUSDT', 'ERAUSDT', 'TONUSDT', 'TRUMPUSDT', 'RADUSDT', 'ASTERUSDT', 'EIGENUSDT', 'PYTHUSDT', 'BCHUSDT', 'BATUSDT', 'CAKEUSDT', 'AUSDT', 'ZKUSDT', 'ALTUSDT', 'NIGHTUSDT', 'WUSDT', 'NFPUSDT', 'AVAUSDT', 'XPLUSDT', 'MINAUSDT', 'LSKUSDT', 'DUSKUSDT', 'NILUSDT', 'RSRUSDT', 'MUBARAKUSDT', 'STRAXUSDT', 'KMNOUSDT', 'NMRUSDT', 'ETHFIUSDT', 'BERAUSDT', 'AXLUSDT', 'PENGUUSDT', 'WALUSDT', 'DASHUSDT', 'AUDIOUSDT', 'RAYUSDT', 'LDOUSDT', 'STXUSDT', 'ZAMAUSDT', 'NXPCUSDT', 'SUSDT', 'RLCUSDT', 'VIRTUALUSDT', 'KITEUSDT']
        DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", VERI_BAS)
        DATA["4h"] = yukle(COINLER + YENI_)
        with mp.Pool(4) as hv:
            tr = calistir(dict(V63[0][1]), COINLER + YENI_, "4h", hv)
        tr.to_csv(f"{OUT}/aday_islemler.csv", index=False)
        rows = [satir("mevcut 46", tr[tr.symbol.isin(COINLER)]), satir("yeni 56", tr[tr.symbol.isin(YENI_)]), satir("toplam 102", tr)]
        pd.DataFrame(rows).to_csv(f"{OUT}/aday.csv", index=False)
    elif mod.startswith("katman"):
        _, a_, b_ = mod.split("-")
        tick = veri._get("/api/v3/ticker/24hr", {})
        haric = set(COINLER) | STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT", "PAXGUSDT"}
        aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric and float(d["quoteVolume"]) > 0
                and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
        aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
        print("toplam aday", len(aday), flush=True)
        dilim = aday[int(a_):int(b_)]
        hacim = {d["symbol"]: float(d["quoteVolume"]) for d in dilim}
        DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", VERI_BAS)
        DATA["4h"] = yukle([d["symbol"] for d in dilim])
        sem = list(DATA["4h"])
        with open(f"{OUT}/{mod}_semboller.txt", "w") as f_:
            f_.write("\n".join(f"{d['symbol']} {float(d['quoteVolume']) / 1e6:.1f} {'VAR' if d['symbol'] in DATA['4h'] else 'YOK'} {len(DATA['4h'][d['symbol']][0]) if d['symbol'] in DATA['4h'] else 0}" for d in dilim))
        with mp.Pool(4) as hv:
            tr = calistir(dict(V63[0][1]), sem, "4h", hv)
        tr.to_csv(f"{OUT}/{mod}_islemler.csv", index=False)
        rows = [satir(f"katman {a_}-{b_} ({len(sem)} coin, toplam aday {len(aday)})", tr)]
        hv_ = sorted(hacim.values())
        rows[0]["medyan_hacim_musd"] = round(hv_[len(hv_) // 2] / 1e6, 1) if hv_ else 0
        rows[0]["min_hacim_musd"] = round(hv_[0] / 1e6, 2) if hv_ else 0
        pd.DataFrame(rows).to_csv(f"{OUT}/{mod}.csv", index=False)
    elif mod in ("formasyon", "kovalama", "limit", "profesyonel", "basarisiz", "seviye", "fikir", "oda", "yas", "uzun", "btcf", "ek", "v63") or mod.startswith("tara") or mod.startswith("kalib") or mod.startswith("k2") or mod.startswith("y6"):
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
        if mod == "profesyonel":
            DATA["1h"] = {}
            for s_ in list(DATA["4h"]):
                try:
                    DATA["1h"][s_] = veri.mumlar_onbellekli(s_, "1h", "2024-05-15")
                except Exception as exc:
                    print("1s veri yok", s_, exc, flush=True)
            print("1s veri hazir", len(DATA["1h"]), flush=True)
        if mod == "oda":
            for s_ in ("OPUSDT",):
                if s_ in DATA["4h"]:
                    teshis(s_, "2026-10-10")
        if mod.startswith("tara"):
            _, a_, b_ = mod.split("-")
            TARA = [(f"{n:03d}", dict(_B2, resistance_len=n)) for n in range(int(a_), int(b_) + 1)]
        elif mod.startswith("kalib"):
            TARA = KALIB[int(mod.split("-")[1])]
        elif mod.startswith("y6"):
            TARA = YENI6S[int(mod.split("-")[1])]
        elif mod.startswith("k2"):
            TARA = K2S[int(mod.split("-")[1])]
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in (TARA if (mod.startswith("tara") or mod.startswith("kalib") or mod.startswith("k2") or mod.startswith("y6")) else {"kovalama": KOVALAMA, "limit": LIMIT, "profesyonel": PROFESYONEL, "basarisiz": BASARISIZ, "seviye": SEVIYE, "fikir": FIKIR, "oda": ODA, "yas": YAS, "uzun": UZUN, "btcf": BTCF, "ek": EK, "v63": V63}.get(mod, FORM_SENARYO)):
                tr = calistir(prm, COINLER + yeni, "4h", hv)
                if mod == "v63":
                    tr.to_csv(f"{OUT}/v63_islemler.csv", index=False)
                if mod == "ek" and ad == "v6.2 TEMEL":
                    tr.to_csv(f"{OUT}/ek_temel_islemler.csv", index=False)
                if mod == "ek" and len(tr) and (tr.tip == "YENIDEN").any():
                    rows.append(satir(f"   {ad} :: sadece YENIDEN [HEPSI]", tr[tr.tip == "YENIDEN"]))
                for etiket, x in (("46", tr[tr.symbol.isin(COINLER)] if len(tr) else tr),
                                  ("YENI", tr[tr.symbol.isin(yeni)] if len(tr) else tr), ("HEPSI", tr)):
                    rows.append(satir(f"{ad} [{etiket}]", x))
                if len(tr) and "formasyonlar" in prm:
                    ft = tr[~tr.tip.isin(["KIRILIM", "GUCLU KIRILIM", "RETEST", "TEYIT"])]
                    for tip, g in ft.groupby("tip"):
                        rows.append(satir(f"   {ad} :: sadece {tip} islemleri [HEPSI]", g))
                print(ad, flush=True)
        res = pd.DataFrame(rows)
        res.to_csv(f"{OUT}/{mod}.csv", index=False)
        with open(f"{OUT}/{mod}.txt", "w") as f:
            f.write(res.to_string(index=False))


if __name__ == "__main__":
    main()
