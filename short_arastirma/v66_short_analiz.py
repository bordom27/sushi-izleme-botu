import pandas as pd, numpy as np
SP='/tmp/claude-0/-home-claude/8f2b9649-89d5-5c6f-a3a8-f1c844161a62/scratchpad/'
def m(t):
    t=t.sort_values('giris_zaman'); r=t.sonuc_r; eq=r.cumsum(); y=t.giris_zaman.dt.year
    son=t[t.giris_zaman>=pd.Timestamp('2025-10-22')].sonuc_r
    yil=' '.join(f"{yy%100}:{(r[y==yy]>0).mean()*100:.0f}/{r[y==yy].sum():+.0f}" for yy in range(2021,2027) if (y==yy).any())
    return f"n={len(t):4d} isabet={(r>0).mean()*100:5.1f} R/i={r.mean():+.3f} top={r.sum():+6.1f} dd={(eq.cummax()-eq).max():5.1f} s12={(son>0).mean()*100:.0f}%/{son.sum():+.0f}R | {yil}"
V={v:pd.read_pickle(SP+f'v6s_{v}.pkl') for v in ('BASE','tp06','tp09_tam','tp06_tam')}
for v,t in V.items():
    t=t[t.giris_zaman>='2020-01-01']; V[v]=t; print(f'{v:9s}', m(t))
b=V['BASE'].copy()
# ozellikler
b['g']=b.giris_zaman
kume=b.groupby('g').size(); b['kume']=b.g.map(kume)
# son 24 saat (6 mum) icinde tum coinlerde v6 short girisi
gs=b.g.sort_values().values
b['kume24']=[((gs>g-np.timedelta64(24,'h'))&(gs<=g)).sum() for g in b.g.values]
k=pd.read_pickle(SP+'iyilestirme.pkl'); kk=k.groupby('giris').size()
ks=k.giris.sort_values().values
b['k69_24']=[((ks>g-np.timedelta64(24,'h'))&(ks<=g)).sum() for g in b.g.values]
b['risk_pct']=(b.stop_ilk/b.giris-1)*100
print(b.kalite.value_counts().to_dict(), b.tip.value_counts().to_dict())
def grup(kol,kes=None):
    x=b if kes is None else b.assign(**{kol:pd.cut(b[kol],kes)})
    print(x.groupby(kol,observed=True).sonuc_r.agg(n='size',isabet=lambda r:round((r>0).mean()*100,1),Ri=lambda r:round(r.mean(),3),top=lambda r:round(r.sum(),1)).to_string())
grup('kalite'); grup('tip'); grup('kume',[0,1,2,4,999]); grup('kume24',[0,1,3,6,12,999]); grup('k69_24',[-1,0,2,5,999]); grup('risk_pct',[0,3,5,8,13])
b.to_pickle(SP+'v6s_base_oz.pkl')
