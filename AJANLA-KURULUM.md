# Ajanla yönlendirmeli kurulum

Bu yönerge, kullanıcının Hafıza OS kurulum isteğini bilgisayarında dosya ve
terminal erişimi olan bir ajanla yürütmek içindir. README ve baslat.py gerçek
kurulum sözleşmesidir; bu belge ek bir otomasyon veya gizli giriş arayüzü kurmaz.

1. İşletim sistemini, Python 3.10+ erişimini ve mevcut kasa klasörünü kontrol et.
   Kullanıcının mevcut kasasını veya ajan ayarlarını silme. Hedef zaten varsa
   yeni klasör seçimini kullanıcıyla netleştir; mevcut kasaya sıfırdan kurucu çalıştırma.
2. Kullanılan ajanı belirle: Codex, Claude Code veya Antigravity. Kullanıcı
   Codex içindeyse varsayılan Codex olabilir. Kurulumun kasa dosyalarını ve
   ajan yönerge bağlantısını hazırlayacağını açıkla.
3. Sohbette önce Mem0, sonra Jev için kullan / şimdilik atla seçimini sor.
   Kullanacaksa anahtarının olup olmadığını sor; değerini sohbet içinde isteme.
   İki hizmet bağımsız ve isteğe bağlıdır. Yerel hafıza anahtarsız kullanılabilir.
4. Yeni anahtar isteyen kullanıcı için resmi sayfaları tarayıcı aracıyla aç.
   Araç yoksa tıklanabilir bağlantı ver. Giriş, hesap/takım seçimi ve anahtar
   oluşturmayı kullanıcı yapsın; ödeme veya abonelik işlemi yapma.
   - Mem0: https://app.mem0.ai/dashboard/settings?subtab=configuration&tab=api-keys
     Giriş yap → API Keys → anahtar oluştur → kopyala.
   - Jev/Vercel: https://vercel.com/d?title=AI+Gateway+API+Keys&to=%2F%5Bteam%5D%2F~%2Fai-gateway%2Fapi-keys
     Giriş yap → hesap/takım → AI Gateway → API Keys → Create key → kopyala.
   - Güncel Jev fiyatı: https://vercel.com/ai-gateway/models?freeTier=true
     19 Eylül 2026 kontrolünde Free görünüyordu; sürekli ücretsiz veya sınırsız
     kullanım sözü verme. Mevcut TypeSafe anahtarı da desteklenir.
5. README’deki işletim sistemine uygun kurucuyu çalıştır. Anahtar kullanılacaksa
   kullanıcının doğrudan yazabildiği gerçek bir terminal gerekli. Ajanın araç
   oturumuna yalnız ajan yazabiliyorsa bunu gizli kullanıcı giriş ekranı gibi
   sunma: komutu kullanıcının kendi terminalinde çalıştırmasını sağla.
   Anahtarı mesaj, araç argümanı, komut satırı veya log üzerinden taşıma.
   Kurucunun getpass girişi kullanılır; anahtarlar kasa dışında saklanır.
   Her iki hizmet atlanacaksa baslat.py için --non-interactive --agent codex
   kullanılabilir; ajan adını gerçek istemciye göre değiştir. Anahtar istendiği
   halde non-interactive kullanıp bağlantı kurulmuş gibi raporlama.
6. Obsidian yoksa kurucu resmi paketi indirir. Windows/macOS uygulama kurucusunu
   kullanıcı tamamlar; Linux AppImage hazırlanır. Obsidian’da Open folder as
   vault ile oluşturulan kasayı açtır. İndirme hatasını kurulmuş gibi sunma.
7. komuta/kurulum-sonucu.json sonucunu kontrol et. Anahtar dosyalarını okuma
   veya çıktıya dökme. configured_unverified yalnız ayar yapıldığıdır; başarılı
   canlı API çağrısı anlamına gelmez. Atlanan hizmetleri açıkça belirt.
8. Ajanı yeniden başlatıp kasa klasöründe yeni sohbet açmasını ve “agents.md
   dosyasını oku; profilimi birlikte hazırlayalım” yazmasını söyle.
   Otomatik sohbet kaydı ve arka plan incelemesinin ayrı kurulum olduğunu
   KULLANIM.md bağlantısıyla belirt; ilk kurulum bunları kurmuş sayılmaz.
