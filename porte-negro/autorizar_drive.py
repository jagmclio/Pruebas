"""Ejecutar SOLO en el ordenador del propietario, nunca en el servidor público."""
import argparse
import json
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Conectar Drive personal sin publicar credenciales.')
    parser.add_argument('--cliente', required=True, help='JSON del cliente OAuth de tipo Aplicación de escritorio')
    parser.add_argument('--salida', default='google-drive.json')
    args = parser.parse_args()
    target = Path(args.salida)
    if target.exists():
        raise SystemExit('El archivo de salida ya existe. Elige otra ruta para conservar la autorización anterior.')
    flow = InstalledAppFlow.from_client_secrets_file(args.cliente, ['https://www.googleapis.com/auth/drive.file'])
    credentials = flow.run_local_server(port=0, access_type='offline', prompt='consent')
    if not credentials.refresh_token:
        raise SystemExit('Google no devolvió una autorización renovable. Repite el consentimiento.')
    data = json.loads(credentials.to_json())
    data['type'] = 'authorized_user'
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(data, output)
    print('Autorización guardada. Sube su contenido solo como archivo secreto google-drive.json en Render.')
