# Porte Negro · Archivo digital

Web pública para rectificar cartas de porte del formato DeCA validado y abrir el PDF actualizado escaneando su QR. Sin registro ni cuenta de Google. Conserva la estética oscura y el recuadro de arrastre.

## Flujo

1. El visitante arrastra el original e introduce el peso real en el único campo Peso (kg).
2. Se conservan las validaciones del complemento: formato de una página de 842 × 595 puntos, una o más partidas, subtotales y total cuya suma se verifica, sin firma digital; peso real positivo y hasta tres decimales, sin un intervalo mínimo o máximo. Los valores largos se ajustan al ancho de su casilla sin cambiar el número.
3. Se reserva un identificador aleatorio y se genera el PDF final con los pesos de cada partida y sus totales, un QR hacia su propia dirección HTTPS y la etiqueta DeCA.
4. Se guarda solo el PDF final en Cloudflare KV. Se vuelven a leer y comparar sus bytes antes de publicar un marcador de integridad. La ruta pública solo sirve documentos publicados cuyo contenido coincide con ese marcador.
5. El visitante descarga el PDF y recibe su enlace directo. El QR abre el mismo documento en el navegador, sin iniciar sesión.

El original no se modifica ni se publica. Se mantienen los datos ajenos al peso/QR. Se admiten QR de origen del servicio DeCA, copias con enlace de Drive y originales compatibles sin marcas de un procesamiento anterior. La detección se limita a QR para evitar falsos positivos de otros códigos. Los pesos se confirman mediante dos lectores independientes a nivel de caracteres, incluso con fuentes incompletas o palabras fusionadas. No se añade texto de rectificación visible. Se conserva un marcador técnico en los metadatos para evitar procesar de nuevo una copia generada. La aplicación no modifica el servicio oficial de Air Products.

El archivo de Cloudflare es persistente y no usa la carpeta temporal de Render. No se configura caducidad automática. La continuidad de los enlaces depende de mantener el dominio, la aplicación, la cuenta y el almacenamiento; no se promete permanencia indefinida. Cualquier persona que reciba un enlace puede abrir el PDF. Los enlaces no se enumeran y las respuestas llevan noindex.

## Configuración

Sigue DESPLIEGUE-RENDER.md. Las únicas variables necesarias son PUBLIC_BASE_URL, CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID y CF_API_TOKEN. La clave queda exclusivamente en Render. No se necesita Google Drive ni OAuth.

## Pruebas

```sh
pip install -r requirements.txt httpx
python -m unittest discover -s tests -v
```

Las pruebas utilizan un archivo remoto simulado. Verifican que el PDF del QR es el que se publica, que se abre inline sin contraseña, que los originales o subidas incompletas no se exponen y que se cancela si cambian los bytes. Falta la prueba con una carta original autorizada para verificar el documento completo y su aspecto final.

## Reparto entre varias partidas

La diferencia entre el total original y el indicado se reparte proporcionalmente a los pesos brutos originales. Se calcula en gramos enteros y los restos de redondeo se asignan por mayor resto, con desempate por mayor peso y orden original. Se recalculan los subtotales y el total general y se vuelven a leer del PDF para comprobar la suma exacta antes de publicar. Los pesos netos y el resto del contenido se conservan. No se añade texto visible.
