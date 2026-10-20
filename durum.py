"""Botun (main) mantigiyla su anki acik pozisyonlari ve bekleyenleri listeler."""
import importlib.util, json, sys, time
import pandas as pd

def yukle(ad, yol):
    spec = importlib.util.spec_from_file_location(ad, yol); m = importlib.util.module_from_spec(spec)
    sys.modules[ad] = m; spec.loader.exec_module(m); return m

veri = yukle("veri", "main_kod/veri.py")
k = yukle("kirilim_v6", "main_kod/kirilim_v6.py")
cl = yukle("coin_listesi", "main_kod/coin_listesi.py")
btc_d = veri.mumlar_onbellekli("BTCUSDT", "1d", "2019-06-01")
btc_4h = veri.mumlar_onbellekli("BTCUSDT", "4h", "2024-06-01")
gen = {}
for s in cl.GENISLIK_COINLER:
    gen[s] = btc_4h if s == "BTCUSDT" else veri.mumlar_onbellekli(s, "4h", "2024-06-01")
    time.sleep(0.1)
genislik = k.genislik_serisi(gen, cl.GENISLIK_COINLER, k.PARAMS["genislik_bar"], k.PARAMS["resistance_len"])
satir = [f"Hesap zamani (UTC): {pd.Timestamp.now(tz='UTC')}", f"BTC son 4s kapanis: {btc_4h['close'].iloc[-1]}"]
acik, giris_hepsi = [], []
for s in cl.COINLER:
    try:
        df = gen[s] if s in gen else veri.mumlar_onbellekli(s, "4h", "2024-06-01")
        r = k.simule_et(s, df, btc_d if s == "BTCUSDT" else None, btc_d, btc_4h, genislik=genislik)
        giris_hepsi += [(o.zaman, o.yon) for o in r.olaylar if o.tur == "GIRIS"]
        if r.acik:
            acik.append((s, r.acik))
    except Exception as exc:
        satir.append(f"{s} hata {exc}")
    time.sleep(0.1)
satir.append(f"ACIK POZISYON: {len(acik)}")
for s, a in sorted(acik, key=lambda x: x[1]["zaman"]):
    z = pd.Timestamp(a["zaman"])
    n = sum(1 for zz, yy in giris_hepsi if yy == a["yon"] and z - pd.Timedelta(hours=20) <= zz <= z)
    satir.append(json.dumps({"coin": s, "yon": "LONG" if a["yon"] == 1 else "SHORT", "giris_mum_kapanisi_utc": str(z + pd.Timedelta(hours=4)),
                             "giris": a["giris"], "stop": a["stop"], "tp1": a["tp1"], "tp1_alindi": a["tp1_done"], "tp2": a["tp2"],
                             "anlik_r": round(a["anlik_r"], 2), "kume_24s": n}, default=str))
son = sorted(giris_hepsi)[-10:]
satir.append("Son 10 giris sinyali (zaman, yon): " + ", ".join(f"{z}/{y}" for z, y in son))
open("arastirma_cikti/durum.txt", "w").write("\n".join(satir))
print("\n".join(satir))
