"""
K69 SHORT 1 saatlik + K69 LONG (ayna) testi (26 Eki 2026).

  S4      : canli K69 SHORT, 4s (referans)
  S1      : ayni kural 1s mumlarda, ayni mum sayilari (80/160 mum destek, 2-30 mum retest, 30 mum zaman stopu)
  S1T     : 1s, takvim olcekli (320/640 mum, 8-120 mum retest, 120 mum zaman stopu) = 4s ile ayni sureler
  L4      : K69 LONG, 4s: kirilan direncin dusuk hacimli retesti (SHORT kuralinin aynasi)
Canli filtre: ayni mumda >= 3 coinde sinyal ya da ⭐⭐.
Islem: sinyal kapanisinda giris, stop/hedef/zaman; ayni mumda ikisi degerse stop. Maliyet %0.2 + funding. Coin basina tek pozisyon.
Kullanim: python short_arastirma/tf_long_test.py   (veri: arastirma_cikti/dok, dok1h)
"""
from __future__ import annotations

import glob
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_retest as SR                                                # noqa: E402

MALIYET = 0.002
SP = os.environ.get("SP", "/tmp")
TEMEL = dict(SR.AYAR)
VAR = {
    "S4": dict(tf="4h", yon=-1, A=TEMEL),
    "S1": dict(tf="1h", yon=-1, A=TEMEL),
    "S1T": dict(tf="1h", yon=-1, A=dict(TEMEL, seviyeler=(320, 640), min_bar=8, maks_bekle=120, zaman_stopu=120)),
    "L4": dict(tf="4h", yon=1, A=TEMEL),
}
FR: dict = {}


def sinyal(g: pd.DataFrame, yon: int, A: dict, mpg: int) -> list[dict]:
    """short_retest.sinyaller ile ayni durum makinesi; yon=+1 aynasi (long). mpg: gunluk mum sayisi."""
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    va = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    q = (pd.Series(c * v).rolling(30 * mpg, min_periods=10 * mpg).median() * mpg).to_numpy()
    T = g.index
    n = len(c)
    out = {}
    for R_ in A["seviyeler"]:
        if yon < 0:
            ref = pd.Series(l).rolling(R_).min().shift(1).to_numpy()
        else:
            ref = pd.Series(h).rolling(R_).max().shift(1).to_numpy()
        sev, k = np.nan, -1
        i = R_ + 1
        while i < n:
            a = atr[i]
            if np.isnan(sev):
                kir = (c[i] < ref[i] - 0.05 * a) if yon < 0 else (c[i] > ref[i] + 0.05 * a)
                if kir and v[i] >= A["kirilim_hacim"] * va[i] and q[i] >= A["min_hacim_usd"]:
                    k, sev = i, ref[i]
                i += 1
                continue
            iptal = (c[i] > sev + 0.5 * a) if yon < 0 else (c[i] < sev - 0.5 * a)
            if i - k > A["maks_bekle"] or iptal:
                sev = np.nan
                continue
            if yon < 0:
                ret = h[i] >= sev - A["yakin_atr"] * a and c[i] < sev and c[i] < o[i]
            else:
                ret = l[i] <= sev + A["yakin_atr"] * a and c[i] > sev and c[i] > o[i]
            if i - k >= A["min_bar"] and ret and q[i] >= A["min_hacim_usd"]:
                e = c[i]
                ka = atr[k]
                if yon < 0:
                    st = max(sev, h[i]) + A["stop_atr"] * a
                    dok = int((l[max(0, k - R_):k] <= sev + 0.3 * ka).sum())
                    ters3 = int((c[i - 2:i + 1] < o[i - 2:i + 1]).sum())
                else:
                    st = min(sev, l[i]) - A["stop_atr"] * a
                    dok = int((h[max(0, k - R_):k] >= sev - 0.3 * ka).sum())
                    ters3 = int((c[i - 2:i + 1] > o[i - 2:i + 1]).sum())
                risk = abs(st - e) / e
                kir_boy = (h[k] - l[k]) / ka
                vor3 = v[i - 2:i + 1].mean() / va[i]
                if (0.004 <= risk <= 0.25 and vor3 < A["dusuk_hacim"] and ters3 == 1
                        and dok >= A["min_dokunus"] and kir_boy < A["maks_kirilim_boy"]):
                    hr = A["hedef_r"] if q[i] >= A["sig_hacim_usd"] else A["hedef_r_sig"]
                    s = {"zaman": T[i], "ix": i, "giris": e, "stop": st, "hedef": e - hr * (st - e), "dokunus": dok,
                         "yildiz": (2 if dok >= A["guclu_dokunus"] else 1 if dok >= 2 else 0)
                         if q[i] >= A["yildiz_hacim_usd"] else 0}
                    eski = out.get(T[i])
                    if eski is None or s["dokunus"] > eski["dokunus"]:
                        out[T[i]] = s
                sev = np.nan
            i += 1
    return [out[t] for t in sorted(out)]


def islemler(s: str, g: pd.DataFrame, ad: str, cfg: dict) -> list[dict]:
    mpg = {"1h": 24, "2h": 12, "4h": 6, "8h": 3, "12h": 2}[cfg["tf"]]
    yon, A = cfg["yon"], cfg["A"]
    sig = sinyal(g, yon, A, mpg)
    if not sig:
        return []
    H, L, C = (g[x].to_numpy(float) for x in "hlc")
    T = g.index
    fr = FR.get(s)
    out = []
    serbest = -1
    for z in sig:
        i = z["ix"]
        tum = {"symbol": s, "var": ad, "giris": T[i], "yildiz": z["yildiz"], "alindi": False}
        if i <= serbest or i >= len(C) - 1:
            out.append(tum)          # kume sayimi icin (canlida da sayilir)
            continue
        e, st, tg = z["giris"], z["stop"], z["hedef"]
        son = min(len(C) - 1, i + A["zaman_stopu"])
        f, jx, neden = C[son], son, "ZAMAN"
        for j in range(i + 1, son + 1):
            if (H[j] >= st) if yon < 0 else (L[j] <= st):
                f, jx, neden = st, j, "STOP"
                break
            if (L[j] <= tg) if yon < 0 else (H[j] >= tg):
                f, jx, neden = tg, j, "HEDEF"
                break
        fon = 0.0
        if fr is not None and len(fr):
            fon = float(fr[(fr.index > T[i]) & (fr.index <= T[jx])].sum())
        risk = abs(st - e) / e
        R = (yon * (f / e - 1) - MALIYET - yon * fon) / risk
        tum.update(alindi=True, cikis=T[jx], R=R, neden=neden)
        out.append(tum)
        serbest = jx
    return out


def _dosya(args):
    yol, tf = args
    K = pd.read_csv(yol)
    K["t"] = pd.to_datetime(K["t"], unit="s")
    out = []
    for s, g in K.groupby("symbol", sort=True):
        g = g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]]
        g = g[g.v > 0]
        if len(g) < 300:
            continue
        for ad, cfg in VAR.items():
            if cfg["tf"] == tf:
                out += islemler(s, g, ad, cfg)
    return out


def ozet(x: pd.DataFrame, ad: str, bas=None) -> dict:
    if bas is not None:
        x = x[x.giris >= bas]
    if not len(x):
        return {"ayar": ad, "n": 0}
    x = x.sort_values("cikis")
    eq = x.R.cumsum()
    gun = (x.giris.max() - x.giris.min()).days or 1
    r = {"ayar": ad, "n": len(x), "hafta": round(len(x) / gun * 7, 1), "isabet%": round((x.R > 0).mean() * 100, 1),
         "R/i": round(x.R.mean(), 3), "top_R": round(x.R.sum(), 1), "maxDD": round((eq.cummax() - eq).max(), 1)}
    y = x.giris.dt.year
    for yy in range(2020, 2027):
        xx = x[y == yy].R
        if len(xx):
            r[str(yy)] = f"{len(xx)}/{(xx > 0).mean() * 100:.0f}%/{xx.sum():+.1f}"
    son12 = x[x.giris >= x.giris.max() - pd.Timedelta(days=365)].R
    r["son12ay"] = f"{len(son12)}/{(son12 > 0).mean() * 100:.0f}%/{son12.sum():+.1f}"
    return r


def birlesik(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Iki sistemi birlikte calistir: coin uzerinde acik pozisyon varken yeni giris yok (once gelen alir)."""
    x = pd.concat([a, b]).sort_values(["giris", "var"])
    acik: dict = {}
    keep = []
    for r in x.itertuples():
        if acik.get(r.symbol, pd.Timestamp(0)) >= r.giris:
            keep.append(False)
            continue
        keep.append(True)
        acik[r.symbol] = r.cikis
    return x[np.array(keep)]


if __name__ == "__main__":
    F = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok/fund_*.csv.gz"))], ignore_index=True)
    F["t"] = pd.to_datetime(F["t"], unit="ms")
    FR = {s: g.set_index("t")["fr"].sort_index() for s, g in F.groupby("symbol")}
    isler = [(f, "4h") for f in sorted(glob.glob("arastirma_cikti/dok/k4h_*.csv.gz"))] + \
            [(f, "1h") for f in sorted(glob.glob("arastirma_cikti/dok1h/k1h_*.csv.gz"))]
    with mp.get_context("fork").Pool(2, maxtasksperchild=1) as hv:
        res = hv.map(_dosya, isler, chunksize=1)
    t = pd.DataFrame([r for lst in res for r in lst])
    t["kume"] = t.groupby(["var", "giris"]).symbol.transform("size")
    t.to_pickle(os.path.join(SP, "tf_long.pkl"))
    a = t[t.alindi].copy()
    a["filtre"] = (a.kume >= 3) | (a.yildiz == 2)
    B24 = pd.Timestamp("2024-01-01")
    rows = []
    for ad in VAR:
        x = a[a["var"] == ad]
        rows.append(ozet(x, f"{ad} tum"))
        rows.append(ozet(x[x.filtre], f"{ad} canli filtre"))
        if ad != "L4":
            rows.append(ozet(x[x.filtre], f"{ad} canli filtre 2024+", B24))
    s4 = a[(a["var"] == "S4") & a.filtre & (a.giris >= B24)]
    for ad in ("S1", "S1T"):
        s1 = a[(a["var"] == ad) & a.filtre & (a.giris >= B24)]
        rows.append(ozet(birlesik(s4, s1), f"S4 + {ad} birlikte (filtre, 2024+)"))
    s4t = a[(a["var"] == "S4") & a.filtre]
    l4 = a[(a["var"] == "L4") & a.filtre]
    rows.append(ozet(birlesik(s4t, l4), "S4 + L4 birlikte (filtre)"))
    pd.set_option("display.width", 320, "display.max_columns", 30)
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv("short_arastirma/kos_tf_long.csv", index=False)
