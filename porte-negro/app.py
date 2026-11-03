import os, tempfile, io, asyncio, json, logging
from pathlib import Path
from functools import partial
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
import google.auth
import httplib2
import google_auth_httplib2
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from corregir import corregir, peso_real

app = FastAPI(title='Porte Negro', docs_url=None, redoc_url=None, openapi_url=None)
ROOT = Path(__file__).parent
MAX_BYTES = 15 * 1024 * 1024
processing = asyncio.Semaphore(1)
logger = logging.getLogger(__name__)

@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; form-action 'self'"
    return response

@app.get('/')
def home(): return FileResponse(ROOT / 'static/index.html')

@app.get('/static/{name}')
def assets(name: str):
    if name not in {'app.js', 'style.css'}: raise HTTPException(404)
    return FileResponse(ROOT / 'static' / name)

def process(source, folder, weight):
    credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '/etc/secrets/google-drive.json')
    drive_folder = os.getenv('DRIVE_FOLDER_ID', '').strip()
    if not Path(credentials_path).is_file():
        raise HTTPException(503, 'El propietario debe conectar su cuenta de Google Drive.')
    with open(credentials_path) as config_file:
        config = json.load(config_file)
    oauth = config.get('type') == 'authorized_user'
    if not oauth and not drive_folder:
        raise HTTPException(503, 'Una cuenta de servicio necesita una carpeta en una unidad compartida.')
    scopes = ['https://www.googleapis.com/auth/drive.file'] if oauth else ['https://www.googleapis.com/auth/drive']
    credentials, _ = google.auth.load_credentials_from_file(credentials_path, scopes=scopes)
    transport = google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=60))
    drive = build('drive', 'v3', http=transport, cache_discovery=False)
    draft, final = folder / 'borrador.pdf', folder / 'carta-rectificada.pdf'
    corregir(source, draft, weight)
    file_id = None
    try:
        created = drive.files().create(body={'name': 'Carta rectificada.pdf', **({'parents': [drive_folder]} if drive_folder else {})}, media_body=MediaFileUpload(str(draft), mimetype='application/pdf'), fields='id,webViewLink', supportsAllDrives=True).execute()
        file_id = created['id']
        link = created.get('webViewLink')
        if not link:
            link = drive.files().get(fileId=file_id, fields='webViewLink', supportsAllDrives=True).execute().get('webViewLink')
        if not link: raise RuntimeError('Drive no devolvió el enlace del archivo.')
        result = corregir(source, final, weight, link, folder / 'preview.png')
        drive.files().update(fileId=file_id, media_body=MediaFileUpload(str(final), mimetype='application/pdf'), fields='id,size', supportsAllDrives=True).execute()
        # Verify the exact final bytes before enabling link access.
        if drive.files().get_media(fileId=file_id, supportsAllDrives=True).execute() != final.read_bytes():
            raise RuntimeError('No se ha podido verificar la copia final de Drive.')
        drive.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader', 'allowFileDiscovery': False}, supportsAllDrives=True).execute()
        permissions = drive.permissions().list(fileId=file_id, fields='permissions(type,role)', supportsAllDrives=True).execute()
        if not any(p.get('type') == 'anyone' and p.get('role') == 'reader' for p in permissions.get('permissions', [])):
            raise RuntimeError('No se ha confirmado el permiso de lectura por enlace.')
        return final.read_bytes(), link, result['peso_kg']
    except Exception:
        if file_id:
            try: drive.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            except Exception: logger.error('No se pudo limpiar la copia nueva de Drive; revisar archivos recientes.')
        raise

async def rectify(pdf: UploadFile = File(...), peso: str = Form(...), autorizado: str = Form(...)):
    if autorizado != 'si': raise HTTPException(400, 'Debes confirmar que estás autorizado por el expedidor.')
    try: weight = peso_real(peso)
    except ValueError as e: raise HTTPException(400, str(e))
    try:
        with tempfile.TemporaryDirectory(prefix='carta-') as temp:
            folder = Path(temp); source = folder / 'original.pdf'
            size = 0
            with source.open('wb') as target:
                while chunk := await pdf.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES: raise HTTPException(413, 'El PDF supera los 15 MB.')
                    target.write(chunk)
            with source.open('rb') as original:
                if not original.read(1024).lstrip().startswith(b'%PDF-'): raise HTTPException(400, 'El archivo no es un PDF válido.')
            content, link, weight = await run_in_threadpool(partial(process, source, folder, weight))
        return StreamingResponse(io.BytesIO(content), media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="carta-rectificada.pdf"', 'X-Drive-URL': link, 'X-Peso-Kg': weight})
    except HTTPException: raise
    except ValueError as e: raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(502, 'No se completó la operación. Revisa la configuración de Drive y sus archivos recientes antes de reintentar.')
    finally: await pdf.close()

@app.get('/healthz')
def health():
    return {'status': 'ok'}

@app.get('/api/estado')
def readiness():
    credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '/etc/secrets/google-drive.json')
    ready = False
    try:
        config = json.loads(Path(credentials_path).read_text())
        ready = bool(config.get('type') == 'authorized_user' and config.get('refresh_token') and config.get('client_id') and config.get('client_secret')) or bool(config.get('type') == 'service_account' and config.get('private_key') and os.getenv('DRIVE_FOLDER_ID'))
    except (OSError, ValueError):
        pass
    return {'configurado': ready, 'mensaje': 'Conexión configurada; se comprobará al generar el PDF.' if ready else 'El propietario todavía tiene que conectar Google Drive. La rectificación estará disponible cuando termine la configuración.'}

@app.post('/api/rectificar')
async def queued_rectify(pdf: UploadFile = File(...), peso: str = Form(...), autorizado: str = Form(...)):
    if processing.locked():
        await pdf.close()
        raise HTTPException(429, 'Se está procesando otra carta. Inténtalo de nuevo en unos instantes.', headers={'Retry-After': '15'})
    async with processing:
        return await rectify(pdf, peso, autorizado)
