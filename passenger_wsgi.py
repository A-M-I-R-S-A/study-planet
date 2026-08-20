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
import traceback

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
# Above this, don't. Compressing needs the whole body as one contiguous buffer plus room for
# the result, which is exactly the memory spike the chunked handling below exists to avoid.
# Everything in _GZIP_TYPES is a page or a JSON reply and lands far under this; anything
# bigger is served as-is rather than risking the worker.
_GZIP_MAX = 4 * 1024 * 1024


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
    when wbufsize is 0, which is the default).

    Writes are kept as a LIST of chunks rather than appended into one BytesIO. The handler
    already streams large files 64KB at a time, and a BytesIO threw that away: it grew one
    contiguous copy of the whole response, which was then sliced to separate head from body --
    a second copy. Measured, that made serving the 4.3MB APK cost 8.6MB of peak allocation
    and a 25MB library file about 50MB, per concurrent download, against the ~1GB a shared
    cPanel account gets. Keeping the chunks apart means the head can be split off without
    touching the body, and the body can be handed to the WSGI server as-is.
    """

    def __init__(self, request_bytes):
        self._reader = io.BytesIO(request_bytes)
        self.chunks = []

    def makefile(self, mode="r", *args, **kwargs):
        if "r" in mode:
            return self._reader
        return _ChunkWriter(self.chunks)

    def sendall(self, data):
        # bytes() rather than keeping the caller's object: _SocketWriter can hand over a
        # memoryview of a buffer it is about to reuse.
        self.chunks.append(bytes(data))

    def close(self):
        pass


class _ChunkWriter(io.RawIOBase):
    """Fallback sink for the makefile('wb') path, so both write routes land in one list."""

    def __init__(self, chunks):
        self._chunks = chunks

    def writable(self):
        return True

    def write(self, data):
        self._chunks.append(bytes(data))
        return len(data)


def _split_head(chunks):
    """(head_bytes, body_chunks). Joins only as many leading chunks as the head needs.

    end_headers() flushes the whole status line and header block in a single write, so in
    practice this consumes exactly one chunk and every body chunk is passed through
    untouched -- no copy of the payload is made anywhere in this module.
    """
    head = b""
    for i, chunk in enumerate(chunks):
        head += chunk
        cut = head.find(b"\r\n\r\n")
        if cut >= 0:
            rest = head[cut + 4:]
            tail = chunks[i + 1:]
            return head[:cut], ([rest] if rest else []) + tail
    return head, []


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
        # Dropped here and re-added below from wsgi.url_scheme. server.py's HTTPS redirect
        # and HSTS both hang off this header, so it must say what the *vhost* saw, not what
        # a client typed -- a forged "https" would otherwise be a free pass past the redirect.
        if name.lower() == "x-forwarded-proto":
            continue
        lines.append("%s: %s" % (name, value))
    # Passenger sets wsgi.url_scheme from the vhost the request arrived on, which is the only
    # trustworthy view of the scheme: the app itself is always spoken to over plain HTTP.
    lines.append("X-Forwarded-Proto: " +
                 ("https" if environ.get("wsgi.url_scheme") == "https" else "http"))
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    return head + body


def application(environ, start_response):
    try:
        conn = _FakeConn(_build_request(environ))
        client = (environ.get("REMOTE_ADDR", "") or "?", 0)

        # Instantiating the handler processes the single request start-to-finish (HTTP/1.0,
        # so it handles exactly one and returns), writing the response into conn.chunks.
        server.Handler(conn, client, None)
        return _respond(environ, start_response, conn.chunks)
    except Exception:
        # Last line of defence. server.Handler guards its own routing, but if anything in
        # this bridge fails the alternative is Passenger's own error page -- which is not
        # this application's, may say more about the host than it should, and is not what a
        # fetch() in the app can parse. Log it here where the app's log is, answer JSON.
        traceback.print_exc()
        body = b'{"error": "Something went wrong."}'
        start_response("500 Internal Server Error", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ])
        return [body]


def _respond(environ, start_response, chunks):
    head, body = _split_head(chunks)
    head_lines = head.split(b"\r\n")

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

    size = sum(len(c) for c in body)
    if _GZIP_MIN <= size <= _GZIP_MAX and _gzip_ok(environ, status, headers):
        blob = gzip.compress(b"".join(body), 6)   # 6: most of the ratio, a fraction of 9's CPU
        body = [blob]
        headers = [(n, v) for n, v in headers if n.lower() != "content-length"]
        headers.append(("Content-Encoding", "gzip"))
        headers.append(("Content-Length", str(len(blob))))
    # Announce that the body varies by encoding even when this particular response wasn't
    # compressed -- otherwise a shared cache can hand a gzipped copy to a client that never
    # asked for one.
    if not any(n.lower() == "vary" for n, _ in headers):
        headers.append(("Vary", "Accept-Encoding"))

    start_response(status, headers)
    # A list of chunks, not one joined blob: the WSGI server writes them out one at a time,
    # so a large file is never assembled in memory here.
    return body
