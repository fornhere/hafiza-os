# Ajan entegrasyonları

Bir kasa, birden fazla okuyucu. `araclar/ajan_kur.py` yalnız ortak yönerge
bloğu kurar. Hook kurucusu çalıştırmaz; mevcut hook, settings, config ve güven
ayarlarını değiştirmez. Konuşmaları istemciler arasında taşımaz.

## Destek düzeyleri

| Bağlantı | Kurucunun yaptığı | Ayrı doğrulanacak olan |
|---|---|---|
| Claude Code | Global `~/.claude/CLAUDE.md` bloğu | Yeni oturumda okunması; shell hook'ları ayrı |
| Codex | Global `AGENTS.md` bloğu | Override önceliği, izinler ve hook etkinliği |
| Antigravity | Global `~/.gemini/GEMINI.md` bloğu | Kurulu sürümde kuralın okunması; transcript adaptörü yok |
| Generic | Açıkça seçilmiş `.md` hedefinde aynı blok | İstemciye elle tanıtım, dosya/terminal izni |
| Web sohbeti | Yerel entegrasyon yok | Yalnız elle paylaşılmış uygun içerik |

Linux mevcut sistemin test platformudur; yeni kurucunun kabul kontrolleri
ayrıca yürütülür. macOS canlı denenmedi. Yerel Windows köprüsü yalnız manuel,
bütçeli dosya okuma yönergesi üretir; canlı istemci testi yapılmış sayılmaz.
`hafiza.py` ve `codex_hafiza.py` koşulsuz POSIX `fcntl` içe aktarır: yerel
Windows'ta CLI erişimi ve konsolidasyon araçları desteklenmez. Tam motor
(CLI erişimi, konsolidasyon ve hook'lar) için WSL içinde ayrı kurulum gerekir.
WSL ile Windows uygulamasının ev dizini ve dosya yolları aynı değildir;
WSL kurulumunda WSL'den görünen kasa ve istemci yollarını kullan.
Bu tablo bütün istemcilerin otomatik çalıştığı iddiası değildir.

Global yönerge konumlarının resmi kaynakları, **19 Eylül 2026** kontrolü:
[Claude Code memory](https://code.claude.com/docs/en/memory),
[Codex AGENTS.md](https://developers.openai.com/es-419/docs/agent-configuration/agents-md),
[Antigravity rules/workflows](https://www.antigravity.google/docs/rules-workflows/).
Codex global `AGENTS.override.md` varsa `AGENTS.md` yerine onu seçebilir;
kurucu override dosyasını değiştirmez. Önceliği ve içerik çakışmalarını elle
incele. Proje yönergeleri ve istemci bağlam bütçesi de sonucu etkileyebilir.

## POSIX kurulumu (Linux; macOS canlı denenmedi)

Komutları indirdiğin depo/kasa kökünde çalıştır. `--vault` zorunludur;
hedef kasada `agents.md`, temel zihin dosyaları ve iki erişim aracı bulunmalıdır.
Boş klasör kasa kabul edilmez. Varsayılan işlem yalnız JSON planını gösterir:

```sh
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent all
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent all --apply
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent claude --dry-run
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent antigravity --apply
```

Codex hedef sırası: açık `--codex-home`, sonra `CODEX_HOME`, sonra
`--home/.codex` (varsayılan `Path.home()`). `--home` Claude/Antigravity için de
ev dizinini değiştirir; **mevcut CODEX_HOME'u geçersiz kılmaz**.

```sh
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent codex --codex-home "$HOME/Codex Profil" --apply
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --home /tmp/hafiza-deneme --codex-home /tmp/hafiza-deneme/.codex --agent all
```

İkinci komut yalnız plan gösterir; gerçek kurulumun yerine geçmez.

## Windows PowerShell: yalnız manuel okuma (canlı denenmedi)

Python 3.10+ kurulu olmalı. Aşağıdaki komutlar yalnız yönerge kurucusunu
çalıştırır; erişim motorunu veya hook'ları kurmaz. Örnek yolları değiştir:

```powershell
python .\araclar\ajan_kur.py --vault 'C:\Hafıza Kasam' --agent all
python .\araclar\ajan_kur.py --vault 'C:\Hafıza Kasam' --agent all --apply
python .\araclar\ajan_kur.py --vault 'C:\Hafıza Kasam' --agent codex --codex-home 'C:\Ajan Profili\Codex' --apply
```

Üretilen Windows bloğu Python erişim komutu içermez. `agents.md`,
`zihin/ruh.md` ve `zihin/hafıza-sistemi.md` dosyalarını manuel oku;
`zihin/son-oturum.md` içinden yalnız en yeni tarihli bölümü en fazla 2500
karakterle al. Göreve göre `zihin/çekirdek.md`, `zihin/açık-işler.md` ve
`komuta/bu-hafta.md` içinden ilgili bölümleri seç. Geçmiş karar bağlamını
manuel olarak en fazla 5 bölüm ve toplam 1200 karakterle sınırla.
Bu okuma kaynak/sürüm doğrulamalı CLI erişimi değildir; öyle raporlama.
Kasadaki POSIX Python/hook komutları yerel Windows'ta çalıştırılmamalıdır.

Tam CLI erişimi ve hook'lar için WSL terminalinde ayrı kurulum yap; yukarıdaki
POSIX adımlarını WSL'den görünen kasa ve istemci yollarıyla uygula. Köprüyü
WSL içinde yeniden üret. Windows global yönergesini WSL'ye kopyalamak yeterli
değildir; Windows istemcisinin kendiliğinden WSL araçlarını çalıştırdığı
varsayılmaz. Kurucu WSL kurulumunu veya yol dönüşümünü otomatik yapmaz.

POSIX komutlarında shell argümanları ayrı alıntılanır. Yukarıdaki PowerShell
kurulum örneklerinde tek tırnak içindeki tek tırnak iki kez yazılır
(`'C:\Kişi''nin Kasası'`); Windows CMD sözdizimi değildir.

## Diğer ajanlar: açık aktarım

```sh
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent generic --export "$HOME/ajan-hafiza.md"
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent generic --export "$HOME/ajan-hafiza.md" --apply
```

`all` yalnız üç tanımlı istemciyi kapsar; generic ayrıca seçilir. Hedef kasa
dışında bir `.md` dosyası olmalıdır. Mevcut metin korunur. Dosyayı diğer ajanın
özel yönerge alanına elle tanıt; yerel dosya okuma ve terminal çalıştırma
izinlerini doğrula. Terminali olmayan ajan kaynakları yalnız kendi desteklediği
okuma araçlarıyla okuyabilir. Salt tarayıcı uygulaması bu yolla diske erişemez;
gerekli, gizlilik açısından uygun kaynak bölümünü elle paylaşman gerekir.

## Smoke kontrolü

1. Dry-run çıktısındaki `vault` ve `targets` yollarını denetle. Aynı kasanın
   kullanıldığını ve beklenmedik bir `CODEX_HOME` olmadığını gör.
2. Apply sonrası hedeflerde tek `HAFIZA-OS:SHARED` bloğu olduğunu kontrol et.
   Aynı komutu yeniden uygula: `changed: false`, yeni yedek yok olmalı.
3. POSIX/WSL içinde kasadan aşağıdaki salt-okunur komutları çalıştır. Yerel
   Windows'ta bunun yerine yukarıdaki manuel, bütçeli dosya okumasını yap;
   CLI kaynak doğrulaması yapılmış sayma. Boş şablonda son oturum bulunmaması
   veya boş bağlam normaldir; var olmayan hafıza uydurulmaz.
4. Her istemcide yeni oturum aç. “Kanonik kasa yolunu ve son oturumun tarihini
   kaynağıyla göster” de; istemcinin gerçekten dosyayı okuduğunu doğrula.
   Kaynaklı bir karar sorusuyla ikinci kontrol yap. Yalnız yolun tekrarlanması
   erişim veya doğru kullanım kanıtı değildir.

```sh
python3 araclar/codex_hafiza.py --vault "$HOME/Hafıza" latest-session
python3 araclar/hafiza.py --vault "$HOME/Hafıza" context 'ilgili karar' --limit 5 --char-budget 1200
```

Yalnız POSIX/WSL için: ilk komut en yeni tarihli bölümü en fazla 2500 karakterle verir; ikincisi
kaynak denetimli, bütçeli yerel bağlam getirir. Kaynak tarihi ve kapsamı yine
incelenmelidir. Hook/transcript akışını sınamak ayrı bir iştir.

## Mevcut hook kurulumları

Bu bölüm POSIX/WSL içindir. Yerel Windows'ta hook ve konsolidasyon araçları
desteklenmez; WSL tarafında ayrı kurulum ve WSL'den görünen yollar gerekir.

Claude Code için kasa kökünde `bash kur.sh` mevcut shell hook'larını kurar;
Git, jq ve bash gerektirir. Yeni oturumda `/hooks` üzerinden kontrol edilir.
[Kurucu](kur.sh) ve [kasa sözleşmesi](agents.md) ayrıntıları içerir.

Codex için [CODEX.md](CODEX.md) geçerlidir. Mevcut kurucunun komutları:

```sh
python3 araclar/codex_kur.py --vault "$HOME/Hafıza"
python3 araclar/codex_kur.py --vault "$HOME/Hafıza" --apply
```

Bunlar ortak köprüden farklı olarak hook ayarlarını da yazar; bu rehberdeki
`ajan_kur.py` onları çağırmaz. Codex'te ayrıca hook etkinleştirme ve isteniyorsa
zamanlanmış konsolidasyon gerekir. Antigravity/generic için bu depoda otomatik
transcript okuyucusu yoktur. Eski kurucuların yönetilen blokları korunur;
eski blok başka kasaya işaret ediyorsa onun kurulumunu ayrıca düzelt.

## Güvenli güncelleme ve kaldırma

Kurucu yalnız `HAFIZA-OS:SHARED:START/END` satırları arasındaki kendi bloğunu
yönetir. Bozuk, ters, yinelenmiş veya eksik işaretlerde hiçbir hedefe yazmadan
hata verir. Hedef, kasa ve üst dizinlerindeki sembolik bağlantıları reddeder;
normal dosya olmayan ya da hardlink'li hedefe yazmaz. Kasa içine aktarım yapmaz.
Mevcut dosya yalnız gerçekten değiştiğinde `.backup-UTC_ZAMAN` yedeği alınır;
yeni dosya ve no-op için yedek yoktur. Yedeklerde eski özel yönergeler olabilir.

```sh
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent all --remove
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent all --remove --apply
python3 araclar/ajan_kur.py --vault "$HOME/Hafıza" --agent generic --export "$HOME/ajan-hafiza.md" --remove --apply
```

Özel ev/Codex yolu kullandıysan kaldırmada aynı seçenekleri ver. Yalnız kendi
bloğu çıkarılır; diğer metin, hook'lar, yedekler ve klasörler kalır. Dosya boş
kalabilir; kurucu dosya silmez. Kasa doğrulaması kaldırmada da gerekir; kasayı
silmeden/taşımadan önce kaldır. Claude hook kaldırması `bash kur.sh --kaldir`,
Codex hook yönetimi [CODEX.md](CODEX.md) üzerinden ayrıdır.

Her hedef atomik değiştirilir; çok hedefli işlem bir veritabanı işlemi değildir.
Yazma ortasında disk/izin hatası olursa önceki hedefler değişmiş olabilir.
Kurulum sırasında aynı dosyaları başka süreçle düzenleme; kontroller saldırgan
bir sürecin eşzamanlı dosya sistemi yarışına karşı güvenlik sınırı değildir.

## Gizlilik

Köprü ağ çağrısı yapmaz ve kasanın içeriğini yönergeye kopyalamaz; kasa yolunu
ve erişim kurallarını yazar. Ajan dosya okuduğunda içerik o ajanın sağlayıcısına
gidebilir. Genel aktarım dosyasını paylaşmadan önce yerel yolu ve gizlilik
kapsamını gözden geçir. API anahtarlarını yönergelere veya Git'e koyma.

Kanonik kayıt ve Mem0 yazımı görev ajanına verilmez; kaynaklı adaylar ayrı
incelemeye gider. Kaydetmeme isteği korunur. İsteğe bağlı [Mem0 politikası](zihin/hafıza-sistemi.md)
ve [Jev veri aktarımı/sınırları](JEV.md) ayrıca değerlendirilir. Ortak yönergenin
kurulması bu servisleri ya da arka plan kaydını etkinleştirmez.
