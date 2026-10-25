# Monitor Control (primera versión)

Aplicación de escritorio para Windows que guarda televisores en SQLite y permite probar conexión y enviar una tecla de navegación.

## Compatibilidad implementada

- **Samsung Tizen**: usa `samsungtvws` por WebSocket seguro (puerto 8002 por defecto). La primera conexión puede mostrar un permiso en la TV. El token se guarda en la carpeta local de la aplicación.
- **LG webOS**: usa `pywebostv` con WebSocket seguro (`secure=True`). En la primera conexión se debe aceptar la solicitud en la TV; el token de autorización se guarda en SQLite.
- **Roku / Roku TV**: usa ECP por HTTP en el puerto 8060. El control puede requerir habilitar el acceso de aplicaciones móviles según versión y ajustes de Roku OS.
- **Android TV**: usa ADB por red. Requiere que el dispositivo permita depuración inalámbrica/ADB y que la PC esté autorizada. Los Android TV modernos pueden requerir el emparejamiento de depuración inalámbrica; esta versión no implementa el flujo de emparejamiento por código.

## Importante

- Una IP accesible no garantiza que el protocolo de control esté habilitado.
- "Probar conexión" verifica que el adaptador pueda establecer una sesión o consultar el dispositivo; algunos dispositivos solo revelan el problema al enviar una tecla.
- "Enviar tecla de prueba" manda una sola flecha derecha. Comprueba visualmente qué hizo en la pantalla.
- `RIGHT` no equivale a "canal siguiente". Las apps IPTV pueden usar flechas, lista de canales, botones CH+/CH- u otros controles.
- La aplicación no cambia canales automáticamente en esta versión. La automatización debe añadirse una vez validado el control real de la app IPTV en cada plataforma.
- Los tokens de emparejamiento son credenciales locales. No compartas la base de datos ni la carpeta de tokens.

## Instalación

1. Instala Python 3.11 de 64 bits desde https://www.python.org/downloads/windows/ (marca "Add Python to PATH").
2. Descomprime el ZIP en una carpeta local.
3. Ejecuta `run_monitor_control.bat`. Creará un entorno virtual, instalará dependencias y abrirá la aplicación.
4. En la interfaz, pulsa **Añadir**, selecciona marca, introduce nombre e IP y guarda.
5. Selecciona el dispositivo y pulsa **Probar conexión**.
6. Para Samsung/LG, acepta el diálogo de autorización en el televisor si aparece.
7. Selecciona **Enviar tecla de prueba** y comprueba visualmente el resultado.

## Instalación manual

Desde PowerShell, en la carpeta del proyecto:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Si PowerShell bloquea la activación, usa CMD y ejecuta el archivo `run_monitor_control.bat`.

## Datos

La base de datos y los tokens se guardan en:

`%LOCALAPPDATA%\\MonitorControl\\`

La tabla guarda nombre, marca, IP y token LG. Los tokens Samsung se almacenan en archivos separados dentro de `tokens`.

## Diagnóstico

- Comprueba que la TV y PC estén en la misma red/VLAN.
- Comprueba la IP desde Ajustes de red de la TV y evita IP duplicadas.
- Permite el control remoto por red y acepta el emparejamiento cuando corresponda.
- El firewall de Windows o el aislamiento Wi-Fi del router pueden bloquear la comunicación.
- Samsung usa el puerto 8002 para WebSocket seguro en este proyecto.
- LG usa WebSocket seguro. Si la TV rechaza la conexión, confirma compatibilidad del modelo/firmware con control webOS por red.
- Roku ECP usa HTTP en el puerto 8060; el acceso puede estar restringido por ajustes o versión de Roku OS.
- Android TV depende de ADB; si `adb` no está instalado o la TV no está autorizada, no funcionará.

## Límites conocidos de esta versión

- No detecta automáticamente marca/modelo por IP.
- No verifica qué canal está reproduciéndose ni confirma visualmente el cambio.
- No hay todavía programación automática de recorridos ni control grupal.
- No hay emparejamiento ADB moderno por código.
- El envío de una tecla de navegación es una prueba, no una afirmación de compatibilidad con una app IPTV concreta.
