import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import multiprocessing as mp, numpy as np, pandas as pd, short_lab as S
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D,FR,M=S.yukle(); X={s:S.ozellik(g) for s,g in D.items()}
L=int(sys.argv[1]) if len(sys.argv)>1 else 120
def bir(s):
    r=S.direnc_olaylari(D[s],X[s],L=L,fr=FR.get(s))
    for t in r: t["symbol"]=s
    return r
if __name__=="__main__":
    with mp.get_context("fork").Pool(2) as hv:
        out=hv.map(bir,list(D))
    t=pd.DataFrame([x for l in out for x in l]); t.to_pickle(SP+f"direnc_L{L}.pkl"); print(len(t))
