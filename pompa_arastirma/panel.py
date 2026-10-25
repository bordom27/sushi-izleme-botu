"""
Pump/dump arastirmasi - her coin, her 4s mum icin: sinyal anindaki ozellikler (sadece gecmis) + ileri sonuclar.
Kullanim: python pompa_arastirma/panel.py <cikti.pkl>
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import multiprocessing as mp
import numpy as np, pandas as pd
import short_lab as S

D, FR, M = S.yukle()
_C = pd.DataFrame({s: g.c for s, g in D.items()})
_R6 = _C / _C.shift(6) - 1
PIY = pd.DataFrame({"genislik": (_R6 > 0).sum(axis=1) / _R6.notna().sum(axis=1).clip(lower=1),
                    "pompa_orani": (_R6 > 0.2).sum(axis=1) / _R6.notna().sum(axis=1).clip(lower=1),
                    "btc_r6": _R6["BTCUSDT"]})


def bir(s):
    g = D[s]
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    n = len(c)
    if n < 250:
        return None
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    V = pd.Series(v); C = pd.Series(c); dv = C * V
    vmed = V.rolling(180, min_periods=60).median().shift(1).to_numpy()
    f = pd.DataFrame(index=g.index)
    f["symbol"] = s
    f["c"] = c
    f["qv"] = (dv.rolling(180, min_periods=60).median() * 6).to_numpy()
    f["yas"] = np.arange(n)
    f["r1"] = c / pc - 1
    f["r6"] = C.pct_change(6).to_numpy()
    f["r42"] = C.pct_change(42).to_numpy()
    f["vx1"] = v / vmed
    f["vx6"] = V.rolling(6).mean().to_numpy() / vmed
    f["vx18"] = V.rolling(18).mean().to_numpy() / vmed       # 3 gunluk hacim birikimi
    f["vx1_onceki"] = np.r_[np.nan, (v / vmed)[:-1]]
    atr100 = pd.Series(atr).rolling(100).mean().to_numpy()
    f["sikisma"] = atr / atr100
    hh = C.rolling(42).max().to_numpy(); lo = C.rolling(42).min().to_numpy()
    f["aralik42"] = hh / lo - 1                                 # 7 gunluk fiyat araligi (dar = sikisma)
    f["dipten180"] = c / C.rolling(180).min().to_numpy() - 1
    f["tepeden180"] = c / C.rolling(180).max().to_numpy() - 1
    f["atrp"] = atr / c
    f["ust_fitil"] = (h - np.maximum(o, c)) / np.maximum(h - l, 1e-12)
    yuk = (h - pc) / pc
    f["pompa_gecmis"] = pd.Series((yuk > 0.3).astype(float)).rolling(540, min_periods=1).sum().to_numpy()  # son 90 gun
    # funding (mum kapanisina kadar bilinen)
    fr = FR.get(s)
    if fr is not None and len(fr):
        kap = g.index + pd.Timedelta(hours=4)
        fs = fr.sort_index()
        a = pd.merge_asof(pd.DataFrame({"t": kap.astype("datetime64[ns]")}), pd.DataFrame({"t": fs.index.astype("datetime64[ns]"), "fr": fs.values, "fr3": fs.rolling(3).sum().values}),
                          on="t", direction="backward")
        f["fr"] = a.fr.to_numpy(); f["fr3"] = a.fr3.to_numpy()
    else:
        f["fr"] = np.nan; f["fr3"] = np.nan
    # ileri sonuclar (giris = bu mumun kapanisi)
    Hs, Ls = pd.Series(h), pd.Series(l)
    for k in (6, 18):
        f[f"ileri_max{k}"] = (Hs[::-1].rolling(k, min_periods=1).max()[::-1].shift(-1).to_numpy()) / c - 1
        f[f"ileri_min{k}"] = (Ls[::-1].rolling(k, min_periods=1).min()[::-1].shift(-1).to_numpy()) / c - 1
    f = f.join(PIY, how="left")
    return f.iloc[60:]


if __name__ == "__main__":
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(bir, list(D), chunksize=8)
    P = pd.concat([x for x in out if x is not None])
    P.index.name = "t"
    P = P.reset_index()
    for k in P.select_dtypes("float64").columns:
        P[k] = P[k].astype("float32")
    P.to_pickle(sys.argv[1])
    print(P.shape, P.t.min(), P.t.max())
