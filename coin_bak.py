"""Tek coin icin K69 SHORT teshisi: python coin_bak.py JSTUSDT"""
import importlib.util, json, sys
import numpy as np, pandas as pd

def yukle(ad, yol):
    spec = importlib.util.spec_from_file_location(ad, yol); m = importlib.util.module_from_spec(spec)
    sys.modules[ad] = m; spec.loader.exec_module(m); return m

veri = yukle("veri", "main_kod/veri.py")
SR = yukle("short_retest", "main_kod/short_retest.py")
s = sys.argv[1]
df = veri.mumlar_onbellekli("F:" + s, "4h", "2026-04-01")
g = df.set_index("open_time").rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})[["o", "h", "l", "c", "v"]]
x = SR.gostergeler(g)
c, o, h, l, v, atr, va, q = (x[k] for k in ("c", "o", "h", "l", "v", "atr", "va", "qv"))
out = [f"{s} | mum {len(g)} | son kapanis {c[-1]} ({g.index[-1] + pd.Timedelta(hours=4)} UTC) | gunluk hacim {q[-1]/1e6:.2f}M$ | ATR {atr[-1]:.6g}"]
for R_ in (80, 160):
    ll = pd.Series(l).rolling(R_).min().shift(1).to_numpy()
    out.append(f"{R_} mumluk dip (destek): {ll[-1]:.6g}  -> fiyat desteğin %{(c[-1]/ll[-1]-1)*100:+.1f} {'ustunde' if c[-1] > ll[-1] else 'altinda'}")
    kir = [i for i in range(len(c) - 60, len(c)) if c[i] < ll[i] - 0.05 * atr[i]]
    for i in kir[-6:]:
        out.append(f"   son 60 mumda dibin altinda kapanis: {g.index[i] + pd.Timedelta(hours=4)} kapanis {c[i]:.6g} seviye {ll[i]:.6g} hacim {v[i]/va[i]:.2f}x (gereken 1.5x) hacim$ {q[i]/1e6:.1f}M")
out.append("Bekleyen retest: " + json.dumps([{k: (str(vv) if not isinstance(vv, (int, float)) else round(float(vv), 6)) for k, vv in b.items()} for b in SR.bekleyenler(g)]))
sig = SR.sinyaller(g)
out.append(f"Gecmis sinyaller (2026-04'ten beri): {len(sig)}")
for z in sig[-5:]:
    r = SR.sonuc_takip(g, z)
    out.append(f"   {z['zaman'] + pd.Timedelta(hours=4)} giris {z['giris']} stop {z['stop']:.6g} hedef {z['hedef']:.6g} yildiz {z['yildiz']} -> {r[0] + f' {r[3]:+.2f}R' if r else 'ACIK'}")
out.append("Son 8 mum (kapanis UTC, a/y/d/k, hacim/ort):")
for i in range(len(c) - 8, len(c)):
    out.append(f"   {g.index[i] + pd.Timedelta(hours=4)} {o[i]:.6g}/{h[i]:.6g}/{l[i]:.6g}/{c[i]:.6g} {'yesil' if c[i] >= o[i] else 'kirmizi'} {v[i]/va[i]:.2f}x")
open("arastirma_cikti/coin_bak.txt", "w").write("\n".join(out))
print("\n".join(out))
