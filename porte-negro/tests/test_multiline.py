import random
import tempfile
import unittest
from pathlib import Path
from corregir import repartir_pesos, localizar_pesos, corregir, gramos

class DistributionTests(unittest.TestCase):
 def test_user_document_proportional(self):
  self.assertEqual(repartir_pesos([500640,579390],980030),[454286,525744])
 def test_rounding_remainder(self):
  self.assertEqual(repartir_pesos([1000,1000,1000],2999),[999,1000,1000])
 def test_many_rows_and_totals_exact(self):
  rng=random.Random(42)
  for _ in range(2000):
   values=[rng.randrange(1,10000000) for _ in range(rng.randrange(1,40))]
   target=rng.randrange(1,sum(values)+1)
   result=repartir_pesos(values,target)
   self.assertEqual(sum(result),target)
   discounts=[v-r for v,r in zip(values,result)]
   self.assertTrue(all(0<=r<=v for v,r in zip(values,result)))
   ordered=sorted(zip(values,discounts))
   self.assertTrue(all(a[1]<=b[1] for a,b in zip(ordered,ordered[1:]) if a[0]<b[0]))
 def test_increase_remains_supported(self):
  self.assertEqual(repartir_pesos([1000,2000],6000),[2000,4000])

class MultiPdfTests(unittest.TestCase):
 def make_source(self,path,groups):
  from reportlab.pdfgen import canvas
  from reportlab.lib.utils import ImageReader
  import qrcode
  c=canvas.Canvas(str(path),pagesize=(842,595))
  c.setFont('Helvetica',10);c.drawString(49,550,'Carburos - DOCUMENTO FICTICIO SIN VALIDEZ')
  c.drawString(482,260,'Peso(KG)')
  y=240; total=0
  for group in groups:
   for value in group:
    c.setFont('Helvetica',8);c.drawRightString(535,y,value);y-=18
   c.drawString(360,y,'Total:')
   subtotal=sum(gramos(v) for v in group);total+=subtotal
   c.drawRightString(535,y,f'{subtotal/1000:.3f}'.replace('.',','));y-=18
  c.setFont('Helvetica-Bold',10);c.drawString(360,y,'Total:');c.drawRightString(535,y,f'{total/1000:.3f}'.replace('.',','))
  c.setFont('Helvetica',8);c.drawString(49,90,'PIE ORIGINAL CONSERVADO')
  c.drawImage(ImageReader(qrcode.make('https://e-transport.airproducts.com/DeCA/PRUEBA-FICTICIA').get_image()),536,519,width=64,height=64)
  c.setFont('Helvetica-Bold',10);c.drawCentredString(568,509,'DeCA');c.save()
 def test_multiline_and_customer_subtotals(self):
  import pymupdf,pdfplumber
  for groups in [[['500,640','579,390']],[['200,000','300,000'],['580,030']]]:
   with self.subTest(groups=groups),tempfile.TemporaryDirectory() as temp:
    source=Path(temp)/'source.pdf';output=Path(temp)/'out.pdf'
    self.make_source(source,groups)
    result=corregir(source,output,'980,030','https://porte-negro.onrender.com/documentos/'+'c'*32+'.pdf')
    with pymupdf.open(output) as pdf:hits=localizar_pesos(pdf[0].get_text('words'))
    self.assertEqual(hits[-1]['grams'],980030)
    self.assertEqual(sum(h['grams'] for h in hits if h['kind']=='item'),980030)
    with pdfplumber.open(output) as pdf:
     text=pdf.pages[0].extract_text()
     self.assertNotIn('RECTIFICACION',text)
     self.assertIn('PIE ORIGINAL CONSERVADO',text)
    self.assertEqual(len(result['partidas_kg']),sum(map(len,groups)))
