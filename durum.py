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
# K69 SHORT retest: son 30 mumda cikip hala acik olanlar (tum likit vadeli)
try:
    SR = yukle("short_retest", "main_kod/short_retest.py")
    info = veri._get("/fapi/v1/exchangeInfo", {}, veri.FAPI_URLS)
    syms = sorted(x["symbol"] for x in info["symbols"] if x.get("contractType") == "PERPETUAL" and x.get("quoteAsset") == "USDT"
                  and x.get("status") == "TRADING" and x.get("underlyingType", "COIN") == "COIN")
    rs_acik, rs_son = [], []
    for s in syms:
        try:
            df = veri.mumlar_onbellekli("F:" + s, "4h", "2026-04-01")
            g = df.set_index("open_time").rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})[["o", "h", "l", "c", "v"]]
            if len(g) < 250:
                continue
            for x in SR.sinyaller(g):
                if x["zaman"] < g.index[-1] - pd.Timedelta(days=10):
                    continue
                r = SR.sonuc_takip(g, x)
                d = {"coin": s, "yildiz": x["yildiz"], "sinyal_mum_kapanisi_utc": str(x["zaman"] + pd.Timedelta(hours=4)),
                     "giris": x["giris"], "stop": round(x["stop"], 8), "hedef": round(x["hedef"], 8), "son_fiyat": float(g["c"].iloc[-1]),
                     "durum": "ACIK" if r is None else f"{r[0]} {r[3]:+.2f}R"}
                (rs_acik if r is None else rs_son).append(d)
        except Exception as exc:
            pass
    satir.append(f"K69 SHORT ACIK: {len(rs_acik)}")
    satir += [json.dumps(d, default=str) for d in rs_acik]
    satir.append(f"K69 SHORT son 10 gunde kapananlar: {len(rs_son)}")
    satir += [json.dumps(d, default=str) for d in rs_son]
except Exception as exc:
    satir.append(f"K69 SHORT hata {exc}")
open("arastirma_cikti/durum.txt", "w").write("\n".join(satir))
print("\n".join(satir))
