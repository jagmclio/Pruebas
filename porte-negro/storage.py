"""Persistent PDF archive in Cloudflare KV. No document bytes are stored in GitHub."""
import hashlib
import json
import os
import re
from urllib.parse import quote
import requests

class ArchiveUnavailable(Exception):
    pass

class DocumentMissing(Exception):
    pass

class Archive:
    def __init__(self):
        account=os.getenv('CF_ACCOUNT_ID','')
        namespace=os.getenv('CF_KV_NAMESPACE_ID','')
        token=os.getenv('CF_API_TOKEN','')
        if not re.fullmatch(r'[a-fA-F0-9]{32}',account) or not re.fullmatch(r'[a-fA-F0-9]{32}',namespace) or not token:
            raise ArchiveUnavailable('Falta conectar el archivo digital permanente.')
        self.base=f'https://api.cloudflare.com/client/v4/accounts/{account}/storage/kv/namespaces/{namespace}/values/'
        self.headers={'Authorization':f'Bearer {token}'}

    def _request(self,method,key,content=None):
        try:
            response=requests.request(method,self.base+quote(key,safe=''),headers={**self.headers,'Content-Type':'application/octet-stream'},data=content,timeout=(10,60),allow_redirects=False)
        except requests.RequestException:
            raise ArchiveUnavailable('El archivo digital no responde. Inténtalo más tarde.') from None
        if response.status_code==404 and method=='GET':raise DocumentMissing()
        if not 200<=response.status_code<300:
            raise ArchiveUnavailable('No se ha podido acceder al archivo digital.')
        return response.content

    @staticmethod
    def validate_id(document_id):
        if not re.fullmatch(r'[a-f0-9]{32}',document_id):raise DocumentMissing()

    def publish(self,document_id,content):
        self.validate_id(document_id)
        key=f'pdf:{document_id}'
        marker=f'published:{document_id}'
        digest=hashlib.sha256(content).hexdigest()
        try:
            self._request('PUT',key,content)
            # A separate publication marker keeps incomplete uploads inaccessible.
            if hashlib.sha256(self._request('GET',key)).hexdigest()!=digest:
                raise ArchiveUnavailable('La copia guardada no coincide con el PDF final.')
            self._request('PUT',marker,json.dumps({'sha256':digest}).encode())
            if self.read(document_id)!=content:
                raise ArchiveUnavailable('No se ha podido verificar el documento publicado.')
        except Exception:
            # Each new key is unpredictable. No overwrite or automatic retry creates duplicates.
            for item in [marker,key]:
                try:self._request('DELETE',item)
                except Exception:pass
            raise

    def read(self,document_id):
        self.validate_id(document_id)
        marker=json.loads(self._request('GET',f'published:{document_id}'))
        try:content=self._request('GET',f'pdf:{document_id}')
        except DocumentMissing:
            raise ArchiveUnavailable('El documento todavía se está sincronizando.') from None
        if hashlib.sha256(content).hexdigest()!=marker.get('sha256'):
            raise ArchiveUnavailable('El documento todavía no está disponible de forma íntegra.')
        return content
