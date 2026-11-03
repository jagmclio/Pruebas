const form=document.querySelector('#form'), file=document.querySelector('#pdf'), drop=document.querySelector('#drop'), statusBox=document.querySelector('#status'), button=document.querySelector('#submit'), result=document.querySelector('#result');
let downloadUrl;
function picked(){const f=file.files[0];document.querySelector('#filename').textContent=f?f.name:'Arrastra aquí la carta de porte que deseas modificar';document.querySelector('#filehint').textContent=f?`${(f.size/1024/1024).toFixed(2)} MB · Pulsa para cambiar`:'SUELTA TU PDF EN ESTE RECUADRO';result.hidden=true;statusBox.hidden=true;}
file.addEventListener('change',picked);
for(const event of ['dragenter','dragover']) drop.addEventListener(event,e=>{e.preventDefault();drop.classList.add('over');});
for(const event of ['dragleave','drop']) drop.addEventListener(event,e=>{e.preventDefault();drop.classList.remove('over');});
drop.addEventListener('drop',e=>{if(e.dataTransfer.files.length!==1){show('Selecciona un único PDF.',true);return;}file.files=e.dataTransfer.files;picked();});
function show(message,error=false){statusBox.hidden=false;statusBox.textContent=message;statusBox.classList.toggle('error',error);}
form.addEventListener('submit',async e=>{e.preventDefault();result.hidden=true;const f=file.files[0], raw=document.querySelector('#peso').value.trim(), value=Number(raw.replace(',','.'));
if(!f||!f.name.toLowerCase().endsWith('.pdf'))return show('Selecciona un archivo PDF.',true);
if(f.size>15*1024*1024)return show('El tamaño máximo es de 15 MB.',true);
if(!/^\d{3}([,.]\d{1,3})?$/.test(raw)||value<920||value>990)return show('El peso no se puede procesar. Comprueba el valor introducido.',true);
if (window.CARTA_STATIC_PREVIEW) return show('El PDF está seleccionado. Falta conectar el archivo digital para generar la copia final.',true);
const body=new FormData();body.append('pdf',f);body.append('peso',raw);body.append('autorizado',document.querySelector('#autorizado').checked?'si':'no');button.disabled=true;form.setAttribute('aria-busy','true');show('Validando el documento, actualizando el peso y verificando el PDF digital y su QR…');
try{const response=await fetch('/api/rectificar',{method:'POST',body});if(!response.ok){let message='No se ha completado la operación.';try{const data=await response.json();if(typeof data.detail==='string')message=data.detail;}catch{}throw new Error(message);}
const blob=await response.blob();const link=response.headers.get('X-Document-URL');if(!link)throw new Error('No se recibió la dirección del PDF digital.');const target=new URL(link);if(target.origin!==window.location.origin||!/^\/documentos\/[a-f0-9]{32}\.pdf$/.test(target.pathname))throw new Error('La dirección del PDF digital no es válida.');
if(downloadUrl)URL.revokeObjectURL(downloadUrl);downloadUrl=URL.createObjectURL(blob);const download=document.querySelector('#download');download.href=downloadUrl;download.download='carta-rectificada.pdf';document.querySelector('#document-link').href=link;document.querySelector('#result-weight').textContent=`Peso total: ${response.headers.get('X-Peso-Kg')} kg · QR y copia final verificados.`;statusBox.hidden=true;result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'nearest'});
}catch(error){show(error.message||'Se interrumpió la conexión. Comprueba la conexión antes de reintentar.',true);}finally{button.disabled=false;form.removeAttribute('aria-busy');}});

// Show the actual configuration state before allowing document generation.
if (!window.CARTA_STATIC_PREVIEW) {
 button.disabled = true;
 fetch('/api/estado').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(state => {
   if (state.configurado) { button.disabled = false; }
   else { const note=document.querySelector('#deployment-note'); note.hidden=false; note.querySelector('p').textContent=state.mensaje; button.textContent='Archivo digital en preparación'; }
 }).catch(() => { show('No se ha podido comprobar la conexión del servidor. Recarga la página.',true); });
}
