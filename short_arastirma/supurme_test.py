"""
Yatay piyasa sistemi adayi: seviye supurme + geri alma (sweep / reclaim), 4s USDT-M vadeli, 2020+ (27 Eki 2026).

Long : mum, son R mumun dibinin en az 0.1 ATR altina igne atar ve dibin USTUNDE kapatir (tek mum),
       ya da onceki mum dibin altinda kapatmis, bu mum dibin ustunde kapatir (iki mum). Mum yesil.
Short: aynasi (tepenin ustune igne, tepenin altinda kirmizi kapanis).
Hacim: supurme mumunun hacmi >= vm x 20 mum ortalama. Coin gunde >= 5M$.
Giris kapanista, stop = igne ucu -/+ 0.3 ATR, hedef = hr R, zaman stopu 30 mum, coin basina tek pozisyon.
Maliyet %0.2 + funding. Ayni mumda stop ve hedef degerse stop.
Rejim: yok | btc_yatay (dunku BTC gunluk kapanisi EMA50'nin %3 icinde) | adx (coin 4s ADX14 < 20).
Kullanim: python short_arastirma/supurme_test.py
"""
from __future__ import annotations

import glob
import itertools
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tf_long_test as T                                                  # noqa: E402

MALIYET = 0.002
HR = (0.5, 0.75, 1.0)
BTC_REJ: pd.Series | None = None


def adx14(h, l, c):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    up = np.r_[np.nan, h[1:] - h[:-1]]
    dn = np.r_[np.nan, l[:-1] - l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    r = lambda x: pd.Series(x).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()   # noqa: E731
    atr = r(tr)
    pdi, mdi = 100 * r(pdm) / atr, 100 * r(mdm) / atr
    dx = 100 * np.abs(pdi - mdi) / np.where(pdi + mdi > 0, pdi + mdi, np.nan)
    return r(np.nan_to_num(dx)), atr


def coin(s, g, fr):
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    adx, atr = adx14(h, l, c)
    va = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    q = (pd.Series(c * v).rolling(180, min_periods=60).median() * 6).to_numpy()
    T_ = g.index
    btc = BTC_REJ.reindex(T_.normalize()).to_numpy() if BTC_REJ is not None else np.zeros(len(c), bool)
    out = []
    for R_ in (80,):
        ll = pd.Series(l).rolling(R_).min().shift(1).to_numpy()
        hh = pd.Series(h).rolling(R_).max().shift(1).to_numpy()
        for yon, tip, vm in itertools.product((1, -1), ("tek", "iki"), (1.0, 1.5)):
            sinyal = []
            for i in range(R_ + 2, len(c) - 1):
                a = atr[i]
                if not (q[i] >= 5e6 and v[i] >= vm * va[i] and a > 0):
                    continue
                if yon > 0:
                    sev = ll[i]
                    if tip == "tek":
                        ok = l[i] <= sev - 0.1 * a and c[i] > sev and c[i] > o[i]
                        uc = l[i]
                    else:
                        ok = c[i - 1] < ll[i - 1] and c[i] > ll[i - 1] and c[i] > o[i]
                        uc, sev = min(l[i], l[i - 1]), ll[i - 1]
                    st = uc - 0.3 * a
                else:
                    sev = hh[i]
                    if tip == "tek":
                        ok = h[i] >= sev + 0.1 * a and c[i] < sev and c[i] < o[i]
                        uc = h[i]
                    else:
                        ok = c[i - 1] > hh[i - 1] and c[i] < hh[i - 1] and c[i] < o[i]
                        uc, sev = max(h[i], h[i - 1]), hh[i - 1]
                    st = uc + 0.3 * a
                if ok:
                    risk = abs(st - c[i]) / c[i]
                    if 0.004 <= risk <= 0.25:
                        sinyal.append((i, c[i], st))
            for hr in HR:
                serbest = -1
                for i, e, st in sinyal:
                    if i <= serbest:
                        continue
                    tg = e + yon * hr * abs(st - e)
                    son = min(len(c) - 1, i + 30)
                    f, jx = c[son], son
                    for j in range(i + 1, son + 1):
                        if (l[j] <= st) if yon > 0 else (h[j] >= st):
                            f, jx = st, j
                            break
                        if (h[j] >= tg) if yon > 0 else (l[j] <= tg):
                            f, jx = tg, j
                            break
                    fon = float(fr[(fr.index > T_[i]) & (fr.index <= T_[jx])].sum()) if fr is not None and len(fr) else 0.0
                    rk = abs(st - e) / e
                    R = (yon * (f / e - 1) - MALIYET - yon * fon) / rk
                    out.append({"symbol": s, "yon": yon, "tip": tip, "vm": vm, "hr": hr, "giris": T_[i], "cikis": T_[jx],
                                "R": R, "btc_yatay": bool(btc[i]), "adx": adx[i]})
                    serbest = jx
    return out


def _dosya(yol):
    K = pd.read_csv(yol)
    K["t"] = pd.to_datetime(K["t"], unit="s")
    out = []
    for s, g in K.groupby("symbol", sort=True):
        g = g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]]
        g = g[g.v > 0]
        if len(g) >= 300:
            out += coin(s, g, T.FR.get(s))
    return out


if __name__ == "__main__":
    F = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok/fund_*.csv.gz"))], ignore_index=True)
    F["t"] = pd.to_datetime(F["t"], unit="ms")
    T.FR = {s: g.set_index("t")["fr"].sort_index() for s, g in F.groupby("symbol")}
    K = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok/k4h_*.csv.gz"))], ignore_index=True)
    b = K[K.symbol == "BTCUSDT"].copy()
    b["t"] = pd.to_datetime(b["t"], unit="s")
    gun = b.drop_duplicates("t").set_index("t").sort_index()["c"].resample("1D").last().dropna()
    BTC_REJ = ((gun / gun.ewm(span=50, adjust=False).mean() - 1).abs() < 0.03).shift(1).fillna(False)
    del K, b
    with mp.get_context("fork").Pool(2, maxtasksperchild=1) as hv:
        res = hv.map(_dosya, sorted(glob.glob("arastirma_cikti/dok/k4h_*.csv.gz")), chunksize=1)
    t = pd.DataFrame([r for lst in res for r in lst])
    t.to_pickle(os.path.join(os.environ.get("SP", "/tmp"), "supurme.pkl"))
    rows = []
    for (yon, tip, vm, hr), x in t.groupby(["yon", "tip", "vm", "hr"]):
        for rj, m in (("yok", np.ones(len(x), bool)), ("btc_yatay", x.btc_yatay.to_numpy()), ("adx<20", (x.adx < 20).to_numpy())):
            r = T.ozet(x[m], f"{'LONG' if yon > 0 else 'SHORT'} {tip} vm{vm} {hr}R rejim={rj}")
            rows.append(r)
    df = pd.DataFrame(rows).sort_values("R/i", ascending=False)
    pd.set_option("display.width", 330, "display.max_columns", 30)
    print(df.to_string(index=False))
    df.to_csv("short_arastirma/kos_supurme.csv", index=False)
