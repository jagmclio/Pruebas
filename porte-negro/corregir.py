#!/usr/bin/env python3
"""Rectifica el peso total de cartas Carburos/Air Products del formato verificado."""
import argparse, io, json, re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
import pdfplumber
import pymupdf as fitz
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
import qrcode
import zxingcpp
from PIL import Image

PROCESSING_MARKER='PorteNegroProcessedV1'

def peso_real(value):
    value=value.strip().removesuffix('kg').strip()
    if not re.fullmatch(r'\d+(?:[,.]\d{1,3})?',value):
        raise ValueError('Introduce el peso real en kg, sin separador de miles y con hasta 3 decimales.')
    weight=Decimal(value.replace(',','.'))
    if not weight.is_finite() or weight<=0:
        raise ValueError('Introduce un peso positivo en kg, con hasta 3 decimales.')
    return f'{weight:.3f}'.replace('.',',')

def qr_origen_admitido(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.fragment:
        return False
    if parsed.hostname=='e-transport.airproducts.com':
        return parsed.path.startswith('/DeCA/')
    if parsed.hostname=='drive.google.com':
        return bool(re.fullmatch(r'/file/d/[A-Za-z0-9_-]+/view',parsed.path))
    if parsed.hostname=='porte-negro.onrender.com':
        return bool(re.fullmatch(r'/documentos/[a-f0-9]{32}\.pdf',parsed.path))
    return False


def gramos(text):
    """Parse printed Spanish weights exactly, never using binary floats."""
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,3})?',text):
        raise ValueError('No se reconoce un peso del documento.')
    return int(Decimal(text.replace('.','').replace(',','.'))*1000)


def texto_peso(value):
    return f'{value//1000},{value%1000:03d}'


def repartir_pesos(values,target):
    """Apportion the difference in integer grams; largest remainders close it."""
    total=sum(values)
    if not values or total<=0 or any(v<0 for v in values) or target<=0:
        raise ValueError('No se puede repartir el peso entre las partidas.')
    difference=abs(total-target)
    changes=[difference*v//total for v in values]
    pending=difference-sum(changes)
    order=sorted(range(len(values)),key=lambda i:(difference*values[i]%total,values[i],-i),reverse=True)
    for i in order[:pending]: changes[i]+=1
    result=[v-change if target<total else v+change for v,change in zip(values,changes)]
    if sum(result)!=target or any(v<0 for v in result):
        raise ValueError('El reparto no coincide con el peso total indicado.')
    return result


def pesos_de_pagina(words):
    """Locate gross weights and total labels on a single page."""
    headers=[w for w in words if w[4]=='Peso(KG)']
    if len(headers)!=1: raise ValueError('No se identifica una unica columna de peso.')
    h=headers[0]
    hits=[{'text':w[4],'x0':w[0],'top':w[1],'x1':w[2],'bottom':w[3]}
          for w in words if w[1]>h[3] and h[0]-6<=w[0]<=h[2]
          and re.fullmatch(r'[\d.,]+',w[4]) and w[2]<=h[2]+20]
    hits.sort(key=lambda w:w['top'])
    labels=[w for w in words if w[4]=='Total:' and w[1]>h[3] and w[2]<h[0]]
    totals=[i for i,hit in enumerate(hits) if any(
        abs((hit['top']+hit['bottom'])/2-(w[1]+w[3])/2)<3 for w in labels)]
    if len(totals)!=len(labels):
        raise ValueError('No se identifican todos los subtotales de una página.')
    return hits,totals


def localizar_pesos(words):
    """Retain the single-page entry point."""
    return localizar_documento([words])


def localizar_documento(pages):
    """Validate every subtotal and the grand total in document order."""
    hits=[];totals=[]
    for page_number,words in enumerate(pages):
        page_hits,page_totals=pesos_de_pagina(words)
        if not page_hits:
            raise ValueError('Faltan pesos en una página del documento.')
        totals.extend(len(hits)+index for index in page_totals)
        for hit in page_hits:
            hit['page']=page_number
        hits.extend(page_hits)
    if len(hits)<3:
        raise ValueError('Faltan partidas o totales en la columna de peso.')
    if not totals and len(pages)==1:
        # Compatible single-customer forms without textual total labels.
        totals=[len(hits)-2,len(hits)-1]
    if len(totals)<2 or totals[-1]!=len(hits)-1 or hits[-1]['page']!=len(pages)-1:
        raise ValueError('No se identifica el total general en la última página.')
    items=[];group=[]
    for i,hit in enumerate(hits):
        hit['grams']=gramos(hit['text'])
        if i not in totals:
            hit['kind']='item';items.append(i);group.append(i)
        else:
            hit['kind']='total'
            members=items[:] if i==totals[-1] else group[:]
            if not members or sum(hits[j]['grams'] for j in members)!=hit['grams']:
                raise ValueError('Las partidas no suman sus subtotales o el total original.')
            hit['members']=members
            if i!=totals[-1]: group=[]
    if group: raise ValueError('Hay partidas sin subtotal verificado.')
    return hits


def dentro(c,box):
    """Match by character center: supports zero-width characters independently."""
    x=(c['x0']+c['x1'])/2; y=(c['top']+c['bottom'])/2
    return box[0]<=x<=box[2] and box[1]<=y<=box[3]


def caja_peso(w):
    return (w['x0']-.3,w['top']-.2,w['x1']+.3,w['bottom']+.2)


def contenido_ajeno(chars,boxes):
    from collections import Counter
    # Spaces and word boundaries depend on font metrics; actual characters do not.
    return Counter(c['text'] for c in chars if not c['text'].isspace()
                   and not any(dentro(c,box) for box in boxes))


QR_BOX=(536,14,600,90)


def leer_qr(image):
    return zxingcpp.read_barcodes(image,formats=zxingcpp.BarcodeFormat.QRCode)


def verificar_original(page,rendered,hits,qr_box):
    spans=[span for block in rendered.get_text('dict')['blocks']
           for line in block.get('lines',[]) for span in line['spans']]
    for hit in hits:
        matching=[span for span in spans if span['text']==hit['text']
                  and abs(span['bbox'][0]-hit['x0'])<.5
                  and abs(span['bbox'][1]-hit['top'])<.5]
        if len(matching)==1:
            hit['baseline']=matching[0]['origin'][1]
            hit['size']=matching[0]['size']
        selected=sorted([c for c in page.chars if not c['text'].isspace()
                         and dentro(c,caja_peso(hit))],key=lambda c:c['x0'])
        if ''.join(c['text'] for c in selected)!=hit['text']:
            raise ValueError('Los lectores del PDF no coinciden al identificar los pesos.')
    boxes=[caja_peso(hit) for hit in hits]
    if qr_box:
        boxes.append(qr_box)
    return boxes,contenido_ajeno(page.chars,boxes)


def escribir_pagina(page,hits,qr,url):
    for hit in hits:
        page.add_redact_annot(fitz.Rect(caja_peso(hit)),fill=False)
    if qr:
        page.add_redact_annot(fitz.Rect(QR_BOX),fill=(1,1,1))
    page.apply_redactions(images=2,graphics=0)
    height=page.rect.height
    buffer=io.BytesIO()
    c=canvas.Canvas(buffer,pagesize=(page.rect.width,height))
    for hit in hits:
        size=hit.get('size',10 if hit.get('grand_total') else 8)
        font='Helvetica-Bold' if size==10 else 'Helvetica'
        available=hit['x1']-hit['x0']
        text_width=stringWidth(hit['new_text'],font,size)
        if text_width>available:
            size*=available/text_width
        c.setFont(font,size)
        baseline=hit.get('baseline',hit['bottom']-size*.207)
        c.drawRightString(hit['x1'],height-baseline,hit['new_text'])
    if qr:
        if url:
            code=qrcode.make(url,box_size=10,border=4)
            c.drawImage(ImageReader(code.get_image()),536,height-76,width=64,height=64)
            c.setFont('Helvetica-Bold',10)
            c.drawCentredString(568,height-86,'DeCA')
        else:
            c.setFont('Helvetica',6)
            c.drawCentredString(568,height-47,'QR pendiente de archivo')
    c.save()
    with fitz.open(stream=buffer.getvalue(),filetype='pdf') as overlay:
        page.show_pdf_page(page.rect,overlay,0)


def corregir(source,output,weight,url=None,preview=None):
    weight=peso_real(weight)
    source,output=Path(source),Path(output)
    if source.resolve()==output.resolve():
        raise ValueError('El original debe conservarse.')
    if url:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not re.fullmatch(r'/documentos/[a-f0-9]{32}\.pdf',parsed.path):
            raise ValueError('El QR nuevo requiere la dirección HTTPS del PDF en el archivo digital.')
    checks=[]
    with fitz.open(source) as doc,pdfplumber.open(source) as pdf:
        if PROCESSING_MARKER in (doc.metadata.get('keywords') or ''):
            raise ValueError('Selecciona el original, no una copia ya rectificada.')
        if doc.get_sigflags()>0:
            raise ValueError('El PDF contiene firmas digitales; requiere un flujo de reemision.')
        for index,page in enumerate(pdf.pages):
            page_text=page.extract_text() or ''
            if abs(page.width-842)>1 or abs(page.height-595)>1 or 'Peso(KG)' not in page_text or (index==0 and 'Carburos' not in page_text):
                raise ValueError('Formato distinto del validado: necesita revision antes de editar.')
            if 'RECTIFICACION:' in page_text:
                raise ValueError('Selecciona el original, no una copia ya rectificada.')
        hits=localizar_documento([page.get_text('words') for page in doc])
        hits[-1]['grand_total']=True
        items=[hit for hit in hits if hit['kind']=='item']
        distributed=repartir_pesos([hit['grams'] for hit in items],gramos(weight))
        for hit,value in zip(items,distributed):
            hit['new_grams']=value
        for hit in hits:
            if hit['kind']=='total':
                hit['new_grams']=sum(hits[i]['new_grams'] for i in hit['members'])
            hit['new_text']=texto_peso(hit['new_grams'])
        original_qr=None
        for index,page in enumerate(pdf.pages):
            page_hits=[hit for hit in hits if hit['page']==index]
            codes=leer_qr(page.to_image(resolution=216).original)
            if index==0:
                if len(codes)!=1 or not qr_origen_admitido(codes[0].text):
                    raise ValueError('No se identifica un QR original del formato validado.')
                original_qr=codes[0].text
            if codes and (len(codes)!=1 or codes[0].text!=original_qr):
                raise ValueError('Se encontró un QR distinto en otra página.')
            if codes:
                position=codes[0].position
                corners=[position.top_left,position.top_right,position.bottom_left,position.bottom_right]
                if any(not (QR_BOX[0]-1<=point.x/3<=QR_BOX[2]+1
                            and QR_BOX[1]-1<=point.y/3<=QR_BOX[3]+1) for point in corners):
                    raise ValueError('El QR está fuera de la zona prevista.')
            has_qr=bool(codes)
            boxes,preserved=verificar_original(page,doc[index],page_hits,QR_BOX if has_qr else None)
            checks.append((boxes,preserved,has_qr))
            escribir_pagina(doc[index],page_hits,has_qr,url)
        output.parent.mkdir(parents=True,exist_ok=True)
        metadata=dict(doc.metadata)
        metadata['keywords']='; '.join(filter(None,[metadata.get('keywords'),PROCESSING_MARKER]))
        doc.set_metadata(metadata)
        doc.save(output,garbage=4,deflate=True)
    try:
        with fitz.open(output) as checked,pdfplumber.open(output) as pdf:
            final_hits=localizar_documento([page.get_text('words') for page in checked])
            if len(checked)!=len(checks) or len(final_hits)!=len(hits) or any(
                (final['grams'],final['kind'],final['page'])!=(original['new_grams'],original['kind'],original['page'])
                for final,original in zip(final_hits,hits)
            ):
                raise ValueError('No se han verificado todas las partidas y los totales finales.')
            for index,(page,(boxes,preserved,has_qr)) in enumerate(zip(pdf.pages,checks)):
                if contenido_ajeno(page.chars,boxes)!=preserved:
                    raise ValueError('La verificacion detecto cambios ajenos al peso y QR. Se cancela la salida.')
                if has_qr or (preview and index==0):
                    result=page.to_image(resolution=216).original
                    if url and has_qr:
                        found=leer_qr(result)
                        if len(found)!=1 or found[0].text!=url:
                            raise ValueError('El QR final no supera la comprobacion.')
                    if preview and index==0:
                        result.save(preview)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {'output':str(output.resolve()),'peso_kg':weight,'peso_anterior':hits[-1]['text'],
            'partidas_kg':[hit['new_text'] for hit in items],'qr_original':original_qr,
            'qr_nuevo':url,'estado':'final' if url else 'borrador_pendiente_de_qr'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--peso',required=True);parser.add_argument('--document-url');parser.add_argument('--preview')
    args=parser.parse_args()
    try: print(json.dumps(corregir(args.input,args.output,args.peso,args.document_url,args.preview),ensure_ascii=False))
    except (ValueError,InvalidOperation) as e: parser.exit(2,str(e)+'\n')
