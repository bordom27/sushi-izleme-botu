"""Parametre taramasi: python pompa_arastirma/kos.py long|short <cikti.csv>"""
import os, sys, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import multiprocessing as mp
import numpy as np, pandas as pd
import short_lab as S
import pompa_arastirma.lab as L

D, FR, M = S.yukle()
TUR = sys.argv[1]
if TUR == "long":
    IZ = {"yok": None, "iz1": (1.0, 1.0), "iz2": (2.0, 1.0)}
    GRID = [dict(r1=a, vx=b, fitil=f, stop=s, tR=t, iz=z, maks=18)
            for a in (0.08, 0.12, 0.2) for b in (3, 5, 10) for f in (0.25, 0.5) for s in ("mum", "orta")
            for t, z in ((1.0, "yok"), (2.0, "yok"), (3.0, "yok"), (None, "iz1"), (None, "iz2"))]
else:
    GRID = [dict(P=p, N=nn, dusus=d, maks_tepe=mt, stop_k=sk, tR=t, maks=30)
            for p in (0.5, 1.0, 2.0) for nn in (12, 18) for d in (0.1, 0.2, 0.3) for mt in (6, 18)
            for sk in (0.3, 1.0) for t in (0.5, 1.0, 2.0)]


def coin(s):
    g = D[s]; fr = FR.get(s); res = []
    for k, p in enumerate(GRID):
        if TUR == "long":
            q = dict(p); q["iz"] = IZ[q["iz"]]
            tr = L.long_ates(g, fr, **q)
        else:
            tr = L.short_cokus(g, fr, **p)
        for x in tr:
            x["k"] = k; x["symbol"] = s
        res += tr
    return res


if __name__ == "__main__":
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(coin, list(D), chunksize=4)
    t = pd.DataFrame([x for l in out for x in l])
    t.to_pickle(sys.argv[2].replace(".csv", ".pkl"))
    rows = []
    for k, p in enumerate(GRID):
        r = dict(p); r.update(L.ozet(t[t.k == k])); rows.append(r)
    pd.DataFrame(rows).to_csv(sys.argv[2], index=False)
    print("bitti", len(t))
