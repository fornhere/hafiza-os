# 2026.09.19.1 — Taşınabilir motor ve yerel ajan adaptörleri

- Linux/macOS/Windows için standart kütüphaneli süreç kilidi; UTF-8, satır sonu ve
  kaynak yolu tutarlılığı. [Üç gerçek OS koşumunda 360 testlik paket başarılı](https://github.com/fornhere/hafiza-os/actions/runs/35442868256).
- Claude Code ve Antigravity için özgün transcript'e bağlı sessiz aday kuyruğu;
  kaynak hash'i, ilk beş mesaj, gizlilik ve ayrı anlamlılık incelemesi korunur.
- Ortak incelenmiş makbuz erişimi; Codex mevcut kayıt/konsolidasyon yolunu korur.
- `ajan_kur.py --with-hooks`: yedekli, tekrar çalıştırılabilir kurulum/kaldırma,
  yalnız sahip olunan eski hook'ların geçişi; ilgisiz ayarlar ve trust korunur.
- Linux/agy ile gerçek kayıt → model incelemesi → farklı oturumda hatırlama geçti.
  Claude canlı model testi hesap erişimindeki 403 nedeniyle açık. Windows/macOS
  uygulama oturumları ayrıca doğrulanmış değildir.
- Reviewer ayrıca yapılandırılır; otomatik zamanlayıcı, tam sohbet senkronu veya
  yeni adaptörlerde otomatik kanonik terfi kurulmaz. [Kurulum](ENTEGRASYONLAR.md).

Aşağıdaki aynı günün ilk köprü sürümündeki Windows/adaptör sınırları bu paketle
kısmen aşılmıştır; güncel destek matrisi yukarıdaki rehberdedir.

# 19 Eylül 2026 — Ajanlar için ortak kasa köprüsü

- Claude Code, Codex ve Antigravity global yönergelerini aynı kasaya yönlendiren
  standart kütüphaneli `ajan_kur.py`; diğer ajanlar için açık Markdown aktarımı.
- Varsayılan dry-run, yalnız değişimde yedek, yönetilen blok, kaldırma ve
  yazmadan önce bozuk işaret/sembolik bağlantı kontrolleri.
- Hook, güven ayarı, otomasyon veya transcript aktarımı kurulmaz. Mevcut
  Claude/Codex kurulumları ayrı kalır; Antigravity/generic transcript adaptörü yoktur.
- Yerel Windows bloğu yalnız manuel, bütçeli dosya okuması sunar; kaynak
  doğrulamalı CLI erişimi iddiası veya çalışmayan Python erişim komutu üretmez.
  Erişim/konsolidasyon araçları POSIX `fcntl` nedeniyle yerel Windows'ta
  desteklenmez. Tam motor ve hook'lar WSL içinde, WSL'den görünen yollarla
  ayrı kurulum gerektirir. macOS canlı denenmedi; Windows canlı kabulü yoktur.
- README yenilendi; platform sınırları ve canlı smoke adımları
  [entegrasyon rehberinde](ENTEGRASYONLAR.md). Yeni köprünün kabulü ayrıca doğrulanır.

# 18 Eylül 2026 — Jev danışmanı ve kaynaklı konu dosyaları

- [Jev](JEV.md): varsayılan kapalı, gölge/açık modlu isteğe bağlı erişim
  sıralaması; kaynak desteği, tekrar ve çelişki için salt-okunur inceleme.
  Model sonucu öneridir; kanonik yazım veya kullanıcı onayı üretmez.
- [Konu sentezi](KONU-SENTEZI.md): incelenmiş bilgi kartlarını kaynak ve kapsamla
  birleştiren, Obsidian'a aktarılabilen türetilmiş konu dosyaları. Kaynak sürümü
  yeniden denetlenir; dışa aktarım anlık görüntüdür.
- Bu özellikler otomatik bilgi doğruluğu, bütün doğal dil sorularında başarı
  veya ölçülmüş zaman kazancı iddiası değildir.

# 2026.09.18 — Hafızanın görünür etkisi

Kaynaklı kullanım açıklaması ve geri okumayla doğrulanan değişiklik bildirimi eklendi. Bağlama gelme, ajan kullanım beyanı ve gerçek yazım ayrı tutulur. Yeni kapanış zorlaması yok.

# 2026.09.18 — Alanlar arası gerekçeli uyarlama

Sunum ve site tercihleri kaynak özellik üzerinden öneri olarak aktarılır; yeni alan onayı uydurulmaz.

# 2026.09.18 — Geri bildirimden kaynaklı bilgi ağına

- Kaynak alıntısı, sürüm, kapsam ve inceleme içeren Markdown bilgi notları.
- Gerçek ilişkiler ve dosya sürümüne bağlı örnekler; görsel onay çıkarımı yok.
- Görev paketinde alan/proje sınırlarıyla erişim; sunum tercihi siteye genellenmez.
- Makbuzdan ayrı bilgi incelemesi kuyruğu; değişen kaynak yeniden beklemeye döner.
- Mevcut konsolidasyon rolü ve yerel Git kaydıyla bütünleşme; yeni servis yok.
- Ayrıntılar: [Bilgi ağı](BILGI-AGI.md).

# 2026.09.18 — Kaynaklı çıktı ve karar takibi

- Devam kapsülüne dosya ve kontrol sürümüne bağlı çıktı eklendi.
- Eski/güncel karar ayrımı, çelişki ve varlık değişimi denetlenir.
- Doğrulanmış çıktılardan sözcük temelli yeniden kullanım önerisi alınır.
- Kaynaklı soru ve deney için yerel pilot doğrulayıcısı eklendi.
- Ek uzak servis veya zamanlayıcı yok; eski çıktılar otomatik onaylanmaz.

# 2026.09.16 — Kısa proje özeti ve seçici tarihçe

- Kaynak sürümü doğrulanmış mevcut kayıtlar, sonraki iş ve ilgili yöntem
  görev paketinin öncelikli bölümüne alınır; ayrı bir özet veri tabanı oluşmaz.
- `--history auto` varsayılanında yeterli güncel bağlam varsa sırf “devam”
  denildiği için tarihçe eklenmez. Açık geçmiş isteği veya devam görevinde
  konu eksikliği geçmişe döner. `always` ve `never` elle seçilebilir.
- Çok sözcüklü geçmiş ifadelerinde sözcüklerin yan yana gelmesi aranır.
- Çalışma kaynağı, ihtiyaç olduğunda açılacak başvuru olarak sunulur.
  Belirsizlik, değişmiş kaynak ve gerçek işlem öncesi doğrulama korunur.
- Yeni iş kayıtları kaynak içerik hash'i taşır; kaynak değişince eski iş
  güncel görünümden çıkar. Eski hash'siz iş, yeniden incelenecek ipucudur;
  güncel özeti veya geçmişi atlama kararını desteklemez.

Hash içerik bütünlüğüdür; anlamsal doğruluk veya yeni kullanıcı kabulü
anlamına gelmez. Konu yeterliliği kelime temelli ve temkinlidir; her görevde
bağlamın küçüleceği veya daha az araç çağrısı yapılacağı garantisi yoktur.

---

# 2026.09.16 — Sentetik çok oturumlu denetim ek düzeltmeleri

- Görev paketinde kapsam, geçerlilik ve kaynak denetimi sıralamadan önce
  uygulanır. Başka projedeki veya değişmiş kaynaklı kayıtlar ilgili kayıtların
  kelime sıklığı puanını etkileyemez.
- Prosedürel ders kaynağı tam içerik hash'iyle sürümlenir. Kaynakta eski
  alıntı kalsa bile sonradan yapılan değişiklik yeniden inceleme gerektirir.
- Kaynak sürümü bulunmayan eski dersler otomatik sabitlenmez. İnceleyen
  kaynağı ve yöntemi okuyup mevcut expected_version ile is_ve_ders.py lesson
  üzerinden yeniden kaydeder; kullanıcı kabulü/statü kendiliğinden yükselmez.

Bu değişiklikler izole kurmaca kasalarda doğrulanan hataları giderir;
kişisel verim kazancı veya tüm Türkçe ifadelerin çözüldüğü iddiası değildir.

---

# 2026.09.16 — Kaynak doğrulaması ve seçici görev bağlamı

Bu güncelleme, mevcut dosya temelli hafızanın kayıt ve geri çağırma
kontrollerini genişletir. Amaç, güncel kaynağı ilgili göreve daha küçük bir
paketle taşımak ve inceleme gerektiren bilgiyi görünür tutmaktır.

- **Özgün beyana bağlı aday:** otomatik semantik adaylar tamamlanan konuşma
  bölümündeki kullanıcı mesajının satırı, hash'i ve birebir alıntısıyla
  eşleştirilir. İnceleme onay kutuları tek başına kaynak kanıtı sayılmaz.
- **Sürümlü kaynak:** yeni kayıtta kaynak içerik hash'i tutulur. Kaynağı
  değişen bilgi, yeniden incelenmiş bir bağ olmadan güncel bağlama alınmaz.
  Eski kayıtlar kanonik metni değiştirmeyen `bind-source` aracıyla incelenebilir.
- **Mahremiyet kapsamı:** açık oturum dışlama isteği ile kapsamı belirsiz
  “bunu kaydetme” ifadeleri ayrılır; ikincisi otomatik kaydı incelemeye bırakır.
- **İlgili ve bütçeli erişim:** yerel sıralama sorgu kapsamını ve kelimelerin
  kayıtlar arasındaki ayırt ediciliğini kullanır. Sınırlı Türkçe ek zincirleri
  ve eş anlam grupları desteklenir. Proje, onaylı varlık ve yöntemler genel
  geçmişten önce bütçeye alınır; proje derslerinin kapsamı denetlenir.
- **Tekrar kontrolü:** aynı görev paketi ardışık ikinci gelişinde bir kez
  atlanabilir; sonraki istemde yenilenir. Kaynak sürümü değişince yeniden
  gönderilir. `SessionStart` olayı tekrar önbelleğini sıfırlar.
- **Ölçülebilir bağlam:** paket ve hook çıktılarının karakter sayıları görünürdür.
  Ölçülmeyen token sayısı `null` kalır; karakter sayısı token veya ücret değildir.
  `latest-session` yalnız en yeni tarihli oturum bölümünü bütçeli döndürür.
- **Kaynaklı doğal sonuç kaydı:** olağan kabul/ret/vazgeçme geri bildirimi
  tamamlanmış özgün kullanıcı mesajına bağlanır. İlk beş mesaj ve kaydetmeme
  kapıları korunur; kayıt sürümlüdür, aynı kanıt tekrar satır üretmez. Doğal
  gözlemler deney koşullarından ayrıdır; bilinmeyen insan ölçümleri null kalır.
- **Açılışta kaynak önceliği:** tarihli son oturum özeti geçmiş bilgi olarak
  okunur; güncel işletim iddiaları canlı sağlık, iş durumu ve yeni makbuzlarla
  denetlenir. Tarihsel notlar sessizce yeniden tarihlenmez.
- **Kaynak biçimi desteği:** `exec` kaynakları açıkça kullanıcı görevine aitse
  kabul edilir; bilinen alt ajan kaynakları ana konuşma olarak işlenmez.

[Geçiş adımları](CODEX.md#16-eylül-kaynak-ve-kapsam-geçişi) kayıt üreticisi,
eski kaynak bağları ve kişisel ders kapsamları için ayrıca uygulanmalıdır.
Dosyaları güncellemek zamanlayıcının canlı çalıştığını kanıtlamaz. Yerel
hash kontrolleri imzalı kimlik doğrulaması değildir; alıntının önerilen
tercihi gerçekten destekleyip desteklemediğini inceleyen değerlendirir.
Kelime benzerliği uyarısı genel anlamsal tekrar/çelişki çözümü değildir.

Bu notlar mekanizmaları açıklar. Testlerin geçmesi gerçek görevlerde daha
iyi çıktı, daha düşük toplam maliyet veya zaman tasarrufu sağlandığını
kanıtlamaz. Bu sonuçlar [ayrı görev karşılaştırmalarıyla](FAYDA-OLCUMU.md)
ölçülür; burada tamamlanmış bir B/C deneyi veya verim artışı iddiası yoktur.

---

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


## 18 Eylül 2026 — Bağlam kimliği ve erişim görünürlüğü

- Skill dosyasının yolu artık hedef proje seçimini, yöntem eşlemesini veya
  geçmiş arama niyetini değiştirmiyor; sıradan yollar ve gerçek proje adları korunuyor.
- Katalog bütünlüğü ve kaynak incelemesi nedeniyle erişime giremeyen etkin
  kayıtlar sağlık çıktısında ayrıldı. Gizlilik ve geçerlilik dışlamaları normaldir.
- Codex sessiz kayıt politikası, Claude Code kapanış şablonundan açıkça ayrıldı.
- İş defteri yokken mevcut iş görünümünü koruyan davranış regresyon testine bağlandı.

Bu kontroller model cevabının kalitesi veya kullanıcı zaman kazancının kanıtı değildir.


## 18 Eylül 2026 — Düşük maliyetli devam görünümü

- Devam isteklerinde üç görev ve beş kaynaklı bilgi kartına kadar yerel kapsül.
- Yeni `resume` komutu ve karakter bütçesi; kaynak değişiminde taze doğrulama.
- Engelli/çoklu/konu dışı görev için otomatik sonraki adım önerilmez.
- Kaynak sürümü incelenmemiş eski kayıtlar yeni bilgi kartı sayılmaz.
- Ek API, ayrı önbellek veya arka plan otomasyonu olmadan mevcut hook'a bağlı.
