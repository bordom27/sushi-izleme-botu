"""
K69 SHORT: isabet + kazanci birlikte artirma denemeleri (25 Eki 2026). 4s (2020+) ve 1s (2024+) dolum simulasyonu.

Sinyaller canli kuralla ayni (short_retest.sinyaller), coin basina tek pozisyon (mevcut cikisa gore).
Fikir 1 - limit giris: sinyal kapanisindan sonra kapanis + m*ATR'ye limit satis, W adet 4s mum gecerli. Stop ayni.
   hedef "R"    : hedef = giris' - hr*(stop - giris')   (risk kuculdugu icin fiyatta yakinlasir)
   hedef "fiyat": hedef = orijinal hedef fiyati       (R buyur)
   "+piyasa"    : limit dolmazsa pencere sonunda kapanistan piyasa girisi
   Dolum mumunda: stop degdiyse stop (kotumser), hedef ancak sonraki mumdan itibaren sayilir.
Fikir 2 - girisin seviyeye uzakligi: d = (seviye - kapanis) / ATR, esik filtreleri.
Fikir 3 - squeeze/kume: ayni 4s mumda kac coinde sinyal var, BTC'nin son 4s / 24s getirisi.
Maliyet %0.2 + funding. Kullanim: python short_arastirma/iyilestirme_test.py
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
from short_arastirma.iz_stop_test import fon_top, yukle_1h, MALIYET     # noqa: E402

SP = os.environ.get("SP", "/tmp")
GIRIS = {"MEVCUT": None}
for m in (0.1, 0.2, 0.3, 0.5):
    for W in (1, 3):
        for hm in ("R", "fiyat"):
            GIRIS[f"limit +{m}ATR {W}mum hedef-{hm}"] = dict(m=m, W=W, hm=hm, piyasa=False)
for m in (0.2, 0.3):
    for hm in ("R", "fiyat"):
        GIRIS[f"limit +{m}ATR 1mum hedef-{hm} +piyasa"] = dict(m=m, W=1, hm=hm, piyasa=True)

D = FR = D1 = None


def sim(O, H, L, C, a0, e0, st, hr, atr0, maks, olcek, v):
    """a0: sinyal kapanisindan sonraki ilk mum. maks/W mum cinsinden (olcek: 4s mum basina mum sayisi).
    Donus: None (dolmadi) ya da (giris, cikis_fiyati, cikis_ix, risk_orani)."""
    n = len(C)
    son = min(n - 1, a0 + maks - 1)
    tg0 = e0 - hr * (st - e0)
    if v is None:
        e, j0, tg = e0, a0, tg0
        bas = a0
    else:
        lim = e0 + v["m"] * atr0
        if lim >= st:
            return None
        pen = min(son, a0 + v["W"] * olcek - 1)
        j = a0
        while j <= pen and H[j] < lim:
            j += 1
        if j > pen:
            if not v["piyasa"]:
                return None
            e, bas = C[pen], pen + 1
            if e >= st or bas > son:
                return None
            tg = e - hr * (st - e) if v["hm"] == "R" else tg0
            if tg >= e:
                return None
        else:
            e = max(lim, O[j])
            if H[j] >= st:
                return e, max(st, O[j]), j, (st - e) / e
            tg = e - hr * (st - e) if v["hm"] == "R" else tg0
            bas = j + 1
    for j in range(bas, son + 1):
        if H[j] >= st:
            return e, max(st, O[j]), j, (st - e) / e
        if L[j] <= tg:
            return e, min(tg, O[j]), j, (st - e) / e
    return e, C[son], son, (st - e) / e


def coin(s):
    g = D[s]
    sig = SR.sinyaller(g)
    if not sig:
        return [], []
    O, H, L, C = (g[x].to_numpy(float) for x in "ohlc")
    atr = SR.gostergeler(g)["atr"]
    T = g.index
    fr = FR.get(s)
    g1 = D1.get(s)
    if g1 is not None:
        O1, H1, L1, C1 = (g1[x].to_numpy(float) for x in "ohlc")
        T1 = g1.index
    tum = [{"symbol": s, "zaman": z["zaman"]} for z in sig]
    out = []
    serbest = pd.Timestamp(0)
    for z in sig:
        i = z["ix"]
        if T[i] <= serbest or i >= len(C) - 1:
            continue
        e0, st, hr = z["giris"], z["stop"], z["hedef_r"]
        row = {"symbol": s, "giris": T[i], "d_atr": (z["seviye"] - e0) / atr[i], "risk%": z["risk_pct"],
               "q": z["gunluk_hacim"], "yildiz": z["yildiz"], "dokunus": z["dokunus"]}
        a1 = None
        if g1 is not None and T[i] >= T1[0]:
            a1 = int(np.searchsorted(T1, T[i] + pd.Timedelta(hours=4)))
            if not (a1 < len(C1) - 1 and T1[a1] == T[i] + pd.Timedelta(hours=4)):
                a1 = None
        for ad, v in GIRIS.items():
            r = sim(O, H, L, C, i + 1, e0, st, hr, atr[i], 30, 1, v)
            if r is None:
                row[f"R4|{ad}"] = np.nan
            else:
                e, f, jx, rk = r
                row[f"R4|{ad}"] = ((e - f) / e - MALIYET + fon_top(fr, T[i], T[jx])) / rk
                if ad == "MEVCUT":
                    serbest = T[jx]
            if a1 is not None:
                r = sim(O1, H1, L1, C1, a1, e0, st, hr, atr[i], 120, 4, v)
                if r is None:
                    row[f"R1|{ad}"] = np.nan
                else:
                    e, f, jx, rk = r
                    row[f"R1|{ad}"] = ((e - f) / e - MALIYET + fon_top(fr, T[i], T1[jx])) / rk
            else:
                row[f"R1|{ad}"] = np.nan
        out.append(row)
    return out, tum


def satir(ad, r, giris, kapsam):
    """r: sinyal basina R (NaN = islem yok). kapsam: toplam sinyal sayisi (dolum orani icin)."""
    x = pd.DataFrame({"R": r, "g": giris}).dropna()
    if not len(x):
        return {"varyant": ad, "n": 0}
    x = x.sort_values("g")
    eq = x.R.cumsum()
    y = x.g.dt.year
    test = x[x.g >= "2024-01-01"].R
    out = {"varyant": ad, "n": len(x), "dolum%": round(len(x) / kapsam * 100, 1), "isabet%": round((x.R > 0).mean() * 100, 1),
           "R/islem": round(x.R.mean(), 3), "toplam_R": round(x.R.sum(), 1), "maxDD": round((eq.cummax() - eq).max(), 1)}
    if (x.g < "2024-01-01").any():
        egit = x[x.g < "2024-01-01"].R
        out.update({"<2024 isabet%": round((egit > 0).mean() * 100, 1), "<2024 R/i": round(egit.mean(), 3)})
    out.update({"2024+ isabet%": round((test > 0).mean() * 100, 1), "2024+ R/i": round(test.mean(), 3)})
    for yy in (2024, 2025, 2026):
        xx = x[y == yy].R
        out[f"{yy}"] = f"{(xx > 0).mean() * 100:.0f}%/{xx.sum():+.1f}" if len(xx) else "-"
    return out


def tablolar(t):
    son = {}
    for kip, kolon_on, alt in (("4s", "R4|", t), ("1s", "R1|", t[t.giris >= "2024-01-01"].dropna(subset=["R1|MEVCUT"]))):
        N = len(alt)
        rows = [satir(ad, alt[kolon_on + ad], alt.giris, N) for ad in GIRIS]
        b = alt[kolon_on + "MEVCUT"]
        # Fikir 2: uzaklik filtresi
        for esik in (0.2, 0.4, 0.6, 0.8, 1.0):
            rows.append(satir(f"filtre d<={esik}ATR", b.where(alt.d_atr <= esik), alt.giris, N))
        # Fikir 3: kume / BTC
        for km in (2, 3, 5):
            rows.append(satir(f"filtre ayni mumda <{km} sinyal", b.where(alt.kume < km), alt.giris, N))
        for es in (0.01, 0.02):
            rows.append(satir(f"filtre BTC 4s getiri <{es*100:.0f}%", b.where(alt.btc_r1 < es), alt.giris, N))
        for es in (0.02, 0.04):
            rows.append(satir(f"filtre BTC 24s getiri <{es*100:.0f}%", b.where(alt.btc_r6 < es), alt.giris, N))
        son[kip] = pd.DataFrame(rows)
        # dagilimlar
        for kol, kes in (("d_atr", [-1, 0.2, 0.4, 0.6, 0.8, 1.2, 9]), ("kume", [0, 1, 2, 4, 9, 999]),
                         ("btc_r6", [-1, -0.03, -0.01, 0.01, 0.03, 1])):
            gr = pd.DataFrame({"R": b, "k": pd.cut(alt[kol], kes)}).dropna()
            son[f"{kip}_{kol}"] = gr.groupby("k", observed=True).R.agg(
                n="size", isabet=lambda r: round((r > 0).mean() * 100, 1), R_i=lambda r: round(r.mean(), 3))
    return son


if __name__ == "__main__":
    D, FR, _ = S.yukle()
    D1 = yukle_1h()
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(coin, list(D))
    t = pd.DataFrame([x for o, _ in out for x in o])
    tum = pd.DataFrame([x for _, a in out for x in a])
    kume = tum.groupby("zaman").size()
    t["kume"] = t.giris.map(kume).fillna(1).astype(int)
    b = D["BTCUSDT"]["c"]
    t["btc_r1"] = t.giris.map(b.pct_change(1))
    t["btc_r6"] = t.giris.map(b.pct_change(6))
    t.to_pickle(os.path.join(SP, "iyilestirme.pkl"))
    pd.set_option("display.width", 300, "display.max_columns", 40, "display.max_colwidth", 45)
    son = tablolar(t)
    for k, v in son.items():
        print(f"\n===== {k} =====")
        print(v.to_string(index=not k in ("4s", "1s")))
    son["4s"].to_csv("short_arastirma/kos_iyilestirme_4s.csv", index=False)
    son["1s"].to_csv("short_arastirma/kos_iyilestirme_1s.csv", index=False)
