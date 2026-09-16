"""Gestión de certificados TLS auto-firmados para el servidor.

Permite arrancar un servidor ``wss://`` sin generar certificados a mano:
genera un par clave/certificado auto-firmado y lo guarda de forma estable
para reutilizarlo entre reinicios (así ``smalilog listen --certfile <CA>``
puede apuntar al mismo certificado y verificar con confianza).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

_log = logging.getLogger("smalilog.tls")


def _generate_with_cryptography(cert_path: str, key_path: str) -> None:
    """Genera un par clave/certificado auto-firmado usando cryptography."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=370))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )

    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    with open(key_path, "wb") as fh:
        fh.write(key_bytes)
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))


def _generate_with_openssl(cert_path: str, key_path: str) -> None:
    """Genera el par con el binario openssl (respaldo)."""
    base = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", key_path, "-out", cert_path, "-days", "370",
        "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ]
    try:
        subprocess.run(base, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # OpenSSL antiguo sin -addext: generamos sin SAN (no verifica por IP).
        plain = base[:-2]
        subprocess.run(plain, check=True, capture_output=True)
        print("Aviso: tu openssl no soporta -addext; el certificado no "
              "verificará por IP. Usa '--wss --insecure' para conectar.",
              file=sys.stderr)


def ensure_self_signed(cert_path: str, key_path: str) -> tuple[str, str]:
    """Devuelve (certfile, keyfile) generando el par si hace falta."""
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    try:
        _generate_with_cryptography(cert_path, key_path)
    except ImportError:
        try:
            _generate_with_openssl(cert_path, key_path)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "No se pudo generar el certificado auto-firmado: faltaba "
                "'cryptography' y el respaldo 'openssl' también falló. "
                "Genera uno manualmente y pásalo con --certfile/--keyfile."
            ) from exc

    print(f"Certificado auto-firmado generado:\n  CA  : {cert_path}\n  key : {key_path}")
    print("Conéctate con 'smalilog listen --wss --insecure' o "
          f"'smalilog listen --wss --certfile {cert_path}'.",
          file=sys.stderr)
    return cert_path, key_path