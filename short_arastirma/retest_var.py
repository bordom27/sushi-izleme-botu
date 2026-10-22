import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import multiprocessing as mp, numpy as np, pandas as pd, short_lab as S
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D,FR,M=S.yukle(); X={s:S.ozellik(g) for s,g in D.items()}
VAR={"sb1.0":dict(stop_buf=1.0),"sb0.8":dict(stop_buf=0.8),"sb0.6m":dict(stop_buf=0.6)}
def bir(a):
    s,k=a; r=S.retest_olaylari(D[s],X[s],fr=FR.get(s),**VAR[k])
    for t in r: t["symbol"]=s
    return r
if __name__=="__main__":
    for k in VAR:
        with mp.get_context("fork").Pool(2) as hv: out=hv.map(bir,[(s,k) for s in D])
        t=pd.DataFrame([x for l in out for x in l]); t.to_pickle(SP+f"retest_{k}.pkl")
        t=t[(t.giris>="2020-01-01")&(t.vor3<0.7)]
        for tR in (0.5,0.75,1.0):
            r=t[f"R{tR}"]; e=r[t.giris<"2024"]; te=r[t.giris>="2024"]
            print(f"{k:7s} tR{tR} n={len(t)} win={(r>0).mean()*100:.0f}% R/i={r.mean():+.3f} e={e.mean():+.3f} t={te.mean():+.3f} C={r[t.giris>='2026-03'].sum():+.1f}",flush=True)
