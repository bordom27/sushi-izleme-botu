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

## v6.1 ayarları (Ekim 2026 araştırması)
GitHub Actions'ta 59 tekil ayar, 12 kombinasyon, 4 zaman dilimi ve listede olmayan 70 coin test edildi (eğitim: Tem 2024–Haz 2025, test: Tem 2025 sonrası).
- **Giriş: kırılım mumunun kapanışında** (retest beklemek yerine). 46 coin: eğitim +31.6R → +45.6R, test +18.2R → +35.2R. 116 coin: +49.9R → +67.3R / +34.3R → +48.6R.
- **4 saatlik** en iyisi (6s zayıf; 8s ve 12s test döneminde zararda).
- Pozisyon tavanı (aynı yönde en fazla 5–8) kazancı ciddi düşürdüğü için uygulanmadı.
- 46 coinde maksimum düşüş ~13R → işlem başı risk **%0.5** önerilir (~%6.5 hesap düşüşü).
- Long tarafı son dönemde zayıf, short tarafı güçlü; bot ikisini de bildirir.

## Kalabalık uyarısı (Ekim 2026 araştırması)
626 işlemde girişteki hacim ivmesi, taker alım/satım oranı, funding, open interest değişimi ve long/short oranları incelendi (Binance arşivi). Tutarlı çıkan tek etken: **büyük oyuncuların (top trader) pozisyon oranı** girişin yönüne yığılmışsa (L/S > 1.69, short'ta S/L > 1.69) işlem başı getiri dört grubun dördünde düşük (test döneminde negatif). Filtre olarak eklemek eğitim döneminde kazancı düşürdüğü için **filtre değil, risk uyarısı**: giriş mesajında "riski yarıya indir" olarak gösterilir. Veri TradingView'da olmadığı için sadece botta.

## v6.2: Başarısız kırılımda erken çıkış (Ekim 2026)
TP1 alınmadan, girişten sonraki ilk 3 mumda 4s kapanış kırılan seviyenin 0.3 ATR gerisine dönerse stop beklenmeden kapanışta çıkılır.
116 coin: eğitim +64.5R → +63.8R, test +42.0R → +52.1R; maksimum düşüş 5.1R → 3.9R ve 20.1R → 14.5R. İsabet ~4–5 puan düşer (küçük kayıplar).
Ayrıca test edilip **eklenmeyenler**: limit emirle giriş, 1 saatlikte giriş, EMA21 geri çekilme sinyali, kovalama filtreleri, klasik formasyonlar.

## Elle çalıştırma
GitHub → Actions → *Genel Izleme Botu* → *Run workflow* (`test_mesaji` = true yalnızca Telegram bağlantısını dener).
