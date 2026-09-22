# Hafıza OS geliştirme rehberi

Bu depo paylaşılabilir motoru ve başlangıç kasasını içerir. Kişisel kurulumdaki
kayıtlar, sırlar, oturumlar ve tercih dosyaları geliştirme girdisi değildir.
Bir şablonun varlığı, kullanıcının onu doldurduğu veya kabul ettiği anlamına gelmez.

## Göreve başlarken

1. Depo kökünde `git status --short` ve `git rev-parse HEAD` çalıştır.
   Başkasının değişikliklerini temizleme, geri alma veya teslimine katma.
2. İstenen davranışı ve hatayı kaynak/test ile doğrula; yalnız ilgili dosyaları değiştir.
   Gerekirse ayrı `codex/` dalı ve worktree kullan.
3. Testleri geçici kasalarda çalıştır. Kullanıcının gerçek kasasına, global istemci
   ayarlarına veya Mem0'a test amacıyla yazma. Kurulum örnekleri gerçek kullanıcı
   ayarlarını değiştirebilir; salt kod incelemesi kurulum yetkisi değildir.

## Yönerge dosyaları

- `agents.md` kişisel kasa sözleşmesinin şablonudur. Küçük harfli ad kurucu ve
  mevcut kasalar tarafından kullanılır; adını tek başına değiştirme.
- `CLAUDE.md` sözleşmeyi okumaya yönlendiren normal dosyadır; symlink desteği
  gerektirmez. Kuralları burada çoğaltma, tek kaynak `agents.md` olarak kalsın.
- Aynı dizine ayrıca `AGENTS.md` ekleme: yalnız harf büyüklüğüyle ayrılan iki
  ad Windows ve bazı macOS dosya sistemlerinde çakışır. Küçük harfli dosyanın
  her ajan tarafından otomatik keşfedildiğini varsayma. Repo geliştirme
  görevine bu rehberi açıkça dahil et; `araclar/AGENTS.md` kod kapsamını tanımlar.
- Kişisel kullanımın desteklenen yönerge köprüsü `araclar/ajan_kur.py` ile
  kurulur. [Entegrasyon rehberi](ENTEGRASYONLAR.md) kurulum, dry-run ve kaldırmayı açıklar.

## Doğrulama

CI'nin Python 3.12 ortamı Linux, macOS ve Windows'ta aynı standart-kütüphane
test paketini çalıştırır. Python 3.10+ ürün gereksinimidir; yalnız 3.12 CI
sonucunu bütün Python sürümlerinde test edilmiş gibi sunma.

Linux/macOS, depo kökünde:

```sh
python3 -X utf8 -m unittest discover -s araclar -p 'test_*.py'
git diff --check
```

Windows PowerShell, depo kökünde:

```powershell
py -3 -X utf8 -m unittest discover -s araclar -p 'test_*.py'
git diff --check
```

İlgili test dosyasını daha dar çalıştırmak için `-p 'test_ajan_kur.py'` gibi bir
desen kullan. Çıkış kodunu kontrol et; yalnız log oluşması başarı değildir.
Yerel Linux testi macOS/Windows testi yerine geçmez. CI, canlı Claude/Codex/
Antigravity model oturumunu doğrulamaz; fixture, kurulum ve uçtan uca canlı
kanıtları raporda ayrı belirt. Güncel destek sınırları [README](README.md) ve
[entegrasyon matrisinde](ENTEGRASYONLAR.md) tutulur.

## Teslim ve yayın

Değişen davranışı, gerekçesini, çalıştırılan testleri ve kalan sınırları bildir.
Kullanıcı kabulünü test başarısından ayır. Commit, push, merge ve release farklı
adımlardır; istenmeyen bir yayını kod görevinin parçası sayma.

[Yayın rehberi](YAYINLAMA.md) ve `publication-manifest.json` kamu/özel kod
sınırını yönetir. Ortak runtime değişirse eşlik kontrolünü de değerlendir;
manifest hash'lerini hatayı susturmak için yenileme. Yayın doğrulayıcısı temiz,
commit edilmiş ağacı test eder; kirli çalışma ağacındaki testlerin yerine geçmez.
`yayinla.py --apply` main'e gönderir; sıradan doğrulama komutu olarak çalıştırma.
Kasa eşliği özel kasaya erişim gerektirir; katkıcı CI'sinin bunu doğruladığını iddia etme.
