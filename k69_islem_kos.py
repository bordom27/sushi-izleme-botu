"""
K69 SHORT otomatik islem botu - kendi bilgisayarinda / VPS'te calisir (GitHub'dan Binance'e emir gonderilemiyor:
GitHub sunuculari ABD'de, Binance ABD IP'lerini engelliyor).

Her saatin 7. dakikasinda: tum likit vadeli coinleri tarar (short_retest_sistemi, filtre dahil), yeni K69 SHORT
sinyalinde Binance'te short + stop + hedef emri acar, acik pozisyonlari takip eder (binance_islem.py).
Sinyal mesajlarini GitHub'daki bot zaten gonderir; bu program sadece islem mesajlari gonderir.

Ayarlar: ayni klasorde k69_islem.env dosyasi (ornek: k69_islem.env.ornek):
  BINANCE_API_KEY=...       BINANCE_API_SECRET=...       BINANCE_ORTAM=demo   (gercek hesap icin: gercek)
  TELEGRAM_BOT_TOKEN=...    TELEGRAM_CHAT_ID=...
Calistirma:  python k69_islem_kos.py          (surekli; her saat calisir)
             python k69_islem_kos.py --tek    (bir kez; cron / Gorev Zamanlayici ile)
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

KLASOR = os.path.dirname(os.path.abspath(__file__))
os.chdir(KLASOR)


def env_yukle(yol="k69_islem.env"):
    if not os.path.exists(yol):
        return
    for satir in open(yol, encoding="utf-8"):
        satir = satir.strip()
        if satir and not satir.startswith("#") and "=" in satir:
            k, v = satir.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


env_yukle()
import genel_izleme_bulut as G   # noqa: E402  (env yuklendikten sonra)
import binance_islem as BI       # noqa: E402

DURUM = "k69_islem_state.json"
TR = timezone(timedelta(hours=3))


def durum_oku() -> dict:
    try:
        with open(DURUM, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def durum_yaz(s: dict):
    gecici = DURUM + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2, default=str)
    os.replace(gecici, DURUM)


def tur():
    s = durum_oku()
    s["islem_aktif"] = True
    cfg = dict(G.CONFIG)
    ilk = not s.get("short_son_bar")
    G.short_retest_sistemi(s, cfg)          # sinyal mesajlari GitHub botundan gelir; burada sadece kuyruk dolar
    BI.calistir(s, G.send_telegram)
    if ilk:
        G.send_telegram(f"🤖 K69 işlem botu başladı ({'GERÇEK HESAP' if os.environ.get('BINANCE_ORTAM') == 'gercek' else 'DEMO'}). "
                        f"Bu turdan sonraki yeni K69 SHORT sinyallerinde otomatik short açacak.")
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    if datetime.now(TR).hour >= 21 and s.get("islem_ozet_gunu") != bugun:
        oz = BI.ozet(s)
        if oz:
            G.send_telegram(oz)
        s["islem_ozet_gunu"] = bugun
    durum_yaz(s)


def main():
    if not os.environ.get("BINANCE_API_KEY"):
        print("k69_islem.env dosyasinda BINANCE_API_KEY yok. Ornek: k69_islem.env.ornek")
        sys.exit(1)
    tek = "--tek" in sys.argv
    while True:
        print(f"--- tur {datetime.now(TR):%d.%m %H:%M}", flush=True)
        try:
            tur()
        except Exception:
            traceback.print_exc()
        if tek:
            break
        simdi = time.time()
        sonraki = simdi // 3600 * 3600 + 7 * 60
        if sonraki <= simdi:
            sonraki += 3600
        time.sleep(sonraki - simdi)


if __name__ == "__main__":
    main()
