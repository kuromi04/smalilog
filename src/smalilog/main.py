"""
CLI de smalilog.

Subcomandos:
    smalilog server [opciones]    Arranca el servidor de logs.
    smalilog listen [opciones]    Escucha y muestra logs por WebSocket.
    smalilog hook   <cmd> [...]   Inyecta hooks en un archivo Smali.
    smalilog menu                  Abre el menú interactivo.

Ejemplos:
    smalilog
    smalilog server
    smalilog server --host 0.0.0.0 -p 8080
    smalilog listen --host 192.168.1.10 -p 9998
    smalilog hook list       app.smali
    smalilog hook enter      app.smali -m Sf
    smalilog hook lifecycle  Application.smali -m onCreate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

from . import config
from .injector.hooker import run_hooker
from .server import LogServer
from .server.tls import ensure_self_signed

# --------------------------------------------------------------------------- #
#  Constantes
# --------------------------------------------------------------------------- #
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# --------------------------------------------------------------------------- #
#  Colores ANSI (fallback mínimo si el usuario tiene NO_COLOR)
# --------------------------------------------------------------------------- #
import os
_USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

def _c(code: str, s: str) -> str:
    return f"{code}{s}\033[0m" if _USE_COLOR else s

_BOLD   = "\033[1m"
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_DIM    = "\033[2m"


def _print_banner() -> None:
    """Muestra la identidad visual compacta de la herramienta."""
    banner = r"""
 ███████╗███╗   ███╗ █████╗ ██╗     ██╗██╗      ██████╗  ██████╗
 ██╔════╝████╗ ████║██╔══██╗██║     ██║██║     ██╔═══██╗██╔════╝
 ███████╗██╔████╔██║███████║██║     ██║██║     ██║   ██║██║  ███╗
 ╚════██║██║╚██╔╝██║██╔══██║██║     ██║██║     ██║   ██║██║   ██║
 ███████║██║ ╚═╝ ██║██║  ██║███████╗██║███████╗╚██████╔╝╚██████╔╝
 ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚═╝╚══════╝ ╚═════╝  ╚═════╝
"""
    print(_c(_CYAN, banner.rstrip()))
    print(_c(_DIM, "  Android Smali logging · Dashboard local · Menú guiado"))
    print(_c(_DIM, "  Autor original: VictorH028"))


# --------------------------------------------------------------------------- #
#  Menú de subcomandos estilo git
# --------------------------------------------------------------------------- #
# (nombre, resumen, args típicos, es_hook)
_COMMANDS = [
    ("server",     "Arranca el servidor HTTP que recibe los logs.",
     "smalilog server [--host H] [-p PORT]", False),
    ("listen",     "Escucha y muestra logs en vivo por WebSocket.",
     "smalilog listen [--host H] [-p PORT] [--wss]", False),

    # --- hook: subcomandos ---
    ("hook list",       "Lista los métodos del archivo Smali.",
     "smalilog hook list <file>", True),
    ("hook show",       "Muestra el código smali de un método.",
     "smalilog hook show <file> -m <m> [--all]", True),
    ("hook analyze",    "Analiza registros y plan de inyección.",
     "smalilog hook analyze <file> -m <m> [--sig S]", True),
    ("hook enter",      "Inyecta hook de entrada.",
     "smalilog hook enter <file> -m <m>", True),
    ("hook exit",       "Inyecta hook de salida.",
     "smalilog hook exit <file> -m <m>", True),
    ("hook both",       "Inyecta enter + exit.",
     "smalilog hook both <file> -m <m>", True),
    ("hook log",        "Inyecta un log tag/mensaje.",
     'smalilog hook log <file> -m <m> --tag T --message MSG', True),
    ("hook lifecycle",  "LifecycleTracker en Application.onCreate.",
     "smalilog hook lifecycle <file> -m onCreate", True),
]


def _print_main_help() -> None:
    """Ayuda principal con subcomandos agrupados al estilo git."""
    prog = "smalilog"
    print()
    print(_c(_BOLD, f"Uso: {prog} <comando> [opciones]"))
    print(_c(_BOLD, f"     {prog} --version"))
    print(_c(_BOLD, f"     {prog} -h | --help"))
    print()
    print("Herramienta para instrumentar aplicaciones Android con log remoto")
    print("vía Smali + JNI + servidor HTTP.")
    print()
    print(_c(_BOLD, "Comandos:"))

    # Ancho para alinear la segunda columna
    width = max(len(name) for name, *_ in _COMMANDS) + 2

    for name, summary, _example, is_hook in _COMMANDS:
        if is_hook:
            label = "  " + _c(_DIM, "└─ ") + _c(_GREEN, name)
        else:
            label = _c(_CYAN, name)
        pad = " " * (width - len(name))
        print(f"  {label}{pad}{summary}")

    print()
    print(_c(_BOLD, "Opciones globales:"))
    print(f"  {_c(_CYAN, '-h, --help'):<28} Muestra esta ayuda.")
    print(f"  {_c(_CYAN, '--version'):<28} Muestra la versión.")
    print()
    print(_c(_BOLD, "Ejemplos:"))
    for name, _s, example, _h in _COMMANDS:
        print(f"  {_c(_DIM, '$')} {example}")
    print()
    print(_c(_DIM, "Usa 'smalilog hook <cmd> -h' para ver opciones de un subcomando."))
    print()


# --------------------------------------------------------------------------- #
#  Tipos validadores de argparse
# --------------------------------------------------------------------------- #
def _port_type(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"puerto inválido: {value!r}") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"el puerto debe estar entre 0 y 65535 (recibido: {port})")
    return port


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"entero inválido: {value!r}") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(
            f"debe ser un entero > 0 (recibido: {number})")
    return number


def _log_level_type(value: str) -> str:
    level = value.upper()
    if level not in LOG_LEVELS:
        raise argparse.ArgumentTypeError(
            f"nivel inválido: {value!r} "
            f"(opciones: {', '.join(sorted(LOG_LEVELS))})")
    return level


# --------------------------------------------------------------------------- #
#  Subparser: server
# --------------------------------------------------------------------------- #
def _add_server_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "server",
        help="Arranca el servidor de logs (POST /log).",
        description="Arranca el servidor HTTP que recibe logs JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplo de petición:\n"
            "  curl -X POST http://127.0.0.1:9999/log \\\n"
            "       -H 'Content-Type: application/json' \\\n"
            "       -d '{\"level\":\"INFO\",\"tag\":\"APP\",\"message\":\"hola\"}'\n"
        ),
    )
    p.add_argument("--host", default=config.DEFAULT_HOST,
                   help="Host donde escuchar (por defecto: %(default)s).")
    p.add_argument("-p", "--port", type=_port_type, default=config.DEFAULT_PORT,
                   metavar="PUERTO",
                   help="Puerto TCP 0-65535 (por defecto: %(default)s).")
    p.add_argument("-f", "--log-file", default=config.DEFAULT_LOG_FILE,
                   metavar="ARCHIVO",
                   help="Archivo de logs (por defecto: %(default)s).")
    p.add_argument("-l", "--log-level", type=_log_level_type,
                   default=str(config.DEFAULT_LOG_LEVEL).upper(),
                   choices=sorted(LOG_LEVELS),
                   help="Nivel mínimo de log (por defecto: %(default)s).")
    p.add_argument("--tag-regex", metavar="PATRÓN",
                   help="Acepta solo tags que coincidan con esta expresión regular.")
    p.add_argument("--min-level", type=_log_level_type, default="DEBUG",
                   choices=sorted(LOG_LEVELS), metavar="NIVEL",
                   help="Descarta eventos por debajo de este nivel (por defecto: DEBUG).")
    p.add_argument("--max-headers", type=_positive_int, default=config.MAX_HEADERS,
                   metavar="BYTES",
                   help="Tamaño máximo de cabeceras HTTP (por defecto: %(default)s).")
    p.add_argument("--max-body", type=_positive_int, default=config.MAX_BODY,
                   metavar="BYTES",
                   help="Tamaño máximo del cuerpo HTTP (por defecto: %(default)s).")
    p.add_argument("--no-blocking", action="store_true",
                   help="Arranca en un hilo aparte.")
    p.add_argument("--ws-port", type=_port_type, default=None,
                   metavar="PUERTO",
                   help="Puerto para la difusión en tiempo real por WebSocket "
                        "(ws:// o wss://). Por defecto desactivado.")
    p.add_argument("--certfile", metavar="ARCHIVO",
                   help="Certificado X.509 para TLS (requiere --keyfile).")
    p.add_argument("--keyfile", metavar="ARCHIVO",
                   help="Clave privada para TLS (requiere --certfile).")
    p.add_argument("--self-signed", action="store_true",
                   help="Genera (o reutiliza) un certificado auto-firmado para "
                        "wss://. Usa ~/.smalilog/ y habilita WebSocket por "
                        "defecto en puerto HTTP+1.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Muestra la configuración antes de arrancar.")


# --------------------------------------------------------------------------- #
#  Subparser: listen
# --------------------------------------------------------------------------- #
def _add_listen_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "listen",
        help="Escucha logs en vivo por WebSocket.",
        description=(
            "Conecta al WebSocket de un servidor smalilog y muestra cada log "
            "recibido en la terminal (sin navegador)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  smalilog listen\n"
            "  smalilog listen --host 192.168.1.10 -p 9998\n"
            "  smalilog listen --wss --insecure --min-level WARNING\n"
        ),
    )
    p.add_argument("--host", default=config.DEFAULT_HOST,
                   help="Host del servidor (por defecto: %(default)s).")
    p.add_argument("-p", "--port", type=_port_type,
                   default=config.DEFAULT_PORT + 1, metavar="PUERTO",
                   help="Puerto WebSocket (por defecto: %(default)s, HTTP+1).")
    p.add_argument("--wss", action="store_true",
                   help="Conecta por TLS (wss://). Requiere trust/TLS en servidor.")
    p.add_argument("--certfile", metavar="CA",
                   help="CA o certificado para verificar el servidor (wss).")
    p.add_argument("--insecure", action="store_true",
                   help="No verificar el certificado TLS (wss auto-firmado).")
    p.add_argument("-m", "--min-level", type=_log_level_type, default="DEBUG",
                   choices=sorted(LOG_LEVELS), metavar="NIVEL",
                   help="Filtra en cliente eventos por debajo de este nivel "
                        "(por defecto: DEBUG).")
    p.add_argument("--raw", action="store_true",
                   help="Imprime el JSON crudo en lugar del formato legible.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Muestra detalles de conexión y reconexiones.")


# --------------------------------------------------------------------------- #
#  Handlers: listen
# --------------------------------------------------------------------------- #
def _level_color(level: str) -> str:
    if level in ("ERROR", "CRITICAL"):
        return "\033[91m"  # rojo
    if level == "WARNING":
        return _YELLOW
    if level == "DEBUG":
        return _DIM
    return _GREEN


def _print_event(evt: dict) -> None:
    """Imprime un evento en formato legible con color por nivel."""
    level = str(evt.get("level", "INFO")).upper()
    tag = str(evt.get("tag", "APP"))
    message = str(evt.get("message", ""))
    ts = str(evt.get("timestamp", ""))
    src = str(evt.get("source", "?"))
    print(
        _c(_DIM, f"[{ts}]")
        + " " + _c(_level_color(level), f"[{level}]")
        + f" [{tag}] " + _c(_DIM, f"[{src}]")
        + f" {message}"
    )


def _listen_ssl_context(args) -> ssl.SSLContext | None:
    """Construye el contexto TLS de cliente, o None para ws:// simple."""
    if not args.wss:
        return None
    import ssl
    if args.insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    try:
        return ssl.create_default_context(cafile=args.certfile)
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(f"Certificado CA inválido: {exc}") from exc


def _cmd_listen(args: argparse.Namespace) -> int:
    import websockets
    from websockets.exceptions import WebSocketException

    scheme = "wss" if args.wss else "ws"
    uri = f"{scheme}://{args.host}:{args.port}"
    min_level = LOG_LEVELS.get(args.min_level, LOG_LEVELS["DEBUG"])
    try:
        ssl_context = _listen_ssl_context(args)
    except ValueError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.verbose:
        tls = f" · {('auto-firmado' if args.insecure else 'verificado')}" \
            if args.wss else ""
        print(f"Escuchando : {uri}{tls}", file=sys.stderr)
        print(f"Nivel mín.  : {args.min_level}", file=sys.stderr)
        print("Ctrl+C para salir", file=sys.stderr)

    async def _run() -> int:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(uri, ssl=ssl_context) as ws:
                    backoff = 1.0
                    if args.verbose:
                        print(f"Conectado a {uri}.", file=sys.stderr)
                    async for raw in ws:
                        try:
                            evt = json.loads(raw)
                        except (ValueError, TypeError):
                            print(raw)
                            continue
                        if not isinstance(evt, dict):
                            print(raw)
                            continue
                        level = str(evt.get("level", "INFO")).upper()
                        if LOG_LEVELS.get(level, logging.INFO) < min_level:
                            continue
                        if args.raw:
                            print(raw)
                        else:
                            _print_event(evt)
            except WebSocketException as exc:
                print(f"Conexión perdida ({exc}). Reintentando…",
                      file=sys.stderr)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)
            except OSError as exc:
                print(f"Error de red: {exc}. Reintentando en {backoff}s…",
                      file=sys.stderr)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)

    try:
        return asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nEscucha detenida.", file=sys.stderr)
        return EXIT_OK


def _prompt(prompt: str, input_fn=input) -> str | None:
    """Lee una respuesta del menú y permite cancelar con EOF."""
    try:
        value = input_fn(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return value


def _go_back(value: str | None) -> bool:
    """Indica si una respuesta pide regresar al menú principal."""
    return value is None or value.lower() in {"0", "b", "back", "volver"}


def _interactive_menu(input_fn=input) -> int:
    """Ejecuta acciones frecuentes de la CLI con preguntas guiadas."""
    actions = {
        "1": ("Listar métodos", "list", False),
        "2": ("Mostrar método", "show", False),
        "3": ("Analizar registros", "analyze", False),
        "4": ("Inyectar hook de entrada", "enter", True),
        "5": ("Inyectar hook de salida", "exit", True),
        "6": ("Inyectar LifecycleTracker", "lifecycle", True),
        "9": ("Escuchar logs por WebSocket (listen)", "listen", False),
    }
    while True:
        print()
        _print_banner()
        print(_c(_BOLD, "\nSMALILOG · Menú interactivo"))
        print("Escribe 0 o 'volver' en cualquier formulario para regresar.")
        for key, (label, _command, _writes) in actions.items():
            print(f"  {key}. {label}")
        print("  7. Iniciar servidor de logs")
        print("  8. Mostrar URL del dashboard")
        print("  0. Salir")
        choice = _prompt("Selecciona una opción: ", input_fn)
        if _go_back(choice):
            return EXIT_OK
        if choice == "7":
            host = _prompt("Host [127.0.0.1]: ", input_fn)
            if _go_back(host):
                continue
            port = _prompt("Puerto [9999]: ", input_fn)
            if _go_back(port):
                continue
            argv = ["server", "--host", host or config.DEFAULT_HOST]
            if port:
                argv.extend(["--port", port])
            return cli(argv)
        if choice == "8":
            host = _prompt("Host del servidor [127.0.0.1]: ", input_fn)
            if _go_back(host):
                continue
            port = _prompt("Puerto del servidor [9999]: ", input_fn)
            if _go_back(port):
                continue
            host = host or config.DEFAULT_HOST
            port = port or str(config.DEFAULT_PORT)
            print(f"\nDashboard: http://{host}:{port}/")
            print("Inicia primero 'smalilog server' si el servidor no está activo.")
            _prompt("Pulsa Enter para volver al menú: ", input_fn)
            continue
        if choice == "9":
            host = _prompt("Host del servidor [127.0.0.1]: ", input_fn)
            if _go_back(host):
                continue
            ws_port = _prompt("Puerto WebSocket [10000]: ", input_fn)
            if _go_back(ws_port):
                continue
            argv = ["listen", "--host", host or config.DEFAULT_HOST, "--port", ws_port or str(config.DEFAULT_PORT + 1)]
            return cli(argv)
        if choice not in actions:
            print("Opción inválida.")
            continue

        _label, command, writes = actions[choice]
        file_path = _prompt("Ruta del archivo .smali [0=volver]: ", input_fn)
        if _go_back(file_path):
            print("Regresando al menú.")
            continue
        argv = [command, file_path]
        if command != "list":
            method = _prompt("Método objetivo [0=volver]: ", input_fn)
            if _go_back(method):
                print("Regresando al menú.")
                continue
            argv.extend(["--method", method])
            signature = _prompt(
                "Firma para sobrecarga, opcional [0=volver]: ", input_fn,
            )
            if _go_back(signature):
                print("Regresando al menú.")
                continue
            if signature:
                argv.extend(["--sig", signature])
        if writes:
            confirmation = _prompt(
                "Esto modificará el archivo y creará un backup. ¿Continuar? [s/N]: ",
                input_fn,
            )
            if _go_back(confirmation) or confirmation.lower() not in {
                "s", "si", "sí", "y", "yes",
            }:
                print("Regresando al menú.")
                continue
        result = run_hooker(argv, prog="smalilog hook")
        print(f"Resultado: {'correcto' if result == EXIT_OK else 'con errores'}")


# --------------------------------------------------------------------------- #
#  Parser principal (solo server; hook se delega)
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smalilog",
        description=(
            "Herramienta para instrumentar aplicaciones Android con log "
            "remoto vía Smali + JNI + servidor HTTP.\n"
            "\n"
            "subcomandos:\n"
            "  server    Arranca el servidor HTTP que recibe los logs.\n"
            "  hook      Inyecta hooks de logging en archivos Smali\n"
            "            (ver ayuda con: smalilog hook -h)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  smalilog server\n"
            "  smalilog server --host 0.0.0.0 -p 8080\n"
            "  smalilog hook list app.smali\n"
            "  smalilog hook enter app.smali -m Sf\n"
            "  smalilog hook lifecycle Application.smali -m onCreate\n"
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {config.VERSION}")

    subparsers = parser.add_subparsers(dest="command", metavar="<comando>")
    _add_server_parser(subparsers)
    _add_listen_parser(subparsers)
    subparsers.add_parser("menu", help="Abre el menú interactivo.")
    return parser


# --------------------------------------------------------------------------- #
#  Espera del servidor en segundo plano
# --------------------------------------------------------------------------- #
def _wait_background_server(server: LogServer) -> None:
    print("Servidor en segundo plano. Presiona Ctrl+C para detenerlo...",
          file=sys.stderr)
    thread = getattr(server, "_thread", None)
    try:
        while True:
            if getattr(server, "is_running", True) is False:
                break
            if thread is not None and not thread.is_alive():
                break
            if thread is not None:
                thread.join(timeout=0.5)
            else:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------- #
#  Handler: server
# --------------------------------------------------------------------------- #
def _cmd_server(args: argparse.Namespace) -> int:
    log_level = LOG_LEVELS.get(str(args.log_level).upper())
    if log_level is None:
        print(f"Nivel de log desconocido: {args.log_level!r}", file=sys.stderr)
        return EXIT_USAGE

    if args.self_signed:
        if args.ws_port is None:
            args.ws_port = args.port + 1
        if not (args.certfile and args.keyfile):
            cert_dir = os.path.join(os.path.expanduser("~"), ".smalilog")
            args.certfile = os.path.join(cert_dir, "server-cert.pem")
            args.keyfile = os.path.join(cert_dir, "server-key.pem")
        try:
            args.certfile, args.keyfile = ensure_self_signed(
                args.certfile, args.keyfile)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR

    if args.verbose:
        print(f"Host        : {args.host}")
        print(f"Puerto      : {args.port}")
        print(f"Log file    : {args.log_file}")
        print(f"Log level   : {args.log_level}")
        print(f"Tag regex   : {args.tag_regex or 'sin filtro'}")
        print(f"Min level   : {args.min_level}")
        print(f"Max headers : {args.max_headers} bytes")
        print(f"Max body    : {args.max_body} bytes")
        print(f"Modo        : "
              f"{'hilo aparte' if args.no_blocking else 'bloqueante'}")
        print(f"WebSocket   : "
              f"{args.ws_port if args.ws_port is not None else 'desactivado'}")
        if args.ws_port is not None:
            scheme = "wss" if (args.certfile and args.keyfile) else "ws"
            print(f"Web URL     : {scheme}://{args.host}:{args.ws_port}")

    common = {
        "host": args.host,
        "port": args.port,
        "log_file": args.log_file,
        "log_level": log_level,
        "tag_regex": args.tag_regex,
        "min_level": args.min_level,
        "max_headers": args.max_headers,
        "max_body": args.max_body,
        "ws_port": args.ws_port,
        "tls_certfile": args.certfile,
        "tls_keyfile": args.keyfile,
    }
    try:
        server = LogServer(**common)
    except (TypeError, ValueError) as exc:
        print(f"Configuración inválida del servidor: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        server.start(blocking=not args.no_blocking)
        if args.no_blocking:
            _wait_background_server(server)
    except KeyboardInterrupt:
        print("\nInterrupción recibida, cerrando...", file=sys.stderr)
    except OSError as exc:
        print(f"Error al iniciar el servidor: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        try:
            server.stop()
        except Exception as exc:
            print(f"Aviso: no se pudo detener limpiamente: {exc}",
                  file=sys.stderr)
    return EXIT_OK


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def cli(argv: list[str] | None = None) -> int:
    """
    Punto de entrada del CLI.

    - `hook` se delega al hooker con su propio parser.
    - Sin subcomando → menú principal (bonito).
    - Devuelve un código de salida; nunca lanza SystemExit.
    """
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)

    # Delegar `hook` completo (con su subparser interno y su propia ayuda).
    if argv and argv[0] == "hook":
        return run_hooker(argv[1:] or ["--help"], prog="smalilog hook")

    # Sin argumentos → menú bonito
    if not argv:
        _print_main_help()
        return EXIT_OK

    # -h/--help a secas → menú bonito también (en vez del argparse feo)
    if argv in (["-h"], ["--help"]):
        _print_main_help()
        return EXIT_OK

    parser = _build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else EXIT_OK

    if args.command == "server":
        return _cmd_server(args)
    if args.command == "listen":
        return _cmd_listen(args)
    if args.command == "menu":
        return _interactive_menu()

    parser.print_help()
    return EXIT_USAGE


# Alias retro-compatible
main = cli


if __name__ == "__main__":
    sys.exit(cli())
