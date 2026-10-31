"""
Vadeli piyasa konumlanma kaydi (Binance USDT-M): saatlik Open Interest, long/short oranlari, taker alim/satim.
Binance bu verinin gecmisini sadece ~30 gun tutuyor; bu betik duzenli calisip kalici arsiv olusturur.
Kullanim: python oi_kayit.py <klasor> [geri]
  normal: son 36 saat (12 saatte bir calisir, ortusme analizde tekillenir)
  geri  : son 29 gun (ilk kurulum)
Cikti: <klasor>/oi_<YYYYMMDD-HHMM>.csv.gz  kolonlar: symbol,t,oi,oi_usd,ls_hesap,ls_top_poz,ls_top_hesap,taker_oran,taker_al,taker_sat
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

import veri

UC = {
    "openInterestHist": {"sumOpenInterest": "oi", "sumOpenInterestValue": "oi_usd"},
    "globalLongShortAccountRatio": {"longShortRatio": "ls_hesap"},
    "topLongShortPositionRatio": {"longShortRatio": "ls_top_poz"},
    "topLongShortAccountRatio": {"longShortRatio": "ls_top_hesap"},
    "takerlongshortRatio": {"buySellRatio": "taker_oran", "buyVol": "taker_al", "sellVol": "taker_sat"},
}
ARALIK = 0.32          # /futures/data: 1000 istek / 5 dk siniri


def cek(sym, uc, bas_ms, bit_ms):
    out = []
    s = bas_ms
    while s < bit_ms:
        e = min(bit_ms, s + 499 * 3600_000)
        try:
            d = veri._get(f"/futures/data/{uc}", {"symbol": sym, "period": "1h", "startTime": s, "endTime": e, "limit": 500},
                          veri.FAPI_URLS)
        except Exception as exc:
            print("  hata", sym, uc, str(exc)[:80], flush=True)
            d = []
        time.sleep(ARALIK)
        out.extend(d or [])
        s = e + 1
    return out


def main():
    klasor = sys.argv[1]
    geri = len(sys.argv) > 2 and sys.argv[2] == "geri"
    os.makedirs(klasor, exist_ok=True)
    info = veri._get("/fapi/v1/exchangeInfo", {}, veri.FAPI_URLS)
    semboller = sorted(s["symbol"] for s in info["symbols"]
                       if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING")
    simdi = int(time.time() * 1000) // 3600_000 * 3600_000
    bas = simdi - (29 * 24 if geri else 36) * 3600_000
    print("sembol", len(semboller), "| saat", (simdi - bas) // 3600_000, flush=True)
    satirlar = []
    for i, sym in enumerate(semboller):
        tablo = {}
        for uc, kol in UC.items():
            for x in cek(sym, uc, bas, simdi):
                t = int(x["timestamp"])
                r = tablo.setdefault(t, {"symbol": sym, "t": t})
                for k, v in kol.items():
                    if k in x:
                        r[v] = float(x[k])
        satirlar.extend(tablo.values())
        if (i + 1) % 50 == 0:
            print(i + 1, len(semboller), len(satirlar), flush=True)
    df = pd.DataFrame(satirlar)
    if df.empty:
        raise SystemExit("veri yok")
    df["t"] = pd.to_datetime(df.t, unit="ms")
    ad = time.strftime("%Y%m%d-%H%M", time.gmtime())
    df.sort_values(["symbol", "t"]).to_csv(f"{klasor}/oi_{ad}.csv.gz", index=False, compression="gzip", float_format="%.6g")
    print("yazildi", len(df), "satir", df.symbol.nunique(), "sembol", df.t.min(), df.t.max())


if __name__ == "__main__":
    main()
