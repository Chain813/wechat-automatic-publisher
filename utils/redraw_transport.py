"""Direct, size-limited HTTP downloads for redraw articles and images."""
import http.client
import ipaddress
import socket
import ssl
from contextlib import closing
from urllib.parse import urljoin, urlsplit

from requests.utils import requote_uri


def _connect_public(host, port, timeout):
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers:
        raise ValueError("Host has no addresses")
    for family, _, _, _, address in answers:
        ip = ipaddress.ip_address(address[0])
        if (family not in (socket.AF_INET, socket.AF_INET6)
                or not ip.is_global or ip.is_multicast or ip.is_reserved
                or (ip.version == 6 and (ip.sixtofour or ip.teredo or ip.is_site_local))):
            raise ValueError("Host has a non-public address")
    for index, (family, kind, proto, _, address) in enumerate(answers):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError:
            sock.close()
            if index == len(answers) - 1:
                raise


def fetch_public(url, *, headers, timeout, max_bytes):
    for hop in range(6):
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or "%" in parts.hostname):
            raise ValueError("Invalid download URL")
        host = parts.hostname.encode("idna").decode("ascii")
        secure = parts.scheme == "https"
        port = parts.port if parts.port is not None else (443 if secure else 80)
        target = requote_uri((parts.path or "/") + ("?" + parts.query if parts.query else ""))
        with closing(http.client.HTTPConnection(host, port, timeout=timeout)) as conn:
            conn.auto_open = False
            conn.sock = _connect_public(host, port, timeout)
            if secure:
                conn.sock = ssl.create_default_context().wrap_socket(conn.sock, server_hostname=host)
            authority = f"[{host}]" if ":" in host else host
            if parts.port is not None:
                authority += f":{port}"
            conn.request("GET", target, headers={**headers, "Host": authority, "Accept-Encoding": "identity"})
            with conn.getresponse() as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location or hop == 5:
                        raise ValueError("Invalid or excessive redirects")
                    url = urljoin(url, location)
                    if secure and urlsplit(url).scheme != "https":
                        raise ValueError("Insecure redirect")
                    continue
                if response.status != 200 or response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("Unexpected download response")
                size = response.getheader("Content-Length")
                if size is not None and (not size.isascii() or not size.isdecimal() or int(size) > max_bytes):
                    raise ValueError("Invalid or excessive Content-Length")
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes or (size is not None and len(body) != int(size)):
                    raise ValueError("Invalid download size")
                return body
