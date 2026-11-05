"""Gelistirme 2c: 'kirmizi3<=2 | kume>=4' gevsetmesinde 2025 oncesi isabet neden dusuyor? Ekstra islemlerin ayrisimi."""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S
from short_arastirma.gelistir2 import tek_pozisyon
t = pd.read_pickle(os.path.join(os.environ.get("SP", "/tmp"), "gelistir2.pkl"))
D, FR, _ = S.yukle()
# hangi onceki mum kirmizi, BTC durumu
k1 = []; k2 = []; btc6 = []; btc42 = []
b = D["BTCUSDT"]["c"]
for _, r in t.iterrows():
    g = D[r.symbol]; i = g.index.get_loc(r.zaman)
    k1.append(int(g.c.iloc[i-1] < g.o.iloc[i-1])); k2.append(int(g.c.iloc[i-2] < g.o.iloc[i-2]))
t["kirmizi_1once"] = k1; t["kirmizi_2once"] = k2
t["btc_r24s"] = t.zaman.map(b.pct_change(6)); t["btc_r7g"] = t.zaman.map(b.pct_change(42))
sert = t.risk.between(0.004, 0.25) & (t.kir_boy < 2.7) & (t.vor3 < 0.7)
eski = sert & (t.kirmizi3 == 1); yeni = sert & (t.kirmizi3 <= 2)
k_e = t.zaman.map(t[eski].groupby("zaman").size()).fillna(0)
k_y = t.zaman.map(t[yeni].groupby("zaman").size()).fillna(0)
t["kume_eski"], t["kume_yeni"] = k_e, k_y
canli = eski & ((k_e >= 3) | (t.yildiz == 2))
gev = yeni & ((k_y >= 4) | (t.yildiz == 2))
t["grup"] = np.select([canli & gev, canli & ~gev, gev & (t.kirmizi3 == 1), gev & (t.kirmizi3 == 2)],
                      ["ikisinde de", "sadece canli (gevsetmede dustu)", "eski tip ama kume sisti", "YENI: onceki 2 mumdan biri kirmizi"], "-")
x = tek_pozisyon(t[canli | gev])
x["donem"] = np.where(x.zaman < "2025-01-01", "<2025", "2025+")
f = lambda r: f"{(r > 0).mean()*100:.0f}% / {r.mean():+.2f}R / n={len(r)}"
pd.set_option("display.width", 250, "display.max_colwidth", 60)
print("=== Gruplar ===")
print(x.groupby(["grup", "donem"]).R.apply(f).unstack().to_string())
y = x[x.grup == "YENI: onceki 2 mumdan biri kirmizi"].copy()
print("\n=== Yeni sinyaller: yil yil ===")
print(y.groupby(y.zaman.dt.year).R.apply(f).to_string())
print("\n=== Yeni sinyaller: hangi mum kirmizi ===")
y["hangi"] = np.where(y.kirmizi_1once == 1, "hemen onceki mum kirmizi (yesil-kirmizi-RET)", "2 onceki kirmizi (kirmizi-yesil-RET)")
print(y.groupby(["hangi", "donem"]).R.apply(f).unstack().to_string())
print("\n=== Yeni sinyaller: kume buyuklugu ===")
y["kg"] = pd.cut(y.kume_yeni, [0, 5, 15, 999])
print(y.groupby(["kg", "donem"], observed=True).R.apply(f).unstack().to_string())
print("\n=== Yeni sinyaller: BTC son 7 gun ===")
y["bg"] = pd.cut(y.btc_r7g, [-1, -0.05, 0, 0.05, 1])
print(y.groupby(["bg", "donem"], observed=True).R.apply(f).unstack().to_string())
print("\n=== Yeni sinyaller: yildiz ===")
print(y.groupby(["yildiz", "donem"]).R.apply(f).unstack().to_string())
print("\n=== Yeni sinyaller: kaybedenler <2025 (tarih kumelenmesi) ===")
kay = y[(y.R <= 0) & (y.donem == "<2025")]
print(kay.groupby(kay.zaman.dt.to_period("M")).size().sort_values(ascending=False).head(8).to_string())
print("\n=== Ayni karsilastirma: CANLI sinyallerde ayni dilimler (kiyas) ===")
z = x[x.grup.isin(["ikisinde de", "sadece canli (gevsetmede dustu)"])].copy()
z["bg"] = pd.cut(z.btc_r7g, [-1, -0.05, 0, 0.05, 1])
print(z.groupby(["bg", "donem"], observed=True).R.apply(f).unstack().to_string())
t.to_pickle(os.path.join(os.environ.get("SP", "/tmp"), "gelistir2_neden.pkl"))
