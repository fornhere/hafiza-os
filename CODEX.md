# Codex kaynak ve kayıt rehberi

Kurulum, hook olayları ve eski kurulum geçişi: [[ENTEGRASYONLAR]].
Veri akışı ve komut girişleri: [[SISTEM]]. Düzenleme: 2026-09-24.
Kayıt uygunluğu, inceleme ve zamanlanmış kaynak taraması:
[[komuta/hafıza-konsolidasyonu]]. Bu belge ayrıntılı Codex kaynak alanlarını
ve geçiş sözleşmelerini tutar; kurulum veya saatlik görev oluşturmaz.

## İşler, dersler ve sağlık

İş/ders sürümleri, test kanıtı ve sağlık komutunun Git yan etkisi için
[[komuta/hafıza-konsolidasyonu]]; komut ve ölçüm tablosu için [[SISTEM]].

## V2 geçişi ve yerel görev paketleri

Kurulu kasaya güncel `araclar/` dosyalarını taşı. Kişisel kimlik ve dışlama
ayarlarını koru; yerel/şablon farklarını publication-manifest.json ile incele.
Saatlik konsolidasyon yönergesini `komuta/hafıza-konsolidasyonu.md` V2 biçimine
geçir: eski checkpoint dosyalarını yeniden kullanma, mevcut makbuzları
karşılaştırarak yalnız yeni anlamlı sonuçları kaydet. Aktif/tanınmayan kaynaklar
bekler; eski işaretler tamamlanma kanıtı yerine geçmez. Stop zorlamasını açma.

`python3 araclar/hafiza.py --vault KASA context "görev sorusu"` yerel çalışır.
Mem0 için açıkça `--remote` ekle. `gorev_baglam.py package` JSON çıktısı proje
manifestiyle eşleşir; yapılandırma örneği ve testler `test_gorev_baglam.py`
içindedir. Onaylı varlık için gerçek dosya, hash, izinli kök ve onay kaynağı
zorunludur. Başkasının kişisel manifestini kopyalama.

Varlık gerektiren araç çağrısından önce [girdi kontrolünü](KULLANIM-DOGRULAMA.md)
uygula. Genel araç engellemesi kurulmaz; ajan bu kontrolü çağırmalıdır.
`konsolidasyon.py --vault KASA health --check` güncel işletim durumuna göre
çıkış kodu verir. Birim testleri gerçek görev kalitesinin yerine geçmez.


### Doğal dil ve bakım güncellemesi

Yeni görev eşlemesi sınırlı Türkçe ekleri ve uzun kelimelerin yakın yazımını
kullanır; genel dil anlama modeli değildir. Açık proje adı cwd'den önce gelir,
iki açık proje netleştirme gerektirir. Geçmişe gönderme yapan belirsiz istekte
kaynak uydurulmaz. Otomasyon yönergesindeki tamamlanan bölüm akışını ve
`--scheduled` bayrağını güncelle. Zamanlayıcı kontrolünü açmak için
`komuta/hafıza-işletim.json` içine `{"require_scheduled_scan": true}` yaz.
Bu ayar tek başına otomasyon kurmaz. Manuel testte `--scheduled` kullanma;
canlı zamanlayıcı doğrulaması ayrı kalmalıdır.


## 16 Eylül kaynak ve kapsam geçişi

Önce kişisel araçları ve ayarları yedekle; güncel araç dosyalarını taşırken
kimlik, dışlama ve proje manifestini koru. Aşağıdaki geçişler birbirinden ayrıdır:

1. **Aday üreticisi:** `semantic_candidates` doluysa `source_snapshot` ve her
   adayda `evidence_source` zorunludur. `evidence_source`, incelenen snapshot'ın
   `session_id`, `path`, `prefix_end_line`, `prefix_hash`, `source_hash`
   değerlerini taşır. Buna özgün JSONL kullanıcı `response_item` satırının
   1 tabanlı `line` numarası, `capture_source.digest(clean_user(mesaj_metni))`
   ile hesaplanan `message_hash` ve adayın `evidence` alanıyla aynı `quote`
   eklenir. `evidence` hem özgün mesajda hem makbuz özetinde birebir bulunmalıdır.
   Aday yoksa `semantic_candidates: []` kullan; kanıt üretmek için metin uydurma.
2. **Eski kaynak bağları:** erişimden düşen kaydı kaynağıyla tek tek karşılaştır.
   Kaynak hâlâ kanonik cümleyi destekliyorsa aşağıdaki araçla incelenen sürümü
   bağla. Desteklemiyorsa topluca hash ekleme; kayıt incelemesini açık tut.
   Kaynak dosyanın varlığı tek başına yeterli değildir. Eski kaydın tam
   cümlesi kaynakta bulunuyorsa bağsız erişim mümkün olabilir; bu, kapsamlı
   bir doğruluk denetimi yerine geçmez.
3. **Ders kapsamı:** projeye özgü derslere `project_id` ve
   `scope: "project:PROJE_KIMLIGI"` ekle. Gerçekten ortak yöntemlerde
   `scope: "global"` kullan. Ne kapsamı ne proje kimliği olan eski dersler
   uyumluluk için global davranır; bunları ayrıca incele. `project_id` varsa
   global etiketi proje sınırını kaldırmaz. Ders güncellemesini `is_ve_ders.py`
   ve `expected_version` ile yap; kapsam düzenlemesi sonucu `verified` yapmaz.
4. **Açılış:** kişisel yönergelerde bütün oturum günlüğünü okuma talebini
   yalnız en yeni bölümle sınırla. `python3 araclar/codex_hafiza.py --vault .
   latest-session` en yeni tarihli bölümü en fazla 2500 karakterle döndürür.
   Diğer açılış dosyaları bu komutla otomatik sınırlandırılmaz.

Kaynak bağlama girdisi `memory_id`, `reviewed_by`, en az 20 karakterlik
`reason`, kaynakta birebir bulunan `evidence` ve
`hafiza.statement_hash(kaynak_metni)` ile hesaplanan `expected_source_hash`
alanlarını taşır. Önce sonucu incele, sonra uygula:

```bash
python3 araclar/hafiza.py --vault . bind-source --input-json kaynak-bagi.json
python3 araclar/hafiza.py --vault . bind-source --input-json kaynak-bagi.json --apply
```

Bağlar `zihin/kaynak-surumleri.jsonl` dosyasına eklenir; kanonik cümle
ve Mem0 içeriği bu komutla değiştirilmez. Kaynak tekrar değişirse yeniden
inceleme gerekir. Farklı `subject_key` altında benzer konu bulunan aday
`needs_semantic_review` dönebilir: bunu doğrulanmış tekrar veya çelişki
sayma. Kaynak incelemesiyle `duplicate`, `reject` veya `defer` kullan;
uyarıyı aşmak için anahtarı ya da kanıtı değiştirme.

`gorev_baglam.py package` çıktısındaki `usage` karakter bütçesini ve seçilen/
dışlanan öğe sayılarını verir. Hook durumundaki `context_usage` gönderilen ve
atlanmış karakterleri biriktirir. `token_count: null` ölçüm yok demektir.
Paket tekrar kontrolü yalnız birebir aynı paket ve kaynak sürümlerinde bir
ardışık tekrarı atlar; her iki istemde yeniden gönderim mümkündür.
`SessionStart` önbelleği sıfırlar; uygulamadaki her bağlam daraltmanın bu
olayı ürettiğini kendi kurulumunda ayrıca gözle. Genel maliyet hesabına
inceleme, kaynak açma ve model yanıtları da katılmalıdır.

Geçiş sonrası birim testlerini, kişisel proje eşleşmesini, değiştirilmiş
kaynağın dışlanmasını ve gerçek hook/zamanlayıcı akışını ayrı doğrula.
Manuel taramayı zamanlanmış başarı gibi kaydetme; `--scheduled` yalnız
zamanlayıcı rolünde kullanılır. İlk beş mesaj ve sessiz bakım kuralları sürer.


### Ders kaynak sürümü geçişi

Güncel ders yazıcısı `source_content_hash` alanını incelenen kaynak
dosyanın tamamından üretir. Ders bağlamı hem bu hash'i hem yöntem hash'ini
doğrular. Eski hash'siz dersler erişimden çıkar; bütün eski dersleri körlemesine
yeniden kaydetmeyin. Kaynak ve yöntemi okuyup hâlâ desteklenenleri mevcut
`expected_version` ile `is_ve_ders.py lesson` üzerinden sürümleyin. İptal
edilen veya belirsiz dersi terfi ettirmeyin.


### Kısa proje özeti ve tekrar okuma

Görev paketi, yeni bir serbest metin hafızası üretmek yerine mevcut kaynaklı
kayıtların güncel görünümünü oluşturur. Kaynak hash'i içerik bütünlüğünü
gösterir; bilginin anlamsal doğruluğu veya kullanıcının yeni onayı değildir.
Yeni kullanıcı isteği ve değişmiş canlı kaynak bu görünümden önceliklidir.
Paketin eksiksiz verdiği, sürümü denetlenmiş bilgiyle metin taslağı üretirken
aynı dosyayı sırf tören olarak yeniden okumak gerekmez. Eksik/çelişkili
bilgi, kaynak değişimi ve gerçek işlem öncesi teknik kontrol bu kolaylığa
dahil değildir. Tarihçe istemleri gerektiğinde geçmiş kaynaklara döner.

Yeni iş kaydı da kaynak içerik sürümünü taşır. Eski hash'siz işler yeniden
incelenmeden sürümü doğrulanmış bilgi sayılmaz; kaynakları topluca körlemesine
sabitlemeyin. İşin kabul durumunu veya son teyit tarihini sırf geçiş için
yükseltmeyin.


## Görev kimliği ve erişim sağlığı

Skill çağrısının SKILL.md dosya yolu görev konusu sayılmaz. `[$skill](.../SKILL.md)`
bağlantılarında skill adı korunur; dosyanın bulunduğu başka proje bağlama sızmaz.
Normal belge bağlantıları ve kullanıcının açık proje adları korunur. Yeni proje
adı için yerel görev manifestindeki aliases ve roots alanlarını güncelleyin.

`status` içindeki operasyonel sağlık artık katalog bütünlüğünü ve erişime uygun
etkin kayıtları ayrı gösterir. `policy_excluded_count` gizlilik/tarih nedeniyle
beklenen dışlamadır; `source_blocked_count` kaynak sürümü incelemesi isteyen
kayıtları gösterir. Karantina/eski sürümler etkin kayıp sayılmaz. Katalog yoksa
isteğe bağlı katman unknown kalır. Bu sayılar sorgu veya proje kapsamından önceki
uygunluktur; doğru cevabı bulma ve kullanıcı faydası ölçümü değildir.
Statik katalog uyarıları sıradan görev açılışlarına tekrar tekrar eklenmez;
ayrıntılı status/health görünümünde kalır. Tarama, zamanlayıcı ve uzak audit
arızalarının açılış bildirimleri sürer. Kaynak uyarısını çözmek için gerçek
inceleme gerekir; hash'i körlemesine yenilemek onay değildir.


## Yerel çalışma kapsülü ve bilgi kartları

`devam`, `nerede kaldık`, `sonraki adım` içeren proje istekleri mevcut görev
paketinde kısa devam kartlarını açar. En fazla üç güncel görev ve beş kaynak
sürümü incelenmiş bilgi kartı gösterilir. Normal görevlerin standart görünümü
korunur. Elle küçük paket almak için:

```bash
python3 araclar/gorev_baglam.py --vault KASA resume "Proje adı devam" --budget 1800
```

`capsule` alanı görevleri, kaynak hash'lerini, tarihleri, bilgi kartlarını ve
varsa önerilen sonraki adımı taşır. Bu bir komut çalıştırmaz, yeni yetki vermez.
Tek güncel aktif görev sorgunun konusuna uyuyorsa adımı önerilir. Birden fazla
veya engelli görevde seçim yapılmaz; eski veya kaynak sürümü değişmiş kayıt
kart olmaz. Son doğrulanmış çıktı, isteğe bağlı outputs kaydının dosya ve kontrol sürümü doğrulanırsa gelir; kayıt yoksa null kalır.
Eksik veri model tarafından doldurulmaz.

Kapsül yeni kanonik hafıza kaydı değildir. Her çağrıda mevcut kaynaklardan
derlenir; ayrı önbellek, zamanlayıcı, ücretli API veya model çağrısı yoktur.
Hook var olan package çağrısını kullanır. Kartlar metin bütçesine bütün olarak
sığar; seçim/varlık kontrolü kapsül başlığından önceliklidir. CLI JSON'undaki
structured capsule, text alanının veri görünümüdür; karakter bütçesi yalnız
ajana verilen text için geçerlidir. Sonraki iş önerisi ve kaynak hash'i içerik
kalitesini veya insan kabulünü ispatlamaz.


## Çıktı, karar geçmişi ve yerel deney

Çıktı doğrulama alanları, karar geçmişi ve yerel deney sözleşmesi:
[bakım sözleşmesinde](komuta/hafıza-konsolidasyonu.md#çıktı-karar-geçmişi-ve-yerel-deney).

## Bağlantılı bilgi incelemesi

Kayıt ve kaynak değerlendirme alanları [[BILGI-AGI]], bakım sırası
[[komuta/hafıza-konsolidasyonu]] içindedir.

## Alanlar arası uyarlama

Kapsamlar arası öneri ve kabul sınırları [[BILGI-AGI]] içindedir.

## Görünür kullanım ve kayıt bildirimi

Güncel sözleşme: [[HAFIZA-GORUNURLUGU]].
