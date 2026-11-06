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


def localizar_pesos(words):
    """Identify items, customer subtotals and the final total from geometry."""
    headers=[w for w in words if w[4]=='Peso(KG)']
    if len(headers)!=1: raise ValueError('No se identifica una unica columna de peso.')
    h=headers[0]
    hits=[{'text':w[4],'x0':w[0],'top':w[1],'x1':w[2],'bottom':w[3]}
          for w in words if w[1]>h[3] and h[0]-6<=w[0]<=h[2]
          and re.fullmatch(r'[\d.,]+',w[4]) and w[2]<=h[2]+20]
    hits.sort(key=lambda w:w['top'])
    if len(hits)<3: raise ValueError('Faltan partidas o totales en la columna de peso.')
    labels=[w for w in words if w[4]=='Total:' and w[1]>h[3] and w[2]<h[0]]
    if labels:
        totals=[i for i,hit in enumerate(hits) if any(abs((hit['top']+hit['bottom'])/2-(w[1]+w[3])/2)<3 for w in labels)]
        if len(totals)!=len(labels) or len(totals)<2 or totals[-1]!=len(hits)-1:
            raise ValueError('No se identifican todos los subtotales y el total final.')
    else:
        # Compatible single-customer forms without textual total labels.
        totals=[len(hits)-2,len(hits)-1]
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
        doc=fitz.open(source)
        if PROCESSING_MARKER in (doc.metadata.get('keywords') or ''):
            doc.close(); raise ValueError('Selecciona el original, no una copia ya rectificada.')
        if doc.get_sigflags()>0:
            doc.close(); raise ValueError('El PDF contiene firmas digitales; requiere un flujo de reemision.')
        hits=localizar_pesos(doc[0].get_text('words'))
        items=[w for w in hits if w['kind']=='item']
        distributed=repartir_pesos([w['grams'] for w in items],gramos(weight))
        for hit,value in zip(items,distributed): hit['new_grams']=value
        for hit in hits:
            if hit['kind']=='total': hit['new_grams']=sum(hits[i]['new_grams'] for i in hit['members'])
            hit['new_text']=texto_peso(hit['new_grams'])
        spans=[span for block in doc[0].get_text('dict')['blocks'] for line in block.get('lines',[]) for span in line['spans']]
        for hit in hits:
            matching=[span for span in spans if span['text']==hit['text'] and abs(span['bbox'][0]-hit['x0'])<.5 and abs(span['bbox'][1]-hit['top'])<.5]
            if len(matching)==1:
                hit['baseline']=matching[0]['origin'][1]
                hit['size']=matching[0]['size']
        chars=page.chars
        # A second PDF reader must confirm every selected weight, even when
        # its word extraction fuses a weight with UN or splits zero-width glyphs.
        for hit in hits:
            selected=sorted([c for c in chars if not c['text'].isspace() and dentro(c,caja_peso(hit))],key=lambda c:c['x0'])
            if ''.join(c['text'] for c in selected)!=hit['text']:
                doc.close(); raise ValueError('Los lectores del PDF no coinciden al identificar los pesos.')
        qr_box=(536,14,600,90)
        preserved=contenido_ajeno(chars,[caja_peso(w) for w in hits]+[qr_box])
        source_image=page.to_image(resolution=216).original
    codes=zxingcpp.read_barcodes(source_image,formats=zxingcpp.BarcodeFormat.QRCode)
    if len(codes)!=1: raise ValueError('No se identifica un unico QR original.')
    original_qr=codes[0].text
    if not qr_origen_admitido(original_qr):
        raise ValueError('El QR no corresponde al formato de carta validado.')
    if url:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not re.fullmatch(r'/documentos/[a-f0-9]{32}\.pdf',parsed.path):
            raise ValueError('El QR nuevo requiere la dirección HTTPS del PDF en el archivo digital.')
    p=doc[0]
    for w in hits:
        p.add_redact_annot(fitz.Rect(caja_peso(w)),fill=False)
    p.add_redact_annot(fitz.Rect(536,14,600,90),fill=(1,1,1))
    p.apply_redactions(images=2,graphics=0)
    buffer=io.BytesIO(); c=canvas.Canvas(buffer,pagesize=(842,595))
    for w in hits:
        size=w.get('size',10 if w['top']==max(v['top'] for v in hits) else 8)
        font='Helvetica-Bold' if size==10 else 'Helvetica'
        available=w['x1']-w['x0']
        text_width=stringWidth(w['new_text'],font,size)
        if text_width>available:
            size*=available/text_width
        c.setFont(font,size)
        baseline=w.get('baseline',w['bottom']-size*.207)
        c.drawRightString(w['x1'],595-baseline,w['new_text'])
    if url:
        qr=qrcode.make(url,box_size=10,border=4)
        c.drawImage(ImageReader(qr.get_image()),536,519,width=64,height=64)
        c.setFont('Helvetica-Bold',10);c.drawCentredString(568,509,'DeCA')
    else:
        c.setFont('Helvetica',6);c.drawCentredString(568,548,'QR pendiente de archivo')
    c.save(); overlay=fitz.open(stream=buffer.getvalue(),filetype='pdf');p.show_pdf_page(p.rect,overlay,0)
    output.parent.mkdir(parents=True,exist_ok=True)
    metadata=dict(doc.metadata)
    metadata['keywords']='; '.join(filter(None,[metadata.get('keywords'),PROCESSING_MARKER]))
    doc.set_metadata(metadata)
    doc.save(output,garbage=4,deflate=True)
    with pdfplumber.open(output) as pdf:
        final=pdf.pages[0].extract_text() or ''
        result=pdf.pages[0].to_image(resolution=216).original
        retained=contenido_ajeno(pdf.pages[0].chars,[caja_peso(w) for w in hits]+[qr_box])
        if preserved!=retained:
            output.unlink(); raise ValueError('La verificacion detecto cambios ajenos al peso y QR. Se cancela la salida.')
        # Re-read every item and total and independently verify all sums.
        with fitz.open(output) as checked:
            final_hits=localizar_pesos(checked[0].get_text('words'))
        if len(final_hits)!=len(hits) or any(w['grams']!=original['new_grams'] or w['kind']!=original['kind'] for w,original in zip(final_hits,hits)):
            output.unlink(); raise ValueError('No se han verificado todas las partidas y los totales finales.')
        found=zxingcpp.read_barcodes(result,formats=zxingcpp.BarcodeFormat.QRCode)
        if url and (len(found)!=1 or found[0].text!=url):
            output.unlink(); raise ValueError('El QR final no supera la comprobacion.')
    if preview: result.save(preview)
    return {'output':str(output.resolve()),'peso_kg':weight,'peso_anterior':hits[-1]['text'],'partidas_kg':[w['new_text'] for w in items],'qr_original':original_qr,'qr_nuevo':url,'estado':'final' if url else 'borrador_pendiente_de_qr'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--peso',required=True);parser.add_argument('--document-url');parser.add_argument('--preview')
    args=parser.parse_args()
    try: print(json.dumps(corregir(args.input,args.output,args.peso,args.document_url,args.preview),ensure_ascii=False))
    except (ValueError,InvalidOperation) as e: parser.exit(2,str(e)+'\n')
