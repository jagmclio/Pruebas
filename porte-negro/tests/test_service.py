import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import app as service

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.credentials = self.folder / 'google-drive.json'
        self.credentials.write_text(json.dumps({'type':'authorized_user','refresh_token':'test','client_id':'test','client_secret':'test'}))
        self.env = patch.dict(os.environ, {'GOOGLE_APPLICATION_CREDENTIALS':str(self.credentials),'DRIVE_FOLDER_ID':''})
        self.env.start()
        self.client = TestClient(service.app)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_public_interface_and_health(self):
        for path in ['/', '/static/app.js', '/static/style.css','/healthz']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('www-authenticate',response.headers)
        self.assertIn('Arrastra aquí la carta de porte que deseas modificar',self.client.get('/').text)
        self.assertEqual(self.client.get('/static/app.py').status_code,404)

    def test_readiness_without_and_with_owner_credentials(self):
        self.assertTrue(self.client.get('/api/estado').json()['configurado'])
        self.credentials.unlink()
        self.assertFalse(self.client.get('/api/estado').json()['configurado'])

    def test_rejects_weight_and_non_pdf_without_drive_mutations(self):
        with patch.object(service,'process') as process:
            for weight in ['919.999','990.001','986.1234','abc']:
                response=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'%PDF-1.7\n')},data={'peso':weight,'autorizado':'si'})
                self.assertEqual(response.status_code,400)
            response=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'not a PDF')},data={'peso':'986,136','autorizado':'si'})
            self.assertEqual(response.status_code,400)
            response=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'%PDF-1.7\n')},data={'peso':'986,136','autorizado':'no'})
            self.assertEqual(response.status_code,400)
            process.assert_not_called()

    def test_upload_limit(self):
        with patch.object(service,'MAX_BYTES',10), patch.object(service,'process') as process:
            response=self.client.post('/api/rectificar',files={'pdf':('x.pdf',b'%PDF-1.7\n'+b'x'*20)},data={'peso':'986,136','autorizado':'si'})
            self.assertEqual(response.status_code,413)
            process.assert_not_called()

    def mock_drive(self):
        drive=MagicMock()
        drive.files.return_value.create.return_value.execute.return_value={'id':'test_id','webViewLink':'https://drive.google.com/file/d/test_id/view'}
        drive.files.return_value.get_media.return_value.execute.return_value=b'final'
        drive.permissions.return_value.list.return_value.execute.return_value={'permissions':[{'type':'anyone','role':'reader'}]}
        return drive

    def correction(self, source, output, weight, url=None, preview=None):
        Path(output).write_bytes(b'final' if url else b'draft')
        return {'peso_kg':'986,136'}

    def run_process(self, drive):
        source=self.folder/'source.pdf';source.write_bytes(b'%PDF-1.7\n')
        with patch.object(service.google.auth,'load_credentials_from_file',return_value=(MagicMock(),None)), patch.object(service.google_auth_httplib2,'AuthorizedHttp'), patch.object(service,'build',return_value=drive), patch.object(service,'corregir',side_effect=self.correction):
            return service.process(source,self.folder,'986,136')

    def test_self_reference_publishes_only_after_same_id_is_updated(self):
        drive=self.mock_drive()
        content,link,weight=self.run_process(drive)
        self.assertEqual(content,b'final')
        self.assertEqual(link,'https://drive.google.com/file/d/test_id/view')
        self.assertEqual(weight,'986,136')
        self.assertEqual(drive.files.return_value.create.call_count,1)
        update=drive.files.return_value.update.call_args.kwargs
        self.assertEqual(update['fileId'],'test_id')
        self.assertEqual(drive.permissions.return_value.create.call_args.kwargs['fileId'],'test_id')
        self.assertNotIn('parents',drive.files.return_value.create.call_args.kwargs['body'])
        names=[call[0] for call in drive.mock_calls]
        self.assertLess(names.index('files().update'),names.index('permissions().create'))
        self.assertLess(names.index('files().get_media().execute'),names.index('permissions().create'))

    def test_failed_byte_verification_never_publishes(self):
        drive=self.mock_drive();drive.files.return_value.get_media.return_value.execute.return_value=b'draft'
        with self.assertRaises(RuntimeError):self.run_process(drive)
        drive.permissions.return_value.create.assert_not_called()
        drive.files.return_value.delete.assert_called_once_with(fileId='test_id',supportsAllDrives=True)

    def test_failed_sharing_verification_does_not_deliver_final(self):
        drive=self.mock_drive();drive.permissions.return_value.list.return_value.execute.return_value={'permissions':[]}
        with self.assertRaises(RuntimeError):self.run_process(drive)
        drive.files.return_value.delete.assert_called_once()

if __name__=='__main__':unittest.main()
