"""K69 islem botu baglanti testi: emir ACMAZ. Anahtar, IP kilidi, Futures izni, bakiye ve Telegram'i kontrol eder."""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import k69_islem_kos as K   # env dosyasini yukler  # noqa: E402
import binance_islem as BI  # noqa: E402

key, sec = os.environ.get("BINANCE_API_KEY", ""), os.environ.get("BINANCE_API_SECRET", "")
ortam = os.environ.get("BINANCE_ORTAM", "demo")
if not key or not sec:
    print("HATA: k69_islem.env icinde BINANCE_API_KEY / BINANCE_API_SECRET bos.")
    sys.exit(1)
try:
    c = BI.Istemci(key, sec, "gercek" if ortam == "gercek" else "demo")
    print(f"Binance ({ortam}) baglandi: {c.base}")
    hedge = c.hedge()
    toplam, serbest = c.bakiye()
    poz = c.pozisyonlar()
except Exception as exc:
    print(f"HATA: {exc}")
    m = str(exc)
    if "-2015" in m or "-2014" in m:
        print("Anahtar, IP ya da izin hatasi: API anahtarindaki IP bu bilgisayarin IPv4'u mu, Futures izni acik mi kontrol et.")
    sys.exit(1)
print(f"Vadeli bakiye: {toplam:.2f} USDT (serbest {serbest:.2f}) | pozisyon modu: {'hedge' if hedge else 'tek yonlu'} | "
      f"acik pozisyon: {len(poz)}")
print(f"Ayarlar: islem basi risk %{BI.AYAR['risk'] * 100:.2f} (~{toplam * BI.AYAR['risk']:.2f} USDT), "
      f"en fazla {BI.AYAR['maks_acik']} acik short, {BI.AYAR['kaldirac']}x izole")
if toplam < 20:
    print("UYARI: vadeli bakiye cok dusuk; cogu sinyalde en kucuk emir tutarina ulasilamaz.")
if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
    K.G.send_telegram(f"✅ K69 işlem botu bağlantı testi başarılı ({ortam}). Vadeli bakiye {toplam:.2f} USDT.")
    print("Telegram test mesaji gonderildi.")
else:
    print("UYARI: Telegram bilgileri bos; islem bildirimleri gelmez.")
print("TEST BASARILI")
