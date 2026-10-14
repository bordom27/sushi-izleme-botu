# Kirilim69 PRO v6 — Telegram izleme botu

TradingView'daki **Kirilim69 PRO** göstergesinin aynısını 46 kripto parada (Binance, 4 saatlik) izler ve sinyalleri Telegram'a gönderir. **Gerçek işlem açmaz.**

## Dosyalar
| Dosya | Görev |
|---|---|
| `kirilim_v6.py` | Göstergenin karar mantığı (elekler, giriş, stop/TP, yönetim). Bot ve backtest bunu kullanır. |
| `genel_izleme_bulut.py` | Bot. Saatte bir çalışır, yeni kapanan mumlardaki olayları gönderir, akşam 21:00'de özet atar. |
| `v6_backtest.py` | Aylık doğrulama: aynı kodla geçmiş işlemleri hesaplar, Telegram'a rapor atar. |
| `coin_listesi.py` | İzlenen coinler. Eklemek/çıkarmak için yalnızca bu listeyi düzenle. |
| `veri.py` | Binance mum verisi (önbellekli). |
| `izleme_state.json` | Botun hafızası (bot kendisi günceller, elle düzenleme). |

## Telegram mesajları
- 🟢/🔴 **GİRİŞ**: giriş, stop, TP1 (%70 kapat), TP2 (kalan %30), önerilen pozisyon büyüklüğü (%1 risk)
- 🟠 **TP1**: %70 kapat, stop giriş + 0.1R
- 🔧 **STOP GÜNCELLE**: TP1 sonrası iz süren stop belirgin ilerlediğinde
- ✅/❌ **KAPANDI**: TP2, stop, zaman stopu — sonuç R (komisyon dahil)
- 🟡 **KIRILIM** / ⚪ **iptal**: retest bekleyen kırılım ön uyarısı (`BILDIR_KIRILIM` ile kapatılabilir)
- 📊 **Günlük özet** (21:00): açık pozisyonlar, BTC durumu, son 30 gün

## Doğrulama (Ekim 2026)
Python sürümü TradingView göstergesiyle karşılaştırıldı (46 coin, Temmuz 2025 sonrası, komisyon dahil):
TradingView 179 işlem / %63.7 / +18.26R — bot 179 işlem / %63.7 / +18.24R.

## Elle çalıştırma
GitHub → Actions → *Genel Izleme Botu* → *Run workflow* (`test_mesaji` = true yalnızca Telegram bağlantısını dener).
