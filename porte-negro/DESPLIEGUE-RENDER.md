# Despliegue gratuito de Porte Negro

## 1. Publicar el servidor

Sube el código a un repositorio de GitHub y conéctalo a Render. Crea un Web Service con runtime Docker, región Frankfurt, plan Free y health check `/healthz`. El archivo render.yaml también permite usar un Blueprint con esos valores. El servidor sirve tanto la interfaz como el procesamiento; no necesita Cloudflare Pages. No contrates un plan de pago para esta prueba.

El servidor arranca aunque Drive esté pendiente y muestra el estado real en la interfaz. Procesa un único PDF a la vez para limitar memoria. No solicita contraseña a los visitantes.

## 2. Conectar Drive personal del propietario

Esta autorización es del propietario de la web, no de cada visitante. Todos los resultados se guardarán en el Drive del propietario. No compartas contraseñas ni pegues claves en el chat o el repositorio.

1. En Google Cloud, crea o selecciona un proyecto y habilita Google Drive API.
2. Configura Google Auth Platform para ese proyecto. Crea un cliente OAuth de tipo **Aplicación de escritorio** y descarga su JSON. Utiliza el alcance `https://www.googleapis.com/auth/drive.file`: permite gestionar archivos creados o autorizados para esta aplicación, sin acceso general a todo el Drive.
3. Si la aplicación está en estado Testing, añade tu Gmail como usuario de prueba. Google normalmente limita a siete días los tokens renovables de aplicaciones externas en Testing con este alcance; configura la publicación adecuada para uso estable. No prometas que el token de prueba será permanente.
4. Ejecuta en tu ordenador, con las dependencias instaladas:

```sh
python autorizar_drive.py --cliente /ruta/privada/client_secret.json --salida /ruta/privada/google-drive.json
```

Se abrirá el consentimiento de Google. Revísalo y autoriza con la cuenta que recibirá las cartas. Este paso requiere tu intervención.

5. En Render → servicio → Environment → Secret Files, añade `google-drive.json` con el contenido de ese archivo. Establece `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/google-drive.json`. Guarda y despliega.
6. Deja `DRIVE_FOLDER_ID` sin configurar para guardar en Mi unidad. Solo configura una carpeta creada o autorizada por este mismo cliente OAuth; un ID cualquiera no concede acceso con drive.file.

## 3. Comprobación

Abre la URL de Render. Prueba una carta original autorizada y un peso real de 920–990 kg. Revisa los tres pesos, la nota y DeCA bajo el QR. Abre el enlace de Drive sin iniciar sesión y escanea el QR. El servidor comprueba el contenido conservado, el QR, los bytes de la copia subida y el permiso anyone/reader. No se ha realizado una prueba con documentación real hasta contar con el PDF y la autorización de Drive.

Después conecta tu dominio desde Settings → Custom Domains. Cloudflare puede seguir gestionando el dominio.

El plan gratuito se suspende por inactividad y tiene límites de recursos; primero mide el consumo con cartas reales. No usa almacenamiento local persistente: los temporales se borran y el PDF final permanece en Drive.
