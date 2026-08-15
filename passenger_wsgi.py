#!/usr/bin/env python3
"""
WSGI entry point for cPanel's "Setup Python App" (Phusion Passenger).

server.py is a standalone stdlib http.server app, not a WSGI app, so Passenger
can't run it directly. This bridge reuses server.py's Handler class unchanged:
for each WSGI request it rebuilds the raw HTTP bytes, feeds them to one Handler
instance through a fake socket, captures what the handler writes back, and
returns that to the WSGI server. All routing, auth, security headers and the
static allow-list live in server.py and are exercised exactly as they are when
you run `python server.py` locally.

Passenger looks for a callable named `application` in this file.
"""
import gzip
import io
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # importing runs module-level setup (reads secrets, defines Handler)

# main() normally does this; under Passenger main() never runs, so do it here — once
# per worker process. init_db() is create-if-not-exists + one-time admin seed, safe to
# repeat. The hourly cleanup thread is a daemon so it never blocks a worker shutting down.
server.init_db()
server.purge_expired()
threading.Thread(target=server.cleanup_loop, daemon=True).start()

# Hop-by-hop headers describe one TCP hop and must not be forwarded to the WSGI server,
# which manages its own connection to the client (RFC 2616 §13.5.1).
_HOP_BY_HOP = frozenset((
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
))

# --- compression ---------------------------------------------------------------------
# Nothing in front of this app compresses: index.html alone is 130KB of markup and inline
# script, and it went out raw on every cold load. These are the types worth compressing --
# text shrinks 70-80%, while JPEG/PNG/MP3/APK are already compressed and re-deflating them
# only burns CPU on a shared host that has little to spare.
_GZIP_TYPES = (
    "text/html", "text/css", "text/plain", "text/csv",
    "application/javascript", "text/javascript",
    "application/json", "image/svg+xml",
)
_GZIP_MIN = 1024   # below this the gzip header costs more than it saves


def _gzip_ok(environ, status, headers):
    if "gzip" not in environ.get("HTTP_ACCEPT_ENCODING", "").lower():
        return False
    if not status.startswith("200"):
        return False
    ctype = ""
    for name, value in headers:
        low = name.lower()
        if low == "content-encoding":
            return False           # already encoded; never double-compress
        if low == "content-type":
            ctype = value.split(";")[0].strip().lower()
    return ctype in _GZIP_TYPES


class _FakeConn:
    """A socket stand-in: hands the request bytes to the handler on makefile('rb')
    and collects everything written back (BaseHTTPRequestHandler writes via sendall
    when wbufsize is 0, which is the default)."""

    def __init__(self, request_bytes):
        self._reader = io.BytesIO(request_bytes)
        self.out = io.BytesIO()

    def makefile(self, mode="r", *args, **kwargs):
        return self._reader if "r" in mode else self.out

    def sendall(self, data):
        self.out.write(data)

    def close(self):
        pass


def _build_request(environ):
    """Reassemble the raw HTTP/1.0 request the handler expects to read off a socket."""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "") or "/"
    query = environ.get("QUERY_STRING", "")
    if query:
        path = path + "?" + query

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = 0
    body = environ["wsgi.input"].read(length) if length > 0 else b""

    lines = ["%s %s HTTP/1.0" % (method, path)]
    if environ.get("CONTENT_TYPE"):
        lines.append("Content-Type: " + environ["CONTENT_TYPE"])
    # Always send the true length of the body we actually read, so the handler reads
    # exactly this many bytes and no request can under- or over-run into the next.
    lines.append("Content-Length: " + str(len(body)))
    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        name = key[5:].replace("_", "-").title()
        if name.lower() in ("content-length", "content-type"):
            continue
        lines.append("%s: %s" % (name, value))
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    return head + body


def application(environ, start_response):
    conn = _FakeConn(_build_request(environ))
    client = (environ.get("REMOTE_ADDR", "") or "?", 0)

    # Instantiating the handler processes the single request start-to-finish (HTTP/1.0,
    # so it handles exactly one and returns) and writes the full response into conn.out.
    server.Handler(conn, client, None)

    raw = conn.out.getvalue()
    # Split on the index rather than with partition(): partition builds a copy of the head
    # AND a copy of the body, so a 25MB library download briefly held three copies of itself
    # in a worker. Slicing once keeps it to two, which on a 1GB shared-hosting memory cap is
    # the difference between serving a few concurrent downloads and having workers killed.
    cut = raw.find(b"\r\n\r\n")
    if cut < 0:
        cut, body = len(raw), b""
    else:
        body = raw[cut + 4:]
    head_lines = raw[:cut].split(b"\r\n")
    del raw

    status_line = head_lines[0].decode("latin-1") if head_lines else "HTTP/1.0 500"
    # "HTTP/1.0 200 OK" -> "200 OK"; WSGI wants the code + reason, without the version.
    parts = status_line.split(" ", 1)
    status = parts[1] if len(parts) > 1 else "500 Internal Server Error"

    headers = []
    for line in head_lines[1:]:
        if b":" not in line:
            continue
        name, value = line.split(b":", 1)
        name = name.decode("latin-1").strip()
        if name.lower() in _HOP_BY_HOP:
            continue
        headers.append((name, value.decode("latin-1").strip()))

    if len(body) >= _GZIP_MIN and _gzip_ok(environ, status, headers):
        body = gzip.compress(body, 6)   # 6: most of the ratio, a fraction of the CPU of 9
        headers = [(n, v) for n, v in headers if n.lower() != "content-length"]
        headers.append(("Content-Encoding", "gzip"))
        headers.append(("Content-Length", str(len(body))))
    # Announce that the body varies by encoding even when this particular response wasn't
    # compressed -- otherwise a shared cache can hand a gzipped copy to a client that never
    # asked for one.
    if not any(n.lower() == "vary" for n, _ in headers):
        headers.append(("Vary", "Accept-Encoding"))

    start_response(status, headers)
    return [body]
