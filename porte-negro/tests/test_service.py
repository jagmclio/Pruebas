import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from fastapi.testclient import TestClient
import app as service
from storage import Archive,ArchiveUnavailable,DocumentMissing

ENV={'CF_ACCOUNT_ID':'a'*32,'CF_KV_NAMESPACE_ID':'b'*32,'CF_API_TOKEN':'test-only','PUBLIC_BASE_URL':'https://porte-negro.onrender.com'}
class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,ENV);self.env.start();self.client=TestClient(service.app)
 def tearDown(self):self.env.stop()
 def test_public_interface_has_plain_weight_and_no_drive(self):
  response=self.client.get('/');self.assertEqual(response.status_code,200)
  self.assertNotIn('Drive',response.text);self.assertNotIn('Entre 920',response.text)
  self.assertIn('Peso (kg)',response.text);self.assertIn('Arrastra aquí la carta de porte',response.text)
  for path in ['/healthz','/static/app.js','/static/style.css']:self.assertEqual(self.client.get(path).status_code,200)
  self.assertEqual(self.client.get('/static/app.py').status_code,404)
 def test_readiness_requires_durable_storage(self):
  self.assertTrue(self.client.get('/api/estado').json()['configurado'])
  with patch.dict(os.environ,{'CF_API_TOKEN':''}):self.assertFalse(self.client.get('/api/estado').json()['configurado'])
 def test_bad_public_base_is_rejected(self):
  for value in ['http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com/?q=1']:
   with patch.dict(os.environ,{'PUBLIC_BASE_URL':value}):self.assertFalse(self.client.get('/api/estado').json()['configurado'])
 def test_rejects_invalid_inputs_without_publication(self):
  with patch.object(service,'process') as process:
   for weight in ['919.999','990.001','986.1234','abc']:
    r=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'%PDF-1.7\n')},data={'peso':weight,'autorizado':'si'});self.assertEqual(r.status_code,400)
   r=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'invalid')},data={'peso':'986,136','autorizado':'si'});self.assertEqual(r.status_code,400)
   r=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'%PDF-1.7\n')},data={'peso':'986,136','autorizado':'no'});self.assertEqual(r.status_code,400)
   process.assert_not_called()
 def test_pdf_size_limit(self):
  with patch.object(service,'MAX_BYTES',10),patch.object(service,'process') as process:
   r=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'%PDF-1.7\n'+b'x'*20)},data={'peso':'986,136','autorizado':'si'})
   self.assertEqual(r.status_code,413);process.assert_not_called()
 def test_qr_and_public_address_are_the_same_pdf(self):
  archive=MagicMock();captured=[]
  def correct(source,output,weight,link,preview):
   captured.append(link);Path(output).write_bytes(b'%PDF-final');return {'peso_kg':'986,136'}
  with tempfile.TemporaryDirectory() as temp,patch.object(service,'Archive',return_value=archive),patch.object(service,'corregir',side_effect=correct):
   content,link,weight=service.process(Path(temp)/'original.pdf',Path(temp),'986,136')
  self.assertEqual(captured,[link]);self.assertRegex(link,r'^https://porte-negro.onrender.com/documentos/[a-f0-9]{32}\.pdf$')
  archive.publish.assert_called_once_with(link.split('/')[-1][:-4],content)
 def test_digital_pdf_opens_inline_without_signin(self):
  archive=MagicMock();archive.read.return_value=b'%PDF-final'
  with patch.object(service,'Archive',return_value=archive):
   response=self.client.get('/documentos/'+'c'*32+'.pdf')
  self.assertEqual(response.status_code,200);self.assertEqual(response.content,b'%PDF-final')
  self.assertEqual(response.headers['content-type'],'application/pdf');self.assertTrue(response.headers['content-disposition'].startswith('inline'))
  self.assertEqual(response.headers['x-robots-tag'],'noindex, nofollow, noarchive')
 def test_missing_or_unsynced_document(self):
  archive=MagicMock()
  with patch.object(service,'Archive',return_value=archive):
   archive.read.side_effect=DocumentMissing();self.assertEqual(self.client.get('/documentos/'+'c'*32+'.pdf').status_code,404)
   archive.read.side_effect=ArchiveUnavailable('Pendiente');self.assertEqual(self.client.get('/documentos/'+'c'*32+'.pdf').status_code,503)

class ArchiveTests(unittest.TestCase):
 def setUp(self):self.env=patch.dict(os.environ,ENV);self.env.start();self.archive=Archive();self.data={};self.operations=[]
 def tearDown(self):self.env.stop()
 def fake_request(self,method,key,content=None):
  self.operations.append((method,key))
  if method=='PUT':self.data[key]=content;return b''
  if method=='DELETE':self.data.pop(key,None);return b''
  if key not in self.data:raise DocumentMissing()
  return self.data[key]
 def test_only_verified_bytes_are_published(self):
  with patch.object(self.archive,'_request',side_effect=self.fake_request):
   self.archive.publish('c'*32,b'%PDF-final');self.assertEqual(self.archive.read('c'*32),b'%PDF-final')
  self.assertLess(self.operations.index(('GET','pdf:'+'c'*32)),self.operations.index(('PUT','published:'+'c'*32)))
 def test_corrupt_bytes_never_publish(self):
  def corrupt(method,key,content=None):
   if method=='GET' and key.startswith('pdf:'):return b'corrupt'
   return self.fake_request(method,key,content)
  with patch.object(self.archive,'_request',side_effect=corrupt):
   with self.assertRaises(ArchiveUnavailable):self.archive.publish('c'*32,b'%PDF-final')
  self.assertNotIn(('PUT','published:'+'c'*32),self.operations)
  self.assertEqual(self.data,{})
 def test_unpublished_bytes_are_not_readable(self):
  self.data['pdf:'+'c'*32]=b'%PDF-final'
  with patch.object(self.archive,'_request',side_effect=self.fake_request):
   with self.assertRaises(DocumentMissing):self.archive.read('c'*32)
 def test_path_traversal_is_rejected_before_network_access(self):
  with patch.object(self.archive,'_request') as request:
   with self.assertRaises(DocumentMissing):self.archive.read('../secrets')
   request.assert_not_called()

if __name__=='__main__':unittest.main()
