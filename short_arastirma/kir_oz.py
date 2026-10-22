"""Destek kirilimi islemlerine giris ozellikleri ekle (kume dahil) ve kaydet."""
import sys, multiprocessing as mp
sys.path.insert(0, "/home/claude/sushi-izleme-botu")
import os; os.chdir("/home/claude/sushi-izleme-botu")
import numpy as np, pandas as pd
import short_lab as S
SP = "/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D, FR, M = S.yukle(); REJ = S.btc_rejim(D); X = {s: S.ozellik(g) for s, g in D.items()}
PRM = [dict(vm=1.5, stop_atr=2.0, tR=1.0, rejim=None), dict(vm=1.5, stop_atr=2.0, tR=2.0, rejim=None),
       dict(vm=1.5, stop_atr=1.0, tR=2.0, rejim=None)]

def oz(s):
    g, x = D[s], X[s]
    c = g.c
    f = pd.DataFrame(index=g.index)
    f["atrp"] = x.atr / c
    f["r7"] = c.pct_change(42); f["r30"] = c.pct_change(180); f["r1"] = c.pct_change(6)
    f["ema50d"] = c / c.ewm(span=50 * 6, adjust=False).mean() - 1      # gunluk ema50 yaklasik
    f["ema20"] = c / c.ewm(span=20, adjust=False).mean() - 1
    f["hv"] = g.v / x.vavg
    f["mum"] = (g.o - c) / x.atr
    f["qv"] = x.qv; f["yas"] = x.yas / 6
    lo = g.l.rolling(80).min().shift(1); f["kir_derin"] = (lo - c) / x.atr
    fr = FR.get(s)
    f["fon"] = fr.rolling(3).mean().reindex(g.index, method="ffill") if fr is not None and len(fr) else np.nan
    return f

def bir(args):
    s, k = args
    r = S.aile_kirilim(D[s], X[s], REJ, fr=FR.get(s), **PRM[k])
    if not r: return None
    t = pd.DataFrame(r); t["symbol"] = s
    f = oz(s).reindex(t.giris).reset_index(drop=True)
    return pd.concat([t.reset_index(drop=True), f], axis=1)

if __name__ == "__main__":
    for k in range(len(PRM)):
        with mp.get_context("fork").Pool(2) as hv:
            parts = [p for p in hv.map(bir, [(s, k) for s in D]) if p is not None]
        t = pd.concat(parts, ignore_index=True)
        # kume: son 6 mumda (bu dahil) kac farkli coinde ayni sinyal (tum sinyaller, islem acilmasa da yaklasik: acilan islemler)
        b = t.giris.dt.floor("4h")
        cnt = b.value_counts().sort_index()
        ix = pd.date_range(cnt.index.min(), cnt.index.max(), freq="4h")
        c6 = cnt.reindex(ix, fill_value=0).rolling(6, min_periods=1).sum()
        t["kume6"] = b.map(c6).values; t["kume1"] = b.map(cnt).values
        rj = REJ.reindex(t.giris.dt.floor("1D")).reset_index(drop=True)
        t["btc_r7"] = rj.btc_r7.values; t["ayi50"] = rj.ayi50.values; t["ayi200"] = rj.ayi200.values
        t["btc_ema"] = (rj.btc / rj.btc_ema50 - 1).values
        t.to_pickle(SP + f"kir_{k}.pkl"); print(k, len(t), flush=True)
