"""
K69 SHORT gelistirme 2 (5 Kas 2026). Tum retest dokunuslari (canli durum makinesiyle ayni) + yeni ozellikler kaydedilir,
sonra filtre/gevsetme fikirleri yil yil olculur.
Secim donemi: < 2025-01-01. Kontrol (secimde kullanilmaz): >= 2025-01-01.
Yeni fikirler:
  1) coin funding (son oran, 3 gun toplam)       2) coin gunluk trendi (4s EMA300 ~ gunluk EMA50, EMA1200 ~ gunluk 200)
  3) coin'in BTC'ye gore guc (7/30 gun)           4) kirilimdan bu yana dusus derinligi, seviyenin altinda gecen sure
  5) saat / gun                                    6) gevsetme: hacim 0.7->0.8/0.9, 2 yesil -> 1 yesil, kirilim boyu 2.7->3.5,
     dokunus/risk sinirlari  (kume>=3 ya da yildiz 2 filtresiyle birlikte: sinyal sayisi artar mi, isabet korunur mu)
Kullanim: python short_arastirma/gelistir2.py
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S                                                    # noqa: E402
import short_retest as SR                                                # noqa: E402

MALIYET = 0.002
D = FR = BTC = None


def fon_top(fr, t0, t1):
    if fr is None or not len(fr):
        return 0.0
    return float(fr[(fr.index > t0) & (fr.index <= t1)].sum())


def coin(s):
    A = SR.AYAR
    g = D[s]
    x = SR.gostergeler(g)
    o, h, l, c, v, atr, va, q = (x[k] for k in ("o", "h", "l", "c", "v", "atr", "va", "qv"))
    T = g.index
    n = len(c)
    cs = pd.Series(c, index=T)
    e300 = cs.ewm(span=300, adjust=False).mean().to_numpy()
    e1200 = cs.ewm(span=1200, adjust=False).mean().to_numpy()
    b = BTC.reindex(T).ffill().to_numpy()
    fr = FR.get(s)
    out = []
    for R_ in A["seviyeler"]:
        ll = pd.Series(l).rolling(R_).min().shift(1).to_numpy()
        sev, k, kir_v = np.nan, -1, np.nan
        i = R_ + 1
        while i < n:
            if np.isnan(sev):
                if c[i] < ll[i] - 0.05 * atr[i] and v[i] >= A["kirilim_hacim"] * va[i] and q[i] >= A["min_hacim_usd"]:
                    k, sev, kir_v = i, ll[i], v[i] / va[i]
                i += 1
                continue
            a = atr[i]
            if i - k > A["maks_bekle"] or c[i] > sev + 0.5 * a:
                sev = np.nan
                continue
            if i - k >= A["min_bar"] and h[i] >= sev - A["yakin_atr"] * a and c[i] < sev and c[i] < o[i] \
                    and q[i] >= A["min_hacim_usd"] and i < n - 1:
                st = max(sev, h[i]) + A["stop_atr"] * a
                e = c[i]
                risk = (st - e) / e
                ka = atr[k]
                hr = A["hedef_r"] if q[i] >= A["sig_hacim_usd"] else A["hedef_r_sig"]
                tg = e - hr * (st - e)
                # sonuc (canli kural: stop once, 30 mum)
                son = min(n - 1, i + A["zaman_stopu"])
                cik, jx = c[son], son
                for j in range(i + 1, son + 1):
                    if h[j] >= st:
                        cik, jx = max(st, o[j]), j
                        break
                    if l[j] <= tg:
                        cik, jx = min(tg, o[j]), j
                        break
                R = ((e - cik) / e - MALIYET + fon_top(fr, T[i], T[jx])) / risk if risk > 0 else np.nan
                dokunus = int((l[max(0, k - R_):k] <= sev + 0.3 * ka).sum())
                f_son = fr[fr.index <= T[i]] if fr is not None else None
                out.append({
                    "symbol": s, "zaman": T[i], "cikis": T[jx], "R": R, "seviye_mum": R_,
                    "risk": risk, "q": q[i], "dokunus": dokunus, "kir_boy": (h[k] - l[k]) / ka,
                    "vor3": v[i - 2:i + 1].mean() / va[i], "kirmizi3": int((c[i - 2:i + 1] < o[i - 2:i + 1]).sum()),
                    "kir_hacim": kir_v, "bekle": i - k,
                    "d_atr": (sev - e) / a, "derinlik_atr": (sev - l[k:i + 1].min()) / a,
                    "ust_govde": (h[i] - max(o[i], c[i])) / a, "mum_boy": (h[i] - l[i]) / a,
                    "fon_son": float(f_son.iloc[-1]) if f_son is not None and len(f_son) else np.nan,
                    "fon_3g": float(f_son.iloc[-9:].sum()) if f_son is not None and len(f_son) >= 9 else np.nan,
                    "trend50": e / e300[i] - 1, "trend200": e / e1200[i] - 1 if i > 600 else np.nan,
                    "r7": c[i] / c[max(0, i - 42)] - 1, "r30": c[i] / c[max(0, i - 180)] - 1,
                    "rs7": (c[i] / c[max(0, i - 42)]) / (b[i] / b[max(0, i - 42)]) - 1,
                    "rs30": (c[i] / c[max(0, i - 180)]) / (b[i] / b[max(0, i - 180)]) - 1,
                    "atrp": a / e, "yas": i,
                })
                sev = np.nan
            i += 1
    return out


def tek_pozisyon(t):
    """coin basina tek pozisyon (zaman sirasiyla, cikisa kadar yeni giris yok)."""
    keep = []
    for s, g in t.sort_values("zaman").groupby("symbol"):
        serbest = pd.Timestamp(0)
        for ix, r in g.iterrows():
            if r.zaman <= serbest:
                continue
            keep.append(ix)
            serbest = r.cikis
    return t.loc[keep]


def olc(t, ad):
    t = tek_pozisyon(t)
    out = {"varyant": ad, "n": len(t)}
    for etk, m in (("sec<2025", t.zaman < "2025-01-01"), ("kontrol2025+", t.zaman >= "2025-01-01")):
        x = t[m].R
        out[f"{etk} n"] = len(x)
        out[f"{etk} isabet"] = round((x > 0).mean() * 100, 1) if len(x) else np.nan
        out[f"{etk} R/i"] = round(x.mean(), 3) if len(x) else np.nan
        out[f"{etk} topR"] = round(x.sum(), 1)
    son12 = t[t.zaman >= t.zaman.max() - pd.Timedelta(days=365)]
    out["son12ay hafta_basi"] = round(len(son12) / 52, 1)
    out["yillar"] = " ".join(f"{y}:{len(b)}/{(b.R > 0).mean() * 100:.0f}%/{b.R.sum():+.0f}" for y, b in t.groupby(t.zaman.dt.year))
    return out


if __name__ == "__main__":
    SP = os.environ.get("SP", "/tmp")
    pk = os.path.join(SP, "gelistir2.pkl")
    if os.path.exists(pk):
        t = pd.read_pickle(pk)
    else:
        D, FR, _ = S.yukle()
        BTC = D["BTCUSDT"]["c"]
        with mp.get_context("fork").Pool(2) as hv:
            out = hv.map(coin, list(D))
        t = pd.DataFrame([x for o in out for x in o])
        # ayni zamanda iki seviye (80/160) dokunusu varsa dokunusu fazla olan
        t = t.sort_values("dokunus").drop_duplicates(["symbol", "zaman"], keep="last")
        t["yildiz"] = np.where(t.q >= 5e6, np.where(t.dokunus >= 3, 2, np.where(t.dokunus >= 2, 1, 0)), 0)
        t["saat"] = t.zaman.dt.hour
        t["gun"] = t.zaman.dt.dayofweek
        t.to_pickle(pk)
    print("toplam dokunus", len(t), t.zaman.min(), t.zaman.max())
    sert = (t.risk.between(0.004, 0.25)) & (t.kir_boy < 2.7)
    temel = sert & (t.vor3 < 0.7) & (t.kirmizi3 == 1)

    def kume(m):
        return t.zaman.map(t[m].groupby("zaman").size()).fillna(0)

    rows = []
    k0 = kume(temel)
    canli = temel & ((k0 >= 3) | (t.yildiz == 2))
    rows.append(olc(t[temel], "K69 ham (filtresiz)"))
    rows.append(olc(t[canli], "CANLI (kume>=3 ya da 2 yildiz)"))
    # gevsetmeler: kume kendi sinyal kumesine gore yeniden sayilir
    for ad, m in {
        "gevset hacim<0.8": sert & (t.vor3 < 0.8) & (t.kirmizi3 == 1),
        "gevset hacim<0.9": sert & (t.vor3 < 0.9) & (t.kirmizi3 == 1),
        "gevset kirmizi3<=2": sert & (t.vor3 < 0.7) & (t.kirmizi3 <= 2),
        "gevset kirilim boyu<3.5": t.risk.between(0.004, 0.25) & (t.kir_boy < 3.5) & (t.vor3 < 0.7) & (t.kirmizi3 == 1),
        "gevset hacim<0.8 + kirmizi3<=2": sert & (t.vor3 < 0.8) & (t.kirmizi3 <= 2),
        "gevset hepsi (0.9, <=2, 3.5)": t.risk.between(0.004, 0.25) & (t.kir_boy < 3.5) & (t.vor3 < 0.9) & (t.kirmizi3 <= 2),
    }.items():
        k = kume(m)
        for km in (3, 4, 5):
            rows.append(olc(t[m & ((k >= km) | (t.yildiz == 2))], f"{ad} | kume>={km}"))
    # kume esigi canli kurala gore
    for km in (2, 4, 5):
        rows.append(olc(t[temel & ((k0 >= km) | (t.yildiz == 2))], f"canli ama kume>={km}"))
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 320, "display.max_columns", 40, "display.max_colwidth", 120)
    print(R.to_string(index=False))
    R.to_csv("short_arastirma/kos_gelistir2_gevset.csv", index=False)

    # ozellik dilimleri (canli sinyaller uzerinde): secim donemi ve kontrol ayri
    c = t[canli].copy()
    c = tek_pozisyon(c)
    c["donem"] = np.where(c.zaman < "2025-01-01", "sec", "kontrol")
    print("\n=== Ozellik dilimleri (canli sinyaller, ceyrek dilimler; isabet% / R/i / n) ===")
    dil = []
    for f in ("fon_son", "fon_3g", "trend50", "trend200", "r7", "r30", "rs7", "rs30", "d_atr", "derinlik_atr", "ust_govde",
              "mum_boy", "kir_hacim", "bekle", "vor3", "atrp", "risk", "q", "saat", "gun", "dokunus", "yas"):
        x = c[f]
        if x.notna().sum() < 100:
            continue
        try:
            qq = pd.qcut(x.rank(method="first"), 4, labels=False)
        except Exception:
            continue
        sinir = [round(x[qq == i].max(), 4) for i in range(3)]
        satir = {"ozellik": f, "sinirlar(Q1/Q2/Q3 ust)": sinir}
        for d in ("sec", "kontrol"):
            for i in range(4):
                b = c.R[(qq == i) & (c.donem == d)]
                satir[f"{d}Q{i + 1}"] = f"{(b > 0).mean() * 100:.0f}/{b.mean():+.2f}/{len(b)}" if len(b) else "-"
        dil.append(satir)
    Dl = pd.DataFrame(dil)
    print(Dl.to_string(index=False))
    Dl.to_csv("short_arastirma/kos_gelistir2_dilim.csv", index=False)
