"""Short + sabit hedef (isabet odakli): duyurudan sonraki ilk tam saatte gir, hedef/stop/tutma; ayni mumda ikisi -> stop."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from duyuru import olay as OL

D, FR = OL.yukle()
M = pd.read_pickle("/tmp/claude-0/-home-claude/13e3c372-aa7b-58c8-a204-e85020633022/scratchpad/duyuru_olcum.pkl")


def sim(e, hedef, stop, tut):
    g = D[e.symbol]; T = g.index; i = T.searchsorted(e.giris_t)
    o, h, l, c = (g[k].to_numpy(float) for k in "ohlc")
    p = o[i]; st = p * (1 + stop); tg = p * (1 - hedef)
    j_son = min(len(c) - 1, i + tut - 1); cik = None
    for j in range(i, j_son + 1):
        if h[j] >= st:
            cik = st; break
        if l[j] <= tg:
            cik = tg; break
    if cik is None:
        j = j_son; cik = c[j]
    fr = FR.get(e.symbol)
    fz = fr[(fr.index > T[i]) & (fr.index <= T[j])].sum() if fr is not None else 0
    return -(cik / p - 1) - OL.MALIYET + fz, T[i].year


rows = []
for tur in ("spot_delist", "izleme", "hodler", "vadeli_delist"):
    ev = M[M.tur == tur]
    for hedef in (0.05, 0.08, 0.12, 0.20):
        for stop in (0.15, 0.25, 0.35):
            for tut in (72, 168):
                R = pd.DataFrame([sim(e, hedef, stop, tut) for _, e in ev.iterrows()], columns=["R", "yil"])
                yy = R.groupby("yil").R.apply(lambda s: (s > 0).mean())
                rows.append({"tur": tur, "hedef": hedef, "stop": stop, "tut": tut, "n": len(R), "isabet": (R.R > 0).mean(),
                             "ort": R.R.mean(), "R_kat": R.R.mean() / stop, "isb24": yy.get(2024), "isb25": yy.get(2025), "isb26": yy.get(2026)})
X = pd.DataFrame(rows); X.to_csv("arastirma_cikti/duyuru/hedefli.csv", index=False)
pd.set_option("display.width", 220)
for tur in X.tur.unique():
    print(f"\n=== {tur}"); print(X[(X.tur == tur) & (X.ort > 0)].sort_values("isabet", ascending=False).head(8).round(3).to_string(index=False))
