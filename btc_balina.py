"""
Buyuk/basarili oyuncularin BTC pozisyonlari (GitHub Actions'ta):
  1) CFTC Traders in Financial Futures: CME Bitcoin vadeli (haftalik; varlik yoneticileri, hedge fonlar, bankalar)
  2) Hyperliquid: liderlik tablosundaki en karli cuzdanlarin BTC islemleri (fills) -> zaman icinde net pozisyon
Cikti: arastirma_cikti/btc/cftc.csv.gz, hl_fills.csv.gz, hl_cuzdan.csv.gz
"""
from __future__ import annotations

import os
import time

import pandas as pd
import requests

OUT = "arastirma_cikti/btc"
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (research script)", "Content-Type": "application/json"}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def kaydet(df, ad):
    df.to_csv(f"{OUT}/{ad}.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi {ad}: {len(df)} satir")


def cftc():
    rows = []
    for kod in ("133741", "133742"):                     # CME Bitcoin, CME Micro Bitcoin
        off = 0
        while True:
            r = requests.get("https://publicreporting.cftc.gov/resource/gpe5-46if.json",
                             params={"cftc_contract_market_code": kod, "$limit": 1000, "$offset": off,
                                     "$order": "report_date_as_yyyy_mm_dd"}, headers=H, timeout=60)
            r.raise_for_status()
            d = r.json()
            rows.extend(d)
            if len(d) < 1000:
                break
            off += 1000
        log(f"cftc {kod}: {len(rows)}")
    df = pd.DataFrame(rows)
    keep = ["report_date_as_yyyy_mm_dd", "cftc_contract_market_code", "open_interest_all"] + \
           [c for c in df.columns if any(k in c for k in ("asset_mgr_positions", "lev_money_positions", "dealer_positions",
                                                          "other_rept_positions", "nonrept_positions"))
            and c.endswith(("_long", "_short", "_long_all", "_short_all"))]
    df = df[[c for c in keep if c in df.columns]].rename(columns={"report_date_as_yyyy_mm_dd": "t"})
    df["t"] = pd.to_datetime(df["t"])
    for c in df.columns[2:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    kaydet(df.sort_values("t"), "cftc")


def hl_post(body):
    for i in range(5):
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", json=body, headers=H, timeout=60)
            if r.status_code == 429:
                time.sleep(5 + 5 * i)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if i == 4:
                raise
            time.sleep(3)


def hyperliquid(N=250):
    r = requests.get("https://stats-data.hyperliquid.xyz/Mainnet/leaderboard", headers=H, timeout=120)
    r.raise_for_status()
    rows = r.json().get("leaderboardRows", [])
    cz = []
    for x in rows:
        perf = {p[0]: p[1] for p in x.get("windowPerformances", [])}
        at = perf.get("allTime", {})
        cz.append({"adres": x["ethAddress"], "hesap_degeri": float(x.get("accountValue", 0) or 0),
                   "pnl_tum": float(at.get("pnl", 0) or 0), "vlm_tum": float(at.get("vlm", 0) or 0)})
    cz = pd.DataFrame(cz)
    log(f"hl liderlik: {len(cz)} cuzdan")
    # basarili + gercekten islem yapan (piyasa yapicilar haric: hacim/kar orani asiri yuksek olanlar elenir)
    cz = cz[(cz.pnl_tum > 0) & (cz.vlm_tum > 0)]
    cz["verim"] = cz.pnl_tum / cz.vlm_tum
    sec = cz[cz.verim > 0.0005].sort_values("pnl_tum", ascending=False).head(N)
    kaydet(sec, "hl_cuzdan")
    tum = []
    bas0 = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
    son = int(pd.Timestamp.utcnow().timestamp() * 1000)
    for k, adr in enumerate(sec.adres):
        bas = bas0
        n0 = len(tum)
        while bas < son:
            try:
                d = hl_post({"type": "userFillsByTime", "user": adr, "startTime": bas, "endTime": son, "aggregateByTime": True})
            except Exception as exc:
                log(f"hl {adr} hata {exc!r}")
                break
            if not d:
                break
            btc = [f for f in d if f.get("coin") == "BTC"]
            for f in btc:
                tum.append({"adres": adr, "t": f["time"], "px": float(f["px"]), "sz": float(f["sz"]), "side": f["side"],
                            "startPosition": float(f.get("startPosition", 0)), "closedPnl": float(f.get("closedPnl", 0)),
                            "dir": f.get("dir", "")})
            if len(d) < 2000:
                break
            bas = max(f["time"] for f in d) + 1
            time.sleep(0.4)
        if k % 20 == 0:
            log(f"hl {k}/{len(sec)} cuzdan, toplam btc fill {len(tum)} (+{len(tum) - n0})")
        time.sleep(0.3)
    df = pd.DataFrame(tum)
    if len(df):
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        kaydet(df.sort_values("t")[["t"] + [c for c in df.columns if c != "t"]], "hl_fills")


if __name__ == "__main__":
    for ad, f in (("cftc", cftc), ("hyperliquid", hyperliquid)):
        try:
            f()
        except Exception as exc:
            log(f"HATA {ad}: {exc!r}")
    open(f"{OUT}/log_balina.txt", "w").write("\n".join(LOG))
