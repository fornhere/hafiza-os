# Codex ve düzenli hafıza incelemesi

Gereksinimler: Linux/macOS, Python 3.10+ ve hook desteği olan Codex.
Bu komutları hafıza kasasının kökünde çalıştır. Mevcut Claude kurulumu için
`kur.sh` kullanılmaya devam eder.

## Bağlantı

```bash
python3 araclar/codex_kur.py           # yapılacak işlemleri gösterir
python3 araclar/codex_kur.py --apply   # mevcut ayarları yedekleyip ekler
```

Kurucu diğer hook'ları ve genel AGENTS.md metnini korur; güven/onay ayarlarını
değiştirmez. Codex'te `/hooks` ekranından dört Hafıza OS bağlantısını inceleyip
etkinleştir. Ardından yeni bir ana oturumda açılış bağlamını kontrol et.
Kasa taşınırsa eski konuma ait hook'ları `/hooks` üzerinden kaldırıp yeni
konumda kurucuyu tekrar çalıştır.

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
