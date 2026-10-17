"""Ortalamaya donus (mean reversion) sistemi - arastirma motoru.

Kirilim69'dan bagimsiz ikinci sistem adayi. Tum kararlar mum KAPANISINDA verilir,
stop mum icinde (high/low) kontrol edilir, bosluklu acilista acilis fiyatindan dolar.
Sonuc R cinsinden, komisyon (her yon) dahil.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import kirilim_v6 as k

VARSAYILAN = {
    "sinyal": "bb",        # "bb" | "rsi2" | "z"
    "bb_len": 20, "bb_k": 2.0,
    "rsi_len": 2, "rsi_alt": 10.0, "rsi_ust": 90.0, "cikis_sma": 5,
    "z_len": 20, "z_esik": 2.0,
    "rejim": "",           # "" | "adx" | "chop" | "trend" (long sadece EMA200 ustunde, short altinda)
    "adx_max": 20.0, "chop_min": 55.0,
    "stop_atr": 2.0, "zaman": 10,
    "yon": "ikisi",        # "ikisi" | "long" | "short"
    "btc_filtre": False,   # long: BTC gunluk > EMA50, short: altinda
    "kom": 0.001,
}


def simule(symbol: str, df: pd.DataFrame, btc_gunluk: pd.DataFrame | None, params: dict,
           giris_bas: pd.Timestamp | None = None) -> list:
    p = dict(VARSAYILAN)
    p.update(params or {})
    df = df.reset_index(drop=True)
    n = len(df)
    ot = pd.to_datetime(df["open_time"])
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    atr = k.rma(k.true_range(h, l, c, True), 14)
    cs = pd.Series(c)
    ema200 = k.ema(c, 200)

    if p["sinyal"] == "bb":
        m = cs.rolling(p["bb_len"]).mean().to_numpy()
        sd = cs.rolling(p["bb_len"]).std(ddof=0).to_numpy()
        al = c < m - p["bb_k"] * sd
        sat = c > m + p["bb_k"] * sd
        hedef = m
    elif p["sinyal"] == "z":
        m = cs.rolling(p["z_len"]).mean().to_numpy()
        sd = cs.rolling(p["z_len"]).std(ddof=0).to_numpy()
        z = (c - m) / sd
        al = z < -p["z_esik"]
        sat = z > p["z_esik"]
        hedef = m
    else:
        r = k.rsi(c, p["rsi_len"])
        al = r < p["rsi_alt"]
        sat = r > p["rsi_ust"]
        hedef = cs.rolling(p["cikis_sma"]).mean().to_numpy()

    rj = p["rejim"]
    if rj == "adx":
        _, _, adx = k.dmi(h, l, c, 14, 14)
        ok = adx < p["adx_max"]
        al, sat = al & ok, sat & ok
    elif rj == "chop":
        tr1 = pd.Series(k.true_range(h, l, c, True))
        chop = (100 * np.log10(tr1.rolling(14).sum() / (pd.Series(h).rolling(14).max() - pd.Series(l).rolling(14).min()))
                / np.log10(14)).to_numpy()
        ok = chop > p["chop_min"]
        al, sat = al & ok, sat & ok
    elif rj == "trend":
        al, sat = al & (c > ema200), sat & (c < ema200)

    if p["btc_filtre"] and btc_gunluk is not None and len(btc_gunluk):
        bc = btc_gunluk["close"].to_numpy(float)
        M = k._htf_onceki(ot, btc_gunluk, "D", {"c": bc, "e": k.ema(bc, 50)})
        up = M["c"] > M["e"]
        dn = M["c"] < M["e"]
        al, sat = al & up, sat & dn
    if p["yon"] == "long":
        sat = np.zeros(n, bool)
    elif p["yon"] == "short":
        al = np.zeros(n, bool)

    islemler = []
    pos = None
    kom = p["kom"]
    for i in range(210, n):
        a = atr[i]
        if pos is not None:
            d = pos["d"]
            cikis = neden = None
            stp = pos["stop"]
            if d == 1 and l[i] <= stp:
                cikis, neden = (o[i] if o[i] < stp else stp), "STOP"
            elif d == -1 and h[i] >= stp:
                cikis, neden = (o[i] if o[i] > stp else stp), "STOP"
            elif not math.isnan(hedef[i]) and d * (c[i] - hedef[i]) >= 0:
                cikis, neden = c[i], "HEDEF"
            elif i - pos["bar"] >= p["zaman"]:
                cikis, neden = c[i], "ZAMAN"
            if cikis is not None:
                rr = d * (cikis - pos["giris"]) / pos["risk"] - 2 * kom * pos["giris"] / pos["risk"]
                islemler.append({"symbol": symbol, "yon": d, "giris_zaman": pos["zaman"], "cikis_zaman": ot[i],
                                 "giris": pos["giris"], "cikis": cikis, "sonuc_r": rr, "neden": neden,
                                 "bar_sayisi": i - pos["bar"], "tip": p["sinyal"]})
                pos = None
                continue   # ayni mumda yeni giris yok
        if pos is None and a > 0 and not math.isnan(a):
            if giris_bas is not None and ot[i] < giris_bas:
                continue
            d = 1 if al[i] else (-1 if sat[i] else 0)
            if d != 0:
                risk = p["stop_atr"] * a
                pos = {"d": d, "giris": c[i], "stop": c[i] - d * risk, "risk": risk, "bar": i, "zaman": ot[i]}
    return islemler
