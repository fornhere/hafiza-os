# Kaynaklı konu sentezi

Konu sentezi, incelenmiş bilgi kartlarını kaynakları ve kapsamlarıyla bir araya
getiren türetilmiş bir görünümdür. Yeni kullanıcı tercihi veya bağımsız kanonik
kayıt değildir. Bu sürüm çıkarımsal bir model özeti yerine mevcut ifadeleri
birleştirir; otomatik çelişki çözümü veya anlamsal arama iddiası taşımaz.

Görev bağlamı açık bir konu özeti istendiğinde bu görünümü kullanır. Olağan
arama ve alanlar arası uyarlama mevcut bilgi ağı davranışını korur. Kaynaklar
her okumada doğrulanır; değişmiş, incelenmemiş veya başka proje kapsamındaki
kayıtlar özete katılmaz. Bağlama sığmayan bilgi teslim edilmiş sayılmaz.

Obsidian için dışa aktarılan Markdown bir anlık görüntüdür. Güncel karar
gerektiğinde görev bağlamı veya sentez aracı yeniden çalıştırılır; dışa
aktarılmış sayfa aramanın doğruluk kaynağı olarak kullanılmaz.

## Ölçüm sözleşmesi

Önce ve sonra aynı kaynak sürümü, aynı sorular ve aynı karakter bütçesiyle
ölçülmelidir. Kaynağın gerçekten bulunması, soruya doğru cevap verilmesi ve
çıktının kullanıcıya faydası ayrı ölçütlerdir. Sorular gerçek kaynaklardan
yazılmış olabilir; bu onları gerçek kullanıcı sorgu kayıtları yapmaz.

Beklenen kaynakların bulunma oranı yanında gereksiz kaynaklar, cevabı olmayan
sorular, alanlar arası önerilerin onaylı tercih sayılmaması, eski kaynak ve
bütçe davranışı incelenmelidir. Küçük bir örnek kümesindeki artış, bütün
hafızanın kalitesine veya zaman tasarrufuna genellenmez.

Kişisel soru kümelerini ve kaynak kopyalarını kamu deposuna koymayın. Burada
yayınlanan testler sentetik kaynaklarla güvenlik ve entegrasyon davranışını
kontrol eder; kişisel pilot ayrı çalışma dizininde tutulur.

## Kullanım

```sh
python3 araclar/konu_sentezi.py --vault KASA build --format markdown
python3 araclar/konu_sentezi.py --vault KASA retrieve 'anlatım tercihlerimi özetle'
python3 araclar/konu_sentezi.py --vault KASA export --apply
python3 araclar/konu_sentezi.py --vault KASA export --project-id PROJE --apply
```

`export` yalnız aracın yönettiği sayfayı günceller; elle değişmiş sayfayı
üzerine yazarak kaybetmez. Kullanıcı kapsamı `bilgi/konu-sentezleri/user.md`,
proje kapsamı `bilgi/konu-sentezleri/project-PROJE.md` altında tutulur.
İlk sürümün konu yönlendirmesi sınırlı kelime kurallarıdır; anlamsal arama
yerine geçmez. Çalışma yöntemi konusunda uygun kart yoksa bilgi uydurulmaz.
