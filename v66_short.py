"""
K69 PRO SHORT - Kirilim69 PRO (v6.6) motoru, sadece short, TUM likit USDT-M vadeli coinlerde (26 Eki 2026).

Motor: kirilim_v6.simule_et, canli PARAMS + yon="Sadece Short" + tp1_pct=100 (TP1'de pozisyonun tamamini kapat).
Filtre (sinyal bildirilir mi):
  - ayni 4s mumda en az MIN_KUME coinde v6.6 short girisi var (tum vadeli coinler sayilir)
  - giris kalitesi B
Test (2020 - Eki 2026, tum vadeli sozlesmeler, komisyon dahil; short_arastirma/v66_short_iyilestirme.py):
  filtresiz 1255 islem, isabet %60.3, islem basi +0.21R, toplam +260R, max dusus 36R
  filtreli   705 islem, isabet %71.1, islem basi +0.37R, toplam +257R, max dusus 27R (2024 oncesi %74, sonrasi %71)
Filtre motorun durumunu degistirmez (elenen sinyal de motorda o coini mesgul tutar) - testle ayni.
"""
from __future__ import annotations

import pandas as pd

import kirilim_v6 as k

MIN_KUME = 5
KALITE = ("B",)
PARAMS = {"yon": "Sadece Short", "tp1_pct": 100.0}


def motor_verisi(g: pd.DataFrame) -> pd.DataFrame:
    """short_retest formatindaki (open_time indeksli o,h,l,c,v) veriyi motor formatina cevir."""
    df = g.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}).reset_index()
    df = df.rename(columns={df.columns[0]: "open_time"})
    df["close_time"] = df["open_time"] + pd.Timedelta(hours=4) - pd.Timedelta(milliseconds=1)
    return df[["open_time", "close_time", "open", "high", "low", "close", "volume"]]


def tara(veri: dict, btc_d: pd.DataFrame, btc_4h: pd.DataFrame, genislik: pd.Series) -> dict:
    """veri: {sym: motor formatinda 4s df}. Donus: {sym: Sonuc}."""
    out = {}
    for sym, df in veri.items():
        try:
            out[sym] = k.simule_et(sym, df, None, btc_d, btc_4h, params=PARAMS, genislik=genislik)
        except Exception as exc:
            print(f"v66s {sym}: {exc}", flush=True)
    return out


def kume_sayaci(sonuclar: dict) -> dict:
    """Her 4s mum (giris zamani) icin kac coinde short GIRIS var."""
    say = {}
    for r in sonuclar.values():
        for o in r.olaylar:
            if o.tur == "GIRIS" and o.yon == -1:
                say[o.zaman] = say.get(o.zaman, 0) + 1
    return say


def gecer(o: k.Olay, kume: dict) -> bool:
    return o.tur == "GIRIS" and o.yon == -1 and kume.get(o.zaman, 0) >= MIN_KUME and o.veri.get("kalite") in KALITE


def tp1_r(giris: float, fiyat: float, risk: float) -> float:
    kom = k.PARAMS["komisyon_pct"] / 100.0
    return (giris - fiyat) / risk - 2 * kom * giris / risk
