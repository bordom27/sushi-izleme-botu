import sys, glob, multiprocessing as mp
sys.path.insert(0,'/home/claude/main-wt')
import pandas as pd, numpy as np, kirilim_v6 as k
from coin_listesi import GENISLIK_COINLER
SP='/tmp/claude-0/-home-claude/8f2b9649-89d5-5c6f-a3a8-f1c844161a62/scratchpad/'
K=pd.concat([pd.read_csv(f) for f in glob.glob('/home/claude/sushi-izleme-botu/arastirma_cikti/dok/k4h_*.csv.gz')])
K['open_time']=pd.to_datetime(K.t,unit='s')
D={}
for s,g in K.groupby('symbol'):
    g=g.drop_duplicates('open_time').sort_values('open_time'); g=g[g.v>0]
    if len(g)<300: continue
    D[s]=g.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})[['open_time','open','high','low','close','volume']].reset_index(drop=True)
b4=D['BTCUSDT']
bd=b4.set_index('open_time').resample('1D').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna().reset_index()
gen=k.genislik_serisi({s:D[s] for s in GENISLIK_COINLER if s in D}, GENISLIK_COINLER, k.PARAMS['genislik_bar'], k.PARAMS['resistance_len'])
VAR={'BASE':{}, 'tp06':{'tp1_r':0.6,'tp1_min_r':0.4,'tp1_max_r':0.8},
     'tp09_tam':{'tp1_pct':100.0}, 'tp06_tam':{'tp1_r':0.6,'tp1_min_r':0.4,'tp1_max_r':0.8,'tp1_pct':100.0}}
def bir(a):
    s,v=a
    try: r=k.simule_et(s, D[s], None, bd, b4, params=dict(VAR[v], yon='Sadece Short'), genislik=gen)
    except Exception: return []
    return [{kk:vv for kk,vv in dict(t, var=v).items() if not isinstance(vv,(list,dict))} for t in r.islemler]
if __name__=='__main__':
    for v in VAR:
        with mp.get_context('fork').Pool(2) as hv: res=hv.map(bir,[(s,v) for s in D])
        t=pd.DataFrame([x for l in res for x in l]); t.to_pickle(SP+f'v6s_{v}.pkl'); print(v,len(t),flush=True)
