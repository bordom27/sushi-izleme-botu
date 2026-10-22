"""v6.6 motorunu sadece short olarak tum vadeli sozlesmelerde 2020+ calistir (yerel veri)."""
import sys, os; sys.path.insert(0,"/home/claude/sushi-izleme-botu"); os.chdir("/home/claude/sushi-izleme-botu")
import multiprocessing as mp, numpy as np, pandas as pd
import short_lab as S, arastirma as A, buyuk as B
SP="/tmp/claude-0/-home-claude/3fb83810-cd80-5ba7-8082-c2cdc2e7ee95/scratchpad/"
D,FR,M=S.yukle()
def cevir(g):
    df=g.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"}).reset_index().rename(columns={"t":"open_time"})
    df["open_time"]=pd.to_datetime(df.open_time).astype("datetime64[ns]")
    df["close_time"]=df.open_time+pd.Timedelta(hours=4)-pd.Timedelta(milliseconds=1)
    gi=g.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    gd=gi.resample("1D").agg(agg).dropna().reset_index().rename(columns={"t":"open_time"})
    wd=gi.resample("W-MON",label="left",closed="left").agg(agg).dropna().reset_index().rename(columns={"t":"open_time"})
    for x in (gd,wd):
        x["open_time"]=pd.to_datetime(x.open_time).astype("datetime64[ns]")
    gd["close_time"]=gd.open_time+pd.Timedelta(days=1)-pd.Timedelta(milliseconds=1)
    wd["close_time"]=wd.open_time+pd.Timedelta(days=7)-pd.Timedelta(milliseconds=1)
    return df[["open_time","close_time","open","high","low","close","volume"]],gd,wd
A.IS_BAS="2020-01-01"
A.DATA["4h"]={s:cevir(g) for s,g in D.items() if len(g)>300}
A.DATA["btc_4h"]=A.DATA["4h"]["BTCUSDT"][0]; A.DATA["btc_d"]=A.DATA["4h"]["BTCUSDT"][1]
print("coin",len(A.DATA["4h"]),flush=True)
p=B.b66(A.DATA["4h"])
SEN=[("v66_short_btcsiz", dict(p, yon="Sadece Short", mkt_short=False))]
if __name__=="__main__":
    for ad,prm in SEN:
        with mp.get_context("fork").Pool(2) as hv:
            tr=A.calistir(prm, list(A.DATA["4h"]), "4h", hv)
        tr.drop(columns=[c for c in tr.columns if tr[c].dtype==object and c not in ("symbol","tip","kalite","neden","yon")],errors="ignore").to_pickle(SP+f"{ad}.pkl")
        print(ad,len(tr),tr.columns.tolist()[:30],flush=True)
