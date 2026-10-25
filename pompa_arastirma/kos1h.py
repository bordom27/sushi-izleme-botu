"""1 saatlik veriyle ateslemede long taramasi (ve ayni donemde 4s karsilastirma).
python pompa_arastirma/kos1h.py 1h|4h <cikti.csv>   (veri: arastirma_cikti/dok1h, funding: dok)"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import multiprocessing as mp
import numpy as np, pandas as pd
import short_lab as S
import pompa_arastirma.lab as L

TUR = sys.argv[1]
BAS = pd.Timestamp("2024-01-01")
F = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok/fund_*.csv.gz"))], ignore_index=True)
F["t"] = pd.to_datetime(F["t"], unit="ms")
FR = {s: g.set_index("t")["fr"].sort_index() for s, g in F.groupby("symbol")}
SON = None


def yukle1h():
    K = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok1h/k1h_*.csv.gz"))], ignore_index=True)
    birim = "s" if K["t"].max() < 1e11 else "ms" if K["t"].max() < 1e14 else "us"
    K["t"] = pd.to_datetime(K["t"], unit=birim)
    D = {}
    for s, g in K.groupby("symbol", sort=True):
        g = g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]]
        g = g[g.v > 0]
        if len(g) >= 24 * 20:
            D[s] = g
    return D


if TUR == "1h":
    L.BPD = 24
    D = yukle1h()
    SON = max(g.index[-1] for g in D.values())
    IZ = {"iz1": (1.0, 1.0), "iz2": (2.0, 1.0), "iz15": (1.5, 0.75)}
    GRID = [dict(r1=a, vx=b, fitil=f, stop=st, tR=None, iz=z, maks=mk)
            for a in (0.04, 0.06, 0.08, 0.12) for b in (5, 10, 20) for f in (0.25, 0.5) for st in ("mum", "orta")
            for z in ("iz1", "iz2", "iz15") for mk in (24, 72)]
else:
    L.BPD = 6
    D0, _, _ = S.yukle()
    D = D0
    IZ = {"iz1": (1.0, 1.0), "iz2": (2.0, 1.0), "iz15": (1.5, 0.75)}
    GRID = [dict(r1=0.12, vx=5, fitil=0.25, stop="mum", tR=None, iz=z, maks=18) for z in ("iz1", "iz2", "iz15")]


def coin(s):
    g = D[s]; fr = FR.get(s); res = []
    for k, p in enumerate(GRID):
        q = dict(p); q["iz"] = IZ[q["iz"]]
        for x in L.long_ates(g, fr, **q):
            if x["zaman"] < BAS:
                continue
            x["k"] = k; x["symbol"] = s; res.append(x)
    return res


def ozet(t):
    if len(t) == 0:
        return {"n": 0}
    kaz = t.R > 0
    eg = t[t.zaman < "2025-01-01"]; ts = t[t.zaman >= "2025-01-01"]; s12 = t[t.zaman >= "2025-10-22"]
    srt = t.R.sort_values(ascending=False)
    return {"n": len(t), "isb": kaz.mean(), "R": t.R.mean(), "R_ilk1yuzde_yok": srt.iloc[max(1, len(t) // 100):].mean(),
            "n_24": len(eg), "R_24": eg.R.mean(), "isb_24": (eg.R > 0).mean(),
            "n_ts": len(ts), "R_ts": ts.R.mean(), "isb_ts": (ts.R > 0).mean(),
            "haftada_s12": len(s12) / 52.1, "R_s12": s12.R.mean(), "risk_med": t.risk.median()}


if __name__ == "__main__":
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(coin, list(D), chunksize=4)
    t = pd.DataFrame([x for l in out for x in l])
    if SON is not None:
        t = t[t.zaman <= SON]
    t.to_pickle(sys.argv[2].replace(".csv", ".pkl"))
    rows = []
    for k, p in enumerate(GRID):
        r = dict(p); r.update(ozet(t[t.k == k])); rows.append(r)
    pd.DataFrame(rows).to_csv(sys.argv[2], index=False)
    print("bitti", len(t))
