# Guía de despliegue de smalilog en Termux

## Requisitos previos

- Dispositivo Android con Termux instalado.
- Conexión a Internet.
- (Opcional) Acceso root en Termux para instalar paquetes del sistema.

## Instalación rápida

### 1. Abrir Termux y actualizar paquetes

```bash
pkg update && pkg upgrade -y
```

### 2. Instalar dependencias del sistema

```bash
pkg install python git openssl -y
```

### 3. Clonar el repositorio

```bash
cd $HOME
git clone https://github.com/1jehuang/smalilog.git
cd smalilog
```

### 4. Crear entorno virtual e instalar dependencias

```bash
python -m venv .venv
source .venv/bin/activate
pip install websockets cryptography
pip install -e .
```

### 5. Verificar instalación

```bash
smalilog --version
smalilog --help
```

## Uso básico

### Servidor de logs

Arranca el servidor HTTP que recibe los logs:

```bash
smalilog server
```

Opciones comunes:

- `--host`: Host donde escuchar (por defecto: `127.0.0.1`).
- `-p, --port`: Puerto TCP (por defecto: `9999`).
- `--ws-port`: Puerto para WebSocket (por defecto: `10000`).
- `--self-signed`: Genera un certificado auto-firmado para `wss://`.
- `-v, --verbose`: Muestra la configuración antes de arrancar.
- `--no-blocking`: Arranca en un hilo aparte.

Ejemplo:

```bash
smalilog server --host 0.0.0.0 -p 8080 --ws-port 8081 --self-signed -v
```

### Dashboard

Accede al dashboard web desde un navegador:

```
http://127.0.0.1:9999/
```

Si el servidor está en otra máquina, accede a `http://IP_SERVIDOR:9999/`.

### Cliente de terminal (listen)

Escucha logs en la terminal:

```bash
smalilog listen
```

Opciones comunes:

- `--host`: Host del servidor (por defecto: `127.0.0.1`).
- `-p, --port`: Puerto WebSocket (por defecto: `10000`).
- `--wss`: Conecta por TLS (`wss://`).
- `--certfile CA`: CA o certificado para verificar el servidor.
- `--insecure`: No verificar el certificado TLS.
- `-m, --min-level`: Filtra eventos por debajo de este nivel.
- `--raw`: Imprime el JSON crudo en lugar del formato legible.
- `-v, --verbose`: Muestra detalles de conexión y reconexiones.

Ejemplo con TLS:

```bash
smalilog listen --host 192.168.1.10 -p 9998 --wss --insecure
```

### Menú interactivo

Abre el menú interactivo:

```bash
smalilog menu
```

## Inyección de hooks

### Listar métodos

Lista los métodos de un archivo Smali:

```bash
smalilog hook list app.smali
```

### Inyectar hooks

Inyecta hooks de entrada, salida o ambos:

```bash
smalilog hook enter app.smali -m onCreate
smalilog hook exit app.smali -m onCreate
smalilog hook both app.smali -m onCreate
```

### Inyectar LifecycleTracker

Inyecta un LifecycleTracker en `Application.onCreate`:

```bash
smalilog hook lifecycle Application.smali -m onCreate
```

## Configuración de firewall

Si el servidor está en un dispositivo Android y quieres acceder desde otro dispositivo en la misma red:

1. Arranca el servidor con `--host 0.0.0.0`:

```bash
smalilog server --host 0.0.0.0 -p 8080 --ws-port 8081
```

2. Asegúrate de que el firewall del dispositivo permita tráfico en los puertos 8080 y 8081.

3. Desde el otro dispositivo, accede a `http://IP_ANDROID:8080/` y `smalilog listen --host IP_ANDROID -p 8081`.

## Instalación en otros dispositivos

### En cualquier Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install websockets cryptography
pip install -e .
smalilog --help
```

### En Windows (con WSL o PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install websockets cryptography
pip install -e .
smalilog --help
```

## Solución de problemas

### `smalilog: command not found`

Asegúrate de que el entorno virtual está activado:

```bash
source $HOME/smalilog-venv/bin/activate
```

O reinicia Termux.

### Error de conexión WebSocket

1. Verifica que el servidor esté activo.
2. Comprueba que el puerto WebSocket sea correcto.
3. Usa `--verbose` para detalles de conexión.

### Certificado TLS no válido

Si el certificado auto-firmado no es válido:

1. Usa `--insecure` para saltar la verificación.
2. Genera un certificado válido con tu CA.

## Funcionalidades avanzadas

### Certificados auto-firmados

Genera un certificado auto-firmado para `wss://`:

```bash
smalilog server --self-signed
```

El certificado se guarda en `~/.smalilog/` y se reutiliza entre reinicios.

### Filtrado por origen

Cada evento incluye el host del cliente:

```json
{
  "timestamp": "2026-09-16T00:16:27.531Z",
  "level": "INFO",
  "tag": "APP",
  "message": "hola",
  "source": "192.168.1.10"
}
```

### Modo raw

Imprime el JSON crudo en lugar del formato legible:

```bash
smalilog listen --raw
```

## Estructura del proyecto

```
smalilog/
├── src/smalilog/          # Código fuente
│   ├── main.py            # CLI principal
│   ├── config.py          # Configuración global
│   ├── server/            # Servidor de logs
│   │   ├── logserver.py   # Servidor TCP/HTTP/WebSocket
│   │   └── tls.py         # Certificados TLS
│   └── injector/          # Inyector de hooks Smali
├── README.md              # Documentación principal
├── GUIDA.md               # Guía completa de funcionalidades
├── setup.py               # Instalación del paquete
└── termux_install.sh      # Script de instalación para Termux
```

## Contribución

Las contribuciones son bienvenidas. Por favor, abre un issue o envía un pull request.

## Licencia

Este proyecto está licenciado bajo la Licencia MIT.