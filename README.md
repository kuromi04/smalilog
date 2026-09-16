# smalilog

Herramienta para instrumentar aplicaciones Android con logging remoto mediante inyección de código Smali y un servidor HTTP.

## Características

- Captura logs desde aplicaciones Android en tiempo real.
- Visualiza los logs en un dashboard web o en terminal.
- Filtra logs por nivel, tag y origen.
- Soporta comunicación segura (TLS) y no segura (WebSocket).

## Instalación

1. Clona el repositorio:

```bash
$ git clone https://github.com/tu-usuario/smalilog.git
$ cd smalilog
```

2. Crea y activa un entorno virtual:

```bash
$ python -m venv .venv
$ source .venv/bin/activate
```

3. Instala las dependencias:

```bash
$ pip install -r requirements.txt
```

## Uso básico

### Servidor de logs

Arranca el servidor HTTP que recibe los logs:

```bash
$ smalilog server
```

Opciones comunes:

- `--host`: Host donde escuchar (por defecto: `127.0.0.1`).
- `-p, --port`: Puerto TCP (por defecto: `9999`).
- `--ws-port`: Puerto para WebSocket (por defecto: `10000`).
- `--self-signed`: Genera un certificado auto-firmado para `wss://`.

### Dashboard

Accede al dashboard web en:

```
http://127.0.0.1:9999/
```

### Cliente de terminal

Escucha logs en la terminal:

```bash
$ smalilog listen
```

Opciones comunes:

- `--wss`: Conecta por TLS (`wss://`).
- `--insecure`: No verificar el certificado TLS.
- `-m, --min-level`: Filtra eventos por debajo de este nivel.

## Inyección de hooks

### Listar métodos

Lista los métodos de un archivo Smali:

```bash
$ smalilog hook list app.smali
```

### Inyectar hooks

Inyecta hooks de entrada, salida o ambos:

```bash
$ smalilog hook enter app.smali -m onCreate
$ smalilog hook exit app.smali -m onCreate
$ smalilog hook both app.smali -m onCreate
```

### Inyectar LifecycleTracker

Inyecta un LifecycleTracker en `Application.onCreate`:

```bash
$ smalilog hook lifecycle Application.smali -m onCreate
```

## Ejemplo completo

1. Arranca el servidor:

```bash
$ smalilog server --ws-port 9998 --self-signed
```

2. Inyecta hooks en un archivo Smali:

```bash
$ smalilog hook both app.smali -m onCreate
```

3. Escucha logs en la terminal:

```bash
$ smalilog listen --wss --insecure
```

4. Accede al dashboard:

```
http://127.0.0.1:9999/
```

## Funcionalidades avanzadas

### Certificados auto-firmados

Genera un certificado auto-firmado para `wss://`:

```bash
$ smalilog server --self-signed
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
$ smalilog listen --raw
```

## Solución de problemas

### Error de conexión WebSocket

Si `listen` no se conecta:

1. Verifica que el servidor esté activo.
2. Comprueba que el puerto WebSocket sea correcto.
3. Usa `--verbose` para detalles de conexión.

### Certificado TLS no válido

Si el certificado auto-firmado no es válido:

1. Usa `--insecure` para saltar la verificación.
2. Genera un certificado válido con tu CA.

## Contribución

Las contribuciones son bienvenidas. Por favor, abre un issue o envía un pull request.

## Licencia

Este proyecto está licenciado bajo la Licencia MIT.