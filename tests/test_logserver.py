"""Pruebas sin dependencias externas del receptor HTTP de smalilog."""

from __future__ import annotations

import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from smalilog.server.logserver import LogServer


def _post(port: int, payload: dict[str, str]) -> bytes:
    """Envía un POST /log mínimo y devuelve la respuesta HTTP completa."""
    body = json.dumps(payload).encode()
    request = (
        b"POST /log HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall(request)
        return conn.recv(4096)


class LogServerIntegrationTests(unittest.TestCase):
    """Comprueba filtros y respuestas contra un socket HTTP real."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "events.log"
        self.server = LogServer(
            port=0,
            log_file=str(self.log_file),
            tag_regex=r"^(AUTH|API)$",
            min_level="WARNING",
        )
        self.server.start(blocking=False)
        for _ in range(30):
            if self.server.port != 0:
                return
            time.sleep(0.05)
        self.fail("El servidor no obtuvo un puerto efímero")

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_dir.cleanup()

    def test_filters_and_persists_only_accepted_event(self) -> None:
        self.assertIn(
            b"204 No Content",
            _post(self.server.port, {"level": "INFO", "tag": "AUTH", "message": "low"}),
        )
        self.assertIn(
            b"204 No Content",
            _post(self.server.port, {"level": "ERROR", "tag": "OTHER", "message": "tag"}),
        )
        self.assertIn(
            b"200 OK",
            _post(self.server.port, {"level": "ERROR", "tag": "AUTH", "message": "saved"}),
        )
        for _ in range(20):
            if self.log_file.exists() and "saved" in self.log_file.read_text():
                break
            time.sleep(0.05)
        contents = self.log_file.read_text()
        self.assertIn("[AUTH] saved", contents)
        self.assertNotIn("low", contents)
        self.assertNotIn("tag", contents)


class LogServerUnitTests(unittest.TestCase):
    """Comprueba la semántica de nivel y expresión regular."""

    def test_accepts_log_requires_tag_and_minimum_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = LogServer(
                log_file=str(Path(temp_dir) / "events.log"),
                tag_regex=r"^AUTH$",
                min_level="WARNING",
            )
            self.assertFalse(server._accepts_log("INFO", "AUTH"))
            self.assertFalse(server._accepts_log("ERROR", "API"))
            self.assertTrue(server._accepts_log("ERROR", "AUTH"))
