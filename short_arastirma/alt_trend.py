import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import numpy as np, pandas as pd, short_lab as S
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D,FR,M=S.yukle()
ab={}; ok={}; r7={}
for s,g in D.items():
    qv=(g.c*g.v).rolling(180,min_periods=60).median()*6
    o=(qv>=20e6)
    ab[s]=(g.c>g.c.ewm(span=300,adjust=False).mean()).where(o)
    r7[s]=g.c.pct_change(42).where(o)
A=pd.DataFrame(ab); R7=pd.DataFrame(r7)
T=pd.DataFrame({"alt_ust50":A.mean(axis=1),"alt_r7_med":R7.median(axis=1)})
T["alt_ust50_d"]=T.alt_ust50-T.alt_ust50.shift(42)
T.to_pickle(SP+"alt.pkl"); print(T.describe())
