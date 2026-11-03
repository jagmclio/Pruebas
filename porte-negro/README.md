# Porte Negro

Web pública para rectificar cartas de porte Carburos / Air Products en el formato DeCA validado. Diseño oscuro con recuadro de arrastre de PDF, adaptable a móvil y sin contraseña de acceso.

El servidor Python sirve la página y procesa el documento. Incluye un despliegue gratuito en Render mediante Docker. Sigue [DESPLIEGUE-RENDER.md](DESPLIEGUE-RENDER.md) para configurar el alojamiento y el Drive personal del propietario.

## Reglas conservadas del complemento

- Peso real confirmado: 920–990 kg inclusive, hasta tres decimales, con coma o punto. No se elige ni ajusta automáticamente.
- PDF original de una página de 842 × 595 puntos, una partida y dos totales coincidentes. Se rechazan formatos distintos, copias rectificadas y firmas digitales.
- Se actualizan las tres apariciones del peso, el QR, la etiqueta DeCA y una nota fechada en Europe/Madrid. Se conserva el resto de información y se verifica mediante lectura independiente.
- El original no se sobrescribe. Se sube una copia nueva privada, se regenera con el enlace real de Drive y se reemplazan los bytes del mismo ID antes de habilitar anyone/reader.
- Los temporales se eliminan al terminar. La copia final permanece en Drive y puede verla quien tenga el enlace. La web no modifica el servicio oficial de Air Products.

`corregir.py` es el script original del complemento. No se incluyen cartas de clientes, claves ni tokens en el proyecto. La web muestra cuándo falta conectar Drive y no presenta una simulación como resultado real.

## Instalación local

Con Python 3.12:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_APPLICATION_CREDENTIALS=/ruta/privada/google-drive.json
uvicorn app:app --host 127.0.0.1 --port 8000
```

Para Docker: construye la imagen, monta la autorización como archivo de solo lectura y publica el puerto 10000. Usa HTTPS al publicarla. La variable PORT se respeta en Render.

## Comprobaciones

```sh
pip install httpx
python -m unittest discover -s tests -v
```

Las pruebas del flujo de Drive utilizan un servicio simulado: comprueban el ID del archivo, el orden de publicación y la cancelación si no coinciden los bytes o permisos. No sustituyen la prueba final con un original autorizado y Drive conectado, ni la revisión visual del PDF y del QR.

Si falla una creación remota sin devolver ID, revisa Drive antes de reintentar. Si falla una etapa posterior, se intenta eliminar la copia nueva. No hay reintentos automáticos que puedan crear duplicados.
