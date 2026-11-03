# Render + archivo digital de Cloudflare

La aplicación se ejecuta como Web Service Docker de Render (Free, Frankfurt, /healthz). Render sirve la interfaz y procesa el PDF. Cloudflare KV conserva los documentos fuera de su disco temporal.

## Archivo permanente

1. En tu cuenta de Cloudflare → Storage & databases → Workers KV, crea un namespace llamado porte-negro-documentos.
2. Anota el ID de cuenta y el ID del namespace.
3. Crea una credencial de API con permiso Account → Workers KV Storage → Edit, restringida a esa cuenta. Este permiso permite leer y escribir KV en la cuenta; revísalo antes de concederlo. No uses la clave global ni concedas acceso DNS.
4. En Render → Environment guarda:

```text
PUBLIC_BASE_URL=https://porte-negro.onrender.com
CF_ACCOUNT_ID=<ID de cuenta>
CF_KV_NAMESPACE_ID=<ID del namespace>
CF_API_TOKEN=<credencial privada>
```

5. Despliega la última versión. La página activará la generación cuando tenga configuración. Eso comprueba la presencia de configuración; la conexión real y los bytes se verifican al generar.

Cloudflare KV incluye 1 GB y cuotas de operaciones en su plan gratuito. No se contrata un plan de pago. Si se supera la cuota, las operaciones fallarán; el servidor no entregará un resultado que no haya podido archivar. Un PDF usa una entrada de bytes y otra de publicación. El documento sigue accesible después de reiniciar o reconstruir Render.

KV tiene consistencia eventual: una escritura nueva puede tardar en propagarse. La aplicación verifica su lectura antes de entregar y devuelve un error temporal si una copia aún no está completa. No hay reintentos automáticos de escritura ni vencimiento automático. Si falla una publicación se intenta eliminar las dos entradas del nuevo ID; ante una interrupción remota ambigua revisa KV.

## Dominio y documentos

Las direcciones son https://porte-negro.onrender.com/documentos/<ID aleatorio>.pdf. PUBLIC_BASE_URL se fija en el servidor; no se toma del encabezado Host del visitante. Conserva esa dirección operativa cuando conectes un dominio propio para no romper los QR ya emitidos. Si se utiliza un dominio distinto para la aplicación, adapta la validación de origen en app.js antes de emitir nuevos documentos.

## Comprobación final

Usa un original autorizado y el peso real. Revisa visualmente los tres pesos, la nota y DeCA. Abre el enlace desde un navegador sin sesión y escanea el QR. Comprueba también que el mismo enlace sigue funcionando tras reiniciar el servidor. No se incluyen documentos ni credenciales en GitHub o el ZIP.

Render Free puede tardar en arrancar después de inactividad; al escanear un QR también puede aparecer esa espera. El archivo sigue guardado en Cloudflare.
