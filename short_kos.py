"""Short ailelerini tum sembollerde calistirir, tablo basar. Kullanim: python short_kos.py <aile>"""
import multiprocessing as mp
import sys

import numpy as np
import pandas as pd

import short_lab as S

D = FR = META = REJ = X = None


def _init():
    global D, FR, META, REJ, X
    D, FR, META = S.yukle()
    REJ = S.btc_rejim(D)
    X = {s: S.ozellik(g) for s, g in D.items()}


def _bir(args):
    aile, prm, s = args
    g, x, fr = D[s], X[s], FR.get(s)
    if aile == "pompa":
        r = S.aile_pompa(g, x, REJ, fr=fr, **prm)
    elif aile == "tuzak":
        r = S.aile_tuzak(g, x, REJ, fr=fr, **prm)
    elif aile == "kirilim":
        r = S.aile_kirilim(g, x, REJ, fr=fr, **prm)
    elif aile == "liste":
        S.MAKS_RISK = 3.0
        ob = META.set_index("symbol").onboard.get(s)
        r = S.aile_listeleme(g, pd.to_datetime(ob, unit="ms") if pd.notna(ob) else None, fr=fr, **prm)
    for t in r:
        t["symbol"] = s
    return r


def calistir(aile, prm, havuz):
    sonuc = havuz.map(_bir, [(aile, prm, s) for s in D])
    return pd.DataFrame([t for l in sonuc for t in l])


IZGARA = {
    "pompa": [dict(N=N, P=P, tR=tR, dusus=d, rejim=rj)
              for N in (6, 18, 42) for P in (0.3, 0.6, 1.0) for tR in (1.0, 2.0) for d in (0.05,) for rj in (None, "ayi50")],
    "pompa_fon": [dict(N=18, P=P, tR=tR, fon_min=f) for P in (0.3, 0.6) for tR in (1.0, 2.0) for f in (0.0003, 0.001)],
    "tuzak": [dict(m=m, tR=tR, rejim=rj, hacimli=hv) for m in (3, 6, 12) for tR in (1.0, 2.0) for rj in (None, "ayi50") for hv in (False, True)],
    "kirilim": [dict(vm=vm, stop_atr=sa, tR=tR, rejim=rj) for vm in (1.5, 2.5) for sa in (1.0, 2.0) for tR in (1.0, 2.0, 4.0)
                for rj in (None, "ayi50", "ayi200")],
    "liste": [dict(gun=g_, maks_gun=m_, stop_k=k_) for g_ in (1, 3, 7, 14) for m_ in (14, 30, 60) for k_ in (0.5, 1.0)],
}

if __name__ == "__main__":
    aile = sys.argv[1]
    _init()
    print("sembol", len(D), flush=True)
    rows = []
    with mp.get_context("fork").Pool(2) as hv:
        for prm in IZGARA[aile]:
            tr = calistir(aile.split("_")[0], prm, hv)
            rows.append(S.rapor(tr, aile + " " + " ".join(f"{k}={v}" for k, v in prm.items())))
            print(rows[-1], flush=True)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40)
    df = pd.DataFrame(rows)
    df.to_csv(f"/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/kos_{aile}.csv", index=False)
    print(df.to_string(index=False))
