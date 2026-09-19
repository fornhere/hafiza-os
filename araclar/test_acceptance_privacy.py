import unittest
import capture_source as c

class AcceptancePrivacy(unittest.TestCase):
    def test_acceptance_qualifier_is_not_privacy(self):
        phrase = "bunu benim kabul ettiğim karar olarak kaydetme"
        self.assertFalse(c.privacy_ambiguous("Bir ekran öner; " + phrase + ". Henüz kodlama."))
        for suffix in (" Bu oturumu kaydetme.", " Şu bilgiyi hafızaya alma.", " Bunu kaydetme."):
            with self.subTest(suffix=suffix):
                self.assertTrue(c.privacy_ambiguous(phrase + "." + suffix))
        self.assertTrue(c.privacy_ambiguous(phrase + " ve hiçbir yerde saklama."))
        self.assertTrue(c.privacy_ambiguous("Bunu karar olarak kaydetme."))

if __name__ == "__main__":
    unittest.main()
