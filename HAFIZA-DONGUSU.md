# Kaynaktan deneyime hafıza döngüsü

Bu akış beş parçayı mevcut araçlarla bağlar: bekleyen aday incelemesi, gerekçeli/koşullu kararlar, iş sonucundan ders, görev bağlamı ve cevap atıflarının kontrolü. Jev semantik danışmandır; puanları tek başına kayıt terfi ettirmez. Testler mekanik sözleşmeyi doğrular, gerçek Türkçe semantik kalite veya kazancı kanıtlamaz.

## Kurulum ve çalıştırma

Depodaki `araclar` dizinini mevcut kurulum yöntemiyle birlikte güncelle. Yeni modüller `hafiza_dongusu.py` ve `jev_answer.py`, yanlarındaki hafiza/bilgi_agi/jev_client modülleriyle çalışır. Python 3.10+ ve standart kütüphane yeterlidir. Linux/macOS `python3`, Windows `py -3` kullanır. Komutlarda `KASA` gerçek kasa yoludur; çalışma dizini repo köküdür.

```sh
python3 araclar/hafiza_dongusu.py --vault KASA review-pending --project-id PROJE --limit 5 --apply
python3 araclar/konsolidasyon.py --vault KASA review-pending --project-id PROJE --limit 5 --apply
python3 araclar/hafiza_dongusu.py --vault KASA context "sunum hazırlayalım" --cwd PROJE_DIZINI --budget 5000
python3 araclar/hafiza_dongusu.py --vault KASA outcome --input-json sonuc.json --apply
python3 araclar/hafiza_dongusu.py --vault KASA review-lesson --input-json inceleme.json --apply
python3 araclar/hafiza_dongusu.py --vault KASA verify-answer --project-id PROJE --input-json iddialar.json
```

İlk iki komut aynı işlemdir; ikisini arka arkaya çalıştırmak gerekmez. `--apply` yokken yazma yapılmaz (Jev'in kendi önbellek/telemetri politikası ayrı geçerlidir). Model çağrıları senkron hook'a eklenmez. Mevcut arka plan reviewer görevinin her turunda, normal oturum kaynak incelemesinden sonra bir `review-pending --limit 5 --apply` çağrısı çalıştırılır. Tek komut bir defalık bounded turdur; kendiliğinden zamanlayıcı kurmaz. Zamanlayıcısı olmayan kurulumda işletim sistemi görev zamanlayıcısından aynı komut çağrılabilir. Reviewer aynı proje kapsamını vermelidir; proje adı verilmezse yalnız kullanıcı kapsamı işlenir.

## Aday inceleme

`konsolidasyon.pending` kataloğu ve `bilgi/` altındaki proposed kartları birlikte tarar. Değişmeyen başarılı inceleme tekrarlanmaz; kaynak, aday, karşılaştırılan bilgi veya Jev ayarı değişince yeniden değerlendirilir. Hatalı/devre dışı çağrılar yeniden denenebilir. Tur başına en fazla 20, varsayılan 5 aday; aday başına mevcut Jev sınırlamaları ve en fazla 8 ilişki karşılaştırması geçerlidir. İncelenmeyen ilişki sayısı döner: eşleşme çıkmaması evrensel yenilik kanıtı değildir.

Makbuz `günlük/hafıza-makbuzları/lifecycle-review.jsonl` içindedir. Kaynak desteği/çelişki ve aynı iddia/daraltma ilişkileri danışma çıktısıdır. Katalog için mevcut deterministik assessment da makbuzdadır. Kaynak değişikliği puanları geçersiz kılar. Terfi mevcut `konsolidasyon review` / `hafiza promote` tek yazıcısıyla; bilgi kartı terfisi `bilgi_agi register` kaynak ve expected-version denetimiyle yapılır. Bu komut otomatik onay vermez.

## Gerekçe, koşul, istisna

`hafiza candidate-add` artık isteğe bağlı `--rationale` ve `--conditions` kabul eder. İkisi de kaynakta aynen bulunan en az 10 karakterlik alıntılardır; terfi sırasında korunur. Görev bağlamı ve karar geçmişi bunları kaynakla beraber bütçeye dahil eder. Mevcut supersedes/valid_from/valid_to tarihçesi değişmez.

Bilgi kartları isteğe bağlı `rationale`, `conditions`, `exceptions` alır; kaynaklardan doğrulanır ve hem yerel hem Jev seçimi sonrası bağlama taşınır. Eski kayıtlar geçerlidir; eksik gerekçe uydurulmaz. Koşulun bulunması makine tarafından her dünyasal koşulun değerlendirildiği anlamına gelmez; ajan göreve uygunluğu inceler.

## İş sonucundan ders

Önce mevcut `is_ve_ders task` ile kaynaklı işi `done` durumuna getir. Sonuç kaydı JSON örneği:

```json
{"task_id":"sunum-test","title":"Sunum yerleşim dersi","lesson":"Bu koşulda kısa cümle yöntemi doğrulandı.","conditions":"Yalnız test edilen sunum yerleşiminde.","method_path":"yontem.md","verification_path":"test-sonucu.json","verification_hash":"DOSYANIN_SHA256_DEGERI","verification_evidence":"TEST_DOSYASINDA_AYNEN_BULUNAN_EN_AZ_20_KARAKTER","verification_kind":"test_result","observed_result":"passed","actor":"worker","triggers":["sunum"]}
```

`test-sonucu.json` gerçek runner'ın ürettiği `task_id`, tamsayı `exit_code`, boolean `passed`, `command`, `finished_at` alanlarını içermelidir. `passed`/`failed` sonucu exit code ile eşleşir. Başarısız test de koşullu uyarı dersine aday olabilir; sonraki bağlamda `failed` olarak görünür, başarılı yöntem gibi sunulmaz. `user_acceptance` türünde `accepted`/`rejected` için kaynaklı kullanıcı alıntısı gereklidir. Dosya ve alan varlığı tek başına gerçek dünyada başarı kanıtı değildir: bağımsız reviewer testin kapsamını, runner çıktısını/kullanıcı beyanını ve dersin genellenebilirliğini kontrol eder. Ajanın kendi puanı kabul edilmez.

`outcome` sadece `gelen-kutusu/lesson-outcomes.jsonl` kuyruğuna yazar. Dönen receipt_id ile:

```json
{"receipt_id":"DONEN_KIMLIK","reviewed_by":"independent-reviewer","reason":"Kaynak sonuç ve dersin uygulanma koşulları karşılaştırıldı.","evidence_checked":true,"conditions_checked":true}
```

`review-lesson` kaynakları tekrar doğrular; önerenden farklı reviewer gerektirir; mevcut `is_ve_ders.put` üzerinden verified ders yazar. Tekrarlı apply yeni sürüm üretmez. Ders `ders_baglam` ve normal görev bağlamında, proje/trigger/metot/kaynak/doğrulama hash kontrollerinden sonra gelir. Sonuç kaynağı değişirse ders teslim edilmez. Kaydetmeme isteğini veya ilk beş mesaj sessizliğini aşmak için bu CLI kullanılmaz; otomatik oturum yakalama zaten mevcut capture/reviewer kapılarında kalır.

## Cevap kontrolü

Hafızaya dayalı “bunu tercih ediyorsun” gibi iddiaları cevap öncesinde şu sözleşmeyle kontrol et:

```json
[{"text":"Sunumda kısa cümle tercih ediyorsun.","citations":[{"card_id":"sunum-tercihi","path":"kaynak.md","sha256":"KAYNAGIN_SHA256_DEGERI","quote":"Kaynak kartındaki aynen doğrulanmış alıntı"}]}]
```

Katalog kaydında `card_id` yerine `memory_id` kullanılır. Geçerli güncel kayıt, kapsam, birebir alıntı ve kaynak hash'i önce deterministik kontrol edilir; ardından Jev yalnız alıntıyla iddiayı karşılaştırır. Bir çağrıda en fazla 20 iddia, her birinde 8 atıf, toplam 32000 karakter. Sonuçlar `supported`, `contradicted`, `insufficient`, `uncertain`, `degraded`; off/shadow semantik onay yerine uncertain verir. Timeout “kanıt yok” değildir, degraded'dır. Kaynak çağrı sırasında değişirse sonuç atılır. Kaynak eksik veya çelişkiliyse ajan iddiayı kaynaklı biçimde daraltır veya çıkarır; araç cevabı kendi kendine değiştirmez. Bu, yapılandırılmış atıflara dayalı araçtır; tüm serbest metindeki iddiaları kendiliğinden keşfettiği iddia edilmez.

## Kontrol ve geri dönüş

```sh
python3 -m unittest discover -s araclar -p 'test_*.py'
```

Jev `komuta/jev.json` içindeki mevcut off/shadow/on ayarıyla kontrol edilir. Off modda yerel görev bağlamı ve kaynak kapıları çalışır; otomatik terfi yoktur. Bakım zamanlayıcısını kapatmak yeni inceleme turlarını durdurur; geçmiş silinmez. Deneysel kaliteyi aynı aday havuzunda Jev açık/kapalı ve güçlü yerel baseline ile ayrıca ölç. Ücret/gecikme/yanlış kabul ve kaçırılan kaynakları ayrı raporla.

[[Ana Sayfa]]

## Ders faydası ve yeniden inceleme

`ders_baglam.context_details()` metinle birlikte gerçekten enjekte edilen derslerin
`id`, `version`, `status` alanlarını döndürür; `context()` aynı metni döndürmeye
devam eder. Görev paketindeki `lessons.applied` yalnız teslim edilen `methods`
segmentinin `{id, version}` listesidir. Ajan bu listeyi `outcome` girdisine isteğe
bağlı `applied_lessons` olarak aktarır (en fazla 20 benzersiz, mevcut ders;
sürüm 1 ile güncel sürüm arasında). Alan yoksa eski makbuz parmak izi değişmez.
Bu atıf, ajanın yöntemi gerçekten uyguladığının bağımsız kanıtı değildir.

`python3 araclar/hafiza_dongusu.py --vault KASA lesson-utility` yazmadan sayım
yapar; `--apply` inceleme gereken derse yeni `proposed` sürümü ve
`review_required={reason, help, harm, outcome_ids}` ekler. `passed`/`accepted`
yardım, `failed`/`rejected` zarar sayılır. Ders, iş ve doğrulama hash'i başına
bir sonuç sayılır; dersin kendi oluşum makbuzu dışlanır. Zarar yardımdan fazla
ve `--min-harm N` eşiğine eşitse veya onu aşarsa inceleme istenir. Varsayılan
`min_harm=2`: tek başarısızlık atıf gürültüsü olabilir; eşik en az 1 olmalıdır.

`review_required` alanı bulunan ders durumundan bağımsız olarak bağlama girmez;
backlog fayda incelemesini gösterir. Ders ve geçmişi silinmez. Ayrı inceleme,
kaynak ve doğrulama kontrolleriyle bu alan kaldırılarak yeni sürüm onaylanabilir.
Son `review_required` sürümünden büyük kullanılan sürümler sayılır; yeniden
onay eski zararları taşımaz, sıradan sürüm yenilemesi sayacı sıfırlamaz.
`--apply`, `zihin/ders-faydasi.json` içine `generated_at`, `min_harm`, `lessons`
alanlarıyla türetilmiş sayaç görünümü yazar; bu dosya kanonik kayıt değildir.
Yazma hatası `demotion_failed:<mesaj>` olarak raporlanır, diğer dersler işlenir.

`fayda_olc.record()` ayrıca isteğe bağlı `applied_lessons` ders kimlikleri
listesini alır (sürüm içermez, en fazla 20 benzersiz mevcut kimlik).
`summarize()['lessons']` en güncel gözlemlerden ders başına
`accepted`, `rejected`, `abandoned`, `unknown` sayar. Ham sayımlar nedensel
başarı veya dersin doğruluğu hakkında karar değildir.

## Talimat dosyası dersleri ve inceleyen kimliği

Her dizin derinliğinde `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `GEMINI.md`,
`SKILL.md`, `.cursorrules`, `hooks.json` ve `.claude/`, `.codex/`, `.agents/`,
`skills/`, `hooks/` altındaki dosyalar talimat hedefidir. Yollar POSIX biçimine
çevrilip küçük harfle `fnmatch` desenlerine eşlenir. İsteğe bağlı
`komuta/talimat-dosyalari.json` içindeki `{"extra_patterns":["komuta/ajan-*.md"]}`
yalnız ek desen tanımlar; bozuk veya okunamayan ayar varsayılanları kaldırmaz.

`target_path` veya `method_path` bu kapsama giriyorsa `verified` ders için
mevcut kaynak/hash/test makbuzu kapılarına ek olarak
`verification_kind=user_acceptance`, `observed_result=accepted` ve
`acceptance_source={session_id, source_snapshot, evidence_source, evidence}`
gerekir. En az 10 karakterlik alıntı `capture_source.validate_candidate_evidence`
ile özgün kullanıcı mesajına bağlanır; ilk beş mesaj, kaydetmeme ve sır taraması
korunur. `outcome` bu alan verilirse doğrular; ayrı `review-lesson` yeniden
doğrular. Test sonucu tek başına talimat dersini onaylamaz; reddedilen sonuç
kuyrukta `proposed` kalır. Bağlam kapısı ayrıca verified/kabul alanlarını arar,
hash kontrollerini sürdürür; kabul eksikse `instruction_target_unaccepted`
tanısı ve backlog görünür. Bağlam okuması transcript'i yeniden doğrulamaz.

Gözetimsiz bakım talimat hedef dosyasına yazmaz; kabul bekleyen değişiklik için
yalnız “Boşluk not edildi, uygulanmadı: talimat dosyası değişikliği kullanıcı
kabulü (özgün kullanıcı mesajı alıntısı) ister.” raporlar. `lesson-utility`
güvenli düşürmeyi sürdürebilir; sonuç ve backlog girdisi `instruction_target=true`
taşır.

`reviewed_by` ve `actor`, NFKC + casefold + yalnız harf/rakam ile karşılaştırılır;
eşit veya boş normalizasyon reddedilir. İsteğe bağlı `actor_session_id` boş
olmayan, en fazla 200 karakterlik dizgedir; varsa farklı `reviewer_session_id`
zorunludur ve derste saklanır. Oturum kimlikleri birebir karşılaştırılır.
Alanlar verilmezse outcome makbuz parmak izi değişmez. Adlar ve oturum kimlikleri
beyandır; bu karşılaştırmalar kimlik doğrulaması veya gerçek bağımsızlık kanıtı
değildir.

## Ders tetiklenme ölçümü

`python3 araclar/ders_tetik.py run --vault KASA --spec spec.json --output rapor.json`
yalnız yerel sözcük eşleşmesini ölçer; Jev çağrısı veya kanonik ders değişikliği yapmaz.
İncelenmiş spec örneği, tetiklemesi gereken 3 / tetiklememesi gereken 3 istem içerir:

```json
{"schema":1,"label_review":{"status":"reviewed","kind":"human","reviewed_by":"inceleyen"},"cases":[{"lesson_id":"kapak","project_id":null,"workflow_ids":[],"should_trigger":["kapak üret","kapak tasarla","kapak düzenle"],"should_not_trigger":["ses düzenle","metni kısalt","raporu denetle"]}]}
```

Spec 1–50 benzersiz ders içerir. Her istem listesi 3–10 benzersiz, boş olmayan,
en fazla 1500 karakterlik metin alır; iki liste kesişmez. `label_review.kind`
`human`, `agent` veya `fixture` olabilir; sır içeren spec reddedilir.
Eksik/uygunsuz ders, kapsam uyuşmazlığı, bağlam hatası, bütçe müdahalesi veya
koşu sırasında değişen kaynak ölçümü durdurur; hata recall 0 diye kaydedilmez,
rapor yazılmaz. CLI hatayı stderr'e JSON olarak yazar ve 2 ile çıkar.

Başarılı rapor değişmezdir: var olan çıktı üzerine yazılmaz. Rapor kaynak
SHA256'larını, ders sürümlerini, kaçırılan ve yanlış tetiklenen istemleri içerir.
Ders başına ve raporun üst düzeyinde `recall` ile `false_trigger_rate` bulunur;
üst düzey oranlar bütün istemler üzerinden micro hesaplanır. Bu bir sözcük
tetiği ölçümüdür, dersin faydasının veya kullanıcı kabulünün kanıtı değildir.

## Deterministik ders yansıtması

`python3 araclar/ders_yansitma.py --vault KASA reflect` dry-run çıktısını
incele; `--apply` yalnız `gelen-kutusu/lesson-reflections.jsonl` öneri kuyruğuna
ekler. Model/LLM çağrısı yoktur. Son `--limit N` satırda (varsayılan 200) aynı
kapsam, yöntem, doğrulama türü ve komut imzasının en az iki işte ve
`--min-sessions N` farklı oturumda (varsayılan/asgari 2) failed/rejected sonucu
aranır. Oturum beyanı yoksa görev kaynak yolu sayılır. Test makbuzunun hash'i
yeniden doğrulanır; olumlu sonuçlar örüntü kanıtı sayılmaz.

İskelet `proposed`, `needs_distillation=true`, `action=null`, `rationale=null`
kalır; inceleyen mevcut outcome/review_lesson veya proposed lesson akışıyla
“koşul → eylem → gerekçe” metnini oluşturur. Ham iz ve serbest ders metni
taşınmaz; yalnız komut imzası, occurrence referansları ve hash bulunur. Önceki
öneriye veya aynı kapsam/yöntemdeki derse delta yalnız yeni referansları ve
koşulu ekler; ders defterine yazmaz. Sayım son pencereyle sınırlıdır; koşuldaki
oturum sayısı bu pencerenin toplamıdır, deltadaki yeni referans sayısı değildir.
Talimat hedefinde yalnız `gap_noted_not_applied` üretilir. Kaynak ve ayrı
inceleme kapıları üzerinden verified olmayan ders bağlama girmez.
