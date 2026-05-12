"""Validate user-supplied Ollama base URLs before outbound requests (SSRF mitigation)."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


def is_ollama_trust_lan_enabled() -> bool:
    return os.getenv("AGENTFORGE_OLLAMA_TRUST_LAN", "").lower() in ("1", "true", "yes")


def _allowed_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, *, trust_lan: bool) -> bool:
    if addr.is_loopback:
        return True
    if trust_lan and (addr.is_private or addr.is_link_local):
        return True
    return False


def _format_origin(scheme: str, host: str, port: int) -> str:
    if scheme == "https" and port == 443:
        return f"https://{host}"
    if scheme == "http" and port == 80:
        return f"http://{host}"
    return f"{scheme}://{host}:{port}"


def validate_ollama_base_url(url: str) -> str:
    """
    Validate and return a normalized Ollama API origin (no path).

    Default policy: host must resolve only to loopback. Set AGENTFORGE_OLLAMA_TRUST_LAN=1
    to allow private/link-local targets (e.g. Docker service names on a bridge network).

    Allowed schemes: http, https. Ports: 80, 443, 11434 unless TRUST_LAN is enabled
    (then any port is permitted for allowed IPs).
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Ollama URL is empty")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Ollama URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("Ollama URL must include a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    trust_lan = is_ollama_trust_lan_enabled()
    if not trust_lan and port not in (80, 443, 11434):
        raise ValueError(
            "Ollama URL port must be 80, 443, or 11434 (or set AGENTFORGE_OLLAMA_TRUST_LAN=1 for LAN/Docker)"
        )

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError("Could not resolve Ollama hostname") from e

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _fam, _socktype, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addrs.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue
    if not addrs:
        raise ValueError("Could not resolve Ollama host to an IP address")
    if not all(_allowed_ip(a, trust_lan=trust_lan) for a in addrs):
        raise ValueError(
            "Ollama host must resolve to loopback addresses only "
            "(or set AGENTFORGE_OLLAMA_TRUST_LAN=1 for private networks)"
        )

    return _format_origin(parsed.scheme, host, port)
