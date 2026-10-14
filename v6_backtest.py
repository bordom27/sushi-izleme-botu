"""
KIRILIM69 PRO v6 - COKLU COIN BACKTEST / AYLIK DOGRULAMA
================================================================================
Botun izledigi tum coinlerde, botla AYNI kodla (kirilim_v6.py) gecmis
islemleri simule eder. Komisyon dahil R sonuclari uretir.

Kullanim:
  python v6_backtest.py                       # aylik rapor: son 30 gun + Temmuz 2025'ten beri
  python v6_backtest.py --dogrulama           # TradingView karsilastirma senaryolari
  python v6_backtest.py --telegram            # ozeti Telegram'a da gonder

Cikti: v6_backtest_sonuclari.csv (tum islemler)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd
import requests

import kirilim_v6 as k
import veri
from coin_listesi import COINLER

VERI_BAS_4H = "2023-06-01"
VERI_BAS_1D = "2019-06-01"


def veri_topla(semboller, veri_bas_4h=VERI_BAS_4H):
    btc_d = veri.mumlar("BTCUSDT", "1d", VERI_BAS_1D)
    btc_4h = veri.mumlar("BTCUSDT", "4h", veri_bas_4h)
    out = {}
    for s in semboller:
        try:
            df = btc_4h if s == "BTCUSDT" else veri.mumlar(s, "4h", veri_bas_4h)
            gd = btc_d if s == "BTCUSDT" else veri.mumlar(s, "1d", VERI_BAS_1D)
            out[s] = (df, gd)
            print(f"  {s}: {len(df)} mum ({df['open_time'].iloc[0] if len(df) else '-'} -> )", flush=True)
        except Exception as exc:
            print(f"  {s}: VERI ALINAMADI ({exc})", flush=True)
        time.sleep(0.2)
    return out, btc_d, btc_4h


def calistir(data, btc_d, btc_4h, params=None, bas=None, bit=None):
    tum = []
    for s, (df, gd) in data.items():
        if len(df) < 120:
            continue
        r = k.simule_et(s, df, gd, btc_d, btc_4h, params=params,
                        giris_bas=pd.Timestamp(bas) if bas else None,
                        giris_bit=pd.Timestamp(bit) if bit else None)
        tum.extend(r.islemler)
    return pd.DataFrame(tum)


def ozet(tr: pd.DataFrame, baslik: str) -> str:
    if tr is None or tr.empty:
        return f"{baslik}: islem yok"
    n = len(tr)
    w = int((tr["sonuc_r"] > 0).sum())
    top = tr["sonuc_r"].sum()
    L = tr[tr["yon"] == 1]
    S = tr[tr["yon"] == -1]
    pf_k = tr.loc[tr["sonuc_r"] > 0, "sonuc_r"].sum()
    pf_z = -tr.loc[tr["sonuc_r"] <= 0, "sonuc_r"].sum()
    pf = pf_k / pf_z if pf_z > 0 else float("inf")
    eq = tr.sort_values("cikis_zaman")["sonuc_r"].cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    return (f"{baslik}: {n} islem | isabet %{100 * w / n:.1f} ({w}/{n}) | toplam {top:+.2f}R | "
            f"islem basi {top / n:+.3f}R | PF {pf:.2f} | maxDD {dd:.1f}R | "
            f"Long {len(L)} ({L['sonuc_r'].sum():+.2f}R) | Short {len(S)} ({S['sonuc_r'].sum():+.2f}R)")


def telegram(mesaj: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("(Telegram ayari yok, sadece konsol)")
        return
    for parca in [mesaj[i:i + 3800] for i in range(0, len(mesaj), 3800)]:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": parca}, timeout=15)
        except Exception as exc:
            print(f"Telegram hatasi: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dogrulama", action="store_true")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--semboller", default="")
    args = ap.parse_args()

    semboller = [s.strip().upper() for s in args.semboller.split(",") if s.strip()] or COINLER
    print(f"{len(semboller)} coin icin veri cekiliyor...", flush=True)
    data, btc_d, btc_4h = veri_topla(semboller)

    satirlar = []
    if args.dogrulama:
        senaryolar = [
            ("OOS BTC>EMA200 (TV: 179 islem, %63.7, +18.26R, long -0.4R)", {}, "2025-07-01", None),
            ("OOS filtresiz (TV: 209 islem, %63.6, +17.0R, long -1.59R / short +18.65R)",
             {"long_sart": "Kapali"}, "2025-07-01", None),
            ("IS filtresiz (TV: 170 islem, %70.6, +34.8R)", {"long_sart": "Kapali"}, "2024-01-01", "2025-06-30 23:59"),
        ]
        for ad, prm, bas, bit in senaryolar:
            tr = calistir(data, btc_d, btc_4h, prm, bas, bit)
            satirlar.append(ozet(tr, ad))
            print(satirlar[-1], flush=True)
            if bas == "2025-07-01" and not prm:
                tr.to_csv("v6_dogrulama_oos.csv", index=False)
                g = tr.groupby("symbol").agg(n=("sonuc_r", "size"), kaz=("sonuc_r", lambda x: int((x > 0).sum())),
                                             R=("sonuc_r", "sum")).round(2)
                print(g.to_string(), flush=True)
        # IS: TradingView'in yukledigi veri ~5000 mumla sinirli olabilir -> farkli veri baslangiciyla da bak
        data2 = {s: (df[df["open_time"] >= "2024-07-01"].reset_index(drop=True), gd) for s, (df, gd) in data.items()}
        tr = calistir(data2, btc_d, btc_4h, {"long_sart": "Kapali"}, "2024-01-01", "2025-06-30 23:59")
        satirlar.append(ozet(tr, "IS filtresiz, veri 2024-07'den"))
        print(satirlar[-1], flush=True)
        return

    simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)
    tr = calistir(data, btc_d, btc_4h, None, "2025-07-01", None)
    tr.to_csv("v6_backtest_sonuclari.csv", index=False)
    son30 = tr[pd.to_datetime(tr["cikis_zaman"]) >= simdi - pd.Timedelta(days=30)] if len(tr) else tr
    son90 = tr[pd.to_datetime(tr["cikis_zaman"]) >= simdi - pd.Timedelta(days=90)] if len(tr) else tr
    satirlar = [
        "KIRILIM69 PRO v6 - AYLIK DOGRULAMA (4 saat, komisyon dahil)",
        ozet(son30, "Son 30 gun"),
        ozet(son90, "Son 90 gun"),
        ozet(tr, "Temmuz 2025'ten beri"),
    ]
    if len(son90) >= 15 and son90["sonuc_r"].sum() < 0:
        satirlar.append("DIKKAT: son 90 gunde sistem zararda. Piyasa rejimi degismis olabilir; "
                        "sinyallerde pozisyonu kucult veya bir sure sadece izle.")
    if len(tr):
        g = tr.groupby("symbol")["sonuc_r"].agg(["size", "sum"]).sort_values("sum")
        satirlar.append("En zayif 5: " + ", ".join(f"{s} {r:+.1f}R/{int(n)}" for s, (n, r) in g.head(5).iterrows()))
        satirlar.append("En guclu 5: " + ", ".join(f"{s} {r:+.1f}R/{int(n)}" for s, (n, r) in g.tail(5)[::-1].iterrows()))
    rapor = "\n".join(satirlar)
    print(rapor)
    if args.telegram:
        telegram(rapor)


if __name__ == "__main__":
    sys.exit(main())
