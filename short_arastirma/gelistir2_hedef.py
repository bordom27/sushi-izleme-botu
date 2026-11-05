"""Gelistirme 2b: canli sinyallerde hedef (0.4-1.0R) ve stop (0.6-1.2 ATR) kume buyuklugune gore farkli mi olmali?
Secim <2025, kontrol 2025+. Kullanim: SP=... python short_arastirma/gelistir2_hedef.py (once gelistir2.py)"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S, short_retest as SR
from short_arastirma.gelistir2 import fon_top, MALIYET
t = pd.read_pickle(os.path.join(os.environ.get("SP", "/tmp"), "gelistir2.pkl"))
temel = t.risk.between(0.004, 0.25) & (t.kir_boy < 2.7) & (t.vor3 < 0.7) & (t.kirmizi3 == 1)
k = t.zaman.map(t[temel].groupby("zaman").size()).fillna(0)
t["kume"] = k
c = t[temel & ((k >= 3) | (t.yildiz == 2))].copy()
D, FR, _ = S.yukle()
rows = []
for _, r in c.iterrows():
    g = D[r.symbol]; x = SR.gostergeler(g)
    i = g.index.get_loc(r.zaman); o, h, l, cc, a = x["o"], x["h"], x["l"], x["c"], x["atr"][i]
    e = cc[i]; st0 = r.risk * e + e - SR.AYAR["stop_atr"] * a          # max(seviye, tepe)
    son = min(len(cc) - 1, i + 30)
    for sa in (0.6, 0.8, 1.2):
        st = st0 + sa * a
        for hr in (0.4, 0.5, 0.75, 1.0):
            tg = e - hr * (st - e); cik, jx = cc[son], son
            for j in range(i + 1, son + 1):
                if h[j] >= st: cik, jx = max(st, o[j]), j; break
                if l[j] <= tg: cik, jx = min(tg, o[j]), j; break
            R = ((e - cik) / e - MALIYET + fon_top(FR.get(r.symbol), g.index[i], g.index[jx])) / ((st - e) / e)
            rows.append({"zaman": r.zaman, "kume": r.kume, "stop": sa, "hedef": hr, "R": R})
X = pd.DataFrame(rows)
X["donem"] = np.where(X.zaman < "2025-01-01", "sec", "kontrol")
X["grup"] = pd.cut(X.kume, [-1, 2, 5, 15, 999], labels=["tek(2yildiz)", "3-5", "6-15", "16+"])
f = lambda b: f"{(b > 0).mean()*100:.0f}%/{b.mean():+.2f}/{len(b)}"
P = X.groupby(["grup", "stop", "hedef", "donem"], observed=True).R.apply(f).unstack()
pd.set_option("display.width", 200); print(P.to_string())
P.to_csv("short_arastirma/kos_gelistir2_hedef.csv")
