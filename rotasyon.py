"""Momentum rotasyon sistemi - arastirma motoru (ikinci sistem adayi).

Her `tut` gunde bir, gunluk kapanista coinler son `bak` gunluk getirisine gore siralanir;
en guclu `n` coin esit agirlikla alinir (istege bagli: en zayif `n` coin short).
Siralama t kapanisiyla yapilir, getiri t -> t+tut kapanislari arasindan alinir (ileriye bakis yok).
Komisyon: her yon %0.1, agirlik degisimi (devir) uzerinden.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import kirilim_v6 as k


def kapanis_matrisi(gunlukler: dict) -> pd.DataFrame:
    seriler = {}
    for s, gd in gunlukler.items():
        if gd is None or len(gd) == 0:
            continue
        seriler[s] = pd.Series(gd["close"].to_numpy(float), index=pd.to_datetime(gd["open_time"]).dt.normalize())
    m = pd.DataFrame(seriler).sort_index()
    return m[~m.index.duplicated()]


def simule(kap: pd.DataFrame, btc: pd.Series, bak: int = 30, n: int = 5, tut: int = 7, ls: bool = False,
           btc_filtre: bool = False, goreli: bool = False, min_gecmis: int = 90, kom: float = 0.001,
           bas: str = "2024-07-01") -> pd.Series:
    """Donemlik (tut gunluk) portfoy getirisi serisi (index = donem sonu)."""
    gun = kap.index
    bas_i = gun.searchsorted(pd.Timestamp(bas))
    btc_ema = pd.Series(k.ema(btc.to_numpy(float), 50), index=btc.index)
    getiri_bak = kap / kap.shift(bak) - 1
    if goreli:
        getiri_bak = getiri_bak.sub(btc / btc.shift(bak) - 1, axis=0)
    yeterli = kap.notna().rolling(min_gecmis).sum() >= min_gecmis
    sonuc = {}
    w_eski = pd.Series(0.0, index=kap.columns)
    i = bas_i
    while i + tut < len(gun):
        t, t2 = gun[i], gun[i + tut]
        skor = getiri_bak.loc[t].where(yeterli.loc[t] & kap.loc[t2].notna())
        skor = skor.dropna()
        w = pd.Series(0.0, index=kap.columns)
        piyasa_ok = (not btc_filtre) or (btc.loc[t] > btc_ema.loc[t])
        if len(skor) >= 2 * n:
            if piyasa_ok:
                w[skor.nlargest(n).index] = 1.0 / n if not ls else 0.5 / n
            if ls:
                w[skor.nsmallest(n).index] = -0.5 / n
        r = (kap.loc[t2] / kap.loc[t] - 1).fillna(0.0)
        brut = float((w * r).sum())
        devir = float((w - w_eski).abs().sum())
        sonuc[t2] = brut - devir * kom
        # donem sonu agirliklar fiyatla kayar
        w_eski = w * (1 + r)
        tot = w_eski.abs().sum()
        w_eski = w_eski / tot * w.abs().sum() if tot > 0 else w_eski
        i += tut
    return pd.Series(sonuc)


def ozet(r: pd.Series, bas: str, bit: str | None, tut: int) -> dict:
    x = r[(r.index >= pd.Timestamp(bas)) & ((r.index <= pd.Timestamp(bit)) if bit else True)]
    if len(x) == 0:
        return dict(getiri=np.nan, sharpe=np.nan, dd=np.nan, kazanan=np.nan)
    eq = (1 + x).cumprod()
    yil = 365 / tut
    sh = x.mean() / x.std() * np.sqrt(yil) if x.std() > 0 else np.nan
    return dict(getiri=round(100 * (eq.iloc[-1] - 1), 1), sharpe=round(sh, 2),
                dd=round(100 * (1 - eq / eq.cummax()).max(), 1), kazanan=round(100 * (x > 0).mean(), 1))
