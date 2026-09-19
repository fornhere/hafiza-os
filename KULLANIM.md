# Hafıza OS kullanım rehberi

Amaç, her yeni sohbette kendini ve projenin geçmişini baştan anlatmak zorunda
kalmaman. Ajan gereken notları senin bilgisayarındaki kasadan okur.
Başlamak için Mem0, Jev veya bir API anahtarı gerekmez.

## 1. Kasayı hazırla ve ajanı bağla

[README'deki indirme ve kurulum adımlarını](README.md#ilk-kez-kullanıyorsan)
uygula. “Kasa” dediğimiz, içinde `agents.md`, `araclar` ve `zihin` bulunan
klasördür. ZIP'ten çıkan dış klasörü değil, bu dosyaların bulunduğu klasörü aç.
Klasörü kişisel belgelerinin yanında kalıcı bir konumda tut.

Yalnız kullandığın ajan için kurulum yap. Birden fazla ajan kullanıyorsan aynı
kasada komutu her ajan için tekrarlayabilirsin. Ajanın yerel dosyaları okuyup
yazabilmesi ve terminal komutlarını çalıştırabilmesi gerekir. Sadece web sohbetine
bu deponun bağlantısını göndermek, bilgisayarındaki kasaya erişim sağlamaz.

## 2. İlk sohbet: kendini ve çalışma biçimini tanıt

Ajanı yeniden başlat, kasa klasörünü aç ve şu mesajı gönder:

> Bu klasör benim hafıza kasam. agents.md dosyasını oku, açılış sırasını izle.
> zihin/çekirdek.md içindeki başlıklar için bana tek tek kısa sorular sor.
> Paylaşmak istemediğim soruları geç. Cevaplarımdan bir taslak çıkar ve
> onayladığım bilgileri bu dosyaya yaz. Bilmediğin alanları boş bırak.

Ardından ajanın nasıl davranmasını istediğini söyle:

> Kısa ve doğrudan cevaplar istiyorum. Teknik konularda önce sonucu, sonra
> gerekçeyi anlat. Bu çalışma biçimini zihin/ruh.md için taslak haline getir.

Bunlar örnek tercihler; kendi istediğin davranışı tarif et.
`zihin/çekirdek.md` seni, `zihin/ruh.md` ajanla çalışma biçimini anlatır.
`agents.md` ise izinler ve kayıt düzeni gibi kuralları içerir. Bu dosyaları
bir metin editöründe veya Obsidian'da açabilirsin. Yazılanları okuyup doğrula.
Şifre veya anahtarları profil dosyalarına koyma.

## 3. Bir gerçek işle başla

Örneğin bir video hazırlıyorsan:

> Bir eğitim videosu hazırlıyorum. Konusu [konu], hedef kitlesi [kitle].
> Önce kasadaki ilgili tercihlerimi oku. Sonra birlikte bir taslak çıkaralım.
> Kesinleşen kararlarla önerileri ayrı tut.

Sonraki sohbette:

> Video projesinde nerede kaldık? Kasadaki ilgili notları bul, kaynağını ve
> tarihini göster. Son kararımızı ve sıradaki adımı kısaca söyle.

Henüz proje notu yoksa ajan geçmiş karar uydurmamalı. İlk işin sonunda proje
notu hazırlanmasını isteyebilirsin:

> Bu işin amacını, kesinleşen kararlarını ve kalan adımını projeler/ altında
> bir not için taslakla. Onayladığım metni dosyaya yaz ve yolunu göster.

Bu açık dosya yazma isteğiyle tuttuğun proje notudur. Otomatik sohbet kaydı
ayrı kurulur; aşağıdaki bölüme bak.

## 4. Çalıştığını yeni sohbette dene

İlk sohbeti kapatmadan önce profil dosyana gerçekten yazılmış, hassas olmayan
bir tercihi kontrol et. Sonra **yeni bir sohbet** aç ve cevabı mesajında vermeden sor:

> Kasadaki profilime göre bana nasıl cevap vermelisin? Dayandığın dosyayı ve
> ilgili ifadeyi göster.

Gösterilen dosyayı kendin aç. Doğru bilgiye doğru kaynaktan ulaşması bu denemenin
başarı ölçütüdür. Sadece “seni hatırlıyorum” demesi yeterli değildir.

Aynı kasaya bağladığın başka bir ajanda da bu soruyu sorabilirsin. Ajanlar
ortak dosyaları okuyabilir; bir ajandaki bütün sohbet diğerine taşınmaz.

## 5. İstersen sohbet kaydını ekle

Temel kurulum notlara erişim içindir. Claude Code ve Antigravity için
`--with-hooks` oturum adaylarını yakalayan bağlantıları ekler. Adayların
kullanılabilir oturum özetine dönüşmesi için ayrıca inceleyici gerekir.
Codex'in kayıt ve konsolidasyon yolu [Codex rehberinde](CODEX.md) anlatılır.

Ajana şu kurulumu yaptırabilirsin:

> Bu kasada kullandığım ajan [ajan adı]. ENTEGRASYONLAR.md dosyasını oku.
> Mevcut kurulumu kontrol et; sessiz oturum kaydı için gereken değişiklikleri
> plan olarak göster. İnceleyici için kullanabileceğim kurulu sağlayıcıları
> belirle; eksik sağlayıcıyı veya zamanlayıcıyı kurulmuş varsayma.

Komutları kendin uygulamak istersen [kurulum adımları](ENTEGRASYONLAR.md#kur-ve-denetle)
ve [aday inceleme akışı](ENTEGRASYONLAR.md#pending--packet--review--recall) hazır.
İnceleme komutlarındaki örnek sağlayıcı yolunu kendi sağlayıcınla değiştir.

İlk beş gerçek kullanıcı mesajı oturum adayı üretmez. Sonraki anlamlı,
tamamlanmış işler incelemeye aday olabilir; her mesaj kalıcı hafıza olmaz.
Kurucu düzenli inceleme zamanlayıcısı kurmaz. Ajanın “bağlantılar kuruldu”
demesi, incelemenin ve arka plan kaydının çalıştığı anlamına gelmez.

## Takılırsan

| Gördüğün durum | Ne yapmalısın? |
|---|---|
| `python3` veya `py` bulunamadı | Python 3.10+ kur; terminali yeniden açıp sürüm komutunu dene. |
| `araclar/ajan_kur.py` bulunamadı | Terminalde `agents.md` ve `araclar` bulunan kasa klasörüne geç. |
| Yeni sohbet kasayı bulamıyor | Kasayı çalışma klasörü olarak aç; ajana tam yolunu ver, kurulumun aynı ajan için yapıldığını kontrol et. |
| Ajan eski bir bilgi söylüyor | Kaynak dosyasını ve tarihini iste; güncel bilgiyi söyleyip düzeltme taslağı hazırlat. |
| Sohbetten kayıt oluşmadı | Temel kurulum ile kayıt kurulumunu ayır; hook ve inceleyici durumunu entegrasyon rehberiyle kontrol et. |
| Kurulum çatışma bildiriyor | Raporu ajana göster; rehberdeki eski kurulumdan geçiş adımlarını uygula. Ayar dosyasını tümden silme. |

Kasayı taşımadan önce [kaldırma ve yeniden kurma](ENTEGRASYONLAR.md#kaldır)
adımlarını izle. Kişisel dosyalarını yedekle; şablon güncellemesi yaparken
`zihin`, `projeler` ve günlük notlarının üzerine boş şablonları kopyalama.
