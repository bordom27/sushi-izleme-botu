import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import numpy as np, pandas as pd, short_lab as S
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D,FR,M=S.yukle(); REJ=S.btc_rejim(D)
G=pd.read_pickle(SP+"genislik.pkl"); A=pd.read_pickle(SP+"alt.pkl")
t=pd.read_pickle(SP+"retest_sb0.8.pkl"); t=t[t.giris>="2020-01-01"].reset_index(drop=True)
def rsi(c,n=14):
    d=c.diff(); u=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+u/dn)
parts=[]
for s,g in t.groupby("symbol"):
    d=D[s]; c=d.c; x=S.ozellik(d)
    f=pd.DataFrame(index=d.index)
    f["rsi"]=rsi(c); f["r7"]=c.pct_change(42); f["r30"]=c.pct_change(180); f["r1"]=c.pct_change(6)
    e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean()
    f["e20"]=c/e20-1; f["e50"]=c/e50-1; f["e50_eg"]=e50.pct_change(6)
    f["kapanis_yeri"]=(c-d.l)/(d.h-d.l).replace(0,np.nan)
    f["govde"]=(d.o-c)/x.atr
    f["mum_sayisi_kirmizi3"]=(c<d.o).astype(int).rolling(3).sum()
    f["gun_saat"]=d.index.hour
    f["rsi_d"]=rsi(c.resample("1D").last().dropna()).shift(1).reindex(d.index,method="ffill")
    fr=FR.get(s); f["fon"]=fr.rolling(3).mean().reindex(d.index,method="ffill") if fr is not None and len(fr) else np.nan
    ff=f.reindex(g.giris); ff.index=g.index; parts.append(ff)
t=t.drop(columns=["fon"],errors="ignore").join(pd.concat(parts))
t=t.join(G,on="giris").join(A,on="giris")
rj=REJ.reindex(t.giris.dt.floor("1D")).reset_index(drop=True)
t["btc_r7"]=rj.btc_r7.values; t["btc_ema"]=(rj.btc/rj.btc_ema50-1).values
b=t.giris.dt.floor("4h"); cnt=b.value_counts()
ix=pd.date_range(cnt.index.min(),cnt.index.max(),freq="4h"); c6=cnt.reindex(ix,fill_value=0).rolling(42,min_periods=1).sum()
t["retest_kume7g"]=b.map(c6).values
t.to_pickle(SP+"retest_oz.pkl"); print(len(t))
