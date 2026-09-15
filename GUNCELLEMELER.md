# 2026.09.15 — Görev bağlamı ve sessiz hafıza bakımı

Bu sürüm, dosya temelli hafızayı günlük görevlerle daha yakından buluşturuyor:
ilgili proje, güncel kaynak ve çalışma yöntemini birlikte getiriyor; tamamlanan
konuşma bölümlerini arka planda işliyor. Mevcut Obsidian/Git temeli ve isteğe
bağlı Mem0 katmanı korunuyor.

## Bu sürümde öne çıkanlar

- **Göreve uygun bağlam:** yerel paket; proje, kaynaklı açık iş, onaylı varlık
  ve ilgili yöntemi bir araya getirir. `context` varsayılan olarak yereldir;
  Mem0 sıralaması için `--remote` açıkça seçilir.
- **Doğal Türkçe ifadeler:** sınırlı ek, özel isim kesmesi ve yakın yazım
  desteği görev eşleşmesini genişletir. Açık proje adı çalışma klasöründen
  önce gelir; birden fazla proje veya belirsiz geçmiş isteği netleştirme bekler.
- **Sessiz, kaynak sürümüne bağlı kayıt:** altıncı gerçek kullanıcı mesajından
  itibaren anlamlı sonuçlar arka plan incelemesine alınır. Açık konuşmanın
  tamamlanan bölümü sınır ve hash ile ayrılır; aktif devam özetlenmez. Alt ajan
  tarafından devralınmış geçmiş ana oturum sayılmaz; mevcut makbuzlar karşılaştırılır.
- **Güncel kaynak ve kullanım kontrolü:** onaylı varlığın dosyası, hash'i ve
  kaynak kanıtı denetlenir. Belirli eski varlık iddiaları tarihçe silinmeden
  güncel bağlamdan ayrılır. Hazırlanan girdi, gözlenen araç çağrısı, teknik
  sonuç ve kullanıcı kabulü ayrı tutulur.
- **İzlenebilir bakım:** zamanlanmış tarama yaşı manuel kontrolden ayrı izlenir;
  eksik, eski ve başarısız kontroller görünür olur. Anlamlı hafıza veri
  değişiklikleri yerel Git'e alınır; kişisel kasa otomatik olarak GitHub'a gönderilmez.
- **Doğrulanmış yayın:** yerel/kamu kod eşliği, tam commit arşivindeki testler
  ve yayın içerik taraması kontrol edilir; push sonrasında uzak commit geri
  okunur. GitHub CI aynı commit kontrollerini çalıştırır.

## Güncelleme ve kapsam

Mevcut kurulumda [Codex geçiş rehberini](CODEX.md#v2-geçişi-ve-yerel-görev-paketleri)
izle; kişisel kimlik, dışlama ve proje ayarlarını koru. Konsolidasyon yönergesini
V2 tamamlanan bölüm akışına geçir. Sessiz kayıt için zamanlayıcı ayrıca etkin
olmalıdır; dosyaları güncellemek tek başına otomasyon kurmaz. Otomasyon uygulama
ve bilgisayarın kullanılabilirliğine bağlıdır. İlk beş mesaj, basit sorular ve
kaydetmeme tercihleri korunur.

Araç girdi kontrolü tanımlanmış üretim akışında uygulanır; tüm araç yollarını
zorunlu olarak engelleyen genel bir hook değildir. Görünmeyen veya sarmalanmış
çağrılar `unknown` kalabilir. Türkçe eşleme genel bir dil anlama modeli değildir.
Birim testleri, gerçek çalışma kalitesini veya zaman tasarrufunu kanıtlamaz;
[fayda ölçümü](FAYDA-OLCUMU.md) bunları ayrı izlemek için eklendi.

Ayrıntılar: [kullanım doğrulaması](KULLANIM-DOGRULAMA.md),
[yayınlama](YAYINLAMA.md), [konsolidasyon yönergesi](komuta/hafıza-konsolidasyonu.md).

---

# 15 Eylül 2026 — Doğal ifadeler ve tamamlanan bölümler

- Türkçe ekler, özel isim kesmeleri ve uzun kelimelerde sınırlı yazım
  varyasyonları görev seçiminde desteklenir. Belirsiz geçmiş isteği açık kalır.
- Açık konuşmaların tamamlanan bölümleri kaynak sınırı ve hash ile işlenir;
  aktif devam kayıt dışındadır. Sonuç geldiğinde yeni sürüm yakalanır.
- Gerçek araç kayıtları için kullanım denetimi eklendi; görünmeyen/sarmalanmış
  çağrılar doğrulanmış sayılmaz. Girdi, araç sonucu ve kullanıcı kabulü ayrıdır.
- Adlandırılmış projede kapak üretirken proje kökü ile kimlik referansı birlikte getirilir.
- Kaynak sürümüyle değiştirilen belirli varlık iddiaları eski semantik sonuçlardan ayrılır; tarihçe silinmez.
- Üretim argümanları doğrulama kapısından çıktıktan sonra değiştirilmeden araca verilebilir.
- Zamanlanmış tarama yaşı manuel kontrolden ayrı izlenebilir; rutin bakım
  başına kaynak sınırı ve tekrarsız bildirim yönergesi eklendi.

# 15 Eylül 2026 — Kaynak sürümü, görev bağlamı ve doğrulama

- Tamamlanan oturumların mesajları ve son sonuçları sürümlenir; kayıt ve
  inceleme işareti aynı kaynak görüntüsüne bağlanır. İlk beş mesaj kapısı korunur.
- Yerel görev paketleri ilgili proje, kaynaklı açık iş, onaylı varlık ve
  uygulanabilir yöntemi bir araya getirir. Mem0 isteğe bağlı sıralama katmanıdır.
- Sağlık durumu tarama ve uzak denetim yaşını izler; eksik, eski ve başarısız
  denetim ayrı görünür. Sessiz arka plan akışı sürer.
- Araç girdisi, gözlenen çağrı ve kullanıcı kabulü ayrı doğrulanır.
- Yayın aracı yerel/şablon eşleşmesini, commit içeriğini ve testleri kontrol
  ederek GitHub uzak commit'ini doğrular. CI aynı commit testlerini çalıştırır.
- Gerçek görev deneyleri için eksik ölçümleri ve başarısız işleri koruyan
  karşılaştırma aracı eklendi; henüz ölçülmüş verim artışı iddiası yoktur.

Geçiş: [CODEX.md](CODEX.md), [kullanım kontrolü](KULLANIM-DOGRULAMA.md),
[yayınlama](YAYINLAMA.md), [fayda ölçümü](FAYDA-OLCUMU.md).

# 15 Eylül 2026 — Oturum kimliği ve konsolidasyon

- Oturum taramasında dosyanın ilk kimlik kaydı esas alınır; alt ajanların
  devraldığı konuşma geçmişi ana oturum olarak işlenmez.
- İnceleme işaretleri oturum kimliğiyle birlikte eşleştirilir; aynı mesajları
  içeren farklı oturumlar bağımsız değerlendirilir.
- Ana oturum/alt ajan ayrımı ve oturumlar arası işaret yalıtımı test edildi;
  şablonun 44 testi geçti.

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
