import os, tempfile, io, asyncio, secrets
from pathlib import Path
from functools import partial
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, Response
from starlette.concurrency import run_in_threadpool
from corregir import corregir, peso_real
from storage import Archive, ArchiveUnavailable, DocumentMissing

app = FastAPI(title='Porte Negro', docs_url=None, redoc_url=None, openapi_url=None)
ROOT = Path(__file__).parent
MAX_BYTES = 15 * 1024 * 1024
processing = asyncio.Semaphore(1)

def public_base():
    value=os.getenv('PUBLIC_BASE_URL',os.getenv('RENDER_EXTERNAL_URL','')).rstrip('/')
    parsed=urlsplit(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ArchiveUnavailable('Falta configurar la dirección pública del archivo digital.')
    return value

@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; form-action 'self'"
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response

@app.get('/')
def home(): return FileResponse(ROOT / 'static/index.html')

@app.get('/static/{name}')
def assets(name: str):
    if name not in {'app.js', 'style.css'}: raise HTTPException(404)
    return FileResponse(ROOT / 'static' / name)

def process(source, folder, weight):
    archive=Archive()
    base=public_base()
    document_id=secrets.token_hex(16)
    link=f'{base}/documentos/{document_id}.pdf'
    final=folder/'carta-rectificada.pdf'
    result=corregir(source,final,weight,link,folder/'preview.png')
    content=final.read_bytes()
    if len(content)>MAX_BYTES:
        raise ValueError('El PDF rectificado supera el tamaño admitido.')
    archive.publish(document_id,content)
    return content,link,result['peso_kg']

async def rectify(pdf, peso, autorizado):
    try:
        if autorizado!='si':raise HTTPException(400,'Debes confirmar que estás autorizado por el expedidor.')
        try:weight=peso_real(peso)
        except ValueError as e:raise HTTPException(400,str(e))
        with tempfile.TemporaryDirectory(prefix='carta-') as temp:
            folder=Path(temp);source=folder/'original.pdf'
            size=0
            with source.open('wb') as target:
                while chunk:=await pdf.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_BYTES:raise HTTPException(413,'El PDF supera los 15 MB.')
                    target.write(chunk)
            with source.open('rb') as original:
                if not original.read(1024).lstrip().startswith(b'%PDF-'):raise HTTPException(400,'El archivo no es un PDF válido.')
            content,link,weight=await run_in_threadpool(partial(process,source,folder,weight))
        return StreamingResponse(io.BytesIO(content),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="carta-rectificada.pdf"','X-Document-URL':link,'X-Peso-Kg':weight})
    except HTTPException:raise
    except ValueError as e:raise HTTPException(422,str(e))
    except ArchiveUnavailable as e:raise HTTPException(503,str(e))
    except Exception:raise HTTPException(502,'No se ha podido completar y verificar la carta. Revisa el PDF o inténtalo más tarde.')
    finally:await pdf.close()

@app.get('/documentos/{document_id}.pdf')
def document(document_id: str):
    try:content=Archive().read(document_id)
    except DocumentMissing:raise HTTPException(404,'Documento no encontrado.')
    except ArchiveUnavailable as e:raise HTTPException(503,str(e),headers={'Retry-After':'30'})
    return Response(content,media_type='application/pdf',headers={'Content-Disposition':'inline; filename="carta-rectificada.pdf"'})

@app.get('/healthz')
def health():return {'status':'ok'}

@app.get('/api/estado')
def readiness():
    try:Archive();public_base();ready=True
    except ArchiveUnavailable:ready=False
    return {'configurado':ready,'mensaje':'Archivo digital configurado; se verificará al generar el PDF.' if ready else 'Estamos preparando el archivo digital. La generación se activará cuando termine la conexión.'}

@app.post('/api/rectificar')
async def queued_rectify(pdf: UploadFile=File(...),peso: str=Form(...),autorizado: str=Form(...)):
    if processing.locked():
        await pdf.close()
        raise HTTPException(429,'Se está procesando otra carta. Inténtalo de nuevo en unos instantes.',headers={'Retry-After':'15'})
    async with processing:return await rectify(pdf,peso,autorizado)
