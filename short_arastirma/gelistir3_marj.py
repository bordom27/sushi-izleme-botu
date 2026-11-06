"""Gelistirme 3 (6 Kas 2026): gevsetilmis K69 SHORT (onceki 2 mumdan >=1 yesil, kume>=4 ya da ⭐⭐) uzerinde islem basi kar.
Isabet dusmeden R/islem artiran fikirler: kume esigi, min risk%, tek ⭐⭐ cikar, limit giris (+m ATR, 1 mum, hedef R olarak).
Secim <2025, kontrol 2025+. Herkese esit risk, coin basina tek pozisyon. Kullanim: SP=... python short_arastirma/gelistir3_marj.py"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S, short_retest as SR
from short_arastirma.gelistir2 import tek_pozisyon, fon_top, MALIYET
SP = os.environ.get("SP", "/tmp")
t = pd.read_pickle(os.path.join(SP, "gelistir2_neden.pkl"))
yeni = t.risk.between(0.004, 0.25) & (t.kir_boy < 2.7) & (t.vor3 < 0.7) & (t.kirmizi3 <= 2)
t = t[yeni].copy()
t["kume"] = t.zaman.map(t.groupby("zaman").size())
pk = os.path.join(SP, "gelistir3_limit.pkl")
if os.path.exists(pk):
    L = pd.read_pickle(pk)
else:
    D, FR, _ = S.yukle()
    rows = []
    for ix, r in t.iterrows():
        g = D[r.symbol]; x = SR.gostergeler(g); T = g.index
        i = T.get_loc(r.zaman); o, h, l, c, a = x["o"], x["h"], x["l"], x["c"], x["atr"][i]
        e0 = c[i]; st = e0 * (1 + r.risk); hr = 0.5 if r.q >= 5e6 else 0.4
        son = min(len(c) - 1, i + 30); out = {"ix": ix}
        for m in (0.05, 0.1, 0.15, 0.2):
            lim = e0 + m * a
            if lim >= st or i + 1 > son or h[i + 1] < lim:
                out[f"L{m}"] = np.nan; out[f"Lc{m}"] = pd.NaT; continue
            e = max(lim, o[i + 1]); tg = e - hr * (st - e); rk = (st - e) / e
            if h[i + 1] >= st:
                cik, jx = max(st, o[i + 1]), i + 1
            else:
                cik, jx = c[son], son
                for j in range(i + 2, son + 1):
                    if h[j] >= st: cik, jx = max(st, o[j]), j; break
                    if l[j] <= tg: cik, jx = min(tg, o[j]), j; break
            out[f"L{m}"] = ((e - cik) / e - MALIYET + fon_top(FR.get(r.symbol), T[i], T[jx])) / rk
            out[f"Lc{m}"] = T[jx]
        rows.append(out)
    L = pd.DataFrame(rows).set_index("ix"); L.to_pickle(pk)
t = t.join(L)


def olc(x, ad, kol="R", cik="cikis"):
    x = x.dropna(subset=[kol]).copy(); x["R"], x["cikis"] = x[kol], x[cik]
    x = tek_pozisyon(x)
    gun = x.groupby(x.cikis.dt.floor("D")).R.sum().sort_index(); eq = gun.cumsum(); dd = (eq.cummax() - eq).max()
    o = {"varyant": ad, "n": len(x), "isabet": round((x.R > 0).mean() * 100, 1), "R/i": round(x.R.mean(), 3),
         "topR": round(x.R.sum(), 1), "maxDD": round(dd, 1)}
    for etk, m in (("<2025", x.zaman < "2025-01-01"), ("2025+", x.zaman >= "2025-01-01")):
        y = x[m].R; o[f"{etk} isb"] = round((y > 0).mean() * 100, 1); o[f"{etk} R/i"] = round(y.mean(), 3); o[f"{etk} n"] = len(y)
    s12 = x[x.zaman >= x.zaman.max() - pd.Timedelta(days=365)]
    o["hafta"] = round(len(s12) / 52, 1)
    return o


rows = []
taban = (t.kume >= 4) | (t.yildiz == 2)
rows.append(olc(t[taban], "TABAN gevset (kume>=4 | 2yildiz)"))
for km in (5, 6, 8, 10):
    rows.append(olc(t[(t.kume >= km) | (t.yildiz == 2)], f"kume>={km} | 2yildiz"))
    rows.append(olc(t[t.kume >= km], f"kume>={km} (tek 2yildiz yok)"))
rows.append(olc(t[t.kume >= 4], "kume>=4 (tek 2yildiz yok)"))
for rmin in (0.02, 0.025, 0.03, 0.035):
    rows.append(olc(t[taban & (t.risk >= rmin)], f"taban + risk>={rmin*100:.1f}%"))
for m in (0.05, 0.1, 0.15, 0.2):
    rows.append(olc(t[taban], f"taban + limit giris +{m}ATR (dolmazsa yok)", f"L{m}", f"Lc{m}"))
for m in (0.05, 0.1):
    for rmin in (0.025, 0.03):
        rows.append(olc(t[taban & (t.risk >= rmin)], f"taban + risk>={rmin*100:.1f}% + limit +{m}ATR", f"L{m}", f"Lc{m}"))
R = pd.DataFrame(rows)
pd.set_option("display.width", 250, "display.max_colwidth", 60)
print(R.to_string(index=False))
R.to_csv("short_arastirma/kos_gelistir3_marj.csv", index=False)
