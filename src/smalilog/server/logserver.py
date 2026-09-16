#!/usr/bin/env python3
"""
Servidor TCP/HTTP ligero para recepción y registro de logs en formato JSON.

Este módulo expone la clase LogServer, pensada para ser usada desde el CLI
(smalilog.main) o programáticamente. Además del HTTP clásico (POST /log y
panel /), ofrece una difusión en tiempo real por WebSocket (ws:// o wss://)
opcional, activada al indicar un puerto con ws_port.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import ssl
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed


class LogServer:
    """Servidor TCP/HTTP ligero para recepción y registro de logs en formato JSON."""

    MAX_HEADERS: int = 16 * 1024
    MAX_BODY: int = 1024 * 1024
    _LEVELS = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9999,
        log_file: str = "app_logs.txt",
        log_level: int = logging.INFO,
        tag_regex: str | None = None,
        min_level: str = "DEBUG",
        max_headers: int | None = None,
        max_body: int | None = None,
        ws_port: int | None = None,
        tls_certfile: str | None = None,
        tls_keyfile: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.log_file = log_file
        self.is_running = False
        self._server_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

        # Estado del servidor WebSocket (opcional).
        self.ws_port = ws_port
        self.tls_certfile = tls_certfile
        self.tls_keyfile = tls_keyfile
        if (tls_certfile is None) != (tls_keyfile is None):
            raise ValueError(
                "--certfile y --keyfile deben indicarse juntos (TLS WebSocket)."
            )
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_done: Optional[asyncio.Future] = None
        self._ws_clients: set = set()
        self._ws_lock = threading.Lock()

        self._events: deque[dict[str, str]] = deque(maxlen=200)
        self._events_lock = threading.Lock()
        self.tag_regex = tag_regex
        self._tag_pattern = re.compile(tag_regex) if tag_regex else None
        self.min_level = min_level.upper()
        if self.min_level not in self._LEVELS:
            raise ValueError(f"Nivel mínimo inválido: {min_level!r}")
        if max_headers is not None:
            self.MAX_HEADERS = max_headers
        if max_body is not None:
            self.MAX_BODY = max_body

        self.logger = logging.getLogger("smalilog.LogServer")
        self.logger.setLevel(log_level)
        self.logger.propagate = False

        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def _accepts_log(self, level: str, tag: str) -> bool:
        """Comprueba si un evento supera los filtros de recepción."""
        event_level = self._LEVELS.get(level.upper(), logging.INFO)
        if event_level < self._LEVELS[self.min_level]:
            return False
        return self._tag_pattern is None or self._tag_pattern.search(tag) is not None

    # ---------------- HTTP helpers ---------------- #
    def _send_response(self, conn: socket.socket, status: str, body: bytes = b"",
                       content_type: str = "text/plain; charset=utf-8") -> None:
        response = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + body
        conn.sendall(response)

    def _read_request(self, conn: socket.socket) -> tuple[str, str, bytes]:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                raise ValueError("Conexión cerrada")
            data += chunk
            if len(data) > self.MAX_HEADERS:
                raise ValueError("Cabeceras HTTP demasiado grandes")

        headers, body = data.split(b"\r\n\r\n", 1)
        lines = headers.decode("latin-1").split("\r\n")
        if not lines or not lines[0]:
            raise ValueError("Petición HTTP vacía")

        request_line = lines[0].split()
        if len(request_line) != 3:
            raise ValueError("Línea HTTP inválida")

        method, path, version = request_line
        if method == "GET" and path in ("/", "/api/logs"):
            return method, path, b""
        if method != "POST":
            raise ValueError("Método no permitido")
        if path != "/log":
            raise ValueError("Ruta no permitida")
        if version not in ("HTTP/1.0", "HTTP/1.1"):
            raise ValueError("Versión HTTP no soportada")

        content_length: Optional[int] = None
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            if name.lower() == "content-length":
                try:
                    content_length = int(value.strip())
                except ValueError:
                    raise ValueError("Content-Length inválido")
                break

        if content_length is None:
            raise ValueError("Falta Content-Length")
        if content_length < 0:
            raise ValueError("Content-Length negativo")
        if content_length > self.MAX_BODY:
            raise ValueError("Cuerpo demasiado grande")

        while len(body) < content_length:
            chunk = conn.recv(4096)
            if not chunk:
                raise ValueError("Cuerpo HTTP incompleto")
            body += chunk

        return method, path, body[:content_length]

    # ---------------- Manejo de cliente ---------------- #
    def handle_client(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        try:
            method, path, body = self._read_request(conn)
            if method == "GET":
                self._handle_dashboard(conn, path)
                return
            log_data = json.loads(body.decode("utf-8"))
            if not isinstance(log_data, dict):
                raise ValueError("El JSON debe ser un objeto")

            level = str(log_data.get("level", "INFO")).upper()[:100]
            tag = str(log_data.get("tag", "APP"))[:500]
            message = str(log_data.get("message", ""))[: self.MAX_BODY]
            source_timestamp = str(log_data.get("timestamp", ""))[:100]

            if not self._accepts_log(level, tag):
                self._send_response(conn, "204 No Content")
                print(f"[FILTERED] [{level}] [{tag}]")
                return

            log_entry = f"[{tag}] {message}"

            match level:
                case "ERROR":
                    self.logger.error(log_entry)
                case "WARNING":
                    self.logger.warning(log_entry)
                case "DEBUG":
                    self.logger.debug(log_entry)
                case _:
                    self.logger.info(log_entry)

            self._send_response(conn, "200 OK", b"OK")
            event = {
                "timestamp": source_timestamp or datetime.now(timezone.utc).isoformat(),
                "level": level,
                "tag": tag,
                "message": message,
                "source": addr[0],
            }
            with self._events_lock:
                self._events.append(event)
            self._broadcast_ws(event)
            print(f"[{level}] [{tag}] {message}")

        except Exception as exc:
            self.logger.error("Error procesando petición de %s: %s", addr, exc)
            print(f"Error de {addr}: {exc}")
            try:
                self._send_response(conn, "400 Bad Request")
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _handle_dashboard(self, conn: socket.socket, path: str) -> None:
        """Sirve el panel y su API de solo lectura en el mismo loopback."""
        if path == "/api/logs":
            with self._events_lock:
                body = json.dumps(list(self._events), ensure_ascii=False).encode()
            self._send_response(conn, "200 OK", body, "application/json; charset=utf-8")
            return
        ws_scheme = "wss" if self._build_ws_ssl_context() else "ws"
        ws_port = str(self.ws_port) if self.ws_port is not None else ""
        body = '''<!doctype html><meta charset="utf-8"><title>Smalilog Dashboard</title>
<style>body{background:#10131a;color:#e8eef7;font:15px system-ui;margin:2rem}h1{color:#48d1cc}table{border-collapse:collapse;width:100%}th,td{padding:.6rem;border-bottom:1px solid #303846;text-align:left}.ERROR,.CRITICAL{color:#ff6b6b}.WARNING{color:#ffd166}.DEBUG{color:#9aa7b8}.live{color:#48d1cc}.poll{color:#ffd166}.off{color:#ff6b6b}</style>
<h1>Smalilog · Eventos recientes</h1><p id="status">Conectando…</p><table><thead><tr><th>Hora UTC</th><th>Nivel</th><th>Tag</th><th>Origen</th><th>Mensaje</th></tr></thead><tbody id="logs"></tbody></table>
<script>
const MAX=200, WS_PORT="__WS_PORT__", WS_SCHEME="__WS_SCHEME__";
const WS_URL = WS_PORT ? (WS_SCHEME+"://"+location.hostname+":"+WS_PORT) : "";
const tbody=document.querySelector('#logs'), status=document.querySelector('#status');
let rows=[], polling=null, ws=null;
function mkRow(x){let tr=document.createElement('tr');tr.className=x.level;for(let v of [x.timestamp,x.level,x.tag,x.source,x.message]){let td=document.createElement('td');td.textContent=v;tr.append(td)}return tr}
function render(){tbody.replaceChildren(...rows.slice().reverse().map(mkRow))}
function setStatus(txt,cls){status.textContent=txt;status.className=cls}
function loadHistory(){return fetch('/api/logs').then(r=>r.json()).then(e=>{rows=e.slice(-MAX);render()}).catch(()=>{})}
function addEvt(x){if(!x.level)return;rows.push(x);if(rows.length>MAX)rows.shift();render()}
function startPolling(){if(polling)return;setStatus('Actualizando cada segundo (respaldo)', 'poll');polling=setInterval(()=>{fetch('/api/logs').then(r=>r.json()).then(e=>{rows=e.slice(-MAX);render()}).catch(()=>{})},1000)}
async function init(){
  await loadHistory();
  if(!WS_URL)return startPolling();
  try{
    ws=new WebSocket(WS_URL);
    ws.onopen=()=>{setStatus('En vivo por WebSocket · '+WS_URL,'live');if(polling){clearInterval(polling);polling=null}};
    ws.onmessage=e=>{try{addEvt(JSON.parse(e.data))}catch(_){}};
    ws.onclose=()=>{setStatus('Sin conexión en vivo · reejecutando por polling','off');startPolling()};
    ws.onerror=()=>{try{ws.close()}catch(_){}};
    setTimeout(()=>{if(ws.readyState!==1)startPolling()},3000);
  }catch(_){startPolling()}
}
init();
</script>'''.replace("__WS_PORT__", ws_port).replace("__WS_SCHEME__", ws_scheme)
        self._send_response(conn, "200 OK", body.encode(), "text/html; charset=utf-8")

    # ---------------- WebSocket (tiempo real) ---------------- #
    def _build_ws_ssl_context(self) -> ssl.SSLContext | None:
        """Construye un contexto TLS para wss:// o None para ws:// simple."""
        if self.tls_certfile and self.tls_keyfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.tls_certfile, self.tls_keyfile)
            return context
        return None

    def _start_ws(self) -> None:
        """Arranca el servidor WebSocket en su propio hilo y event loop."""
        self._ws_loop = asyncio.new_event_loop()
        self._ws_thread = threading.Thread(
            target=self._ws_loop.run_until_complete,
            args=(self._ws_serve(),),
            daemon=True,
            name="LogServer-WS",
        )
        self._ws_thread.start()
        scheme = "wss" if self._build_ws_ssl_context() else "ws"
        print(f"WebSocket  : {scheme}://{self.host}:{self.ws_port}")

    async def _ws_serve(self) -> None:
        """Ejecuta el servidor WebSocket hasta que se cierre."""
        self._ws_done = asyncio.get_running_loop().create_future()
        context = self._build_ws_ssl_context()
        try:
            async with websockets.serve(
                self._ws_handler, self.host, self.ws_port, ssl=context,
            ):
                await self._ws_done
        finally:
            self._ws_done = None

    async def _ws_handler(self, websocket) -> None:
        """Registra un cliente WebSocket y espera su cierre."""
        with self._ws_lock:
            self._ws_clients.add(websocket)
        try:
            async for _ in websocket:
                pass
        except ConnectionClosed:
            pass
        finally:
            with self._ws_lock:
                self._ws_clients.discard(websocket)

    async def _ws_send(self, websocket, payload: str) -> None:
        """Envía una trama JSON a un único cliente WebSocket."""
        try:
            await websocket.send(payload)
        except Exception:
            with self._ws_lock:
                self._ws_clients.discard(websocket)

    def _broadcast_ws(self, log_data: dict[str, str]) -> None:
        """Propaga un evento a todos los clientes WebSocket conectados."""
        loop = self._ws_loop
        if loop is None or not loop.is_running():
            return
        payload = json.dumps(log_data, ensure_ascii=False)
        with self._ws_lock:
            clients = list(self._ws_clients)
        for websocket in clients:
            asyncio.run_coroutine_threadsafe(self._ws_send(websocket, payload), loop)

    def _stop_ws(self) -> None:
        """Detiene el servidor WebSocket y su hilo."""
        done = self._ws_done
        loop = self._ws_loop
        if done is not None and loop is not None:
            def _finish() -> None:
                if not done.done():
                    done.set_result(True)
            loop.call_soon_threadsafe(_finish)
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2.0)
        self._ws_thread = None
        self._ws_loop = None

    # ---------------- Ciclo de vida ---------------- #
    def start(self, blocking: bool = True) -> None:
        if self.ws_port is not None:
            self._start_ws()
        if blocking:
            self._run()
        else:
            self.is_running = True
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="LogServer"
            )
            self._thread.start()

    def _run(self) -> None:
        self.is_running = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            self._server_socket = server
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.settimeout(1.0)

            server.bind((self.host, self.port))
            self.port = server.getsockname()[1]
            server.listen(5)

            print(f"Servidor de logs en http://{self.host}:{self.port}")

            while self.is_running:
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                except Exception as exc:
                    if self.is_running:
                        print(f"Error en el loop del servidor: {exc}")
                    break

                threading.Thread(
                    target=self.handle_client,
                    args=(conn, addr),
                    daemon=True,
                ).start()

        self._server_socket = None

    def stop(self) -> None:
        self.is_running = False
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._stop_ws()
        print("Servidor detenido")