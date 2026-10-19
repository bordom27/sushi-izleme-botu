"""
Gunluk trend portfoyu (Zarattini, Pagani, Barbon 2025 "Catching Crypto Trends" yaklasimi, sadece LONG).

Her coin ve her bakis suresi L icin (5, 10, 20, 30, 60, 90, 150, 250, 360 gun):
  - giris: gunluk kapanis, onceki L gunun en yuksek kapanisini gecerse
  - cikis: kapanis iz suren stopun altina inerse; stop = max(onceki stop, son L gun kapanislarinin (en yuksek + en dusuk) / 2)
Coinin sinyali = trendde olan bakis surelerinin orani (0..1).
Boyut: sinyal x (hedef yillik oynaklik %25 / coinin 90 gunluk oynakligi), en fazla 2 kat; son 30 gunun hacmine gore
en likit 20 coin (en az 365 gunluk gecmis) arasinda, her biri sermayenin 1/20'si uzerinden.
Kararlar gunluk mum kapanisinda (00:00 UTC) verilir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BAKIS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
AYAR = {"top": 20, "hedef_vol": 0.25, "max_kaldirac": 2.0, "min_gecmis": 365, "bant": 0.01, "bant_oran": 0.33}


def tablolar(G: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """G: sembol -> gunluk df (open_time, close, volume; SADECE kapanmis mumlar)."""
    kapan = pd.DataFrame({s: g.set_index("open_time")["close"].astype(float) for s, g in G.items()}).sort_index()
    hacim = pd.DataFrame({s: g.set_index("open_time")["close"].astype(float) * g.set_index("open_time")["volume"].astype(float)
                          for s, g in G.items()}).reindex(kapan.index)
    return kapan, hacim


def hedef_agirlik(kapan: pd.DataFrame, hacim: pd.DataFrame, LB=BAKIS, top=20, hedef_vol=0.25, max_kaldirac=2.0,
                  min_gecmis=365) -> pd.DataFrame:
    """Her gun kapanisindan sonra tutulmasi gereken agirliklar (sermayenin orani)."""
    ret = kapan.pct_change()
    sig = ret.rolling(90, min_periods=60).std() * np.sqrt(365)
    likid = hacim.rolling(30, min_periods=20).median()
    yas = kapan.notna().cumsum()
    secili = likid.where(yas >= min_gecmis).rank(axis=1, ascending=False) <= top
    toplam = np.zeros(kapan.shape)
    C = kapan.to_numpy(float)
    for L in LB:
        mx = kapan.rolling(L, min_periods=L).max()
        mn = kapan.rolling(L, min_periods=L).min()
        B = (kapan > mx.shift(1)).to_numpy()
        O = ((mx + mn) / 2).to_numpy(float)
        stop = np.full(C.shape[1], np.nan)
        icinde = np.zeros(C.shape[1], bool)
        for t in range(C.shape[0]):
            for j in range(C.shape[1]):
                if np.isnan(C[t, j]):
                    icinde[j] = False
                    continue
                if icinde[j]:
                    if C[t, j] < stop[j]:
                        icinde[j] = False
                    elif not np.isnan(O[t, j]):
                        stop[j] = max(stop[j], O[t, j])
                elif B[t, j]:
                    icinde[j] = True
                    stop[j] = O[t, j]
                if icinde[j]:
                    toplam[t, j] += 1.0
    sinyal = pd.DataFrame(toplam / len(LB), index=kapan.index, columns=kapan.columns)
    olcek = (hedef_vol / sig).clip(upper=max_kaldirac)
    return ((sinyal * olcek).where(secili, 0.0).fillna(0.0) / top)


def bantli(w: pd.DataFrame, bant: float, oran: float = 0.0) -> pd.DataFrame:
    """Elle uygulama: kucuk degisikliklerde islem yapilmaz. Giris (0 -> >0) ve cikis (>0 -> 0) her zaman yapilir;
    acik pozisyon hedeften 'bant' (sermayenin orani) kadar uzaklasinca hedefe getirilir."""
    if bant <= 0 and oran <= 0:
        return w
    W = w.to_numpy(float)
    H = np.zeros_like(W)
    h = np.zeros(W.shape[1])
    for t in range(W.shape[0]):
        hedef = W[t]
        esik = np.maximum(bant, oran * np.maximum(h, hedef))
        degis = ((h == 0) & (hedef > 0)) | ((h > 0) & (hedef == 0)) | (np.abs(hedef - h) > esik)
        h = np.where(degis, hedef, h)
        H[t] = h
    return pd.DataFrame(H, index=w.index, columns=w.columns)


def getiri(w_tutulan: pd.DataFrame, kapan: pd.DataFrame, gecikme: int = 0, komisyon: float = 0.001) -> pd.Series:
    """Gunluk portfoy getirisi. gecikme=0: kapanista uygulanir; 1: bir gun sonraki kapanista."""
    ret = kapan.pct_change()
    w = w_tutulan.shift(gecikme).fillna(0.0)
    brut = (w.shift(1) * ret).sum(axis=1)
    maliyet = w.diff().abs().sum(axis=1) * komisyon
    return brut - maliyet
