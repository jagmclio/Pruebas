#!/usr/bin/env python3
"""Rectifica el peso total de cartas Carburos/Air Products del formato verificado."""
import argparse, io, json, re
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pdfplumber
import pymupdf as fitz
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import qrcode
import zxingcpp
from PIL import Image

def peso_real(value):
    value=value.strip().removesuffix('kg').strip()
    if not re.fullmatch(r'\d{3}(?:[,.]\d{1,3})?',value):
        raise ValueError('Introduce el peso real en kg, sin separador de miles y con hasta 3 decimales.')
    weight=Decimal(value.replace(',','.'))
    if not Decimal('920') <= weight <= Decimal('990'):
        raise ValueError('El peso real debe estar entre 920 y 990 kg. No se ha modificado el documento.')
    return f'{weight:.3f}'.replace('.',',')

def corregir(source,output,weight,url=None,preview=None):
    weight=peso_real(weight)
    source,output=Path(source),Path(output)
    if source.resolve()==output.resolve(): raise ValueError('El original debe conservarse.')
    with pdfplumber.open(source) as pdf:
        if len(pdf.pages)!=1: raise ValueError('Formato no admitido: se requiere una sola pagina.')
        page=pdf.pages[0]; text=page.extract_text() or ''; words=page.extract_words()
        if abs(page.width-842)>1 or abs(page.height-595)>1 or 'Carburos' not in text or 'Peso(KG)' not in text:
            raise ValueError('Formato distinto del validado: necesita revision antes de editar.')
        if 'RECTIFICACION:' in text: raise ValueError('Selecciona el original, no una copia ya rectificada.')
        headers=[w for w in words if w['text']=='Peso(KG)']
        if len(headers)!=1: raise ValueError('No se identifica una unica columna de peso.')
        h=headers[0]
        hits=[w for w in words if w['top']>h['bottom'] and h['x0']-6<=w['x0']<=h['x1'] and re.fullmatch(r'[\d.,]+',w['text']) and w['x1']<=h['x1']+20]
        if len(hits)!=3 or len({w['text'] for w in hits})!=1:
            raise ValueError('Se esperaban una partida y dos totales iguales. Necesita revision manual.')
        source_image=page.to_image(resolution=216).original
    codes=zxingcpp.read_barcodes(source_image)
    if len(codes)!=1: raise ValueError('No se identifica un unico QR original.')
    original_qr=codes[0].text
    if not original_qr.startswith('https://e-transport.airproducts.com/DeCA/'):
        raise ValueError('El QR no corresponde al formato de carta validado.')
    if url and not re.fullmatch(r'https://drive\.google\.com/file/d/[A-Za-z0-9_-]+/view(?:\?[^\s]*)?',url):
        raise ValueError('El QR nuevo requiere la URL verificada del archivo en Drive.')
    doc=fitz.open(source)
    if doc.get_sigflags()>0: raise ValueError('El PDF contiene firmas digitales; requiere un flujo de reemision.')
    p=doc[0]
    for w in hits:
        gray=w['top']==max(v['top'] for v in hits)
        p.add_redact_annot(fitz.Rect(w['x0']-.3,w['top']-.2,w['x1']+.3,w['bottom']+.2),fill=(.9,.9,.9) if gray else (1,1,1))
    p.add_redact_annot(fitz.Rect(536,14,600,90),fill=(1,1,1))
    p.apply_redactions(images=2,graphics=0)
    buffer=io.BytesIO(); c=canvas.Canvas(buffer,pagesize=(842,595))
    for w in hits:
        size=10 if w['top']==max(v['top'] for v in hits) else 8
        c.setFont('Helvetica-Bold' if size==10 else 'Helvetica',size)
        c.drawRightString(w['x1'],595-w['bottom']+size*.207,weight)
    date=datetime.now(ZoneInfo('Europe/Madrid')).strftime('%d/%m/%Y')
    c.setFont('Helvetica',8)
    c.drawString(49,128,f'RECTIFICACION: peso total corregido a {weight} kg por indicacion del expedidor. {date}.')
    if url:
        qr=qrcode.make(url,box_size=10,border=4)
        c.drawImage(ImageReader(qr.get_image()),536,519,width=64,height=64)
        c.setFont('Helvetica-Bold',10);c.drawCentredString(568,509,'DeCA')
    else:
        c.setFont('Helvetica',6);c.drawCentredString(568,548,'QR pendiente de Drive')
    c.save(); overlay=fitz.open(stream=buffer.getvalue(),filetype='pdf');p.show_pdf_page(p.rect,overlay,0)
    output.parent.mkdir(parents=True,exist_ok=True)
    doc.save(output,garbage=4,deflate=True)
    with pdfplumber.open(output) as pdf:
        final=pdf.pages[0].extract_text() or ''
        result=pdf.pages[0].to_image(resolution=216).original
        newwords=pdf.pages[0].extract_words()
        old_unchanged=[w['text'] for w in words if w not in hits and w['text']!='DeCA']
        new_unchanged=[w['text'] for w in newwords if w['top']<455 and w['text'] not in (weight,'DeCA') and not (536<=w['x0']<=600 and w['top']<90)]
        # Word order can change after redaction; compare the multiset of retained original content.
        from collections import Counter
        if Counter(old_unchanged)!=Counter(new_unchanged):
            output.unlink(); raise ValueError('La verificacion detecto cambios ajenos al peso y QR. Se cancela la salida.')
        found=zxingcpp.read_barcodes(result)
        if url and (len(found)!=1 or found[0].text!=url):
            output.unlink(); raise ValueError('El QR final no supera la comprobacion.')
    if preview: result.save(preview)
    return {'output':str(output.resolve()),'peso_kg':weight,'peso_anterior':hits[0]['text'],'qr_original':original_qr,'qr_nuevo':url,'estado':'final' if url else 'borrador_pendiente_de_qr'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--peso',required=True);parser.add_argument('--drive-url');parser.add_argument('--preview')
    args=parser.parse_args()
    try: print(json.dumps(corregir(args.input,args.output,args.peso,args.drive_url,args.preview),ensure_ascii=False))
    except (ValueError,InvalidOperation) as e: parser.exit(2,str(e)+'\n')
