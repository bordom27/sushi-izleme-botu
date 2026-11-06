"""Gelistirme 4 (6 Kas 2026): YENI kural (onceki 2 mumdan >=1 yesil, kume>=6, tek 2 yildiz yok) uzerinde
 a) cikis izgarasi: hedef 0.4-0.75R x stop 0.6-1.0 ATR x zaman stopu 10-30 mum
 b) kume icinden secim: ayni mumda en iyi k sinyal (ozellige gore)
Secim <2025, kontrol 2025+. Kullanim: SP=... python short_arastirma/gelistir4.py"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S, short_retest as SR
from short_arastirma.gelistir2 import tek_pozisyon, fon_top, MALIYET
SP = os.environ.get("SP", "/tmp")
t = pd.read_pickle(os.path.join(SP, "gelistir2_neden.pkl"))
m = t.risk.between(0.004, 0.25) & (t.kir_boy < 2.7) & (t.vor3 < 0.7) & (t.kirmizi3 <= 2)
t = t[m].copy(); t["kume"] = t.zaman.map(t.groupby("zaman").size())
t = t[t.kume >= 6].copy()
print("YENI kural dokunus:", len(t))


def olc(x, ad):
    x = tek_pozisyon(x.dropna(subset=["R"]))
    gun = x.groupby(x.cikis.dt.floor("D")).R.sum().sort_index(); eq = gun.cumsum()
    o = {"varyant": ad, "n": len(x), "isabet": round((x.R > 0).mean() * 100, 1), "R/i": round(x.R.mean(), 3),
         "topR": round(x.R.sum(), 1), "maxDD": round((eq.cummax() - eq).max(), 1)}
    for etk, mm in (("<2025", x.zaman < "2025-01-01"), ("2025+", x.zaman >= "2025-01-01")):
        y = x[mm].R; o[f"{etk} isb"] = round((y > 0).mean() * 100, 1); o[f"{etk} R/i"] = round(y.mean(), 3)
    return o


# a) cikis izgarasi
pk = os.path.join(SP, "gelistir4_cikis.pkl")
if os.path.exists(pk):
    C = pd.read_pickle(pk)
else:
    D, FR, _ = S.yukle(); rows = []
    for ix, r in t.iterrows():
        g = D[r.symbol]; x = SR.gostergeler(g); T = g.index
        i = T.get_loc(r.zaman); o, h, l, c, a = x["o"], x["h"], x["l"], x["c"], x["atr"][i]
        e = c[i]; tepe = e * (1 + r.risk) - 0.8 * a          # max(seviye, mum tepesi)
        hr0 = 1.0 if r.q >= 5e6 else 0.8                     # hedef carpani (sig coinde 0.4/0.5 orani korunur)
        for sa in (0.6, 0.8, 1.0):
            st = tepe + sa * a; rk = (st - e) / e
            for hr in (0.4, 0.5, 0.6, 0.75):
                tg = e - hr * hr0 * (st - e)
                for zs in (10, 15, 20, 30):
                    son = min(len(c) - 1, i + zs); cik, jx = c[son], son
                    for j in range(i + 1, son + 1):
                        if h[j] >= st: cik, jx = max(st, o[j]), j; break
                        if l[j] <= tg: cik, jx = min(tg, o[j]), j; break
                    rows.append({"ix": ix, "stop": sa, "hedef": hr, "zaman_stopu": zs,
                                 "R": ((e - cik) / e - MALIYET + fon_top(FR.get(r.symbol), T[i], T[jx])) / rk, "cikis": T[jx]})
    C = pd.DataFrame(rows); C.to_pickle(pk)
base = t.drop(columns=["R", "cikis"])
rows = []
for (sa, hr, zs), g in C.groupby(["stop", "hedef", "zaman_stopu"]):
    x = base.join(g.set_index("ix")[["R", "cikis"]], how="inner")
    rows.append(olc(x, f"stop {sa} ATR, hedef {hr}R, zaman {zs} mum" + ("  <== MEVCUT" if (sa, hr, zs) == (0.8, 0.5, 30) else "")))
A = pd.DataFrame(rows).sort_values("R/i", ascending=False)
pd.set_option("display.width", 250, "display.max_colwidth", 60, "display.max_rows", 100)
print("\n=== a) cikis izgarasi (R/i'ye gore) ===")
print(A.to_string(index=False))
A.to_csv("short_arastirma/kos_gelistir4_cikis.csv", index=False)

# b) kume icinden secim
print("\n=== b) ayni mumda en iyi k sinyal ===")
rows = [olc(t, "HEPSI (YENI kural)")]
for f, yon in (("risk", -1), ("risk", 1), ("q", -1), ("dokunus", -1), ("d_atr", 1), ("d_atr", -1), ("rs7", 1), ("rs7", -1),
               ("vor3", 1), ("kir_hacim", -1), ("derinlik_atr", 1), ("trend50", -1), ("atrp", -1), ("atrp", 1)):
    sira = t.groupby("zaman")[f].rank(ascending=(yon == 1), method="first")
    for k in (3, 5):
        rows.append(olc(t[sira <= k], f"en iyi {k}: {f} {'kucuk' if yon == 1 else 'buyuk'} once"))
B = pd.DataFrame(rows)
print(B.to_string(index=False))
B.to_csv("short_arastirma/kos_gelistir4_secim.csv", index=False)
