import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import numpy as np, pandas as pd, short_lab as S
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D,FR,M=S.yukle()
up={}; dn={}; liq={}
for s,g in D.items():
    hh=g.h.rolling(80).max().shift(1); ll=g.l.rolling(80).min().shift(1)
    qv=(g.c*g.v).rolling(180,min_periods=60).median()*6
    ok=qv>=20e6
    up[s]=((g.c>hh)&ok).astype(float); dn[s]=((g.c<ll)&ok).astype(float); liq[s]=ok.astype(float)
U=pd.DataFrame(up).fillna(0); Dn=pd.DataFrame(dn).fillna(0); L=pd.DataFrame(liq).fillna(0)
G=pd.DataFrame({"up6":(U.rolling(6,min_periods=1).max()>0).sum(axis=1),"dn6":(Dn.rolling(6,min_periods=1).max()>0).sum(axis=1),"nliq":L.sum(axis=1)})
G.to_pickle(SP+"genislik.pkl"); print(G.describe())
