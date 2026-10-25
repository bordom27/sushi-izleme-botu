import pandas as pd, numpy as np
t=pd.read_pickle("sq.pkl")
t["yil"]=t.zaman.dt.year; t["donem"]=np.where(t.zaman<"2025-01-01","eg","ts")
t["yeni"]=t.yas<6*200   # 200 gunden genc
K={
 "taban": pd.Series(False,index=t.index),
 "sicrama30>%15": t.maks_sicrama30>0.15,
 "sicrama30>%20": t.maks_sicrama30>0.20,
 "pompa30(>%10 mum)>=2": t.pompa30>=2,
 "pompa30>=3": t.pompa30>=3,
 "pompa30_atr>=2": t.pompa30_atr>=2,
 "yeni<200g": t.yeni,
 "yeni<120g": t.yas<6*120,
 "funding9<0": t.f9<0,
 "funding9<-0.03%": t.f9<-0.0003,
 "sikisma<0.8": t.sikisma<0.8,
 "pompa30>=2|yeni200": (t.pompa30>=2)|t.yeni,
 "sicrama20|yeni200": (t.maks_sicrama30>0.20)|t.yeni,
 "pompa30>=2|yeni200|f9<-0.03%": (t.pompa30>=2)|t.yeni|(t.f9<-0.0003),
}
rows=[]
for ad,m in K.items():
    m=m.fillna(False)
    kal=t[~m]; at=t[m]
    r={"kural":ad,"elenen":int(m.sum()),"elenen_isb":at.kazandi.mean() if len(at) else np.nan,"kalan":len(kal),"isb":kal.kazandi.mean(),"R":kal.R.mean(),"topR":kal.R.sum()}
    for d in ["eg","ts"]:
        k=kal[kal.donem==d]; a=at[at.donem==d]
        r[f"isb_{d}"]=k.kazandi.mean(); r[f"n_{d}"]=len(k); r[f"elen_isb_{d}"]=a.kazandi.mean() if len(a) else np.nan; r[f"topR_{d}"]=k.R.sum()
    rows.append(r)
print(pd.DataFrame(rows).round(3).to_string())
print()
