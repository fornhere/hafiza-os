# 15 Eylül 2026 — Sessiz kayıt ve görevle ilişkili dersler

- Codex kayıtları cevap sonunu bölmeden arka plan konsolidasyonunda hazırlanır.
- Anlamlı hafıza değişiklikleri sağlık kontrolü sonunda yerel Git'e kaydedilir.
- Dersler kaynak kanıtı ve yapılandırılabilir tetikleyicilerle ilgili göreve taşınır.
- Yöntemin uygulanması ile gerçek sonuç doğrulaması ayrı izlenir.
- Önceden hazırlanmış Git değişiklikleri korunur; saat değişimi tek başına commit oluşturmaz.

Kurulum ve geçiş ayrıntıları: [CODEX.md](CODEX.md). Sessiz kayıt için zamanlanmış
konsolidasyon etkin olmalıdır; kurucu tek başına otomasyon oluşturmaz.

# Güncelleme notları

## 12 Eylül 2026 — Süreklilik ve görünür hafıza

Bu paket, dosya temelli hafıza yapısını yeni bağlantılar ve bakım araçlarıyla
genişletiyor. Mevcut Claude Code akışı korunuyor; Codex desteği ayrıca kurulabiliyor.

### Eklenenler

- **Codex bağlantısı:** açılış bağlamı, gerçek kullanıcı mesajı sayacı,
  altıncı mesajdan itibaren anlamlı oturum makbuzu ve kesintide takip kaydı.
- **Kaynaklı konsolidasyon:** kısa kullanıcı beyanından aday üretme, ayrı
  inceleme aşaması, kalıcı kataloğa terfi ve Mem0'dan geri okuyarak doğrulama.
- **Sürümlü iş defteri:** kimlik, durum, sonraki adım ve son teyit tarihi.
  Kapanan veya teyitsiz işler güncel açılış gündemine alınmaz; geçmiş korunur.
- **Prosedürel ders defteri:** yöntem dosyası ve test makbuzuyla doğrulanan
  dersler. Dosya değiştiğinde yeniden doğrulama ihtiyacı görünür olur.
- **Sağlık görünümü:** son senkron, bekleyen adaylar, eksik işaretli makbuzlar,
  arama ve bağlam testleri tek Obsidian notunda toplanır.

### İyileştirmeler

- Mem0 aramasında yeniden sıralama; bulunan kaydın bütçeli bağlama ulaşmasını
  ayrı ölçen değerlendirme. Süre dışı, özel ve etkin olmayan kayıtların elenmesi.
- Yerel yazıcı kilidi, eşzamanlı sürüm kontrolü ve yarım kalan senkronu
  kayıt kimliğinden devam ettirme.
- Güncellenen gerçeklerin tarihçesini ve erişim durumunu birlikte koruma.
- Otomasyon ve sentetik devam mesajlarının kullanıcı mesajı eşiğinden ayrılması.

### Kurulum ve kapsam

[Codex kurulum rehberi](CODEX.md), mevcut ayarları koruyarak bağlantıları
ekleme ve isteğe bağlı düzenli inceleme adımlarını anlatır. Mem0 isteğe bağlıdır;
her kullanıcı kendi kimliğini ve anahtarını tanımlar. Saatlik inceleme,
zamanlayıcıda ayrıca etkinleştirilir; yalnız dosyaları indirmek bir otomasyon başlatmaz.

Paketin yerel testleri 39 senaryoyu kapsar. Kendi ortamında yeni oturum açılışı,
altıncı gerçek mesajda kayıt ve Mem0 geri çağırma denemesini de yap. Otomasyonun
çalışması uygulamanın ve bilgisayarın kullanılabilirliğine bağlıdır.

## 4 Eylül 2026 — Kaynaklı hafıza kapısı

Kanonik kayıt kataloğu, aday kuyruğu, kaynak ve kimlik metadata'sı, bütçeli
erişim paketleri ve Mem0 senkron denetimi eklendi. Bu temel, yeni konsolidasyon
ve iş takibi araçlarının üzerine kurulduğu yapıyı oluşturuyor.
