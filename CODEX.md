# Codex ve düzenli hafıza incelemesi

[Birleşik yerel kurucu](ENTEGRASYONLAR.md) varsayılan olarak yalnız yönerge,
`--with-hooks` ile mevcut Codex adaptörünü kurar. Güven ayarını değiştirmez.
Python 3.10+ gerekir; macOS/Windows native CI ve canlı istemci sonuçları henüz
bekliyor. Windows string hook kabuğunu ayrıca doğrulamak gerekir.

```sh
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent codex --with-hooks
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent codex --with-hooks --apply
```

Eski `codex_kur.py` komutu bulunursa `--migrate-legacy` ile açık geçiş yap.
`/hooks` ekranında bağlantıları inceleyip etkinleştir; yeni ana oturum başlat.
Trust otomatik açılmaz. Kasa taşıma/kaldırma için entegrasyon rehberini kullan.
Aşağıdaki eski düzenli konsolidasyon örnekleri POSIX araçları içerebilir;
bunlar modern yerel kurucunun veya Windows otomasyonunun kendisi değildir.

Açılış ve kullanıcı bağlamı, varsa kaynak doğrulamalı incelenmiş native
Claude/Antigravity makbuzlarını en fazla 1800 karakter ekler. Kaynak silinir veya
değişirse makbuz recall'a alınmaz; ek okuyucu hatası mevcut Codex akışını bozmaz.
Tam transcript senkronu, otomatik profil güncellemesi veya kanonik terfi değildir.

İlk beş gerçek kullanıcı mesajı kayıt istemez. Altıncıdan sonra karar, sonuç
ve kalan işi içeren kısa makbuz arka plan konsolidasyonunda üretilir; cevap
sonunda kayıt zorlaması yapılmaz. Bunun için aşağıdaki otomasyon etkin olmalıdır. Basit sorular biriktirilmez; kayıt
istemediğin konuşmalar dışarıda kalır. Kapanış devamı ve `[HAFIZA_OTOMASYON]`
ile başlayan zamanlayıcı mesajları sayaç artırmaz.

## Kalıcı bilgi ve Mem0

Mem0 kullanıyorsan `MEM0_API_KEY` ve kişisel `HAFIZA_MEM0_USER_ID` ortam
değişkenlerini kendi güvenli ortamında tanımla; değerlerini kasaya yazma.
Makbuz üreticisi `semantic_candidates` listesini değerlendirir. Kalıcı bir
tercih yoksa `[]` bırakır. Adaylar sırayla kaynak, kalıcılık ve tekrar
incelemesinden geçer; inceleyen rol `codex-consolidator` olarak kaydedilir.

```bash
python3 araclar/konsolidasyon.py pending
python3 araclar/konsolidasyon.py review --input-json karar.json
python3 araclar/konsolidasyon.py review --input-json karar.json --apply
python3 araclar/hafiza.py --vault . sync
python3 araclar/hafiza.py --vault . sync --apply
python3 araclar/hafiza.py --vault . audit
```

`karar.json`: candidate_id, reviewed_by, decision ve reason alanlarını taşır.
approve için source_checked, explicit_user, durable, normal_sensitivity,
no_semantic_duplicate alanları true olmalıdır. Bu değerler gerçek inceleme
sonucudur; sırf geçsin diye doldurulmaz. Çelişkide defer kullanılır.

## İsteğe bağlı saatlik inceleme

Codex'ten aşağıdaki istemle saatlik bir otomasyon oluşturmasını iste;
`KASA_YOLU` yerine kasanın tam yolunu yaz. İstem metninin başındaki işaret kalsın.

> [HAFIZA_OTOMASYON]
> KASA_YOLU kasasında komuta/hafıza-konsolidasyonu.md yönergesini saatlik uygula.
> Bekleyen adayları ve belirtilen başlangıç tarihinden sonraki uygun boşta
> oturumları incele. İlk beş gerçek kullanıcı mesajını, basit soruları,
> kaydetmeme taleplerini ve özel bilgileri kaydetme. Kaynaklı adayları incele;
> belirsizliği ertele. Terfi varsa Mem0'a senkronla ve geri okuyarak doğrula.
> İş ve ders defterlerini kaynaklarıyla güncelle; sonunda sağlık görünümünü üret.
> Değişiklik veya gereken kullanıcı eylemi yoksa sessiz kal. Harici mesaj
> gönderme, yayınlama veya silme yapma.

Otomasyonu oluştururken başlangıç tarihini belirle. Yedek tarama komutu
`python3 araclar/konsolidasyon.py sessions --since YYYY-AA-GG` biçimindedir;
tarih verilmezse bugünden başlar. Son 20 dakikada değişmiş oturumları erteler.
Transkript biçimi uygulamayla değişebileceği için canlı kontrolü sürdür.

## İşler, dersler ve sağlık

`araclar/is_ve_ders.py task --input-json DOSYA` işin id, title, status,
next_step, source_path, evidence, actor ve last_verified alanlarını kaydeder.
Güncellemede mevcut version değerini expected_version olarak ver.
`render` açık işler görünümünü defterden üretir; önce mevcut notunu arşivle
ve içindeki işleri kaynaklarıyla deftere aktar. Defter yoksa görünüm korunur.

`lesson` komutu aynı kaynak alanlarıyla proposed ders bırakır. verified
olabilmesi için target_path, target_hash, verification_path ve
verification_evidence gerekir. Gerçek test çalıştırmadan ders doğrulanmaz.

```bash
python3 araclar/konsolidasyon.py health
python3 -m unittest discover -s araclar -p 'test*.py'
python3 araclar/hafiza.py --vault . eval --file araclar/hafıza-testleri.örnek.json
```

Örnek erişim testlerini kendi kayıt kimliklerin ve sorularınla doldur.
Paketin birim testleri, senin uygulamanda canlı hook veya zamanlayıcı
çalıştığının yerine geçmez. Gemini/Hermes çalışma zamanı adaptörleri bu
Codex kurucusunun kapsamı dışındadır.

## Sessiz kayıt, Git ve ders uygulama — 15 Eylül

`health` anlamlı hafıza veri değişikliklerini yerel Git commitine alır. Kasa
Git deposu olmalı ve Git kullanıcı kimliği tanımlı olmalıdır. Uzak depoya push
yapılmaz. Yalnız sağlık tarihi değiştiyse commit atılmaz; önceden staged
değişiklik, silme, sembolik bağ veya sır taraması bulgusunda işlem hata verir.
Kod ve ilgisiz kullanıcı dosyaları otomatik eklenmez.

Ders kaydına `triggers` (örneğin `["kapak", "thumbnail"]`) ve kasa içinde
`method_path` ekle. UserPromptSubmit kaynak kanıtı bulunan ilgili yöntemleri
bütçeli bağlama alır; ilgisiz görevleri bölmez. `implementation_status: applied`
yöntemin uygulandığını belirtir; gerçek sonuç testi olmadan `verified` yapma.
`status` çıktısındaki `lesson_backlog`, uygulanmamış veya sonuç testi bekleyen
dersleri gösterir. Varsayılan şablonda kişisel ders veya tercih bulunmaz.


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

Görev defterinin isteğe bağlı `outputs` alanı doğrulanmış dosyaları taşır.
İnceleme rolü yalnız gerçekten kontrol ettiği dosyayı mevcut görev sürümüne
`is_ve_ders.py task` ile ekler; eski teslimatları topluca onaylamaz.
Her çıktı id, label, mutlak path, sha256, saat dilimli verified_at, reviewer,
verification_path (kasa içi), verification_sha256 ve birebir
verification_evidence içerir; isteğe bağlı uses bir metin listesidir.
Çıktı tanımlı projenin roots dizininde olmalıdır. Hash alanları dosya
baytlarının düz SHA-256 değeridir. Kontrol raporuna `output-review: ` ardından
`cikti_kayit.review_binding(output)` sözlüğünün tek satırlık JSON'u yazılır;
rapor hash'i bundan sonra alınır. Kontrol dosya kimliğine, yoluna, sürümüne,
inceleyene ve zamana bağlıdır. Hash tek başına kalite veya insan kabulü değildir.
Dosya, kontrol raporu veya görev kaynağı değişirse çıktı yeniden incelemeye
kadar kapsülden ve yeniden kullanım önerilerinden çıkar. İlk beş mesaj,
kaydetmeme ve ayrı inceleme rolü kuralları değişmez.

“Proje adı karar geçmişi” eski ve güncel kararları kaynaklarıyla gösterir.
Çelişkide güncel karar seçilmez; kayıtlı gerekçe yoksa gerekçe uydurulmaz.
“Proje adı CSV yeniden kullan” doğrulanmış çıktıların etiket ve uses alanlarını
sözcüklerle eşleştirir. Sonuç öneridir; uyarlama ve yeniden kontrol gerekir.
Eşleşmeyen ihtiyaçta boş döner; zaman tasarrufu veya kullanıcı kabulü çıkarmaz.

`python3 araclar/ogrenme_pilotu.py --vault KASA --input-json deney.json`
kaynaklı küçük deney önerisini doğrular. Girdi topic, source_path, evidence,
expected_source_hash (`sha256:` önekli kaynak metin hash'i), question,
experiment ve success_criterion alanlarını içerir. Kaynak sürümü değişirse
reddedilir. Araç deneyi yürütmez, kişisel bilgi eksikliği veya öğrenme sonucu
çıkarmaz; deney ayrıca uygulanıp ölçülür. Bu özellikler ek API çağrısı,
abonelik veya zamanlayıcı eklemez. Dosya doğrulaması yerel disk okuması yapar.


## Bağlantılı bilgi incelemesi

Makbuz kaydı, konuşmadan işe yarar bilgi çıkarıldığını tek başına göstermez.
Mevcut saatlik inceleme rolü artık [bağlantılı bilgi akışını](BILGI-AGI.md)
da yürütür: tamamlanmış kaynakları inceler, kaynaklı tercih/karar/ders/örnekleri
kapsamıyla kaydeder ve Obsidian'da kaynaklara bağlı Markdown görünümü üretir.
Eski makbuzların varlığı bu incelemeyi atlatmaz; kaynak engelleri otomatik hash
sabitlenerek çözülmez. Yeni otomasyon veya ek API kurulmaz.

Yalnız dosyaları güncellemek zamanlanmış rolün çalıştığını kanıtlamaz.
Kurulu otomasyonun `komuta/hafıza-konsolidasyonu.md` dosyasını her bakımda
okuduğunu ve son çalışmanın bilgi incelemesi sonucunu ayrıca doğrula.
Kayıt oluşturma, sorguda geri getirme ve gerçek görevde doğru uygulama ayrı
başarı ölçütleridir. Bir sunum akışı tercihi, site görsel tasarımı tercihi
olarak kullanılamaz; açık kapsam ve kaynak desteği gerekir.


## Alanlar arası uyarlama

Sunum ve site arasında kaynağın açıkça belirttiği anlatı sırası, metin dili,
tipografi, renk, yerleşim veya hareket özelliği için uyarlama önerisi getirilebilir.
Bunlar `transfers` alanında `status=proposed` taşır; hedef alanın onaylı tercihi
olarak `records` listesine girmez. Kaynak kapsamı ve sürümü korunur. Özellik
eşlemesi sınırlı sözcük kurallarıdır; anlamsal uygunluğu ajan görevde inceler.
Bir özelliğin anılması onun beğenildiğini tek başına kanıtlamaz; kaynak cümledeki
olumsuzluk ve koşulları koru. Bahsedilmeyen görsel özellikleri çıkarma.
Doğrudan alan eşleşmeleri önerilerden önce gelir; proje sınırı ve bütçe korunur.
Mevcut köprü sunum ↔ site ile sınırlıdır; bütün alanlar birbirine açılmaz.


## 18 Eylül — Hafızanın görünür etkisi

Rutin kapanış/kayıt zorlaması kapalı kalır. Kullanıcı, anlamlı hafıza kullanımının
ve gerçek kayıt değişikliklerinin görünmesini istedi. Geçmiş bilgi somut bir
seçimi etkilediyse tek kısa cümlede etkisini ve kaynak bağlantısını belirt.
Bağlama gelmek kullanım değildir; kullanım beyanı ajanın açıklamasıdır, bağımsız
nedensellik kanıtı değildir. Aynı kaynağı her yanıtta tekrarlama. Uyarlama
önerisini hedef alanda kabul edilmiş tercih gibi sunma.

Anlamlı yeni/değişmiş bilgi kaydı gerçekten yazılıp geri okunmuşsa, sohbet içinde
en fazla bir kısa bildirimde değişen bilgiyi ve dosyayı göster. `bilgi_agi register`
apply sonucu `notice` bunu destekler; dry-run/no-op bildirim üretmez. Bekleyen
aday için kalıcı tercih kaydedildi deme. Arka plan yazımı daha sonra olduysa
önceki yanıtta yapılmış gibi söyleme. Mevcut bakımın anlamlı değişiklik sonucu
bildirilebilir; kullanıcıdan ayrıca kayıt onayı veya puan istenmez. Sırları
ve özel kaydetmeme kapsamını bildirimde de koru.
