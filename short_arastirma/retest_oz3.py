import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import multiprocessing as mp, numpy as np, pandas as pd, short_lab as S
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
import json
KW=json.loads(sys.argv[1]) if len(sys.argv)>1 else {}
AD=sys.argv[2] if len(sys.argv)>2 else ""
D,FR,M=S.yukle(); X={s:S.ozellik(g) for s,g in D.items()}
def bir(s):
    g=D[s]; x=X[s]
    r=S.retest_olaylari(g,x,fr=FR.get(s),stop_buf=0.8,tRs=(0.4,0.5,0.75),**KW)
    if not r: return []
    o,h,l,c,v=(g[k].to_numpy(float) for k in "ohlcv"); atr=x.atr.to_numpy(); va=x.vavg.to_numpy()
    gd=S.gunluk(g); ge50=gd.c.ewm(span=50,adjust=False).mean(); ge200=gd.c.ewm(span=200,adjust=False).mean()
    gdf=pd.DataFrame({"g_e50":(gd.c/ge50-1).shift(1),"g_e200":(gd.c/ge200-1).shift(1),"g_lh":(gd.h.rolling(5).max()<gd.h.rolling(20).max()).shift(1).astype(float)})
    out=[]
    for t in r:
        k=t["k_ix"]; si=t["si_ix"]; sev=t["sev"]; a=atr[k]
        once=l[max(0,k-KW.get("R_",80)):k]
        t["destek_dokunus"]=int(((once<=sev+0.3*a)).sum())
        t["kir_boy"]=(h[k]-l[k])/a; t["kir_kapanis_yeri"]=(c[k]-l[k])/max(h[k]-l[k],1e-12)
        t["kir_mesafe"]=(sev-c[k])/a
        t["igne"]=(h[si]-sev)/atr[si]
        t["v_oran"]=v[si]/max(v[k],1e-12)
        t["yas_gun"]=si/6; t["haftagun"]=g.index[si].dayofweek
        t["onceki_retest"]=int((h[k+1:si]>=sev-0.2*atr[si]).sum())
        t["ralli_atr"]=(h[si]-l[k:si+1].min())/atr[si]
        gi=gdf.reindex([g.index[si].floor("1D")],method="ffill").iloc[0]
        t.update({kk:gi[kk] for kk in gdf.columns}); t["symbol"]=s
        out.append(t)
    return out
if __name__=="__main__":
    with mp.get_context("fork").Pool(2) as hv: out=hv.map(bir,list(D))
    t=pd.DataFrame([x for l in out for x in l]); t.to_pickle(SP+f"retest_oz2{AD}.pkl"); print(len(t))
