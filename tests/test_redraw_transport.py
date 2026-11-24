import io
import socket
import ssl
from unittest.mock import Mock

import pytest

from utils import redraw_transport as transport


def install_network(monkeypatch, addresses, replies):
    resolve = Mock(side_effect=[
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]
        for ips, port in addresses
    ])
    sockets = []
    for reply in replies:
        sock = Mock()
        sock.makefile.return_value = io.BytesIO(reply)
        sockets.append(sock)
    factory = Mock(side_effect=sockets)
    monkeypatch.setattr(transport.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(transport.socket, "socket", factory)
    return resolve, factory, sockets


def fetch(url):
    return transport.fetch_public(url, headers={}, timeout=2, max_bytes=4)


def test_pins_every_hop_and_authenticates_https_hostname(monkeypatch):
    resolve, _, socks = install_network(monkeypatch, [(["8.8.8.8"], 80), (["1.1.1.1"], 443)], [
        b"HTTP/1.1 302 Found\r\nLocation: https://cdn.example/img\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndata",
    ])
    wrap = Mock(return_value=socks[1])
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    assert fetch("http://article.example/") == b"data"
    assert resolve.call_count == 2
    socks[0].connect.assert_called_once_with(("8.8.8.8", 80))
    socks[1].connect.assert_called_once_with(("1.1.1.1", 443))
    wrap.assert_called_once_with(socks[1], server_hostname="cdn.example")
    assert b"Host: cdn.example\r\n" in socks[1].sendall.call_args.args[0]


def test_redirect_rejects_mixed_public_private_answers(monkeypatch):
    _, factory, _ = install_network(monkeypatch, [(["8.8.8.8"], 80), (["1.1.1.1", "127.0.0.1"], 80)], [
        b"HTTP/1.1 307 Redirect\r\nLocation: /next\r\n\r\n",
    ])
    with pytest.raises(ValueError, match="non-public"):
        fetch("http://article.example/")
    assert factory.call_count == 1


@pytest.mark.parametrize("response", [
    b"Content-Length: 5\r\n\r\n",
    b"\r\n12345",
    b"Transfer-Encoding: chunked\r\n\r\n5\r\n12345\r\n0\r\n\r\n",
    b"Content-Length: 4\r\n\r\nx",
])
def test_body_limits(monkeypatch, response):
    install_network(monkeypatch, [(["8.8.8.8"], 80)], [b"HTTP/1.1 200 OK\r\n" + response])
    with pytest.raises(ValueError):
        fetch("http://article.example/")


def test_certificate_failure_closes_without_sending(monkeypatch):
    _, _, socks = install_network(monkeypatch, [(["8.8.8.8"], 443)], [b""])

    def fail(context, sock, *, server_hostname):
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        raise ssl.SSLCertVerificationError()

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", fail)
    with pytest.raises(ssl.SSLCertVerificationError):
        fetch("https://article.example/")
    socks[0].close.assert_called_once()
    socks[0].sendall.assert_not_called()
