import unittest
from unittest.mock import patch
from collections import Counter
from corregir import localizar_pesos,contenido_ajeno,qr_origen_admitido,dentro

class PdfReaderTests(unittest.TestCase):
 def words(self,weight='1000,000'):
  return [(482.55,333.82,528.11,343.82,'Peso(KG)',0,0,0),
          (506.338,386.746,539.709,394.746,weight,1,0,0),
          (540.05,384.664,553.028,393.664,'UN',2,0,0),
          (499.45,417.676,532.827,425.676,weight,3,0,0),
          (498.15,429.429,539.871,439.429,weight,4,0,0)]
 def test_adjacent_un_does_not_merge_into_weight(self):
  self.assertEqual([w['text'] for w in localizar_pesos(self.words())],['1000,000']*3)
 def test_mismatched_totals_are_still_rejected(self):
  words=self.words();words[-1]=(*words[-1][:4],'1001,000',4,0,0)
  with self.assertRaises(ValueError):localizar_pesos(words)
 def test_multiple_items_are_still_rejected(self):
  with self.assertRaises(ValueError):localizar_pesos(self.words()+[(505,400,539,408,'1000,000',5,0,0)])
 def test_zero_width_characters_remain_verifiable(self):
  c={'text':'3','x0':523.93,'x1':523.93,'top':415.836,'bottom':423.836}
  self.assertTrue(dentro(c,(499,417,533,426)))
 def test_preservation_ignores_word_segmentation_but_detects_un_related_loss(self):
  chars=[{'text':'U','x0':540,'x1':546,'top':384,'bottom':393},
         {'text':'N','x0':546,'x1':553,'top':384,'bottom':393},
         {'text':'1','x0':506,'x1':510,'top':386,'bottom':395}]
  self.assertEqual(contenido_ajeno(chars,[(505,386,539,395)]),Counter('UN'))
 def test_only_known_source_qr_hosts_are_admitted(self):
  self.assertTrue(qr_origen_admitido('https://drive.google.com/file/d/example_test/view?usp=drivesdk'))
  self.assertTrue(qr_origen_admitido('https://e-transport.airproducts.com/DeCA/example'))
  for url in ['https://drive.google.com.evil.test/file/d/example/view','http://drive.google.com/file/d/example/view','https://evil.test/DeCA/example','https://drive.google.com/other']:
   self.assertFalse(qr_origen_admitido(url))

if __name__=='__main__':unittest.main()
