#!/usr/bin/env python3
"""
Study Planet — backend server (Python standard library only, no pip installs).

Run:   python server.py         (defaults to http://localhost:8000)
       PORT=9000 python server.py

Serves the static frontend (index.html, login.html, dashboard.html) and a small
JSON API backed by SQLite (focus.db, created automatically next to this file).

Endpoints
  POST /api/auth/otp/request  {phone}                     -> texts a 5-digit code (SMS.ir)
  POST /api/auth/otp/verify   {phone,code}                -> known number: signs in.
                                                             new number: {ticket} for signup
  POST /api/signup            {phone,ticket,name?,education?,email?,password?} -> session cookie
  POST /api/login             {phone|email,password}      -> sets session cookie
  POST /api/logout                                        -> clears session
  GET  /api/me                                            -> {user, settings, tasks, stats}
  GET  /api/stats                                         -> stats summary
  PUT  /api/settings          {settings:{...}}            -> save personalized settings
  PUT  /api/tasks             {tasks:[{text,done}...]}    -> replace task list
  POST /api/session-complete  {minutes}                   -> record a finished focus session
  PATCH /api/profile          {name?, avatar?, education?} -> update profile
  GET  /api/appearance?platform=web|mobile                -> resolved theme + background
  GET  /api/library                                       -> the shelf for this student
  GET  /api/library/file/<id>[?dl=1]                      -> one file, if it targets them

Signing in
  The phone number is the account. Someone types it, gets a 5-digit code by SMS, and typing
  the code back either signs them in (the number is already an account) or hands them a
  short-lived ticket to finish registering with. Email is optional everywhere — an account
  without one stores NULL, never '', so any number of accounts can go without. A password is
  optional too: set one and /api/login works, skip it and the code is the only way in.

Education & the library
  A student says what they study at sign-up: stage (school|uni), and for school a grade
  (elementary,7..12) plus, from tenth up, a major (biology|math|fanni). University students
  type their field as free text. The admin uploads material and aims each piece at a stage,
  a grade and a major — an empty column means "any" — so one upload can serve one class or
  everybody. Files live in media/library and are never served statically; the endpoint above
  is the only way to them and it re-checks the targeting on every request.

Admin panel (owner only — separate credentials, separate session cookie)
  /admin                     the panel; serves the sign-in form without a valid admin session
  POST /api/admin/login      {username,password}          -> admin cookie + CSRF token
  /api/admin/*               users, themes, backgrounds, library, settings — 404 to everyone else
"""
import os, re, sys, json, time, base64, hmac, hashlib, secrets, sqlite3, traceback, threading
from datetime import datetime, timezone, date, timedelta
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, quote, urlencode

ROOT = os.path.dirname(os.path.abspath(__file__))
# Overridable so a throwaway copy can be pointed at for testing without touching the real one.
DB_PATH = os.environ.get("FOCUS_DB") or os.path.join(ROOT, "focus.db")
PORT = int(os.environ.get("PORT", "8000"))
# Bind address. Defaults to loopback so the server is not exposed by accident; set
# HOST=0.0.0.0 to reach it from other devices on the LAN (e.g. the Android app in dev).
HOST = os.environ.get("HOST", "127.0.0.1")
PBKDF_ITER = 200_000
SESSION_DAYS = 30
ROOM_MAX = 10  # max members per room; a user may be in only one room at a time
ROOM_DESC_MAX = 400          # characters of room description an owner can write
ROOM_TASK_TEXT_MAX = 200     # characters in one assigned task
ROOM_TASKS_MAX = 300         # assignments kept per room, so a room can't grow without bound
ROOM_TASK_MIN_MAX = 600      # largest "suggested time" in minutes (10 hours)
MAX_BODY = 8 * 1024 * 1024   # cap request bodies (bytes): stops memory-exhaustion reads,
                             # still roomy for background-image data URLs synced via /api/settings
MAX_PW = 128                 # cap password length so PBKDF2 hashing cost stays bounded
# Set SECURE_COOKIES=1 when serving over HTTPS so the session cookie gets the Secure flag.
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "").lower() in ("1", "true", "yes", "on")
# One printed line per request. Off in production: see Handler.log_message.
ACCESS_LOG = os.environ.get("ACCESS_LOG", "").lower() in ("1", "true", "yes", "on")
# Reuse one SQLite connection per thread instead of opening one per call. Set DB_POOL=0 to
# turn it off and go back to a connection per call -- slower, but it takes every failure mode
# that involves a connection outliving a request off the table. Worth reaching for if the
# site starts returning 500s that only a restart clears.
DB_POOL = os.environ.get("DB_POOL", "1").lower() not in ("0", "false", "no", "off")
# Set FORCE_HTTPS=1 in production to redirect plain-HTTP requests to the https:// URL and
# send HSTS on the secure ones. Off by default because local `python server.py` has no TLS
# in front of it -- turning this on without a working certificate makes the site unreachable.
# It needs TRUST_PROXY=1 as well: the scheme is read from the X-Forwarded-Proto header that
# passenger_wsgi.py stamps from the WSGI environ, since the app itself only ever speaks HTTP.
FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "").lower() in ("1", "true", "yes", "on")
# "Study day" boundary. Days (streaks, calendar, per-day stats) are bucketed on UTC shifted
# by DAY_OFFSET_MIN minutes, so behaviour is the same wherever the server runs. 0 = UTC;
# e.g. 210 for Iran (UTC+3:30), 60 for CET, -480 for US Pacific. Set it to your users' zone.
DAY_OFFSET_MIN = int(os.environ.get("DAY_OFFSET_MIN", "0"))
MAX_DAY_SECONDS = 24 * 3600   # per-user daily ceiling on logged focus time (anti-inflation sanity cap)
# How much of session_log to keep. It holds one row per flush (every 30s of a running timer)
# and exists only to answer "how long on which subject" for the month the calendar is showing.
# The day totals everything else reads live in stat_days and are never pruned.
SESSION_LOG_KEEP_DAYS = int(os.environ.get("SESSION_LOG_KEEP_DAYS", "400"))
STREAK_MIN_SECONDS = 45 * 60  # a day has to reach this much focus time to count toward the streak
# Don't re-write `last_seen` if it is already younger than this. The client beats every 30s,
# so the freshest a skipped row can be is this + one interval = 75s -- still inside the 90s
# window _recent() calls "online", so nobody's presence dot changes. Any change of focus
# state ignores this and writes at once. Must stay below 60 to keep that guarantee.
HEARTBEAT_MIN_WRITE = 45

# --- admin panel --------------------------------------------------------------------
# The first admin is seeded once, from the environment when it is set, otherwise from
# admin_credentials.txt next to this file — the same pattern quotes_api_key.txt already
# uses here, and git-ignored for the same reason. The password is never stored or served
# in plain text: it is PBKDF2-hashed into the `admins` table on first run exactly like a
# user password, and the seed is ignored on every later start. Rotate it from the panel's
# Admin Account screen, then delete the file.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not (ADMIN_USERNAME and ADMIN_PASSWORD):
    try:
        with open(os.path.join(ROOT, "admin_credentials.txt"), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip().upper(), v.strip()
                if k == "ADMIN_USERNAME" and not ADMIN_USERNAME:
                    ADMIN_USERNAME = v
                elif k == "ADMIN_PASSWORD" and not ADMIN_PASSWORD:
                    ADMIN_PASSWORD = v
    except OSError:
        pass
# Admin sessions are deliberately far shorter-lived than the 30-day user session: an absolute
# cap plus an inactivity cutoff, both enforced server-side on every request.
ADMIN_SESSION_HOURS = float(os.environ.get("ADMIN_SESSION_HOURS", "8"))
ADMIN_IDLE_MINUTES = float(os.environ.get("ADMIN_IDLE_MINUTES", "60"))
# Uploaded background images live on disk and only their path goes in the database — the
# rest of the app already keeps its bytes out of SQLite, and a 4 MB blob per row would bloat
# every query that touches the table.
MEDIA_DIR = os.path.join(ROOT, "media", "backgrounds")
# A student's own uploaded background. Kept under the backgrounds directory on purpose: the
# "immutable, cache for a year" rule in _cache_control() and the service worker's on-device
# cache both key off the /media/backgrounds/ prefix, so putting these below it means they
# inherit both without a second rule to keep in sync. The subdirectory only separates whose
# they are -- the admin gallery is the `backgrounds` table, which never looks in here.
USER_BG_DIR = os.path.join(MEDIA_DIR, "u")
USER_BG_URL = "/media/backgrounds/u/"
# Swatch-sized copies of the gallery images, named after the original with a .jpg extension.
# The picker draws them at ~70px and used to point at the 2-3MB originals to do it.
THUMB_DIR = os.path.join(MEDIA_DIR, "thumb")
THUMB_URL = "/media/backgrounds/thumb/"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
# Ceiling on one account's settings blob once its background has been moved to disk. What is
# left is preferences -- durations, language, accent, volume -- which run to a few hundred
# bytes; 64KB is far above any honest value and far below anything that would slow a query
# down. Without a cap the column was bounded only by MAX_BODY, i.e. 8MB per account, read
# back on every page load.
MAX_SETTINGS_BYTES = 64 * 1024
# Accepted upload types, keyed by the magic bytes each file has to actually start with.
# The declared MIME type is attacker-controlled, so it is never what decides.
IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
    (b"RIFF", "webp", "image/webp"),   # RIFF....WEBP — the WEBP tag is checked separately
)

# --- what a student is studying -----------------------------------------------------
# Stored as stable keys, never as display text: the panel and both languages render their
# own labels from these, so renaming "فنی" in the UI never orphans a row.
EDU_STAGES = ("school", "uni")
SCHOOL_GRADES = ("elementary", "7", "8", "9", "10", "11", "12")
SCHOOL_MAJORS = ("biology", "math", "fanni")
# Majors (رشته) only start at دهم in the Iranian system, so a 9th-grader has no major to
# pick. Anything below tenth stores an empty major, which library targeting reads as
# "any major" — an item aimed at نهم reaches every ninth-grader regardless.
MAJOR_GRADES = ("10", "11", "12")
UNI_MAJOR_MAX = 60           # university major is free text — people type their own field

# --- library ------------------------------------------------------------------------
# Admin-uploaded study material, targeted at a stage/grade/major. Files live on disk and
# only their path goes in the database, exactly like uploaded backgrounds; unlike those,
# they are never reachable as static files — /api/library/file/<id> is the only way in,
# and it checks that this material is actually meant for this caller.
LIBRARY_DIR = os.path.join(ROOT, "media", "library")
LIBRARY_MAX_BYTES = 25 * 1024 * 1024
LIBRARY_TITLE_MAX = 120
LIBRARY_DESC_MAX = 400
LIBRARY_NAME_MAX = 120       # original filename kept for display and the download name
# Types accepted for upload, keyed by the magic bytes the file has to actually start with.
# The browser's declared type is attacker-controlled and never what decides.
DOC_MAGIC = (
    (b"%PDF-", "pdf", "application/pdf"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
    (b"RIFF", "webp", "image/webp"),
)
# docx/pptx/xlsx/epub are all zip containers, so the magic bytes can't tell them apart —
# the extension picks which of the whitelisted ones it is, and an unknown one becomes .zip.
ZIP_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "epub": "application/epub+zip",
    "zip": "application/zip",
}
TEXT_TYPES = {"txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8",
              "csv": "text/csv; charset=utf-8"}

# --- quotes (api-ninjas) ------------------------------------------------------------
# The key stays server-side: the browser calls /api/quotes here, never api-ninjas directly.
# Putting it in page JS would publish it to every visitor, and the page's own CSP
# (connect-src 'self') blocks off-origin calls anyway.
# Set QUOTES_API_KEY, or drop the key in quotes_api_key.txt next to this file (gitignored).
QUOTES_API_KEY = os.environ.get("QUOTES_API_KEY", "").strip()
if not QUOTES_API_KEY:
    try:
        with open(os.path.join(ROOT, "quotes_api_key.txt"), "r", encoding="utf-8") as fh:
            QUOTES_API_KEY = fh.read().strip()
    except OSError:
        pass
QUOTES_URL = "https://api.api-ninjas.com/v2/quotes"
# On the free tier each call returns exactly ONE quote, the "limit" param is premium-only,
# and repeating a call with the same categories returns the identical quote. Variety
# therefore has to come from varying the category -- one request per category, deduped.
QUOTES_CATEGORIES = [c.strip() for c in os.environ.get(
    "QUOTES_CATEGORIES",
    "success,wisdom,motivational,education,learning,knowledge,time,work,perseverance,discipline"
).split(",") if c.strip()]
QUOTES_TTL = 6 * 3600   # refresh the pool at most this often (≈40 calls/day)
# api-ninjas is reachable from some networks and not others -- from Iran it usually is not.
# An unreachable API must cost a page load almost nothing, so a refresh pass is bounded on
# three axes: each call gets a short timeout, the pass as a whole gets a wall-clock budget,
# and a failed pass is remembered so the next request doesn't try again for QUOTES_RETRY.
QUOTES_TIMEOUT = 2.0    # per-call ceiling (was 5s x 10 categories = 50s worst case)
QUOTES_BUDGET = 6.0     # total wall-clock ceiling for one refresh pass
QUOTES_RETRY = 3600     # after a failed pass, serve the cache and don't retry for an hour
# The pool and the timestamp are kept in a file, not just in this process. Passenger starts a
# worker on demand and shuts it down again when the site goes quiet, so an in-memory-only
# cache was empty for the first request of nearly every visit -- and on a host that cannot
# reach api-ninjas (which is the normal case from Iran) that first request paid the full
# QUOTES_BUDGET before answering. Measured against the live site: 8.6s cold, 1.7s warm. On
# disk the back-off outlives the worker, so a cold start reads the last good pool and the
# retry clock keeps ticking across restarts.
QUOTES_CACHE = os.path.join(ROOT, "quotes_cache.json")
_quotes = {"at": 0.0, "items": [], "loaded": False}
_quotes_lock = threading.Lock()


def _quotes_load():
    """Seed this process from the on-disk pool. Called once, under the lock."""
    _quotes["loaded"] = True
    try:
        with open(QUOTES_CACHE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            _quotes["items"] = data["items"]
            _quotes["at"] = float(data.get("at") or 0.0)
    except (OSError, ValueError, TypeError):
        pass


def _quotes_store():
    """Persist the pool for the next worker. Never raises -- a read-only disk is not fatal."""
    try:
        tmp = QUOTES_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"at": _quotes["at"], "items": _quotes["items"]}, fh)
        os.replace(tmp, QUOTES_CACHE)   # atomic: a reader never sees a half-written file
    except OSError:
        pass

# --- phone verification (SMS.ir) -----------------------------------------------------
# The key stays server-side for the same reason the quotes key does: the browser talks to
# /api/auth/otp/* here and never to api.sms.ir, and the pages' own CSP (connect-src 'self')
# blocks off-origin calls anyway. Anything that reached the frontend would be readable by
# every visitor and could be used to burn the SMS credit.
# Set SMSIR_API_KEY / SMSIR_TEMPLATE_ID, or put them in smsir_credentials.txt next to this
# file — same pattern (and same gitignore line) as admin_credentials.txt.
SMSIR_API_KEY = os.environ.get("SMSIR_API_KEY", "").strip()
SMSIR_TEMPLATE_ID = os.environ.get("SMSIR_TEMPLATE_ID", "").strip()
# The {{PLACEHOLDER}} name inside the SMS.ir template the code is substituted into.
SMSIR_PARAM = os.environ.get("SMSIR_PARAM", "").strip()
if not (SMSIR_API_KEY and SMSIR_TEMPLATE_ID and SMSIR_PARAM):
    try:
        with open(os.path.join(ROOT, "smsir_credentials.txt"), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip().upper(), v.strip()
                if k == "SMSIR_API_KEY" and not SMSIR_API_KEY:
                    SMSIR_API_KEY = v
                elif k == "SMSIR_TEMPLATE_ID" and not SMSIR_TEMPLATE_ID:
                    SMSIR_TEMPLATE_ID = v
                elif k == "SMSIR_PARAM" and not SMSIR_PARAM:
                    SMSIR_PARAM = v
    except OSError:
        pass
SMSIR_PARAM = SMSIR_PARAM or "CODE"
SMSIR_URL = "https://api.sms.ir/v1/send/verify"
OTP_LENGTH = 5               # digits, as the template expects
OTP_TTL = 300                # a code is good for 5 minutes and not a second longer
OTP_RESEND_SECONDS = 90      # cooldown between two texts to the same number
OTP_MAX_PER_HOUR = 5         # texts per number per hour — the cap on what one person can cost
OTP_IP_MAX_PER_HOUR = 20     # and per network, so one client can't farm codes for many numbers
OTP_MAX_ATTEMPTS = 5         # wrong guesses before the code is burned (5 digits = 100k space)
# Background uploads one account can make in an hour. Each one writes a file that lives until
# it is replaced, so this is the ceiling on how fast a single account can fill the disk.
BG_UPLOADS_PER_HOUR = 20
# How long an uploaded background file must have sat unreferenced before the hourly sweep
# will delete it. Long enough that a file written by a request still in flight is never
# mistaken for an orphan. See sweep_orphan_backgrounds().
ORPHAN_BG_GRACE = 3600
# Least time between two database sweeps, across every worker. Passenger runs several and
# each has its own cleanup thread; without a shared claim they all sweep at once and contend
# for the write lock. Slightly under the hourly cadence so a run is never skipped by a few
# seconds of clock drift between workers.
PURGE_MIN_INTERVAL = 3000
OTP_TICKET_TTL = 900         # a "this number is verified" ticket is good for 15 minutes
# Dev switch: deliver codes to the server log *instead of* texting them. It short-circuits
# the API call entirely rather than shadowing it, so working on the sign-in flow can't text
# a stranger or spend credit even with a live key configured. The code is only ever printed
# server-side; no setting puts it in a response.
OTP_ECHO = os.environ.get("OTP_ECHO", "").lower() in ("1", "true", "yes", "on")


def fetch_quotes():
    """One quote per category. Returns [] on failure -- callers fall back to the cache."""
    import urllib.request
    out, seen = [], set()
    deadline = time.time() + QUOTES_BUDGET
    for cat in QUOTES_CATEGORIES:
        # Stop early rather than walk every category: when the host can't reach api-ninjas
        # each call burns its full timeout, and ten of those in a row is a minute of a
        # worker's life for a decorative quote.
        if time.time() >= deadline:
            break
        req = urllib.request.Request(
            QUOTES_URL + "?" + urlencode({"categories": cat}),
            headers={"X-Api-Key": QUOTES_API_KEY},
        )
        try:
            with urllib.request.urlopen(req, timeout=QUOTES_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue   # a bad category or a network hiccup shouldn't sink the whole batch
        # v2 returns a list; tolerate a {"quotes": [...]} envelope in case that changes
        if isinstance(data, dict):
            data = data.get("quotes") or data.get("data") or []
        for q in data if isinstance(data, list) else []:
            text = " ".join((q.get("quote") or "").split())   # source data has ragged whitespace
            author = " ".join((q.get("author") or "").split()) or "unknown"
            # a few entries glue the attribution on after a stray closing quote, e.g.
            # 'ceaseless perseverance.”Baron Manfred von Richthofen (1892-1918); Pilot'
            if "”" in text:
                head = text.split("”", 1)[0].strip()
                if len(head) >= 20:
                    text = head
            text = text.strip("“”\"' ")
            # the hero area is built for one or two lines; skip anything that would overflow it
            if text and len(text) <= 200 and text not in seen:
                seen.add(text)
                out.append({"t": text, "by": author})
    return out


def quotes_cached():
    """Pool of quotes, refreshed at most every QUOTES_TTL. Never raises.

    Freshness is decided by the timestamp *alone*. It used to also require a non-empty pool
    (`... and _quotes["items"]`), which quietly defeated the whole cache whenever the API was
    unreachable: `items` stayed empty, so every single request re-ran the full refresh, and
    the back-off written on the line below it could never be read. On a host that can't reach
    api-ninjas that meant every page load spent ~50s inside this function -- with the lock
    held -- which is enough to pin every Passenger worker the app has.

    The network call is also made outside the lock now. Holding a global lock across a
    blocking socket read serialised all callers behind the slowest possible one.
    """
    now = time.time()
    with _quotes_lock:
        if not _quotes["loaded"]:
            _quotes_load()          # a freshly spawned worker inherits the last good pool
        if not QUOTES_API_KEY or (now - _quotes["at"]) < QUOTES_TTL:
            return _quotes["items"]
        # Claim the refresh slot before releasing the lock, so that concurrent callers see a
        # fresh timestamp and return the cache instead of piling into the same fetch. Written
        # through to disk as well, so a *second worker* starting during the fetch sees the
        # claim too -- in-memory alone, every worker made its own attempt.
        _quotes["at"] = now
        _quotes_store()
        stale = _quotes["items"]

    got = fetch_quotes()   # outside the lock: this is the part that can block for seconds

    with _quotes_lock:
        if got:
            _quotes["items"] = got
            _quotes["at"] = time.time()
        else:
            # Keep serving whatever we had, and try again in QUOTES_RETRY rather than a full
            # TTL -- backdating the timestamp is what makes the next attempt due early.
            _quotes["at"] = time.time() - QUOTES_TTL + QUOTES_RETRY
        _quotes_store()
        return _quotes["items"] or stale

# Sent on every response. 'unsafe-inline' is unavoidable (the pages use inline <script>/<style>),
# but the remaining directives still block framing, plugins, <base> hijacking and off-origin form
# posts. Fonts load from Google; custom backgrounds are data: URLs.
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy",
     "default-src 'self'; "
     "script-src 'self' 'unsafe-inline'; "
     "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
     "font-src 'self' https://fonts.gstatic.com; "
     "img-src 'self' data: blob:; "
     # The music host, so the ambient tiles and tracks can stream on the website. Only
     # media-src is widened: the page still can't fetch(), XHR or connect anywhere but here,
     # so a <audio src> is the whole of what this buys.
     "media-src 'self' https://irsv.upmusics.com; "
     "connect-src 'self'; "
     "base-uri 'none'; "
     "object-src 'none'; "
     "form-action 'self'; "
     "frame-ancestors 'none'"),
]

# Sent only on responses that actually travelled over TLS (see Handler._is_https), never on
# plain HTTP -- a browser ignores it there anyway, and a year-long promise sent by a site
# whose certificate later breaks locks every visitor out with no way back. A year is the
# shortest max-age browsers and the preload list take seriously.
HSTS_HEADER = ("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

# The only file types ever served as static assets. Everything the frontend needs — the
# pages, the favicon, the two shared scripts, uploaded background images — is one of these.
# Source (server.py), the database and its backups (focus.db, focus.db.bak-*), the secret
# files (admin_credentials.txt, smsir_credentials.txt, quotes_api_key.txt) and the docs
# (README.md, MOBILE.md) are none of them. This is an allow-list on purpose: a deny-list of
# extensions kept letting things through — a backup named focus.db.bak-preotp doesn't end in
# ".db", and every secret here is a .txt — whereas a new file dropped next to the app can
# only be downloaded if its type is on this short list.
STATIC_OK_EXT = (".html", ".htm", ".css", ".js", ".mjs", ".svg", ".png",
                 ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf",
                 # The Android build, offered for direct download from the landing page
                 # (the "Download for Android" button). Drop the signed release at a stable
                 # path — e.g. /study-planet.apk — and point landing.html's LINKS.apk at it.
                 ".apk")

# Static types a browser may hold on to without asking again. Deliberately excludes .html:
# the pages are the deploy surface and must revalidate. See Handler._cache_control().
CACHEABLE_ASSET_EXT = (".css", ".js", ".mjs", ".svg", ".png", ".jpg", ".jpeg",
                       ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf")
# How long, in seconds. Since these URLs carry no version or content hash, this doubles as
# the worst-case delay before a deploy reaches a browser that is already on the site.
ASSET_MAX_AGE = int(os.environ.get("ASSET_MAX_AGE", "600"))


# ---------------------------------------------------------------- database ----
class _Conn(sqlite3.Connection):
    """A pooled connection. close() releases it back to the thread instead of closing it.

    Opening a SQLite connection is not free: the handshake plus the four PRAGMAs below cost
    a few milliseconds on a local SSD and considerably more on the network-backed disk a
    shared host gives you. That was paid *per call*, and a single request makes several --
    /api/me alone opened five (the session lookup, tasks, stats, subjects, and its own), and
    /api/log five more every 30 seconds for every running timer. Reusing one connection per
    thread turns all of those into one.

    Overriding close() rather than editing seventy call sites is deliberate: every existing
    `conn = db() ... conn.close()` keeps reading exactly as it did, and none of them can
    accidentally close a connection another part of the same request is still using.

    close() is a plain no-op, and specifically does NOT roll back. Several handlers call a
    helper that opens and closes "its own" connection in the middle of their own work --
    library_file() consults library_enabled() partway through, for instance -- and with one
    shared connection that inner close() is the same object as the outer one. Rolling back
    there would silently discard the caller's uncommitted writes. Cleanup belongs at the
    boundary where a request actually ends, which is release_pooled(), called from
    Handler._guard()'s finally.
    """

    def close(self):
        pass

    def _close_for_real(self):
        sqlite3.Connection.close(self)


_pool = threading.local()


def _drop_pooled(conn=None):
    """Forget this thread's pooled connection, closing it if it still can be closed."""
    held = getattr(_pool, "conn", None)
    if conn is not None and held is not conn:
        return
    _pool.conn = None
    if held is not None:
        try:
            held._close_for_real()
        except Exception:
            pass


def release_pooled():
    """End-of-request cleanup for the pooled connection. Never raises.

    A handler that raised between a write and its commit leaves a transaction open, and an
    open transaction on a pooled connection holds SQLite's single write lock until something
    ends it -- which, with a worker kept warm between requests, could be minutes. Rolling
    back here bounds that to the request that caused it, and hands the next request a clean
    connection. A connection too broken to roll back is dropped rather than reused.
    """
    conn = getattr(_pool, "conn", None)
    if conn is None:
        return
    try:
        if conn.in_transaction:
            conn.rollback()
    except Exception:
        _drop_pooled(conn)


def new_conn():
    """A brand-new, configured connection that nothing else shares. Caller must close it."""
    conn = sqlite3.connect(DB_PATH, timeout=15.0, factory=_Conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Longer than it was: a pooled connection is reused rather than reopened, so waiting out
    # a writer costs nothing extra, while failing outright costs the caller their request.
    conn.execute("PRAGMA busy_timeout=15000")
    # With WAL on, the default synchronous=FULL fsyncs the log on every single commit, which
    # on shared hosting (network-backed disks, 5-20ms a flush) caps the WHOLE app at a few
    # dozen writes a second -- and heartbeats alone are one write per user per 30s. NORMAL
    # stops fsyncing per commit and lets the checkpoint do it instead: an app or process
    # crash is still safe (WAL replays), only a kernel panic or power cut can lose the last
    # commits, which for a focus timer's presence data is the right trade.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Room for the hot pages (users, sessions, stat_days and their indexes) to sit in memory
    # instead of being re-read per query. Negative = KiB, so this is a 16MB ceiling per
    # connection -- and there is now one connection per thread, not one per call.
    conn.execute("PRAGMA cache_size=-16000")
    return conn


def db():
    """The connection for the request being served on this thread.

    Only ever call this from inside a request. Anything running outside one -- startup,
    the hourly cleanup thread -- must use background_conn() instead, because the release
    that undoes an abandoned transaction hangs off the end of a request and nothing else.
    """
    if not DB_POOL:
        # Kill switch. Restores the original behaviour exactly: a fresh connection per call,
        # really closed by the close() every caller already makes. Slower, and immune to
        # anything that can go wrong with a connection that outlives one request.
        return new_conn_unpooled()
    conn = getattr(_pool, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")     # cheap liveness check; a dead handle is replaced
            return conn
        except Exception:
            _drop_pooled(conn)
    conn = new_conn()
    _pool.conn = conn
    return conn


def new_conn_unpooled():
    """A connection whose close() really closes, for callers that manage their own."""
    conn = new_conn()
    conn.close = conn._close_for_real
    return conn


class background_conn(object):
    """`with background_conn() as conn:` for work that is not serving a request.

    Startup and the hourly cleanup thread must not touch the pool. The pool's safety net --
    release_pooled(), which rolls back a transaction an exception left open -- is called from
    Handler._guard()'s finally, i.e. only ever at the end of a *request*. A background thread
    that took a pooled connection would therefore never be released, and if it failed between
    a write and its commit it would sit on SQLite's single write lock indefinitely: every
    later write waits out busy_timeout and then fails, so the whole site returns 500 to
    anything that writes, forever, until someone restarts the app. That is not hypothetical
    -- it is what this class was written to fix.

    A real connection, really closed, is the right shape for work that happens once an hour.
    """

    def __enter__(self):
        self.conn = new_conn()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.conn.in_transaction:
                self.conn.rollback()
        except Exception:
            pass
        try:
            self.conn._close_for_real()
        except Exception:
            pass
        return False


def init_db():
    # Import-time, not request-time: its own connection, closed when it is done. A pooled one
    # would be left open on whichever thread happened to import the module, holding a write
    # lock for the life of the worker if any of the migrations below failed part-way.
    with background_conn() as conn:
        _init_db(conn)


def _init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer (and vice versa)
    conn.executescript(
        """
        /* `email` is deliberately nullable and `phone` is what an account is identified by.
           "No email" is stored as NULL rather than '': SQLite counts NULLs as distinct in a
           UNIQUE index, so any number of accounts can go without one, while '' would collide
           on the second. Same reasoning for pw_hash/pw_salt — an account that only ever signs
           in with a texted code has no password, and NULL is what that is.
           An older database created these columns NOT NULL; migrate_users() below rebuilds
           the table on first run after the upgrade. */
        CREATE TABLE IF NOT EXISTS users(
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          email          TEXT UNIQUE,
          phone          TEXT UNIQUE,
          phone_verified INTEGER DEFAULT 0,
          name           TEXT,
          avatar         TEXT DEFAULT '🦊',
          pw_hash        TEXT,
          pw_salt        TEXT,
          settings       TEXT DEFAULT '{}',
          created_at     TEXT NOT NULL
        );
        /* ---- phone verification ----
           One row per code texted out. The code is never stored in the clear: a 5-digit code
           is a 100k space that any leak would brute-force instantly, so what protects it is
           the five-minute window, the five-attempt ceiling and single use — the salted hash
           just keeps the live codes out of a database dump.
           Rows are kept (not deleted) after use until purge_expired() sweeps them, so
           "already used" can be told apart from "never existed" and answered honestly. */
        CREATE TABLE IF NOT EXISTS otp_codes(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          phone      TEXT NOT NULL,
          code_hash  TEXT NOT NULL,
          code_salt  TEXT NOT NULL,
          created_at REAL NOT NULL,
          expires    REAL NOT NULL,
          attempts   INTEGER DEFAULT 0,
          used       INTEGER DEFAULT 0,
          ip         TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_otp_phone ON otp_codes(phone, id);
        /* Proof that a number was verified, handed out when the code checks out for a number
           with no account yet and spent by /api/signup. It exists so registration never has
           to trust a phone number the browser simply claims, and so a half-filled signup form
           doesn't leave a half-made account behind. Single use: consumed rows are deleted. */
        CREATE TABLE IF NOT EXISTS phone_tickets(
          token      TEXT PRIMARY KEY,
          phone      TEXT NOT NULL,
          expires    REAL NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
          token    TEXT PRIMARY KEY,
          user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          text       TEXT NOT NULL,
          done       INTEGER DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stat_days(
          user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day      TEXT NOT NULL,
          sessions INTEGER DEFAULT 0,
          minutes  INTEGER DEFAULT 0,
          seconds  INTEGER DEFAULT 0,
          PRIMARY KEY(user_id, day)
        );
        CREATE TABLE IF NOT EXISTS rooms(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          name       TEXT NOT NULL,
          owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          visibility TEXT DEFAULT 'private',
          code       TEXT UNIQUE NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS room_members(
          room_id   INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
          user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role      TEXT DEFAULT 'member',
          joined_at TEXT NOT NULL,
          PRIMARY KEY(room_id, user_id)
        );
        /* Owner-assigned work. Deliberately NOT rows in `tasks`: that table is the timer's
           personal checklist, and PUT /api/tasks replaces it wholesale from localStorage, so
           anything an owner assigned would be deleted by the assignee's next sync. Keeping
           assignments in their own table also lets them carry a due date and a suggested
           length without inventing columns on the personal list. */
        CREATE TABLE IF NOT EXISTS room_tasks(
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          room_id     INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
          user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- assignee
          assigned_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- the owner
          text        TEXT NOT NULL,
          due         TEXT DEFAULT '',    -- 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'; '' = no deadline
          suggest_min INTEGER DEFAULT 0,  -- suggested focus minutes; 0 = no suggestion
          done        INTEGER DEFAULT 0,
          done_at     TEXT,
          created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_room_tasks_room ON room_tasks(room_id);
        CREATE INDEX IF NOT EXISTS idx_room_tasks_user ON room_tasks(user_id, done);
        CREATE TABLE IF NOT EXISTS session_log(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day        TEXT NOT NULL,
          minutes    INTEGER DEFAULT 0,
          seconds    INTEGER DEFAULT 0,
          topic      TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subjects(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name       TEXT NOT NULL,
          color      TEXT DEFAULT '#d9a24e',
          created_at TEXT NOT NULL
        );

        /* ---- admin panel ----
           Admins are a separate table from users on purpose: there is no role column on
           `users` that a signup could ever set, so no amount of tampering with a normal
           account can promote it. The two session stores are separate for the same reason —
           a user's `sid` is not an admin credential and can never be mistaken for one. */
        CREATE TABLE IF NOT EXISTS admins(
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          username    TEXT UNIQUE NOT NULL,
          pw_hash     TEXT NOT NULL,
          pw_salt     TEXT NOT NULL,
          created_at  TEXT NOT NULL,
          last_login  TEXT,
          last_ip     TEXT
        );
        CREATE TABLE IF NOT EXISTS admin_sessions(
          token      TEXT PRIMARY KEY,
          admin_id   INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
          csrf       TEXT NOT NULL,
          expires    REAL NOT NULL,   -- absolute cap
          last_seen  REAL NOT NULL,   -- drives the inactivity cutoff
          created_at TEXT NOT NULL,
          ip         TEXT,
          ua         TEXT
        );
        /* A theme is a row of design tokens, not code: the pages already read every colour
           off a CSS variable, so a theme is just the set of values to write into them. */
        CREATE TABLE IF NOT EXISTS themes(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          name       TEXT NOT NULL,
          slug       TEXT UNIQUE NOT NULL,
          tokens     TEXT NOT NULL DEFAULT '{}',
          is_system  INTEGER DEFAULT 0,   -- seeded, and refused deletion so the app always has one
          enabled    INTEGER DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        /* `kind` mirrors the shape the frontend already stores in settings.bg:
           'preset' -> value is a CSS background, 'image' -> value is a served path. */
        CREATE TABLE IF NOT EXISTS backgrounds(
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          name        TEXT NOT NULL,
          slug        TEXT UNIQUE NOT NULL,
          kind        TEXT NOT NULL DEFAULT 'preset',
          value       TEXT NOT NULL,
          platform    TEXT NOT NULL DEFAULT 'both',   -- both | web | mobile
          enabled     INTEGER DEFAULT 1,
          description TEXT DEFAULT '',
          is_system   INTEGER DEFAULT 0,
          created_at  TEXT NOT NULL,
          updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_settings(
          key        TEXT PRIMARY KEY,
          value      TEXT,
          updated_at TEXT NOT NULL
        );
        /* Bookkeeping the workers keep between themselves -- currently just when the last
           database sweep ran, so that several Passenger workers don't all run it at once and
           fight over the write lock. Deliberately NOT app_settings: that table is the admin
           panel's, and everything in it is shown there. */
        CREATE TABLE IF NOT EXISTS worker_state(
          key   TEXT PRIMARY KEY,
          value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_admin_sessions_admin ON admin_sessions(admin_id);

        /* ---- library ----
           Study material the admin uploads, aimed at a stage/grade/major. Targeting is
           three nullable-by-emptiness columns rather than a join table on purpose: an
           empty column means "any", which is what makes one row able to serve every
           tenth-grader, or every riyazi student in any grade, without a row per pairing.

           A category is a folder the admin arranges the shelf with. It carries its own
           visibility, and hiding it hides everything filed under it — so an admin can
           prepare a whole term's material and publish it in one switch. */
        CREATE TABLE IF NOT EXISTS library_categories(
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          name        TEXT NOT NULL,
          slug        TEXT UNIQUE NOT NULL,
          description TEXT DEFAULT '',
          stage       TEXT NOT NULL DEFAULT 'all',   -- all | school | uni
          grade       TEXT DEFAULT '',               -- '' = any grade
          major       TEXT DEFAULT '',               -- '' = any major
          visible     INTEGER DEFAULT 1,
          sort_order  INTEGER DEFAULT 0,
          created_at  TEXT NOT NULL,
          updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS library_items(
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          title       TEXT NOT NULL,
          description TEXT DEFAULT '',
          /* ON DELETE SET NULL, not CASCADE: deleting a folder should unfile its material,
             never destroy uploaded files the admin still has targeting rules for. */
          category_id INTEGER REFERENCES library_categories(id) ON DELETE SET NULL,
          stage       TEXT NOT NULL DEFAULT 'school',
          grade       TEXT DEFAULT '',
          major       TEXT DEFAULT '',
          file_path   TEXT NOT NULL,   -- /media/library/<token>.<ext>, never served statically
          file_name   TEXT DEFAULT '', -- what it was called when uploaded
          file_size   INTEGER DEFAULT 0,
          mime        TEXT DEFAULT '',
          visible     INTEGER DEFAULT 1,
          downloads   INTEGER DEFAULT 0,
          created_at  TEXT NOT NULL,
          updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_library_items_target
          ON library_items(visible, stage, grade, major);
        CREATE INDEX IF NOT EXISTS idx_library_items_cat ON library_items(category_id);
        """
    )
    for col, ddl in (("focusing", "INTEGER DEFAULT 0"), ("last_seen", "REAL DEFAULT 0"),
                     ("edu_stage", "TEXT DEFAULT ''"), ("edu_grade", "TEXT DEFAULT ''"),
                     ("edu_major", "TEXT DEFAULT ''")):
        if not any(r["name"] == col for r in conn.execute("PRAGMA table_info(users)")):
            conn.execute("ALTER TABLE users ADD COLUMN %s %s" % (col, ddl))
    if not any(r["name"] == "subject_id" for r in conn.execute("PRAGMA table_info(session_log)")):
        conn.execute("ALTER TABLE session_log ADD COLUMN subject_id INTEGER")
    if not any(r["name"] == "description" for r in conn.execute("PRAGMA table_info(rooms)")):
        conn.execute("ALTER TABLE rooms ADD COLUMN description TEXT DEFAULT ''")
    # second-level precision: add `seconds` and backfill from the older minute counts
    for tbl in ("stat_days", "session_log"):
        if not any(r["name"] == "seconds" for r in conn.execute("PRAGMA table_info(%s)" % tbl)):
            conn.execute("ALTER TABLE %s ADD COLUMN seconds INTEGER DEFAULT 0" % tbl)
            conn.execute("UPDATE %s SET seconds=minutes*60 WHERE seconds=0 AND minutes>0" % tbl)
    conn.commit()
    migrate_users(conn)
    seed_admin(conn)
    seed_appearance(conn)
    conn.commit()
    ensure_indexes(conn)
    migrate_inline_backgrounds(conn)
    # No close() here: background_conn() in init_db() owns this connection and closes it.


def migrate_inline_backgrounds(conn):
    """Move backgrounds that were stored inside settings as base64 out to files. Once.

    Accounts created before backgrounds lived on disk carry a ~570KB data URL in their
    settings column, and every page load sent it back twice. The row can't be left as it is
    and simply ignored, because it is what /api/appearance reads to know what this student
    picked -- so it is rewritten in place, pointing at a file holding the same bytes.

    Bounded by a `LIKE` that an index can't help with, but it only ever matches rows that
    haven't been converted yet, so the second run of this scans nothing and finds nothing.
    """
    try:
        rows = conn.execute(
            "SELECT id, settings FROM users WHERE settings LIKE '%data:image/%'").fetchall()
    except sqlite3.Error:
        traceback.print_exc()
        return
    moved = 0
    for r in rows:
        try:
            settings = json.loads(r["settings"] or "{}")
        except ValueError:
            continue
        if not isinstance(settings, dict):
            continue
        before = json.dumps(settings.get("bg"))
        if externalize_bg(settings) is not None:
            continue                      # unreadable image: leave the row alone, don't lose it
        if json.dumps(settings.get("bg")) == before:
            continue
        conn.execute("UPDATE users SET settings=? WHERE id=?", (json.dumps(settings), r["id"]))
        moved += 1
    if moved:
        conn.commit()
        print("  + Moved %d inline background(s) out of the database and onto disk" % moved)


def ensure_indexes(conn):
    """The covering indexes for every per-user lookup on a hot path.

    Without these each of these queries is a full table scan, and the tables they scan grow
    with the whole user base rather than with one user: `session_log` gains a row per finished
    session from everybody, so one student opening their dashboard walked every session every
    other student had ever logged. That is invisible with ten accounts and fatal with a
    thousand. Created after the migrations above, because some of the columns are added there.

    CREATE INDEX IF NOT EXISTS is idempotent, so this is safe to re-run on every start; on an
    existing database the first run backfills them, which takes a moment and then never again.
    """
    conn.executescript(
        """
        /* tasks/subjects: read on every dashboard and timer load */
        CREATE INDEX IF NOT EXISTS idx_tasks_user          ON tasks(user_id);
        CREATE INDEX IF NOT EXISTS idx_subjects_user       ON subjects(user_id);
        /* session_log: the biggest table, and subjects_for() hits it once per subject */
        CREATE INDEX IF NOT EXISTS idx_session_log_user    ON session_log(user_id, day, subject_id);
        /* room_members' PK is (room_id,user_id), which cannot answer "which room is this
           user in" -- the lookup /api/rooms/current makes on every room poll. */
        CREATE INDEX IF NOT EXISTS idx_room_members_user   ON room_members(user_id);
        /* the admin dashboard's online/focusing counters and its sign-ups-per-day loop */
        CREATE INDEX IF NOT EXISTS idx_users_last_seen     ON users(last_seen);
        CREATE INDEX IF NOT EXISTS idx_users_created       ON users(created_at);
        /* sessions.token is the PK, but expiry sweeps scan by date */
        CREATE INDEX IF NOT EXISTS idx_sessions_expires    ON sessions(expires);
        """
    )
    conn.commit()


def migrate_users(conn):
    """Bring a pre-phone `users` table up to the shape above. No-op once done.

    The original table declared `email TEXT UNIQUE NOT NULL`, which makes an account without
    an email impossible — and '' is no substitute, because the UNIQUE index would reject the
    second account that tried it. SQLite cannot drop a NOT NULL in place, so the column has
    to be rebuilt: the create/copy/drop/rename dance below is the procedure from the SQLite
    documentation, foreign keys off for the duration (the child tables reference `users` by
    name and are whole again the moment the rename lands) and re-checked before it commits.
    It is also the one chance to add phone, so both changes ride the same rebuild.

    Existing accounts keep their id, password and everything hanging off them; they come out
    with phone NULL, which simply means they still sign in with their email and password
    until they verify a number.
    """
    cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(users)")}
    if "phone" in cols and not cols["email"]["notnull"]:
        return
    # Snapshot first: this rewrites the table every account hangs off, and a copy costs
    # seconds. `conn.backup` is WAL-safe in a way that copying the file is not.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak_path = DB_PATH + ".bak-" + stamp
    try:
        bak = sqlite3.connect(bak_path)
        with bak:
            conn.backup(bak)
        bak.close()
        print("  + Backed up the database to %s before migrating users" % os.path.basename(bak_path))
    except Exception:
        traceback.print_exc()
        raise RuntimeError("refusing to migrate `users` without a backup")

    # Carry over every column the table actually has: the ones added by ALTER above exist by
    # now, but a database from an older build might be missing some.
    carried = [c for c in ("focusing", "last_seen", "edu_stage", "edu_grade", "edu_major") if c in cols]
    extra_ddl = "".join(",\n          %s %s" % (c, {"focusing": "INTEGER DEFAULT 0",
                                                    "last_seen": "REAL DEFAULT 0"}.get(c, "TEXT DEFAULT ''"))
                        for c in carried)
    keep = ["id", "email", "phone", "phone_verified", "name", "avatar", "pw_hash", "pw_salt",
            "settings", "created_at"] + carried
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("""
        CREATE TABLE users_migrating(
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          email          TEXT UNIQUE,
          phone          TEXT UNIQUE,
          phone_verified INTEGER DEFAULT 0,
          name           TEXT,
          avatar         TEXT DEFAULT '🦊',
          pw_hash        TEXT,
          pw_salt        TEXT,
          settings       TEXT DEFAULT '{}',
          created_at     TEXT NOT NULL%s
        )""" % extra_ddl)
        # NULLIF collapses any '' email that predates this to the NULL the new column means it
        # to be, so "has no email" is one value and not two.
        conn.execute(
            "INSERT INTO users_migrating(%s) SELECT id, NULLIF(TRIM(email),''), %s, 0, name, avatar, "
            "pw_hash, pw_salt, settings, created_at%s FROM users"
            % (",".join(keep),
               "phone" if "phone" in cols else "NULL",
               "".join(", " + c for c in carried))
        )
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_migrating RENAME TO users")
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError("foreign keys broke during the users migration: %r" % (bad[:5],))
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        print("  + Migrated `users`: email is now optional, phone added (%d accounts kept)" % n)
    except Exception:
        conn.rollback()
        print("  ! users migration failed — the database is untouched, backup at %s" % bak_path)
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


# ------------------------------------------------------- appearance seed data ----
# The tokens every page already declares on :root, split into the two appearances the app
# ships. Themes are seeded from these so the panel starts out describing what is actually
# on screen rather than an invented palette.
CLASSIC_TOKENS = {
    "appearance": "classic", "accentInk": "#16303a",
    "surface": "#faf6ee", "surface2": "#efe9de", "ink": "#2b2824", "muted": "#8a8175",
    "line": "rgba(0,0,0,.06)", "hair": "rgba(0,0,0,.14)", "field": "#ffffff", "radius": "22px",
}
GLASS_TOKENS = {
    "appearance": "glass", "accentInk": "#16303a",
    "surface": "rgba(18,24,30,.68)", "surface2": "rgba(255,255,255,.07)",
    "ink": "#f1f5f8", "muted": "rgba(233,240,246,.58)",
    "line": "rgba(255,255,255,.14)", "hair": "rgba(255,255,255,.2)",
    "field": "rgba(255,255,255,.08)", "radius": "22px",
}
# The accent pairs from index.html — focus tone + the calmer break tone that goes with it.
SEED_ACCENTS = {
    "amber":  ("oklch(0.7 0.12 62)",  "oklch(0.72 0.09 175)"),
    "coral":  ("oklch(0.71 0.14 40)", "oklch(0.75 0.08 60)"),
    "rose":   ("oklch(0.68 0.15 15)", "oklch(0.73 0.08 350)"),
    "violet": ("oklch(0.66 0.16 300)", "oklch(0.72 0.09 285)"),
    "sky":    ("oklch(0.7 0.13 235)", "oklch(0.75 0.08 205)"),
    "green":  ("oklch(0.7 0.14 150)", "oklch(0.75 0.08 168)"),
}
# The built-in gradient presets, seeded so the panel manages the same list the app shows
# instead of a second one beside it. Kept deliberately to two: everything else a deployment
# wants is uploaded from the admin panel, which is the supported way to add backgrounds.
# This list must stay in step with BGS in index.html, theme.js and dashboard.html.
SEED_BACKGROUNDS = [
    ("midnight", "Midnight", "linear-gradient(180deg,#1f2838,#0d1420)"),
    ("indigo", "Indigo", "linear-gradient(180deg,#232a4a,#0d1024)"),
]
# Defaults the app falls back to when no admin default is configured — the values the
# frontend has always hardcoded, so an empty app_settings table changes nothing.
# Must name a slug that actually exists in SEED_BACKGROUNDS, or every fallback path
# resolves to nothing and pages paint with no background at all.
FALLBACK_BG_SLUG = "midnight"
FALLBACK_THEME_SLUG = "classic-amber"
SETTING_KEYS = ("default_theme", "web_default_background", "mobile_default_background",
                "default_dim", "default_blur", "default_language", "library_enabled")


def seed_admin(conn):
    """Create the initial admin once, from env or admin_credentials.txt. Never overwrites."""
    if conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        return
    if not (ADMIN_USERNAME and ADMIN_PASSWORD):
        print("  ! No admin seeded — set ADMIN_USERNAME/ADMIN_PASSWORD or admin_credentials.txt")
        return
    h, s = hash_pw(ADMIN_PASSWORD)
    conn.execute("INSERT INTO admins(username,pw_hash,pw_salt,created_at) VALUES(?,?,?,?)",
                 (ADMIN_USERNAME.strip(), h, s, now_iso()))
    print("  + Admin account created for %r (password stored PBKDF2-hashed)" % ADMIN_USERNAME.strip())


def seed_appearance(conn):
    """Seed themes, backgrounds and the global defaults. Idempotent — only fills what's missing."""
    ts = now_iso()
    for accent, (focus, brk) in SEED_ACCENTS.items():
        for skin, base in (("classic", CLASSIC_TOKENS), ("glass", GLASS_TOKENS)):
            slug = "%s-%s" % (skin, accent)
            if conn.execute("SELECT 1 FROM themes WHERE slug=?", (slug,)).fetchone():
                continue
            tokens = dict(base, accent=focus, accentBreak=brk)
            conn.execute(
                "INSERT INTO themes(name,slug,tokens,is_system,enabled,created_at,updated_at) "
                "VALUES(?,?,?,?,1,?,?)",
                ("%s %s" % (accent.capitalize(), skin.capitalize()), slug, json.dumps(tokens),
                 1 if slug == FALLBACK_THEME_SLUG else 0, ts, ts),
            )
    for slug, name, css in SEED_BACKGROUNDS:
        if conn.execute("SELECT 1 FROM backgrounds WHERE slug=?", (slug,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO backgrounds(name,slug,kind,value,platform,enabled,description,is_system,"
            "created_at,updated_at) VALUES(?,?,'preset',?,'both',1,?,?,?,?)",
            (name, slug, css, "Built-in gradient", 1 if slug == FALLBACK_BG_SLUG else 0, ts, ts),
        )
    have = {r["key"] for r in conn.execute("SELECT key FROM app_settings")}
    theme = conn.execute("SELECT id FROM themes WHERE slug=?", (FALLBACK_THEME_SLUG,)).fetchone()
    bgrow = conn.execute("SELECT id FROM backgrounds WHERE slug=?", (FALLBACK_BG_SLUG,)).fetchone()
    defaults = {
        "default_theme": str(theme["id"]) if theme else "",
        "web_default_background": str(bgrow["id"]) if bgrow else "",
        "mobile_default_background": str(bgrow["id"]) if bgrow else "",
        "default_dim": "0", "default_blur": "0", "default_language": "en",
        "library_enabled": "1",
    }
    for k, v in defaults.items():
        if k not in have:
            conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)", (k, v, ts))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today_date():
    """Current 'study day' as a date — UTC shifted by DAY_OFFSET_MIN (0 = UTC)."""
    return (datetime.now(timezone.utc) + timedelta(minutes=DAY_OFFSET_MIN)).date()


def today_str():
    return today_date().isoformat()


def invite_code(raw):
    """Pull a room code out of whatever the user pasted.

    People share the invite *link*, so that is what gets pasted into a box asking for a
    code. Accept both: a full URL yields the `join` parameter, anything else is treated as
    the bare code. Nothing here trusts the input — the caller still looks it up by exact
    match, so an unrecognised string simply finds no room.
    """
    s = str(raw or "").strip()
    if "join=" in s:
        s = s.split("join=", 1)[1].split("&", 1)[0].split("#", 1)[0]
        s = unquote(s).strip()
    return s.strip("/")


# ------------------------------------------------- rate limiting + upkeep ----
# Set TRUST_PROXY=1 only when behind a reverse proxy you control, so the client
# IP is read from X-Forwarded-For instead of the (proxy's) socket address.
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes", "on")

# FORCE_HTTPS reads the scheme from X-Forwarded-Proto, which _is_https() only believes when
# TRUST_PROXY is set. Without it every request -- including the HTTPS ones -- looks insecure,
# so the redirect would send https:// back to https:// forever and take the whole site down.
# Refusing the combination here turns that outage into one startup line in the log.
if FORCE_HTTPS and not TRUST_PROXY:
    print("  ! FORCE_HTTPS ignored: it needs TRUST_PROXY=1 to tell http from https "
          "(without it, every request would redirect to itself). Set both, or neither.")
    FORCE_HTTPS = False

_rl_lock = threading.Lock()
_rl_hits = {}  # key -> [timestamps]; trimmed on access and hourly by purge_expired()

# --- what went wrong, and when -------------------------------------------------------
# A 500 that clears when you restart the app is the hardest kind of bug to chase, because by
# the time anyone looks the evidence has been restarted away. These keep the last few
# failures in the worker that had them, and count them, so /api/admin/diagnostics can answer
# "what is actually failing, and did it start at some particular moment" without needing
# somebody to be tailing a log at the time.
WORKER_STARTED = time.time()
FAILURE_LOG_MAX = 25
_fail_lock = threading.Lock()
_failures = []      # newest last; capped at FAILURE_LOG_MAX
_counters = {"requests": 0, "failures": 0, "db_failures": 0}


def record_failure(method, path, exc):
    """Log a failed request loudly, and remember it for the diagnostics endpoint."""
    detail = traceback.format_exc()
    # One clearly-marked line first, so it is greppable in a log full of other noise.
    print("  !! %s %s -> %s: %s" % (method, path, type(exc).__name__, exc))
    print(detail)
    try:
        sys.stderr.flush()
    except Exception:
        pass
    with _fail_lock:
        _counters["failures"] += 1
        if isinstance(exc, sqlite3.Error):
            _counters["db_failures"] += 1
        _failures.append({
            "at": now_iso(),
            "method": method,
            "path": path,
            "error": type(exc).__name__,
            "message": str(exc)[:300],
            "traceback": detail[-2000:],
        })
        del _failures[:-FAILURE_LOG_MAX]


def worker_diagnostics():
    """A snapshot of this worker: how long it has been up, and what has gone wrong in it.

    Deliberately per-worker. Passenger runs several, each with its own memory, its own pooled
    connection and its own failures, so "the site is broken" is often really "one worker is
    broken" -- and a reading that averaged them would hide exactly that.
    """
    with _fail_lock:
        failures = list(_failures)
        counters = dict(_counters)
    pooled = getattr(_pool, "conn", None)
    out = {
        "pid": os.getpid(),
        "uptimeSeconds": int(time.time() - WORKER_STARTED),
        "startedAt": datetime.fromtimestamp(WORKER_STARTED, timezone.utc).isoformat(),
        "counters": counters,
        "pool": {"enabled": DB_POOL, "hasConnection": pooled is not None,
                 "inTransaction": bool(pooled is not None and pooled.in_transaction)},
        "threads": threading.active_count(),
        "failures": failures,
    }
    # Can this worker actually write? This is the question behind almost every 500 the app
    # can produce, and the answer is either "yes" or the reason why not.
    try:
        with background_conn() as conn:
            # A real write, committed, on a row that exists for exactly this purpose. "Can
            # this worker write?" is the question behind nearly every 500 this app can
            # produce -- a read-only check would answer a different, easier question.
            conn.execute("INSERT OR REPLACE INTO worker_state(key,value) VALUES('healthcheck',?)",
                         (now_iso(),))
            conn.commit()
            out["database"] = {
                "writable": True,
                "path": DB_PATH,
                "sizeBytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else None,
                "walBytes": (os.path.getsize(DB_PATH + "-wal")
                             if os.path.exists(DB_PATH + "-wal") else 0),
                "journalMode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            }
    except Exception as exc:
        out["database"] = {"writable": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    try:
        st = os.statvfs(ROOT)
        out["disk"] = {"freeBytes": st.f_bavail * st.f_frsize}
    except (AttributeError, OSError):
        pass    # statvfs is POSIX-only; absent on Windows, and not worth faking
    return out


def rate_ok(key, limit, window):
    """Allow up to `limit` hits per `window` seconds for `key`; False once exceeded."""
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl_hits.get(key, ()) if now - t < window]
        if len(hits) >= limit:
            _rl_hits[key] = hits
            return False
        hits.append(now)
        _rl_hits[key] = hits
        return True


def claim_purge(conn):
    """True if this worker should do the sweep now, false if another one just did.

    Passenger runs several workers and each starts its own cleanup thread, so without this
    every one of them runs the same deletes on the same tables at the same time -- at boot,
    when they all start together, and then on the hour. They contend for SQLite's single
    write lock, and the loser gets "database is locked" partway through its sequence.

    One UPDATE decides it: whoever's UPDATE actually changes the row holds the claim, and
    SQLite evaluates that condition under the write lock, so exactly one worker can win.
    Kept in worker_state rather than app_settings because app_settings is the admin panel's
    table -- everything in it is shown, and some of it is editable, and this is neither.
    """
    now = time.time()
    cur = conn.execute(
        "UPDATE worker_state SET value=? WHERE key='last_purge_at' "
        "AND CAST(COALESCE(NULLIF(value,''),'0') AS REAL) < ?",
        (repr(now), now - PURGE_MIN_INTERVAL))
    if cur.rowcount:
        conn.commit()
        return True
    # Nothing updated: either another worker holds a fresh claim, or the row does not exist
    # yet. INSERT OR IGNORE settles the second case without a race -- a concurrent worker's
    # identical insert simply changes nothing, and rowcount tells us which of us wrote it.
    cur = conn.execute(
        "INSERT OR IGNORE INTO worker_state(key,value) VALUES('last_purge_at',?)",
        (repr(now),))
    conn.commit()
    return bool(cur.rowcount)


def purge_expired(force=False):
    """Delete expired rows, then drop stale rate-limit entries. At startup + hourly.

    Two halves, and only the first is shared. The database sweep is the same work whichever
    worker does it, so one of them claims it and the rest skip; the rate-limit table is this
    process's own memory and every worker has to trim its own.

    Runs on the cleanup thread and at import, never inside a request, so it takes its own
    connection rather than the request pool's -- see background_conn() for why that matters.
    """
    try:
        _purge_database(force)
    except Exception:
        traceback.print_exc()
    now = time.time()
    with _rl_lock:
        for k in list(_rl_hits):
            hits = [t for t in _rl_hits[k] if now - t < 3600]
            if hits:
                _rl_hits[k] = hits
            else:
                del _rl_hits[k]


def _purge_database(force=False):
    with background_conn() as conn:
        if not (force or claim_purge(conn)):
            return          # another worker has this covered
        now = time.time()
        conn.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        # Admin sessions go on both counts: past their absolute cap, or idle too long.
        conn.execute("DELETE FROM admin_sessions WHERE expires < ? OR last_seen < ?",
                     (now, now - ADMIN_IDLE_MINUTES * 60))
        # Spent and expired codes are kept a while past their five minutes so "that code
        # was already used" stays answerable, then swept — of no use to anyone after.
        conn.execute("DELETE FROM otp_codes WHERE expires < ?", (now - 3600,))
        conn.execute("DELETE FROM phone_tickets WHERE expires < ?", (now,))
        # session_log grows without bound and faster than anything else here: /api/log
        # writes a row per flush, one every 30 seconds for every running timer. Nothing
        # was ever deleting it. The day totals the dashboard, streak and calendar read
        # live in stat_days and are untouched by this -- session_log is only needed at
        # per-subject granularity, which the app shows for the current month. A year is
        # far more than that and keeps the table a few thousand rows per active user
        # instead of an ever-growing scan behind every subject query.
        conn.execute("DELETE FROM session_log WHERE day < ?",
                     ((today_date() - timedelta(days=SESSION_LOG_KEEP_DAYS)).isoformat(),))
        conn.commit()
        # Fold the write-ahead log back into the database and truncate it. Without this
        # the -wal file only ever grows to its high-water mark and stays there, and every
        # reader pays for walking it. Pages freed by the deletes above stay inside the
        # file as free space for future rows -- reclaiming those to the filesystem would
        # need a full VACUUM, which rewrites the whole database and is not something to
        # do behind a request on a shared host.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        sweep_orphan_backgrounds(conn)


def sweep_orphan_backgrounds(conn):
    """Delete uploaded backgrounds no account points at any more.

    Replacing your own background deletes the file it replaced, and that covers the common
    case -- but not every case. Deleting an account leaves its upload behind; so does a write
    that stores the file and then fails before the settings row is updated. Neither is
    recoverable from, and on a shared host the cost of never noticing is the disk quota.

    The grace period is what makes this safe to run against a live site: a file written
    seconds ago may belong to a request that has not committed its settings row yet, and
    sweeping it would delete a background out from under the student who just chose it. An
    hour is far longer than any request and far shorter than "forever".
    """
    if not os.path.isdir(USER_BG_DIR):
        return
    try:
        names = os.listdir(USER_BG_DIR)
    except OSError:
        return
    cutoff = time.time() - ORPHAN_BG_GRACE
    stale = []
    for name in names:
        path = os.path.join(USER_BG_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                stale.append(name)
        except OSError:
            pass
    if not stale:
        return
    # Only now read the accounts, and only because there is something that might be deleted.
    keep = set()
    for r in conn.execute("SELECT settings FROM users WHERE settings LIKE ?",
                          ("%" + USER_BG_URL + "%",)):
        try:
            bg = (json.loads(r["settings"] or "{}") or {}).get("bg") or {}
        except (ValueError, AttributeError):
            continue
        value = bg.get("value") if isinstance(bg, dict) else None
        if isinstance(value, str) and value.startswith(USER_BG_URL):
            keep.add(os.path.basename(value))
    gone = 0
    for name in stale:
        if name in keep:
            continue
        try:
            os.remove(os.path.join(USER_BG_DIR, name))
            gone += 1
        except OSError:
            pass
    if gone:
        print("  + Removed %d unreferenced background file(s)" % gone)


def cleanup_loop():
    while True:
        time.sleep(3600)
        purge_expired()


# ------------------------------------------------------------------- auth ----
def hash_pw(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITER)
    return base64.b64encode(dk).decode(), base64.b64encode(salt).decode()


def verify_pw(password, hash_b64, salt_b64):
    salt = base64.b64decode(salt_b64)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITER)
    return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    conn = db()
    conn.execute(
        "INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)",
        (token, user_id, time.time() + SESSION_DAYS * 86400),
    )
    conn.commit()
    conn.close()
    return token


_LEAN_USER_COLS = None


def lean_user_cols(conn):
    """`u.*` minus the one column nothing on a hot path wants: `settings`.

    Every authenticated request resolves its session through user_from_token(), and `u.*`
    meant every one of them -- a heartbeat, a room poll, a stats read -- loaded, copied and
    parsed the whole settings blob to look at `id`. Backgrounds live on disk now so the blob
    is small again, but a per-request `SELECT *` over a free-form text column is the kind of
    thing that silently comes back, so the hot path no longer asks for it at all. The two
    endpoints that genuinely need it (/api/me, /api/appearance) read it by itself with
    settings_of(); everything else goes through col(), which already answers "a narrower
    SELECT didn't ask for this" with a default.

    Built from the live table rather than hardcoded so a migration that adds a column does
    not have to remember to come back here.
    """
    global _LEAN_USER_COLS
    if _LEAN_USER_COLS is None:
        names = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
        keep = [n for n in names if n != "settings"] or ["*"]
        _LEAN_USER_COLS = ",".join("u." + n for n in keep)
    return _LEAN_USER_COLS


def settings_of(uid):
    """One user's settings blob, parsed. {} for anything unreadable."""
    conn = db()
    row = conn.execute("SELECT settings FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    try:
        out = json.loads((row["settings"] if row else None) or "{}")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def user_from_token(token):
    if not token:
        return None
    conn = db()
    row = conn.execute(
        "SELECT s.expires AS _exp, " + lean_user_cols(conn) +
        " FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,),
    ).fetchone()
    conn.close()
    if not row or row["_exp"] < time.time():
        return None
    return row


# ------------------------------------------------- phone + one-time codes ----
# Persian and Arabic-Indic digits, so a number typed on a Persian keyboard is the same
# number as one typed on an English one.
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_PHONE_RE = re.compile(r"^09\d{9}$")


def norm_phone(raw):
    """An Iranian mobile number in the one form everything stores: 09xxxxxxxxx.

    People type +98, 0098, a bare 9…, and with spaces or dashes in between; all of those are
    the same account, so they have to normalise to the same string before anything looks a
    number up. Returns '' for anything that isn't a mobile number, and every caller treats
    that as "not a valid number" rather than guessing.
    """
    s = str(raw or "").strip().translate(_DIGIT_MAP)
    s = re.sub(r"[\s\-()‌‏\.]", "", s)
    if s.startswith("+"):
        s = "00" + s[1:]
    if s.startswith("0098"):
        s = "0" + s[4:]
    elif s.startswith("98") and len(s) == 12:
        s = "0" + s[2:]
    if len(s) == 10 and s.startswith("9"):
        s = "0" + s
    return s if _PHONE_RE.match(s) else ""


def mask_phone(phone):
    """09123456789 -> 0912***6789. What gets shown back to someone mid-flow, and logged."""
    p = str(phone or "")
    return (p[:4] + "***" + p[-4:]) if len(p) >= 8 else p


def hash_code(code, salt_b64):
    """Salted hash of a one-time code. See the otp_codes comment for why this is plain
    SHA-256 and not PBKDF2: a 5-digit code has no work factor worth buying, and what
    actually guards it is the TTL, the attempt ceiling and single use."""
    dk = hashlib.sha256(base64.b64decode(salt_b64) + str(code).encode("utf-8")).digest()
    return base64.b64encode(dk).decode()


def send_otp_sms(phone, code):
    """Hand a code to SMS.ir's verify/template endpoint. Returns (ok, detail).

    Never raises: a texting outage should come back as a plain "couldn't send" the caller can
    turn into a message, not a 500. The API key only ever appears in this request header.
    """
    if OTP_ECHO:
        # The console *is* the delivery channel here. Returning before the request is the
        # whole point: a developer typing a number into the form must not be able to text
        # whoever actually owns it.
        print("  * OTP for %s is %s  (OTP_ECHO — nothing was texted)" % (mask_phone(phone), code),
              flush=True)
        return True, "echo"
    if not (SMSIR_API_KEY and SMSIR_TEMPLATE_ID):
        # A misconfiguration, not a user error, and it says so rather than blaming the number.
        return False, "SMS is not configured on the server."
    import urllib.request, urllib.error
    try:
        template_id = int(str(SMSIR_TEMPLATE_ID).strip())
    except ValueError:
        return False, "SMSIR_TEMPLATE_ID is not a number."
    payload = json.dumps({
        "mobile": phone,
        "templateId": template_id,
        "parameters": [{"name": SMSIR_PARAM, "value": str(code)}],
    }).encode("utf-8")
    req = urllib.request.Request(SMSIR_URL, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "text/plain",
        "x-api-key": SMSIR_API_KEY,
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        print("  ! SMS.ir HTTP %s for %s: %s" % (e.code, mask_phone(phone), body[:300]))
    except Exception as e:
        print("  ! SMS.ir unreachable for %s: %r" % (mask_phone(phone), e))
        return False, "network"
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if isinstance(data, dict) and str(data.get("status")) == "1":
        return True, ""
    detail = (data.get("message") if isinstance(data, dict) else "") or body[:200]
    print("  ! SMS.ir refused %s: %s" % (mask_phone(phone), detail))
    return False, detail


def issue_otp(phone, ip):
    """Make a code for this number, store its hash, text it. Returns (ok, detail).

    Any earlier live code for the number is invalidated first, so only the newest text ever
    works — otherwise a resend would widen the window instead of replacing it.
    """
    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    salt = base64.b64encode(secrets.token_bytes(16)).decode()
    now = time.time()
    conn = db()
    conn.execute("UPDATE otp_codes SET used=1 WHERE phone=? AND used=0", (phone,))
    conn.execute(
        "INSERT INTO otp_codes(phone,code_hash,code_salt,created_at,expires,ip) VALUES(?,?,?,?,?,?)",
        (phone, hash_code(code, salt), salt, now, now + OTP_TTL, ip or ""),
    )
    conn.commit()
    conn.close()
    ok, detail = send_otp_sms(phone, code)
    if not ok:
        # Delete rather than mark used: a text that never arrived should leave no trace at
        # all, so the person can fix the number and try again straight away instead of
        # serving a 90-second cooldown for a code they never got. The hourly caps still hold.
        conn = db()
        conn.execute("DELETE FROM otp_codes WHERE phone=? AND used=0", (phone,))
        conn.commit()
        conn.close()
    return ok, detail


def check_otp(phone, code):
    """Check a code against the newest one issued for this number.

    Returns (ok, error_key). The error keys are what the endpoint turns into wording:
      none     nothing outstanding for this number
      used     that code has already been spent
      expired  it was issued more than OTP_TTL ago
      locked   too many wrong guesses — the code is dead, ask for a new one
      wrong    it simply doesn't match (the attempt is counted)
    A correct code is marked used inside the same statement that checks it, so two requests
    racing with the same code can't both win: only the one whose UPDATE changes a row does.
    """
    digits = str(code or "").strip().translate(_DIGIT_MAP)
    digits = re.sub(r"\D", "", digits)
    conn = db()
    try:
        row = conn.execute(
            "SELECT * FROM otp_codes WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,)
        ).fetchone()
        if not row:
            return False, "none"
        if row["used"]:
            return False, "used"
        if row["expires"] < time.time():
            return False, "expired"
        if row["attempts"] >= OTP_MAX_ATTEMPTS:
            return False, "locked"
        if len(digits) != OTP_LENGTH or not hmac.compare_digest(
                hash_code(digits, row["code_salt"]), row["code_hash"]):
            conn.execute("UPDATE otp_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
            conn.commit()
            left = OTP_MAX_ATTEMPTS - (row["attempts"] + 1)
            return False, ("locked" if left <= 0 else "wrong")
        cur = conn.execute("UPDATE otp_codes SET used=1 WHERE id=? AND used=0", (row["id"],))
        conn.commit()
        if cur.rowcount != 1:
            return False, "used"
        return True, ""
    finally:
        conn.close()


def otp_seconds_left(phone):
    """Seconds before this number may be texted again — 0 when it can be, now."""
    conn = db()
    row = conn.execute(
        "SELECT created_at FROM otp_codes WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,)
    ).fetchone()
    conn.close()
    if not row:
        return 0
    return max(0, int(round(row["created_at"] + OTP_RESEND_SECONDS - time.time())))


def issue_phone_ticket(phone):
    """Proof of a verified number, for a signup that hasn't been filled in yet."""
    token = secrets.token_urlsafe(32)
    conn = db()
    conn.execute("DELETE FROM phone_tickets WHERE phone=?", (phone,))
    conn.execute("INSERT INTO phone_tickets(token,phone,expires,created_at) VALUES(?,?,?,?)",
                 (token, phone, time.time() + OTP_TICKET_TTL, now_iso()))
    conn.commit()
    conn.close()
    return token


def check_phone_ticket(token, phone):
    """Is this ticket real, for this number, and still in date? Doesn't consume it.

    Separate from spending it so a signup can be rejected for a malformed email without
    burning the proof that the number was verified — otherwise a typo would send someone
    back through the whole SMS round trip.
    """
    if not token:
        return False
    conn = db()
    row = conn.execute("SELECT * FROM phone_tickets WHERE token=?", (str(token),)).fetchone()
    conn.close()
    return bool(row and row["phone"] == phone and row["expires"] >= time.time())


def spend_phone_ticket(token, phone):
    """Consume a ticket, once. True only for the caller whose DELETE actually removed it,
    so two requests racing with the same ticket can't both make an account."""
    if not token:
        return False
    conn = db()
    try:
        cur = conn.execute("DELETE FROM phone_tickets WHERE token=? AND phone=? AND expires>=?",
                           (str(token), phone, time.time()))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


# ------------------------------------------------------------ admin auth ----
def create_admin_session(admin_id, ip, ua):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = time.time()
    conn = db()
    conn.execute(
        "INSERT INTO admin_sessions(token,admin_id,csrf,expires,last_seen,created_at,ip,ua) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (token, admin_id, csrf, now + ADMIN_SESSION_HOURS * 3600, now, now_iso(),
         ip, (ua or "")[:200]),
    )
    conn.commit()
    conn.close()
    return token, csrf


def admin_from_token(token):
    """Resolve an admin session, enforcing both the absolute cap and the idle cutoff.

    An expired-either-way session is deleted on sight rather than merely rejected, so a
    stolen token stops being a live row the moment it is next used. Every accepted request
    slides `last_seen` forward, which is what makes the idle window a real inactivity
    timeout instead of a fixed one.
    """
    if not token:
        return None
    now = time.time()
    conn = db()
    row = conn.execute(
        "SELECT s.expires AS _exp, s.last_seen AS _seen, s.csrf AS _csrf, s.token AS _tok, "
        "a.id, a.username, a.created_at, a.last_login, a.last_ip "
        "FROM admin_sessions s JOIN admins a ON a.id=s.admin_id WHERE s.token=?",
        (token,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    if row["_exp"] < now or (now - row["_seen"]) > ADMIN_IDLE_MINUTES * 60:
        conn.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
        return None
    conn.execute("UPDATE admin_sessions SET last_seen=? WHERE token=?", (now, token))
    conn.commit()
    conn.close()
    return row


# --------------------------------------------------- appearance resolution ----
def settings_map():
    conn = db()
    rows = conn.execute("SELECT key,value FROM app_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


_thumbs = {"at": 0.0, "names": frozenset()}
_thumbs_lock = threading.Lock()


def thumb_names():
    """Filenames present in media/backgrounds/thumb, re-read at most once a minute.

    One listdir instead of a stat() per background per request, and the answer barely ever
    changes -- a new entry appears only when an admin uploads a background.
    """
    now = time.time()
    with _thumbs_lock:
        if now - _thumbs["at"] < 60:
            return _thumbs["names"]
        try:
            names = frozenset(os.listdir(THUMB_DIR))
        except OSError:
            names = frozenset()
        _thumbs.update(at=now, names=names)
        return names


def thumb_for(value):
    """The swatch-sized copy of a background image, if one has been generated.

    The picker renders these at about 70px, and it was pointing them at the originals --
    which are full-resolution photographs of 2-3MB each. Opening Settings once downloaded
    roughly 30MB to draw a grid of thumbnails; the generated versions total 110KB. Returns
    None when there is no thumbnail, and the client falls back to the original.
    """
    if not isinstance(value, str) or not value.startswith("/media/backgrounds/"):
        return None
    name = os.path.basename(value)
    if not name:
        return None
    jpg = os.path.splitext(name)[0] + ".jpg"
    return (THUMB_URL + jpg) if jpg in thumb_names() else None


def bg_payload(row):
    out = {"id": row["id"], "name": row["name"], "slug": row["slug"], "kind": row["kind"],
           "value": row["value"], "platform": row["platform"], "enabled": bool(row["enabled"]),
           "description": row["description"] or "", "is_system": bool(row["is_system"]),
           "created_at": row["created_at"], "updated_at": row["updated_at"]}
    if row["kind"] == "image":
        out["thumb"] = thumb_for(row["value"])
    return out


def theme_payload(row):
    try:
        tokens = json.loads(row["tokens"] or "{}")
    except ValueError:
        tokens = {}
    return {"id": row["id"], "name": row["name"], "slug": row["slug"], "tokens": tokens,
            "is_system": bool(row["is_system"]), "enabled": bool(row["enabled"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def decode_image(raw):
    """(bytes, ext) for a data: URL that really is an image, or (None, reason).

    The declared MIME type never decides -- the magic bytes do. Shared with the admin
    uploader so both doors accept exactly the same set of files.
    """
    if not isinstance(raw, str) or not raw.startswith("data:") or "," not in raw:
        return None, "Expected an image data URL."
    try:
        blob = base64.b64decode(raw.split(",", 1)[1], validate=True)
    except Exception:
        return None, "That image couldn't be decoded."
    if not blob:
        return None, "That image is empty."
    if len(blob) > MAX_IMAGE_BYTES:
        return None, "Image is larger than %d MB." % (MAX_IMAGE_BYTES // (1024 * 1024))
    for magic, ext, _mime in IMAGE_MAGIC:
        if blob.startswith(magic):
            if magic == b"RIFF" and blob[8:12] != b"WEBP":
                continue
            return blob, ext
    return None, "Only JPEG, PNG, GIF or WebP images are accepted."


def store_user_bg(raw):
    """Write a student's uploaded background to disk. Returns (url, None) or (None, error).

    This is the whole point of the change: a background used to live inside the account's
    settings JSON as a base64 data URL, which meant ~570KB of it went out again with every
    /api/appearance AND every /api/me -- twice per page load, uncompressible (it is already
    JPEG), through a worker that serves one request at a time. On disk it is a 40-byte path
    that the browser fetches once and then caches for a year.
    """
    blob, ext = decode_image(raw)
    if blob is None:
        return None, ext            # `ext` carries the reason when the decode failed
    try:
        os.makedirs(USER_BG_DIR, exist_ok=True)
        # Server-generated name: nothing from the request reaches the filesystem path. A new
        # name per upload is also what makes "cache this forever" safe -- replacing a
        # background produces a new URL rather than new bytes at an old one.
        fname = "%s.%s" % (secrets.token_urlsafe(12).replace("-", "_"), ext)
        with open(os.path.join(USER_BG_DIR, fname), "wb") as fh:
            fh.write(blob)
    except OSError:
        traceback.print_exc()
        return None, "Couldn't save that image — try again."
    return USER_BG_URL + fname, None


def user_bg_present(url):
    """Is this account's uploaded background still on disk?

    Worth asking because the answer can be no. The database stores a path and the bytes live
    in media/, so the two can come apart -- a database restored without its media directory
    is the obvious way, and it is exactly what a routine "just restore the database" does.
    Before this check the student got a page pointing at a 404 and simply no background;
    now they fall through to the admin's default, which is what someone who never chose one
    sees. Only their own uploads are checked: gallery backgrounds are the admin's to fix.
    """
    if not isinstance(url, str) or not url.startswith(USER_BG_URL):
        return True                      # not one of ours to vouch for
    name = os.path.basename(url)
    return bool(name) and os.path.isfile(os.path.join(USER_BG_DIR, name))


def without_missing_bg(settings):
    """`settings` with a background whose file has gone missing reset to the default.

    resolve_appearance() already refuses to serve a dead path, but /api/me hands the raw
    settings straight to the browser, which caches them in localStorage and paints from
    there before /api/appearance has answered. Left alone, the dead path would live on in
    the client for as long as that entry did. Returning the default in its place is what
    makes the browser overwrite it -- omitting the key entirely would leave the stale copy
    untouched. Their dim and blur are kept; only the dead image goes.
    """
    if not isinstance(settings, dict):
        return settings
    bg = settings.get("bg")
    if not isinstance(bg, dict) or user_bg_present(bg.get("value")):
        return settings
    fixed = dict(settings)
    fixed["bg"] = {"type": "preset", "value": FALLBACK_BG_SLUG, "chosen": False,
                   "dim": bg.get("dim") or 0, "blur": bg.get("blur") or 0}
    return fixed


def drop_user_bg(url):
    """Delete a background this account no longer points at. Never raises.

    Only ever touches a file inside USER_BG_DIR, and only by basename, so a value that
    somehow arrived from a request cannot reach anything else on disk.
    """
    if not isinstance(url, str) or not url.startswith(USER_BG_URL):
        return
    name = os.path.basename(url)
    if not name or name in (".", ".."):
        return
    try:
        os.remove(os.path.join(USER_BG_DIR, name))
    except OSError:
        pass


def externalize_bg(settings, previous=None):
    """Move an inline data: URL background in `settings` out to a file, in place.

    Called on every settings write, not just at migration time, because an older tab or a
    cached copy of the page can still be sending the old shape hours after a deploy. Returns
    an error string if the image was rejected, None otherwise (including "nothing to do").
    """
    if not isinstance(settings, dict):
        return None
    bg = settings.get("bg")
    if not isinstance(bg, dict):
        return None
    value = bg.get("value")
    old = (previous or {}).get("bg") if isinstance(previous, dict) else None
    old_url = old.get("value") if isinstance(old, dict) else None
    if isinstance(value, str) and value.startswith("data:"):
        url, err = store_user_bg(value)
        if err:
            return err
        bg["value"] = url
        bg["type"] = "image"
        # The file this account used to point at is now unreachable; don't leave it behind.
        if old_url != url:
            drop_user_bg(old_url)
    elif old_url and old_url != value:
        # Switched to a preset or to a different image: the old upload is orphaned either way.
        drop_user_bg(old_url)
    return None


def user_picked_bg(bg):
    """Did this user actually choose a background, or is this just the built-in default?

    New choices carry `chosen:true`, written the moment a swatch is tapped or an image is
    uploaded. Accounts that predate that flag are read by their content instead: an uploaded
    image, or any preset other than the default `midnight` at its default dim/blur, can only
    have got there by someone picking it. A settings blob that still holds exactly the
    shipped default is treated as "never chose", which is what lets a global default reach
    long-standing accounts that never touched the setting.
    """
    if not isinstance(bg, dict) or not bg.get("value"):
        return False
    if bg.get("chosen"):
        return True
    if bg.get("type") == "image":
        return True
    return not (bg.get("value") == FALLBACK_BG_SLUG and not bg.get("dim") and not bg.get("blur"))


def user_picked_theme(prefs):
    """Same idea for themes: an explicit flag, or an accent/appearance that isn't the default."""
    if not isinstance(prefs, dict):
        return False
    if prefs.get("themeChosen"):
        return True
    return bool(prefs.get("accent") and prefs.get("accent") != "amber") or bool(prefs.get("glass"))


def resolve_appearance(platform, user_row=None):
    """User preference → admin default for the platform → application fallback.

    Returns the resolved theme and background plus, for each, where it came from. The same
    three-step order applies to both; a user preference is only ever read from that user's
    own settings, so a global default can never overwrite one.
    """
    platform = "mobile" if platform == "mobile" else "web"
    cfg = settings_map()
    conn = db()
    out = {"platform": platform, "theme": None, "background": None,
           "source": {"theme": "fallback", "background": "fallback"},
           "dim": None, "blur": None}

    # The session lookup no longer carries the settings blob (see lean_user_cols), so read it
    # here by id. col() covers the case where a caller *did* hand over a row that has it.
    settings = {}
    if user_row is not None:
        raw = col(user_row, "settings")
        if raw is None:
            settings = settings_of(user_row["id"])
        else:
            try:
                settings = json.loads(raw or "{}")
            except ValueError:
                settings = {}
    ubg = settings.get("bg") if isinstance(settings, dict) else None
    uprefs = settings.get("prefs") if isinstance(settings, dict) else None

    # ---- background ----
    # An upload whose file has gone missing is treated as "never chose one", so the answer
    # falls through to the admin default below instead of pointing the page at a 404.
    if user_picked_bg(ubg) and user_bg_present(ubg.get("value")):
        out["background"] = {"kind": "image" if ubg.get("type") == "image" else "preset",
                             "value": ubg.get("value"), "name": "Your background"}
        out["dim"] = ubg.get("dim") or 0
        out["blur"] = ubg.get("blur") or 0
        out["source"]["background"] = "user"
    else:
        key = "mobile_default_background" if platform == "mobile" else "web_default_background"
        row = None
        if (cfg.get(key) or "").isdigit():
            row = conn.execute(
                "SELECT * FROM backgrounds WHERE id=? AND enabled=1 AND platform IN ('both',?)",
                (int(cfg[key]), platform),
            ).fetchone()
        if row:
            out["background"] = {"kind": row["kind"], "value": row["value"], "name": row["name"],
                                 "id": row["id"], "slug": row["slug"]}
            out["source"]["background"] = "global"
        else:
            row = conn.execute("SELECT * FROM backgrounds WHERE slug=?", (FALLBACK_BG_SLUG,)).fetchone()
            if row:
                out["background"] = {"kind": row["kind"], "value": row["value"],
                                     "name": row["name"], "id": row["id"], "slug": row["slug"]}
        try:
            out["dim"] = int(cfg.get("default_dim") or 0)
            out["blur"] = int(cfg.get("default_blur") or 0)
        except ValueError:
            out["dim"], out["blur"] = 0, 0

    # ---- theme ----
    if user_picked_theme(uprefs):
        out["source"]["theme"] = "user"
        out["theme"] = {"accentKey": uprefs.get("accent") or "amber",
                        "appearance": "glass" if uprefs.get("glass") else "classic",
                        "name": "Your theme", "tokens": {}}
    else:
        row = None
        if (cfg.get("default_theme") or "").isdigit():
            row = conn.execute("SELECT * FROM themes WHERE id=? AND enabled=1",
                               (int(cfg["default_theme"]),)).fetchone()
        if row:
            out["theme"] = theme_payload(row)
            out["source"]["theme"] = "global"
        else:
            row = conn.execute("SELECT * FROM themes WHERE slug=?", (FALLBACK_THEME_SLUG,)).fetchone()
            if row:
                out["theme"] = theme_payload(row)
    out["language"] = cfg.get("default_language") or "en"
    conn.close()
    return out


# ------------------------------------------------- education + library ----
def norm_major_text(v):
    """Fold a free-text major for comparison: lowercase, whitespace collapsed."""
    return " ".join(str(v or "").lower().split())


def norm_edu(d, current=None):
    """Validate what a student says they're studying, against the vocabulary above.

    `current` is the education already on the account: a field the caller left out keeps
    its existing value, so a PATCH that only changes the grade doesn't wipe the major.
    Everything is checked against the fixed key lists — a stage, grade or school major
    that isn't one of ours is dropped rather than stored, which is what keeps library
    targeting matching on values that actually exist.
    """
    cur = current or {}
    stage = d.get("stage", cur.get("stage") or "")
    stage = stage if stage in EDU_STAGES else ""
    if stage == "school":
        grade = str(d.get("grade", cur.get("grade") or "") or "")
        grade = grade if grade in SCHOOL_GRADES else ""
        major = str(d.get("major", cur.get("major") or "") or "").lower()
        # A major below tenth grade isn't a thing to record, so it is cleared rather
        # than half-kept — a student who picks یازدهم then drops to نهم ends up with the
        # empty major that grade really has.
        major = major if (major in SCHOOL_MAJORS and grade in MAJOR_GRADES) else ""
        return {"stage": "school", "grade": grade, "major": major}
    if stage == "uni":
        major = " ".join(str(d.get("major", cur.get("major") or "") or "").split())[:UNI_MAJOR_MAX]
        return {"stage": "uni", "grade": "", "major": major}
    return {"stage": "", "grade": "", "major": ""}


def edu_of(row):
    """The education block for a user row, in the shape the API hands out everywhere."""
    try:
        stage = row["edu_stage"] or ""
        grade = row["edu_grade"] or ""
        major = row["edu_major"] or ""
    except (IndexError, KeyError):
        stage = grade = major = ""
    return {"stage": stage, "grade": grade, "major": major,
            # Enough to draw the "finish your profile" prompt without the page having to
            # know that majors start at tenth grade.
            "complete": bool(stage) and (stage == "uni" or bool(grade)),
            "needsMajor": stage == "school" and grade in MAJOR_GRADES}


def library_match(alias, edu):
    """SQL fragment + args selecting the rows aimed at this student.

    Each targeting column reads '' as "any", which is what lets one row serve a whole
    grade, a whole major, or everybody, instead of needing a row per combination. The
    major comparison folds case and spacing because a university major is free text the
    student typed themselves.
    """
    clause = ("({a}.stage='all' OR {a}.stage=?) AND ({a}.grade='' OR {a}.grade=?) "
              "AND ({a}.major='' OR LOWER(TRIM({a}.major))=?)").format(a=alias)
    return clause, [edu.get("stage") or "", edu.get("grade") or "",
                    norm_major_text(edu.get("major"))]


def lib_category_payload(row):
    return {"id": row["id"], "name": row["name"], "slug": row["slug"],
            "description": row["description"] or "", "stage": row["stage"],
            "grade": row["grade"] or "", "major": row["major"] or "",
            "visible": bool(row["visible"]), "sort": row["sort_order"] or 0,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def lib_item_payload(row, full=False):
    """One piece of material. `full` adds the admin-only bookkeeping.

    file_path is never in either shape: the bytes are reached through
    /api/library/file/<id>, which is where the "is this meant for you" check lives.
    """
    out = {"id": row["id"], "title": row["title"], "description": row["description"] or "",
           "categoryId": row["category_id"], "stage": row["stage"],
           "grade": row["grade"] or "", "major": row["major"] or "",
           "fileName": row["file_name"] or "", "size": row["file_size"] or 0,
           "mime": row["mime"] or "", "ext": (row["file_path"] or "").rsplit(".", 1)[-1].lower(),
           "url": "/api/library/file/%d" % row["id"], "created_at": row["created_at"]}
    if full:
        out.update({"visible": bool(row["visible"]), "downloads": row["downloads"] or 0,
                    "updated_at": row["updated_at"],
                    # A row whose bytes have gone — a stray cleanup, a database restored
                    # without its media folder, a half-finished copy between machines —
                    # looks perfectly healthy in a list, and the student is the one who
                    # finds out. One stat per row while an admin is looking at the page is
                    # a cheap price for the panel saying so itself.
                    "missing": not lib_file_on_disk(row["file_path"])})
    return out


def lib_file_on_disk(path):
    """Are the bytes for this row still there? basename() keeps the check inside MEDIA."""
    name = os.path.basename(path or "")
    return bool(name) and os.path.isfile(os.path.join(LIBRARY_DIR, name))


def library_enabled():
    return (settings_map().get("library_enabled") or "1") != "0"


def library_for_user(conn, edu):
    """The shelf as one student sees it: visible material aimed at them, in its folders.

    A hidden category takes its material with it — that is the whole point of the switch,
    so an admin can stage a term's worth of files and publish them in one move.
    """
    where, args = library_match("i", edu)
    rows = conn.execute(
        "SELECT i.* FROM library_items i "
        "LEFT JOIN library_categories c ON c.id=i.category_id "
        "WHERE i.visible=1 AND (i.category_id IS NULL OR c.visible=1) AND " + where +
        " ORDER BY i.category_id IS NULL, i.category_id, i.id DESC", args).fetchall()
    # A row whose file has gone is not material — it is a card that would 404 when tapped.
    # It stays in the admin's list, flagged, because that is who can fix it.
    rows = [r for r in rows if lib_file_on_disk(r["file_path"])]
    items = [lib_item_payload(r) for r in rows]
    used = {r["category_id"] for r in rows if r["category_id"] is not None}
    cats = []
    if used:
        marks = ",".join("?" * len(used))
        cats = [lib_category_payload(r) for r in conn.execute(
            "SELECT * FROM library_categories WHERE visible=1 AND id IN (%s) "
            "ORDER BY sort_order, name" % marks, list(used))]
    return cats, items


def ext_mime(ext):
    """The type an extension we accepted maps to. Never taken from the client: this value
    goes out as a response header, so it is looked up from our own table."""
    for _magic, e, mime in DOC_MAGIC:
        if e == ext:
            return mime
    return ZIP_TYPES.get(ext) or TEXT_TYPES.get(ext) or "application/octet-stream"


def sniff_upload(blob, filename):
    """Decide what an uploaded file really is, from its bytes. (ext, mime) or (None, None).

    The extension in the filename only ever picks *between* the zip-container formats,
    which are byte-identical; it never gets to claim a type the content doesn't back up.
    """
    for magic, ext, mime in DOC_MAGIC:
        if blob.startswith(magic):
            if magic == b"RIFF" and blob[8:12] != b"WEBP":
                continue
            return ext, mime
    suffix = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if blob[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        ext = suffix if suffix in ZIP_TYPES else "zip"
        return ext, ZIP_TYPES[ext]
    if suffix in TEXT_TYPES:
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            return None, None
        return suffix, TEXT_TYPES[suffix]
    return None, None


# ------------------------------------------------------------- serializers ----
def col(row, name, default=None):
    """Read a column that a narrower SELECT may not have asked for."""
    try:
        return row[name] if name in row.keys() else default
    except (IndexError, KeyError):
        return default


def display_name(row):
    """What to call someone who never set a name.

    It used to be the local part of their email, which stopped working the moment email
    became optional. The order below is simply most human first: their name, then whatever
    they typed before the @, then the last four digits of the number they signed up with.
    """
    name = (col(row, "name") or "").strip()
    if name:
        return name
    email = (col(row, "email") or "").strip()
    if email and "@" in email:
        return email.split("@")[0]
    if email:
        return email
    phone = (col(row, "phone") or "").strip()
    if phone:
        # Digits only, no English word wrapped around them: this string is rendered as-is in
        # both languages, and "…6789" reads the same in each.
        return "…" + phone[-4:]
    return "#%s" % col(row, "id", "?")


def public_user(row):
    return {
        "id": row["id"],
        # Optional now: null, not "", so the frontend can tell "didn't give one" from
        # "gave an empty one" without inventing a rule for the difference.
        "email": col(row, "email") or None,
        "phone": col(row, "phone") or None,
        "phoneVerified": bool(col(row, "phone_verified", 0)),
        "hasPassword": bool(col(row, "pw_hash")),
        "name": row["name"],
        "displayName": display_name(row),
        "avatar": row["avatar"] or "🦊",
        "created_at": row["created_at"],
        "education": edu_of(row),
    }


def get_tasks(uid):
    conn = db()
    rows = conn.execute(
        "SELECT id,text,done FROM tasks WHERE user_id=? ORDER BY id", (uid,)
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "text": r["text"], "done": bool(r["done"])} for r in rows]


def subjects_for(uid):
    """Every subject with the time on it today, in two queries rather than N+1.

    This ran one SUM per subject, and /api/log calls it on every flush -- i.e. every 30
    seconds for every running timer, multiplied by however many subjects that student keeps.
    The grouped query below walks exactly the same (user_id, day, subject_id) index, once.
    """
    conn = db()
    today = today_str()
    rows = conn.execute("SELECT id,name,color FROM subjects WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    totals = {r["subject_id"]: r["s"] for r in conn.execute(
        "SELECT subject_id, COALESCE(SUM(seconds),0) AS s FROM session_log "
        "WHERE user_id=? AND day=? AND subject_id IS NOT NULL GROUP BY subject_id",
        (uid, today),
    )}
    conn.close()
    return [{"id": r["id"], "name": r["name"], "color": r["color"],
             "todayMinutes": totals.get(r["id"], 0) // 60,
             "todaySeconds": totals.get(r["id"], 0)}
            for r in rows]


def compute_streak(by):
    """Consecutive days of real study time.

    A day joins the streak once its focused time passes STREAK_MIN_SECONDS, whether that came
    from countdown blocks or the stopwatch — counting sessions instead would let a handful of
    ten-second blocks keep a streak alive.
    """
    def qualifies(d):
        return by.get(d.isoformat(), {}).get("seconds", 0) >= STREAK_MIN_SECONDS

    streak = 0
    d = today_date()
    if not qualifies(d):
        d = d - timedelta(days=1)  # today still pending -> count from yesterday
    while qualifies(d):
        streak += 1
        d -= timedelta(days=1)
    return streak


def stats_summary(uid):
    conn = db()
    rows = conn.execute(
        "SELECT day,sessions,seconds FROM stat_days WHERE user_id=? ORDER BY day", (uid,)
    ).fetchall()
    conn.close()
    by = {r["day"]: {"sessions": r["sessions"], "seconds": r["seconds"] or 0} for r in rows}
    today = today_str()
    history = []
    for i in range(13, -1, -1):
        d = (today_date() - timedelta(days=i)).isoformat()
        cell = by.get(d, {})
        secs = cell.get("seconds", 0)
        history.append(
            {"day": d, "minutes": secs // 60, "seconds": secs, "sessions": cell.get("sessions", 0)}
        )
    tcell = by.get(today, {"sessions": 0, "seconds": 0})
    return {
        "today": {"sessions": tcell["sessions"], "minutes": tcell["seconds"] // 60, "seconds": tcell["seconds"]},
        "totalSessions": sum(r["sessions"] for r in rows),
        "totalMinutes": sum((r["seconds"] or 0) for r in rows) // 60,
        "streak": compute_streak(by),
        "bestMinutes": max(((r["seconds"] or 0) // 60 for r in rows), default=0),
        "activeDays": len([r for r in rows if r["sessions"] > 0]),
        "history": history,
    }


# ---------------------------------------------------------------- handler ----
class Handler(SimpleHTTPRequestHandler):
    _sent = False   # has a status line gone out yet? _guard() needs to know (see below)

    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def send_response(self, *a, **k):
        self._sent = True
        return super().send_response(*a, **k)

    def send_response_only(self, *a, **k):
        self._sent = True
        return super().send_response_only(*a, **k)

    def log_message(self, fmt, *args):
        """Quiet by default.

        This printed a line per request, and under Passenger stderr is a file on the same
        shared, network-backed disk everything else is competing for -- a synchronous write
        on the way out of every response, including the 304s that make up most of a repeat
        visit, into a log nothing rotates. Set ACCESS_LOG=1 to get it back while debugging.
        """
        if ACCESS_LOG:
            print("  %s - %s" % (self.command, self.path))

    def version_string(self):
        return "Study Planet"  # don't advertise the Python/stdlib version in the Server header

    def end_headers(self):
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        if FORCE_HTTPS and self._is_https():
            self.send_header(*HSTS_HEADER)
        # Only add a Cache-Control if the handler hasn't already chosen one. _json() and the
        # admin pages send their own ("no-store"), and this used to append a second, weaker
        # header next to it -- two Cache-Control lines on one response, with which of them
        # wins left to the client.
        already = any(line[:14].lower() == b"cache-control:"
                      for line in getattr(self, "_headers_buffer", []))
        if not already:
            self.send_header("Cache-Control", self._cache_control())
        super().end_headers()

    def _cache_control(self):
        """Caching policy for whatever this response is about to send.

        Uploaded backgrounds are the one genuinely immutable thing served here: the filename
        is a random token minted per upload (see the upload handler), so replacing a
        background produces a *new* URL rather than new bytes at the old one. That makes a
        one-year immutable cache safe, and it is what lets a phone keep a background across
        launches instead of re-downloading a megabyte of JPEG on every single page load.

        The *pages* must stay on "no-cache". They carry only Last-Modified otherwise, and
        clients -- the Android WebView especially -- invent a freshness window from that and
        serve a stale copy for hours, so deployed changes silently never arrive. "no-cache"
        still permits conditional requests, so an unchanged page comes back as a cheap 304.

        Their assets do not need the same treatment, and giving it to them was expensive: a
        page load revalidated i18n.js, theme.js and favicon.svg every single time, and each
        of those 304s is a full round trip that occupies a worker for the duration -- of which
        this app has very few, and they serve one request at a time. A short window instead
        means a visitor moving between /app, /dashboard and /rooms fetches them once. It is
        deliberately short, because these URLs are not versioned: ASSET_MAX_AGE is the longest
        a deploy can take to reach somebody who is already on the site, so it is a number to
        raise only alongside cache-busting filenames.
        """
        path = urlparse(self.path).path
        if path.startswith("/media/backgrounds/"):
            return "public, max-age=31536000, immutable"
        low = path.lower()
        if low.endswith(".apk"):
            # A 4MB download nobody expects to change between two taps of the same button.
            return "public, max-age=3600"
        if low.endswith(CACHEABLE_ASSET_EXT):
            return "public, max-age=%d" % ASSET_MAX_AGE
        return "no-cache"

    def list_directory(self, path):
        # never expose directory listings
        self.send_error(404, "Not found")
        return None

    # -- helpers --
    def _json(self, code, obj, extra_headers=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = cookies.SimpleCookie(raw)
        return jar["sid"].value if "sid" in jar else None

    def _user(self):
        return user_from_token(self._token())

    def _admin_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = cookies.SimpleCookie(raw)
        return jar["asid"].value if "asid" in jar else None

    def _admin(self):
        return admin_from_token(self._admin_token())

    def _set_admin_cookie(self, token):
        sec = "; Secure" if SECURE_COOKIES else ""
        # SameSite=Strict, not Lax: no cross-site navigation should ever arrive already
        # authenticated as the admin. Combined with the CSRF header check on every mutating
        # call, an off-origin page cannot drive the panel even if it can make the browser
        # issue requests. Path=/ because both /admin and /api/admin/* need it.
        return [("Set-Cookie", "asid=%s; HttpOnly; SameSite=Strict; Path=/%s; Max-Age=%d"
                 % (token, sec, int(ADMIN_SESSION_HOURS * 3600)))]

    def _clear_admin_cookie(self):
        sec = "; Secure" if SECURE_COOKIES else ""
        return [("Set-Cookie", "asid=; HttpOnly; SameSite=Strict; Path=/%s; Max-Age=0" % sec)]

    def _serve_file(self, name):
        """Send a file from ROOT directly, bypassing the static path mapping."""
        try:
            with open(os.path.join(ROOT, name), "rb") as fh:
                body = fh.read()
        except OSError:
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # never let an admin page sit in a cache
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self):
        if TRUST_PROXY:
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "?"

    def _is_https(self):
        """True when the request reached the browser over TLS.

        The socket is never the answer: Apache terminates TLS and hands Passenger a plain
        HTTP request, so every request looks insecure from in here. X-Forwarded-Proto is what
        carries the truth, and passenger_wsgi.py stamps it from wsgi.url_scheme -- which
        Passenger sets from the vhost the request actually arrived on -- overwriting anything
        a client sent under that name. Gated on TRUST_PROXY for the same reason _client_ip()
        is: with no trusted proxy in front, the header is just something a client typed.
        """
        if not TRUST_PROXY:
            return False
        proto = self.headers.get("X-Forwarded-Proto") or ""
        return proto.split(",")[0].strip().lower() == "https"

    def _require_https(self):
        """Redirect a plain-HTTP request to the https:// URL. True once it has answered.

        No-op unless FORCE_HTTPS is set, so local development over http is unaffected. 301 for
        GET/HEAD and 308 for the rest: a 301 would let a client turn a POST into a GET and
        drop the body, which for this API means a silently discarded write.
        """
        if not FORCE_HTTPS or self._is_https():
            return False
        host = self.headers.get("Host") or ""
        # Host and the request target are both client-controlled, so neither is pasted into a
        # Location as-is: anything but a bare hostname[:port] and an origin-form path would
        # make this an open redirect (a request line in absolute form -- "GET http://elsewhere/"
        # -- is the one that would otherwise send visitors off-site). The port goes with the
        # host: the https URL belongs on 443, whatever port the plain-HTTP request came in on.
        if not self.path.startswith("/") or not re.match(r"^[A-Za-z0-9.\-]+(:\d+)?$", host):
            self._json(400, {"error": "bad host"})
            return True
        self.send_response(301 if self.command in ("GET", "HEAD") else 308)
        self.send_header("Location", "https://%s%s" % (host.split(":")[0], self.path))
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _set_cookie(self, token):
        sec = "; Secure" if SECURE_COOKIES else ""
        return [("Set-Cookie",
                 "sid=%s; HttpOnly; SameSite=Lax; Path=/%s; Max-Age=%d" % (token, sec, SESSION_DAYS * 86400))]

    def _clear_cookie(self):
        sec = "; Secure" if SECURE_COOKIES else ""
        return [("Set-Cookie", "sid=; HttpOnly; SameSite=Lax; Path=/%s; Max-Age=0" % sec)]

    # -- routing --
    def _resolve_static(self):
        """Shared gate for GET and HEAD. Returns True if it has already sent a response
        (an API/admin reply or a 404) and the caller must stop; returns False after
        rewriting self.path to the vetted static file the caller should serve. HEAD goes
        through the same allow-list as GET so it can never confirm the existence or size
        of a file GET would refuse — secrets, the database, or another student's material."""
        p = urlparse(self.path).path
        head = self.command == "HEAD"
        if p.startswith("/api/"):
            # The API isn't meant for HEAD; only GET/POST/… carry it. Answer 404 rather
            # than run a read handler with no body to return.
            self._json(404, {"error": "not found"}) if head else self.api()
            return True
        # Never serve dotfiles/dot-directories (.git, .gitignore, .env, …) or bytecode caches.
        # Decode first so a percent-encoded dot (%2e) can't slip past the check.
        dp = unquote(p)
        if any(seg.startswith(".") or seg == "__pycache__" for seg in dp.split("/") if seg):
            self._json(404, {"error": "not found"})
            return True
        clean = p.rstrip("/") or "/"
        # The admin panel is served by the server, never as a static file: /admin hands back
        # the dashboard only to a live admin session and the sign-in form to everyone else,
        # so the panel's markup and its API surface are never sent to an unauthenticated
        # visitor. The static blocklist below then makes the two files unreachable by name,
        # which is what stops /admin.html from being an unguarded way in.
        if clean == "/admin" or clean.startswith("/admin/"):
            if head:
                self._json(404, {"error": "not found"})
            elif clean == "/admin/logout":
                self._serve_file("admin-login.html")
            else:
                self._serve_file("admin.html" if self._admin() else "admin-login.html")
            return True
        pretty = {"/login": "/login.html", "/dashboard": "/dashboard.html",
                  "/rooms": "/rooms.html", "/library": "/library.html", "/app": "/index.html",
                  # The public landing page is the homepage: "/" and "/landing" both serve it,
                  # and the timer lives at "/app" (its CTA buttons already point there).
                  # The Android shell must therefore remote-load "/app", NOT the site root --
                  # see server.url in mobile/capacitor.config.json before building the APK.
                  "/": "/landing.html", "/landing": "/landing.html",
                  "/about": "/about.html", "/contact": "/contact.html"}
        if clean in pretty:
            self.path = pretty[clean]
        # Serve only known-safe static asset types (see STATIC_OK_EXT). self.path is the
        # file that would actually be sent — pretty routes have already been rewritten to
        # their .html above — so anything that isn't a whitelisted asset (source, the
        # database, its backups, the secret .txt files, the docs) is refused here.
        served = unquote(urlparse(self.path).path)
        low = served.lower()
        if not (low.endswith("/") or low.endswith(STATIC_OK_EXT)):
            self._json(404, {"error": "not found"})
            return True
        # Library files are never static. /api/library/file/<id> is the only route to them,
        # because that is where "is this material meant for this student" is decided — a
        # served path would hand a private grade's material to anyone who knew the name.
        if low.startswith("/media/library"):
            self._json(404, {"error": "not found"})
            return True
        if os.path.basename(served).lower() in ("admin.html", "admin-login.html"):
            self._json(404, {"error": "not found"})
            return True
        return False

    # Every entry point starts with the same scheme check. It sits here rather than in
    # _resolve_static()/api() so a plain-HTTP request is turned away before any routing,
    # auth or database work happens -- and, more to the point, before a session cookie can
    # be read off or written to a connection anyone on the path can read.
    def _guard(self, fn):
        """Run one request, and answer even when it fails.

        api() has always caught its own exceptions, but the static and /admin paths did not,
        and nothing above them does either: BaseHTTPRequestHandler lets anything that isn't a
        timeout propagate, so under Passenger it came out of application() and the visitor got
        Passenger's own 500 page instead of the app's JSON -- with a stack trace's worth of
        detail about the host in some configurations. _resolve_static() reaches the database
        (the /admin route asks whether there is a live admin session), so "this can't fail" was
        never true. Anything already half-written is left alone: a second send_response() on a
        response that has begun would corrupt it, so the guard only speaks when nothing has.
        """
        with _fail_lock:
            _counters["requests"] += 1
        try:
            return fn()
        except Exception as exc:
            record_failure(self.command, self.path, exc)
            if isinstance(exc, sqlite3.Error):
                # Never reuse a connection that just failed at the database layer. "database
                # is locked", "disk I/O error" and friends are exactly the failures that, on a
                # connection kept alive between requests, would otherwise repeat for every
                # request after them -- a site that 500s until someone restarts it. Throwing
                # the connection away means the damage stops at this request.
                _drop_pooled()
            if not getattr(self, "_sent", False):
                try:
                    self._json(500, {"error": "Something went wrong."})
                except Exception:
                    pass
            return None
        finally:
            # The request is over, whether it succeeded or not: this is the one place that
            # knows that, and the only safe place to undo a transaction a handler abandoned.
            release_pooled()

    def do_GET(self):
        return self._guard(self._do_get)

    def _do_get(self):
        if self._require_https() or self._resolve_static():
            return
        return super().do_GET()

    def do_HEAD(self):
        return self._guard(self._do_head)

    def _do_head(self):
        if self._require_https() or self._resolve_static():
            return
        return super().do_HEAD()

    def do_POST(self):
        return self._guard(lambda: None if self._require_https() else self.api())

    def do_PUT(self):
        return self._guard(lambda: None if self._require_https() else self.api())

    def do_PATCH(self):
        return self._guard(lambda: None if self._require_https() else self.api())

    def do_DELETE(self):
        return self._guard(lambda: None if self._require_https() else self.api())

    def api(self):
        p = urlparse(self.path).path
        m = self.command
        # Library uploads are the one thing that legitimately exceeds MAX_BODY — a term's
        # worth of scanned PDF doesn't fit in the budget sized for a settings blob. It gets
        # its own, larger ceiling; everything else keeps the old one.
        cap = LIBRARY_MAX_BYTES if p == "/api/admin/library/upload" else MAX_BODY
        # A header is whatever the client typed: "Content-Length: abc" used to raise ValueError
        # from here, outside the try below, which on the standalone server dropped the
        # connection without a reply at all. Unreadable means "not a length I can trust".
        try:
            declared = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            return self._json(400, {"error": "Bad Content-Length."})
        if declared > cap:
            return self._json(413, {"error": "Request too large."})
        try:
            if p.startswith("/api/admin/"):
                return self.admin_api(p, m)
            if p == "/api/appearance" and m == "GET":
                return self.appearance()
            if p == "/api/auth/otp/request" and m == "POST":
                return self.otp_request()
            if p == "/api/auth/otp/verify" and m == "POST":
                return self.otp_verify()
            if p == "/api/signup" and m == "POST":
                return self.signup()
            if p == "/api/login" and m == "POST":
                return self.login()
            if p == "/api/logout" and m == "POST":
                return self.logout()
            if p == "/api/me" and m == "GET":
                return self.me()
            if p == "/api/stats" and m == "GET":
                return self.get_stats()
            if p == "/api/quotes" and m == "GET":
                # open to guests too: the timer shows quotes whether or not you're signed in
                return self._json(200, {"quotes": quotes_cached()})
            if p == "/api/settings" and m == "PUT":
                return self.save_settings()
            if p == "/api/background" and m == "POST":
                return self.background_upload()
            if p == "/api/tasks" and m == "PUT":
                return self.save_tasks()
            if p == "/api/session-complete" and m == "POST":
                return self.session_complete()
            if p == "/api/profile" and m == "PATCH":
                return self.save_profile()
            if p == "/api/rooms" and m == "POST":
                return self.room_create()
            if p == "/api/rooms" and m == "GET":
                return self.rooms_mine()
            if p == "/api/rooms/public" and m == "GET":
                return self.rooms_public()
            if p == "/api/rooms/current" and m == "GET":
                return self.room_current()
            if p == "/api/rooms/join" and m == "POST":
                return self.room_join()
            if p == "/api/heartbeat" and m == "POST":
                return self.heartbeat()
            if p == "/api/calendar" and m == "GET":
                return self.calendar()
            if p == "/api/log" and m == "POST":
                return self.log_focus()
            if p == "/api/library" and m == "GET":
                return self.library()
            if p.startswith("/api/library/file/") and m == "GET":
                tail = p[len("/api/library/file/"):]
                if tail.isdigit():
                    return self.library_file(int(tail))
                return self._json(404, {"error": "not found"})
            if p == "/api/subjects" and m == "GET":
                return self.subjects_list()
            if p == "/api/subjects" and m == "POST":
                return self.subject_create()
            seg = [x for x in p.split("/") if x]
            if len(seg) == 3 and seg[0] == "api" and seg[1] == "subjects" and seg[2].isdigit() and m == "DELETE":
                return self.subject_delete(int(seg[2]))
            if len(seg) >= 3 and seg[0] == "api" and seg[1] == "rooms" and seg[2].isdigit():
                rid = int(seg[2])
                if len(seg) == 3 and m == "GET":
                    return self.room_get(rid)
                if len(seg) == 3 and m == "DELETE":
                    return self.room_delete(rid)
                if len(seg) == 4 and seg[3] == "leave" and m == "POST":
                    return self.room_leave(rid)
                if len(seg) == 4 and seg[3] == "visibility" and m == "POST":
                    return self.room_visibility(rid)
                if len(seg) == 4 and seg[3] == "description" and m == "POST":
                    return self.room_description(rid)
                if len(seg) == 4 and seg[3] == "kick" and m == "POST":
                    return self.room_kick(rid)
                if len(seg) == 4 and seg[3] == "tasks" and m == "GET":
                    return self.room_tasks_list(rid)
                if len(seg) == 4 and seg[3] == "tasks" and m == "POST":
                    return self.room_task_create(rid)
                if len(seg) == 5 and seg[3] == "tasks" and seg[4].isdigit() and m == "PATCH":
                    return self.room_task_update(rid, int(seg[4]))
                if len(seg) == 5 and seg[3] == "tasks" and seg[4].isdigit() and m == "DELETE":
                    return self.room_task_delete(rid, int(seg[4]))
            return self._json(404, {"error": "not found"})
        except Exception as exc:
            # Same treatment _guard() gives the paths it covers -- this catch is *inside* it,
            # so without repeating the two lines here an API failure would be recorded
            # nowhere and, worse, would leave a database connection that has already failed
            # in the pool for the next request to inherit.
            record_failure(m, p, exc)
            if isinstance(exc, sqlite3.Error):
                _drop_pooled()
            return self._json(500, {"error": "Something went wrong."})

    # -- endpoints --
    # ---- phone verification ----
    def _clean_email(self, raw, current=None):
        """Validate an optional email. Returns (value_or_None, error_or_None).

        Email is optional everywhere: nothing here rejects an empty one, and an account
        without one stores NULL. A `current` value means "leave it alone if the caller didn't
        send the field at all", which is what makes PATCH /api/profile a patch.
        """
        if raw is None:
            return (current, None)
        email = str(raw).strip().lower()
        if not email:
            return (None, None)   # deliberately cleared, or never given
        if len(email) > 254 or "@" not in email or "." not in email.split("@")[-1] \
                or " " in email or email.startswith("@") or email.endswith("@"):
            return (None, "Please enter a valid email address.")
        return (email, None)

    def otp_request(self):
        """Text a fresh 5-digit code to a number. Says nothing about whether it has an account."""
        ip = self._client_ip()
        d = self._read_json()
        phone = norm_phone(d.get("phone"))
        if not phone:
            return self._json(400, {"error": "Enter a valid mobile number."})
        # Three ceilings, because they stop three different things: one number being texted
        # over and over (cooldown + hourly), and one network farming codes for many numbers.
        if not rate_ok("otp-ip:" + ip, OTP_IP_MAX_PER_HOUR, 3600):
            return self._json(429, {"error": "Too many code requests from this network — try again later."},
                              [("Retry-After", "3600")])
        wait = otp_seconds_left(phone)
        if wait > 0:
            return self._json(429, {"error": "A code was just sent — wait a moment before asking for another.",
                                    "retryAfter": wait}, [("Retry-After", str(wait))])
        if not rate_ok("otp-phone:" + phone, OTP_MAX_PER_HOUR, 3600):
            return self._json(429, {"error": "Too many codes requested for this number — try again in an hour."},
                              [("Retry-After", "3600")])
        ok, detail = issue_otp(phone, ip)
        if not ok:
            if detail == "SMS is not configured on the server.":
                return self._json(503, {"error": detail})
            return self._json(502, {"error": "Couldn't send the code — check the number and try again."})
        return self._json(200, {"ok": True, "phone": mask_phone(phone),
                                "expiresIn": OTP_TTL, "resendIn": OTP_RESEND_SECONDS,
                                "length": OTP_LENGTH})

    def otp_verify(self):
        """Check a code. A known number is signed in; a new one gets a ticket to register with.

        Which of the two it is only comes back *after* the code checks out, so this endpoint
        can't be used to ask "is this number registered?" — the answer costs a text and the
        physical phone.
        """
        ip = self._client_ip()
        d = self._read_json()
        phone = norm_phone(d.get("phone"))
        if not phone:
            return self._json(400, {"error": "Enter a valid mobile number."})
        # Per-number and per-network ceilings on top of the per-code attempt counter, so
        # guessing can't be spread across a stream of freshly requested codes.
        if not rate_ok("otpv-ip:" + ip, 30, 600) or not rate_ok("otpv:" + phone, 12, 600):
            return self._json(429, {"error": "Too many attempts — wait a few minutes and try again."},
                              [("Retry-After", "600")])
        ok, why = check_otp(phone, d.get("code"))
        if not ok:
            return self._json(*{
                "none":    (400, {"error": "Ask for a code first."}),
                "used":    (400, {"error": "That code was already used — ask for a new one."}),
                "expired": (400, {"error": "That code has expired — ask for a new one."}),
                "locked":  (429, {"error": "Too many wrong codes — ask for a new one."}),
                "wrong":   (400, {"error": "That code isn't right."}),
            }.get(why, (400, {"error": "That code isn't right."})))
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        conn.close()
        if not row:
            # No account on this number yet: hand back proof of the check so signup can be
            # filled in without the browser ever being trusted about whose number it is.
            return self._json(200, {"ok": True, "registered": False, "phone": phone,
                                    "ticket": issue_phone_ticket(phone),
                                    "ticketExpiresIn": OTP_TICKET_TTL})
        # A verified code is a sign-in. Mark the number verified for accounts that predate
        # the flag, then hand over the ordinary session cookie the rest of the app runs on.
        if not row["phone_verified"]:
            conn = db()
            conn.execute("UPDATE users SET phone_verified=1 WHERE id=?", (row["id"],))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            conn.close()
        token = create_session(row["id"])
        return self._json(200, {"ok": True, "registered": True, "user": public_user(row)},
                          self._set_cookie(token))

    def signup(self):
        """Finish registration for a number that has just been verified.

        The ticket is what makes this safe to accept: without it anyone could POST a phone
        number they don't own. Email and password are both optional — neither one blocks the
        account being created, and an account with no password simply signs in with a code.
        """
        if not rate_ok("signup:" + self._client_ip(), 8, 3600):
            return self._json(429, {"error": "Too many sign-ups from this network — try again later."},
                              [("Retry-After", "3600")])
        d = self._read_json()
        phone = norm_phone(d.get("phone"))
        if not phone:
            return self._json(400, {"error": "Enter a valid mobile number."})
        # Checked, not spent: everything that can be rejected is rejected while the proof of
        # verification is still good, so a typo in the optional email doesn't cost a new text.
        if not check_phone_ticket(d.get("ticket"), phone):
            return self._json(403, {"error": "Verify your phone number again — that step expired."})
        email, err = self._clean_email(d.get("email"))
        if err:
            return self._json(400, {"error": err})
        pw = d.get("password") or ""
        if pw:
            if len(pw) < 6:
                return self._json(400, {"error": "Password must be at least 6 characters."})
            if len(pw) > MAX_PW:
                return self._json(400, {"error": "Password is too long (max %d characters)." % MAX_PW})
        name = (d.get("name") or "").strip()[:60]
        conn = db()
        try:
            if conn.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
                return self._json(409, {"error": "That number already has an account — sign in instead."})
            if email and conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                return self._json(409, {"error": "That email is already registered."})
            # Nothing left that can fail on the caller's account, so the ticket is spent now.
            # The delete is what decides: two requests racing on one ticket, only one lands.
            if not spend_phone_ticket(d.get("ticket"), phone):
                return self._json(403, {"error": "Verify your phone number again — that step expired."})
            h, s = hash_pw(pw) if pw else (None, None)
            # What they're studying, asked for at sign-up because it is what decides which
            # shelf of the library they see. Left empty if they skipped it — the library page
            # asks again rather than the account being unusable without it.
            edu = norm_edu(d.get("education") or d)
            try:
                cur = conn.execute(
                    "INSERT INTO users(email,phone,phone_verified,name,pw_hash,pw_salt,created_at,"
                    "edu_stage,edu_grade,edu_major) VALUES(?,?,1,?,?,?,?,?,?,?)",
                    (email, phone, name, h, s, now_iso(), edu["stage"], edu["grade"], edu["major"]),
                )
            except sqlite3.IntegrityError:
                # The UNIQUE indexes, not the SELECTs above, are what actually guarantee this;
                # someone else claiming the number or the email in between is a 409, not a 500.
                return self._json(409, {"error": "That number already has an account — sign in instead."})
            uid = cur.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        finally:
            conn.close()
        token = create_session(uid)
        return self._json(200, {"ok": True, "user": public_user(row)}, self._set_cookie(token))

    def login(self):
        """Password sign-in, by phone or email.

        Kept beside the code flow rather than replaced by it: every account that existed
        before phone verification has an email and a password and nothing else, and this is
        the door they already know. Accounts created without a password can't use it — they
        get told to use a code rather than a wrong-password error they could never fix.
        """
        if not rate_ok("login:" + self._client_ip(), 15, 300):
            return self._json(429, {"error": "Too many attempts — wait a few minutes and try again."},
                              [("Retry-After", "300")])
        d = self._read_json()
        # One box on the form, either kind of identifier in it.
        ident = str(d.get("identifier") or d.get("phone") or d.get("email") or "").strip()
        pw = d.get("password") or ""
        if len(pw) > MAX_PW:  # reject before the costly PBKDF2 hash; don't reveal which field was wrong
            return self._json(401, {"error": "Wrong email or password."})
        phone = norm_phone(ident)
        conn = db()
        if phone:
            row = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM users WHERE email=?", (ident.lower(),)).fetchone()
        conn.close()
        if row and not row["pw_hash"]:
            return self._json(401, {"error": "This account signs in with a code — ask for one instead."})
        if not row or not verify_pw(pw, row["pw_hash"], row["pw_salt"]):
            return self._json(401, {"error": "Wrong email or password."})
        token = create_session(row["id"])
        return self._json(200, {"ok": True, "user": public_user(row)}, self._set_cookie(token))

    def logout(self):
        tok = self._token()
        if tok:
            conn = db()
            conn.execute("DELETE FROM sessions WHERE token=?", (tok,))
            conn.commit()
            conn.close()
        return self._json(200, {"ok": True}, self._clear_cookie())

    def me(self):
        u = self._user()
        if not u:
            return self._json(200, {"user": None})
        return self._json(200, {
            "user": public_user(u),
            "settings": without_missing_bg(settings_of(u["id"])),
            "tasks": get_tasks(u["id"]),
            "stats": stats_summary(u["id"]),
            "subjects": subjects_for(u["id"]),
        })

    def get_stats(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        return self._json(200, {"stats": stats_summary(u["id"])})

    def save_settings(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        settings = d.get("settings", d)
        if not isinstance(settings, dict):
            return self._json(400, {"error": "Expected a settings object."})
        # An older tab can still be sending its background inline. Move it to a file rather
        # than refusing the write, so a client that hasn't reloaded since the deploy keeps
        # working -- and so the account stops carrying the blob from here on either way.
        err = externalize_bg(settings, settings_of(u["id"]))
        if err:
            return self._json(400, {"error": err})
        blob = json.dumps(settings)
        if len(blob) > MAX_SETTINGS_BYTES:
            return self._json(413, {"error": "Those settings are too large to save."})
        conn = db()
        conn.execute("UPDATE users SET settings=? WHERE id=?", (blob, u["id"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "settings": settings})

    def background_upload(self):
        """Store an uploaded background and hand back its URL.

        The dedicated door, used by the picker in the timer. Uploading through /api/settings
        still works (externalize_bg above catches it), but going through here means the
        573KB of image crosses the wire exactly once instead of riding along with every
        subsequent preference write -- dragging the dim slider used to resend the whole
        picture, because the image was a field inside the object being saved.
        """
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        if not rate_ok("bg:%d" % u["id"], BG_UPLOADS_PER_HOUR, 3600):
            return self._json(429, {"error": "Too many background uploads — try again later."},
                              [("Retry-After", "3600")])
        url, err = store_user_bg(d.get("data") or "")
        if err:
            return self._json(400, {"error": err})
        # Point the account at the new file in the same call, so a client that drops the
        # connection before its follow-up settings write still ends up consistent.
        settings = settings_of(u["id"])
        bg = settings.get("bg")
        old = bg.get("value") if isinstance(bg, dict) else None
        base = bg if isinstance(bg, dict) else {}
        base.update({"type": "image", "value": url, "chosen": True})
        if not base.get("dim"):
            base["dim"] = 40        # an unreadable clock over a bright photo helps nobody
        settings["bg"] = base
        conn = db()
        conn.execute("UPDATE users SET settings=? WHERE id=?", (json.dumps(settings), u["id"]))
        conn.commit()
        conn.close()
        drop_user_bg(old)
        return self._json(200, {"ok": True, "path": url, "bg": base})

    def save_tasks(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        tasks = d.get("tasks", [])
        conn = db()
        conn.execute("DELETE FROM tasks WHERE user_id=?", (u["id"],))
        for t in tasks[:500]:
            conn.execute(
                "INSERT INTO tasks(user_id,text,done,created_at) VALUES(?,?,?,?)",
                (u["id"], str(t.get("text", ""))[:200], 1 if t.get("done") else 0, now_iso()),
            )
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "tasks": get_tasks(u["id"])})

    def session_complete(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        mins = max(0, min(600, int(d.get("minutes") or 0)))
        secs = mins * 60
        topic = (d.get("topic") or "").strip()[:200]
        today = today_str()
        conn = db()
        have = conn.execute(
            "SELECT COALESCE(seconds,0) AS s FROM stat_days WHERE user_id=? AND day=?", (u["id"], today)
        ).fetchone()
        secs = min(secs, max(0, MAX_DAY_SECONDS - (have["s"] if have else 0)))  # a day can't exceed 24h
        mins = secs // 60
        conn.execute(
            "INSERT INTO stat_days(user_id,day,sessions,seconds) VALUES(?,?,1,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET sessions=sessions+1, seconds=seconds+?",
            (u["id"], today, secs, secs),
        )
        conn.execute("UPDATE stat_days SET minutes=seconds/60 WHERE user_id=? AND day=?", (u["id"], today))
        conn.execute(
            "INSERT INTO session_log(user_id,day,minutes,seconds,topic,created_at) VALUES(?,?,?,?,?,?)",
            (u["id"], today, mins, secs, topic, now_iso()),
        )
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "stats": stats_summary(u["id"])})

    def save_profile(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        name = (d.get("name") or u["name"] or "").strip()[:60]
        avatar = (d.get("avatar") or u["avatar"] or "🦊").strip()[:8]
        # Education is patched the same way the rest of the profile is: anything the caller
        # didn't send keeps what the account already had.
        edu = norm_edu(d.get("education") or {}, edu_of(u))
        # Email stays optional here too: sending "" clears it back to NULL, not sending the
        # field at all leaves it alone, and only a non-empty value is format-checked.
        email, err = self._clean_email(d.get("email", None), u["email"])
        if err:
            return self._json(400, {"error": err})
        conn = db()
        try:
            if email and email != (u["email"] or "") and conn.execute(
                    "SELECT 1 FROM users WHERE email=? AND id<>?", (email, u["id"])).fetchone():
                return self._json(409, {"error": "That email is already registered."})
            try:
                conn.execute("UPDATE users SET name=?, avatar=?, email=?, edu_stage=?, edu_grade=?, "
                             "edu_major=? WHERE id=?",
                             (name, avatar, email, edu["stage"], edu["grade"], edu["major"], u["id"]))
            except sqlite3.IntegrityError:
                return self._json(409, {"error": "That email is already registered."})
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
        finally:
            conn.close()
        return self._json(200, {"ok": True, "user": public_user(row)})

    # ---- rooms ----
    def _recent(self, last_seen):
        return (time.time() - (last_seen or 0)) < 90

    def _current_room(self, conn, uid):
        """Return the id of the single room this user belongs to, or None."""
        row = conn.execute(
            "SELECT room_id FROM room_members WHERE user_id=? LIMIT 1", (uid,)
        ).fetchone()
        return row["room_id"] if row else None

    def _members_payload(self, conn, u, room):
        """Build the {room, members[]} view for a room, ranked by today's focus time."""
        rid = room["id"]
        today = today_str()
        # Today's total joins in rather than being fetched per member. It used to be a query
        # per row, so a room of N cost N+1 round trips on a poll every member of that room
        # makes -- the app's hottest read, multiplied by room size. stat_days' PK is
        # (user_id, day), so the join is the same indexed lookup, just done once.
        rows = conn.execute(
            "SELECT u.id,u.name,u.email,u.phone,u.avatar,u.focusing,u.last_seen,mm.role,"
            "COALESCE(sd.seconds,0) AS today_seconds "
            "FROM room_members mm JOIN users u ON u.id=mm.user_id "
            "LEFT JOIN stat_days sd ON sd.user_id=u.id AND sd.day=? "
            "WHERE mm.room_id=?",
            (today, rid),
        ).fetchall()
        me_member = False
        members = []
        for r in rows:
            secs = r["today_seconds"] or 0
            mine = r["id"] == u["id"]
            me_member = me_member or mine
            members.append({
                "id": r["id"], "name": display_name(r),
                "avatar": r["avatar"] or "🦊", "role": r["role"],
                "todaySeconds": secs, "todayMinutes": secs // 60,
                "focusing": bool(r["focusing"]) and self._recent(r["last_seen"]),
                "me": mine,
            })
        members.sort(key=lambda x: -x["todaySeconds"])
        is_owner = room["owner_id"] == u["id"]
        out = {"id": room["id"], "name": room["name"], "visibility": room["visibility"],
               "description": room["description"] or "",
               "isOwner": is_owner, "isMember": me_member}
        # The invite code is the room's key: anyone holding it can walk into a private room.
        # Only the owner is ever told what it is, so a member can't quietly pass it on.
        if is_owner:
            out["code"] = room["code"]
        return {"room": out, "members": members}

    def room_create(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        name = (d.get("name") or "").strip()[:60] or "Study room"
        vis = "public" if d.get("visibility") == "public" else "private"
        desc = (d.get("description") or "").strip()[:ROOM_DESC_MAX]
        code = secrets.token_urlsafe(6)
        conn = db()
        if self._current_room(conn, u["id"]) is not None:
            conn.close()
            return self._json(409, {"error": "You're already in a room — leave it before creating a new one."})
        cur = conn.execute(
            "INSERT INTO rooms(name,owner_id,visibility,code,description,created_at) VALUES(?,?,?,?,?,?)",
            (name, u["id"], vis, code, desc, now_iso()),
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO room_members(room_id,user_id,role,joined_at) VALUES(?,?,'owner',?)",
            (rid, u["id"], now_iso()),
        )
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "room_id": rid, "code": code})

    def rooms_mine(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        rows = conn.execute(
            "SELECT r.id,r.name,r.visibility,r.code,r.owner_id,r.description, "
            "(SELECT COUNT(*) FROM room_members m2 WHERE m2.room_id=r.id) AS members "
            "FROM rooms r JOIN room_members m ON m.room_id=r.id WHERE m.user_id=? "
            "ORDER BY r.created_at DESC",
            (u["id"],),
        ).fetchall()
        conn.close()
        return self._json(200, {"rooms": [
            {"id": r["id"], "name": r["name"], "visibility": r["visibility"],
             "description": r["description"] or "", "members": r["members"],
             "isOwner": r["owner_id"] == u["id"],
             # same rule as _members_payload: the code is the owner's to share
             **({"code": r["code"]} if r["owner_id"] == u["id"] else {})}
            for r in rows]})

    def rooms_public(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        rows = conn.execute(
            "SELECT r.id,r.name,r.owner_id,r.description, COUNT(m.user_id) AS members, "
            "MAX(CASE WHEN m.user_id=? THEN 1 ELSE 0 END) AS joined "
            "FROM rooms r LEFT JOIN room_members m ON m.room_id=r.id "
            "WHERE r.visibility='public' GROUP BY r.id ORDER BY members DESC LIMIT 50",
            (u["id"],),
        ).fetchall()
        conn.close()
        # The description is what tells someone whether this is the room they want, so it
        # travels with the discovery list. The invite code never does — it isn't here at all.
        return self._json(200, {"rooms": [
            {"id": r["id"], "name": r["name"], "description": r["description"] or "",
             "members": r["members"], "joined": bool(r["joined"])}
            for r in rows]})

    def room_get(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
        if not room:
            conn.close()
            return self._json(404, {"error": "Room not found."})
        mem = conn.execute(
            "SELECT role FROM room_members WHERE room_id=? AND user_id=?", (rid, u["id"])
        ).fetchone()
        if not mem and room["visibility"] != "public":
            conn.close()
            return self._json(403, {"error": "This room is private."})
        payload = self._members_payload(conn, u, room)
        conn.close()
        return self._json(200, payload)

    def room_current(self):
        """The single room the signed-in user is in (for the timer's co-focus panel)."""
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        rid = self._current_room(conn, u["id"])
        if rid is None:
            conn.close()
            return self._json(200, {"room": None, "members": []})
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
        if not room:
            conn.close()
            return self._json(200, {"room": None, "members": []})
        payload = self._members_payload(conn, u, room)
        # What the owner has put on this user's plate, carried on the poll the timer already
        # makes, so the timer's task deck costs no extra request.
        rows = conn.execute(
            "SELECT * FROM room_tasks WHERE room_id=? AND user_id=? ORDER BY done, "
            "CASE WHEN due='' THEN 1 ELSE 0 END, due, id", (rid, u["id"])).fetchall()
        names = {u["id"]: display_name(u)}
        payload["tasks"] = [self._task_row(r, names) for r in rows]
        conn.close()
        return self._json(200, payload)

    def room_join(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        conn = db()
        room = None
        if d.get("code"):
            room = conn.execute("SELECT * FROM rooms WHERE code=?", (invite_code(d["code"]),)).fetchone()
        elif d.get("room_id"):
            room = conn.execute("SELECT * FROM rooms WHERE id=?", (int(d["room_id"]),)).fetchone()
            if room and room["visibility"] != "public":
                room = None
        if not room:
            conn.close()
            return self._json(404, {"error": "Room not found — check the invite code."})
        # already in this room? treat join as a no-op so invite links stay idempotent.
        already = conn.execute(
            "SELECT 1 FROM room_members WHERE room_id=? AND user_id=?", (room["id"], u["id"])
        ).fetchone()
        if not already:
            if self._current_room(conn, u["id"]) is not None:
                conn.close()
                return self._json(409, {"error": "You can only be in one room at a time — leave your current room first."})
            members = conn.execute(
                "SELECT COUNT(*) AS n FROM room_members WHERE room_id=?", (room["id"],)
            ).fetchone()["n"]
            if members >= ROOM_MAX:
                conn.close()
                return self._json(409, {"error": "This room is full — it already has %d people." % ROOM_MAX})
            conn.execute(
                "INSERT INTO room_members(room_id,user_id,role,joined_at) VALUES(?,?,'member',?)",
                (room["id"], u["id"], now_iso()),
            )
            conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "room_id": room["id"]})

    def room_leave(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        room = conn.execute("SELECT owner_id FROM rooms WHERE id=?", (rid,)).fetchone()
        if room and room["owner_id"] == u["id"]:
            conn.close()
            return self._json(400, {"error": "Owners can't leave — delete the room instead."})
        conn.execute("DELETE FROM room_members WHERE room_id=? AND user_id=?", (rid, u["id"]))
        conn.execute("DELETE FROM room_tasks WHERE room_id=? AND user_id=?", (rid, u["id"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    def room_delete(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        room = conn.execute("SELECT owner_id FROM rooms WHERE id=?", (rid,)).fetchone()
        if not room or room["owner_id"] != u["id"]:
            conn.close()
            return self._json(403, {"error": "Only the owner can delete this room."})
        conn.execute("DELETE FROM room_tasks WHERE room_id=?", (rid,))
        conn.execute("DELETE FROM room_members WHERE room_id=?", (rid,))
        conn.execute("DELETE FROM rooms WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    def room_visibility(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        vis = "public" if d.get("visibility") == "public" else "private"
        conn = db()
        room = conn.execute("SELECT owner_id FROM rooms WHERE id=?", (rid,)).fetchone()
        if not room or room["owner_id"] != u["id"]:
            conn.close()
            return self._json(403, {"error": "Only the owner can change this."})
        conn.execute("UPDATE rooms SET visibility=? WHERE id=?", (vis, rid))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "visibility": vis})

    # ---- room owner authority ----
    # Everything below is gated the same way `room_delete` already is: the room's owner_id
    # must match the signed-in user, checked on the server for every call. The frontend hides
    # these controls from members, but hiding is never what enforces them.
    def _owner_of(self, conn, rid, uid):
        """The room row if `uid` owns room `rid`, else None."""
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
        return room if room and room["owner_id"] == uid else None

    def _is_member(self, conn, rid, uid):
        return conn.execute(
            "SELECT 1 FROM room_members WHERE room_id=? AND user_id=?", (rid, uid)
        ).fetchone() is not None

    def room_description(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        desc = (d.get("description") or "").strip()[:ROOM_DESC_MAX]
        conn = db()
        if not self._owner_of(conn, rid, u["id"]):
            conn.close()
            return self._json(403, {"error": "Only the owner can change this."})
        conn.execute("UPDATE rooms SET description=? WHERE id=?", (desc, rid))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "description": desc})

    def room_kick(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        try:
            target = int(d.get("user_id") or 0)
        except (TypeError, ValueError):
            target = 0
        conn = db()
        if not self._owner_of(conn, rid, u["id"]):
            conn.close()
            return self._json(403, {"error": "Only the owner can remove people."})
        if target == u["id"]:
            conn.close()
            return self._json(400, {"error": "You can't remove yourself — delete the room instead."})
        if not self._is_member(conn, rid, target):
            conn.close()
            return self._json(404, {"error": "That person isn't in this room."})
        conn.execute("DELETE FROM room_members WHERE room_id=? AND user_id=?", (rid, target))
        # their assignments belong to this room, so they go with the membership
        conn.execute("DELETE FROM room_tasks WHERE room_id=? AND user_id=?", (rid, target))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    def _task_row(self, r, names):
        return {
            "id": r["id"], "text": r["text"], "done": bool(r["done"]),
            "due": r["due"] or "", "suggestMin": r["suggest_min"] or 0,
            "userId": r["user_id"], "assignee": names.get(r["user_id"], "—"),
            "createdAt": r["created_at"], "doneAt": r["done_at"] or "",
        }

    def room_tasks_list(self, rid):
        """Owners see every assignment in the room; members see only their own."""
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        room = conn.execute("SELECT owner_id FROM rooms WHERE id=?", (rid,)).fetchone()
        if not room or not self._is_member(conn, rid, u["id"]):
            conn.close()
            return self._json(404, {"error": "Room not found."})
        is_owner = room["owner_id"] == u["id"]
        names = {r["id"]: display_name(r) for r in conn.execute(
            "SELECT u.id,u.name,u.email,u.phone FROM room_members mm JOIN users u ON u.id=mm.user_id "
            "WHERE mm.room_id=?", (rid,))}
        if is_owner:
            rows = conn.execute(
                "SELECT * FROM room_tasks WHERE room_id=? ORDER BY done, "
                "CASE WHEN due='' THEN 1 ELSE 0 END, due, id", (rid,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM room_tasks WHERE room_id=? AND user_id=? ORDER BY done, "
                "CASE WHEN due='' THEN 1 ELSE 0 END, due, id", (rid, u["id"])).fetchall()
        conn.close()
        return self._json(200, {"tasks": [self._task_row(r, names) for r in rows], "isOwner": is_owner})

    def room_task_create(self, rid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        text = (d.get("text") or "").strip()[:ROOM_TASK_TEXT_MAX]
        if not text:
            return self._json(400, {"error": "Write what the task is."})
        # A date alone, or a date and a time — anything else is stored as "no deadline"
        # rather than rejected, so a browser that formats the field differently still saves.
        due = (d.get("due") or "").strip()[:16]
        if not re.match(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$", due):
            due = ""
        try:
            mins = int(d.get("suggestMin") or 0)
        except (TypeError, ValueError):
            mins = 0
        mins = max(0, min(ROOM_TASK_MIN_MAX, mins))
        try:
            target = int(d.get("user_id") or 0)
        except (TypeError, ValueError):
            target = 0
        conn = db()
        if not self._owner_of(conn, rid, u["id"]):
            conn.close()
            return self._json(403, {"error": "Only the owner can assign tasks."})
        if not self._is_member(conn, rid, target):
            conn.close()
            return self._json(404, {"error": "That person isn't in this room."})
        n = conn.execute("SELECT COUNT(*) AS n FROM room_tasks WHERE room_id=?", (rid,)).fetchone()["n"]
        if n >= ROOM_TASKS_MAX:
            conn.close()
            return self._json(409, {"error": "This room has too many assigned tasks — clear some first."})
        conn.execute(
            "INSERT INTO room_tasks(room_id,user_id,assigned_by,text,due,suggest_min,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (rid, target, u["id"], text, due, mins, now_iso()),
        )
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    def room_task_update(self, rid, tid):
        """Ticking a task off: the assignee does it for their own, the owner for any."""
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        done = 1 if d.get("done") else 0
        conn = db()
        row = conn.execute("SELECT * FROM room_tasks WHERE id=? AND room_id=?", (tid, rid)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "Task not found."})
        room = conn.execute("SELECT owner_id FROM rooms WHERE id=?", (rid,)).fetchone()
        if row["user_id"] != u["id"] and not (room and room["owner_id"] == u["id"]):
            conn.close()
            return self._json(403, {"error": "That isn't your task."})
        conn.execute("UPDATE room_tasks SET done=?, done_at=? WHERE id=?",
                     (done, now_iso() if done else None, tid))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "done": bool(done)})

    def room_task_delete(self, rid, tid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        if not self._owner_of(conn, rid, u["id"]):
            conn.close()
            return self._json(403, {"error": "Only the owner can remove assigned tasks."})
        conn.execute("DELETE FROM room_tasks WHERE id=? AND room_id=?", (tid, rid))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    def heartbeat(self):
        u = self._user()
        if not u:
            return self._json(200, {"ok": False})
        d = self._read_json()
        f = 1 if d.get("focusing") else 0
        now = time.time()
        # Skip the write when nothing anyone can see would change. `u` is the row _user()
        # already loaded, so the comparison is free -- no extra query to decide this.
        #
        # Every one of these used to be a committed write, i.e. one per signed-in user per
        # 30s funnelled through SQLite's single writer. Presence is only ever read through
        # two thresholds (_recent() at 90s, and the admin panel's 300s "online"), so
        # refreshing a timestamp that is already inside the tighter of them changes no
        # answer. A change of focus state always writes immediately.
        fresh = (now - (col(u, "last_seen", 0) or 0)) < HEARTBEAT_MIN_WRITE
        if f == (1 if col(u, "focusing", 0) else 0) and fresh:
            return self._json(200, {"ok": True})
        conn = db()
        conn.execute("UPDATE users SET focusing=?, last_seen=? WHERE id=?", (f, now, u["id"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    def calendar(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        q = parse_qs(urlparse(self.path).query)
        month = (q.get("month", [None])[0]) or today_date().strftime("%Y-%m")
        conn = db()
        days = {}
        # Day totals come from stat_days. session_log holds one row per *flush* -- a pause, a
        # 30s heartbeat, the end of a block -- so counting its rows would report one session as
        # several, and summing its per-row minutes would floor every part-minute away to zero.
        for r in conn.execute(
            "SELECT day,sessions,COALESCE(seconds,0) AS secs FROM stat_days "
            "WHERE user_id=? AND day LIKE ?",
            (u["id"], month + "-%"),
        ):
            days[r["day"]] = {"day": r["day"], "minutes": r["secs"] // 60, "seconds": r["secs"],
                              "sessions": r["sessions"], "topics": []}
        # One entry per subject per day with the total time on it. Grouping here is the point:
        # the log has a row per flush, so a subject picked once still lands in it many times.
        for r in conn.execute(
            "SELECT day, topic, SUM(COALESCE(seconds, minutes*60)) AS secs FROM session_log "
            "WHERE user_id=? AND day LIKE ? AND topic IS NOT NULL AND topic<>'' "
            "GROUP BY day, topic ORDER BY secs DESC",
            (u["id"], month + "-%"),
        ):
            cell = days.setdefault(r["day"], {"day": r["day"], "minutes": 0, "seconds": 0,
                                              "sessions": 0, "topics": []})
            cell["topics"].append({"name": r["topic"], "seconds": r["secs"], "minutes": r["secs"] // 60})
        conn.close()
        return self._json(200, {"month": month, "days": list(days.values())})

    # ---- subjects + focus logging ----
    def subjects_list(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        return self._json(200, {"subjects": subjects_for(u["id"])})

    def subject_create(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        name = (d.get("name") or "").strip()[:40]
        if not name:
            return self._json(400, {"error": "Give the subject a name."})
        color = (d.get("color") or "").strip()[:16] or "#d9a24e"
        conn = db()
        conn.execute(
            "INSERT INTO subjects(user_id,name,color,created_at) VALUES(?,?,?,?)",
            (u["id"], name, color, now_iso()),
        )
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "subjects": subjects_for(u["id"])})

    def subject_delete(self, sid):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        conn.execute("DELETE FROM subjects WHERE id=? AND user_id=?", (sid, u["id"]))
        conn.execute("UPDATE session_log SET subject_id=NULL WHERE subject_id=? AND user_id=?", (sid, u["id"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "subjects": subjects_for(u["id"])})

    def log_focus(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        # prefer exact seconds; fall back to the older minutes field for compatibility
        if d.get("seconds") is not None:
            secs = max(0, min(36000, int(d.get("seconds") or 0)))
        else:
            secs = max(0, min(36000, int(d.get("minutes") or 0) * 60))
        session = 1 if d.get("session") else 0
        sid = d.get("subject_id")
        sid = int(sid) if sid else None
        topic = (d.get("topic") or "").strip()[:200]
        if secs <= 0 and not session:
            return self._json(200, {"ok": True, "stats": stats_summary(u["id"]), "subjects": subjects_for(u["id"])})
        today = today_str()
        conn = db()
        have = conn.execute(
            "SELECT COALESCE(seconds,0) AS s FROM stat_days WHERE user_id=? AND day=?", (u["id"], today)
        ).fetchone()
        secs = min(secs, max(0, MAX_DAY_SECONDS - (have["s"] if have else 0)))  # a day can't exceed 24h
        if secs <= 0 and not session:
            conn.close()
            return self._json(200, {"ok": True, "stats": stats_summary(u["id"]), "subjects": subjects_for(u["id"])})
        conn.execute(
            "INSERT INTO stat_days(user_id,day,sessions,seconds) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET sessions=sessions+?, seconds=seconds+?",
            (u["id"], today, session, secs, session, secs),
        )
        conn.execute("UPDATE stat_days SET minutes=seconds/60 WHERE user_id=? AND day=?", (u["id"], today))
        conn.execute(
            "INSERT INTO session_log(user_id,day,minutes,seconds,topic,subject_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (u["id"], today, secs // 60, secs, topic, sid, now_iso()),
        )
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "stats": stats_summary(u["id"]), "subjects": subjects_for(u["id"])})

    # --------------------------------------------------------------- library ----
    def library(self):
        """The shelf for the signed-in student: only what targets their stage/grade/major."""
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        edu = edu_of(u)
        if not library_enabled():
            return self._json(200, {"enabled": False, "education": edu,
                                    "categories": [], "items": []})
        conn = db()
        cats, items = library_for_user(conn, edu)
        conn.close()
        return self._json(200, {"enabled": True, "education": edu,
                                "categories": cats, "items": items})

    def library_file(self, iid):
        """Send one file: any of them to an admin, only their own shelf's to a student."""
        adm = self._admin()
        u = None if adm else self._user()
        if not adm and not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        row = conn.execute("SELECT * FROM library_items WHERE id=?", (iid,)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "not found"})
        if not adm:
            allowed = False
            if library_enabled():
                where, args = library_match("i", edu_of(u))
                allowed = conn.execute(
                    "SELECT 1 FROM library_items i "
                    "LEFT JOIN library_categories c ON c.id=i.category_id "
                    "WHERE i.id=? AND i.visible=1 AND (i.category_id IS NULL OR c.visible=1) "
                    "AND " + where, [iid] + args).fetchone() is not None
            if not allowed:
                conn.close()
                # The same answer a missing file gets. Whether material exists for some
                # other grade is not something to confirm to someone it isn't meant for.
                return self._json(404, {"error": "not found"})
        # basename() is what keeps this inside the media directory: the stored path was
        # generated by the upload handler, but reading it back through the filesystem is
        # exactly where a traversal would land if one were ever written into the row.
        fname = os.path.basename(row["file_path"] or "")
        path = os.path.join(LIBRARY_DIR, fname)
        if not fname or not os.path.isfile(path):
            conn.close()
            return self._json(404, {"error": "not found"})
        if not adm:
            conn.execute("UPDATE library_items SET downloads=downloads+1 WHERE id=?", (iid,))
            conn.commit()
        conn.close()

        q = parse_qs(urlparse(self.path).query)
        disp = "attachment" if (q.get("dl", [""])[0] or "") in ("1", "true") else "inline"
        mime = (row["mime"] or "application/octet-stream")
        if any(c in mime for c in ("\r", "\n", ";")) and not mime.startswith("text/"):
            mime = "application/octet-stream"
        # Most of these filenames are Persian, so the header carries both forms: a stripped
        # ASCII one for old clients and the RFC 5987 UTF-8 one everything current reads.
        ext = fname.rsplit(".", 1)[-1].lower()
        raw = (row["file_name"] or ("material." + ext))
        ascii_name = re.sub(r"_{2,}", "_", re.sub(r'[^A-Za-z0-9._ -]', "_", raw)).strip(" _")
        # A wholly Persian name reduces to a row of underscores, which is a worse filename
        # than no name at all. Anything with nothing left to read by falls back to something
        # legible; clients that understand filename* never see this field anyway.
        if not re.search(r"[A-Za-z0-9]", ascii_name.rsplit(".", 1)[0]):
            ascii_name = "material-%d.%s" % (row["id"], ext)
        try:
            size = os.path.getsize(path)
            fh = open(path, "rb")
        except OSError:
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", '%s; filename="%s"; filename*=UTF-8\'\'%s'
                         % (disp, ascii_name, quote(raw, safe="")))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        with fh:
            while True:
                chunk = fh.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    # ------------------------------------------------------------ appearance ----
    def appearance(self):
        """Resolved theme + background for the caller. Public: every page needs it on load.

        Signed-in callers get their own preference applied on top; guests and never-configured
        accounts fall through to the admin default for their platform, then to the built-in.
        """
        q = parse_qs(urlparse(self.path).query)
        platform = (q.get("platform", [""])[0] or "").lower()
        if platform not in ("web", "mobile"):
            platform = self._guess_platform()
        out = resolve_appearance(platform, self._user())
        conn = db()
        out["backgrounds"] = [
            bg_payload(r) for r in conn.execute(
                "SELECT * FROM backgrounds WHERE enabled=1 AND platform IN ('both',?) ORDER BY id",
                (platform,),
            )
        ]
        out["themes"] = [theme_payload(r) for r in
                         conn.execute("SELECT * FROM themes WHERE enabled=1 ORDER BY id")]
        conn.close()
        return self._json(200, out)

    def _guess_platform(self):
        """Server-side fallback only — the pages send ?platform= from their own detection.

        The app's existing signal is `window.Capacitor` (the Android shell) plus viewport
        width, both of which only the client can see; this is the coarse UA read used when
        the query string is missing.
        """
        ua = (self.headers.get("User-Agent") or "").lower()
        if any(t in ua for t in ("android", "iphone", "ipad", "ipod", "mobile", "capacitor")):
            return "mobile"
        return "web"

    # ----------------------------------------------------------- admin panel ----
    def admin_api(self, p, m):
        """Every /api/admin/* call lands here. Authentication and CSRF are enforced once,
        up front, so no individual handler can be reached without passing both."""
        seg = [x for x in p.split("/") if x][2:]   # drop "api", "admin"
        if seg == ["login"] and m == "POST":
            return self.admin_login()

        adm = self._admin()
        if not adm:
            # 404, not 401: an unauthenticated caller gets the same answer here as for any
            # path that does not exist, so the admin surface cannot be enumerated by probing.
            return self._json(404, {"error": "not found"})
        if m != "GET":
            # Double-submit CSRF token. The cookie alone is never enough to mutate anything,
            # and a custom header cannot be attached by a cross-origin form or image.
            sent = self.headers.get("X-Admin-CSRF") or ""
            if not sent or not hmac.compare_digest(sent, adm["_csrf"]):
                return self._json(403, {"error": "Invalid request token — reload the panel."})

        if seg == ["logout"] and m == "POST":
            return self.admin_logout()
        if seg == ["me"] and m == "GET":
            return self._json(200, {"admin": {"id": adm["id"], "username": adm["username"],
                                              "created_at": adm["created_at"],
                                              "last_login": adm["last_login"],
                                              "last_ip": adm["last_ip"]},
                                    "csrf": adm["_csrf"]})
        if seg == ["overview"] and m == "GET":
            return self.admin_overview()
        if seg == ["diagnostics"] and m == "GET":
            # Behind the admin session like everything else here: it names the database path
            # and carries tracebacks, neither of which is a visitor's business.
            return self._json(200, worker_diagnostics())
        if seg == ["users"] and m == "GET":
            return self.admin_users()
        if len(seg) == 2 and seg[0] == "users" and seg[1].isdigit():
            if m == "GET":
                return self.admin_user_detail(int(seg[1]))
            if m == "PATCH":
                return self.admin_user_update(int(seg[1]))
            if m == "DELETE":
                return self.admin_user_delete(int(seg[1]))
        if seg == ["themes"] and m == "GET":
            return self.admin_themes()
        if seg == ["themes"] and m == "POST":
            return self.admin_theme_save(None)
        if len(seg) == 2 and seg[0] == "themes" and seg[1].isdigit():
            if m == "PUT":
                return self.admin_theme_save(int(seg[1]))
            if m == "DELETE":
                return self.admin_theme_delete(int(seg[1]))
        if seg == ["backgrounds", "upload"] and m == "POST":
            return self.admin_bg_upload()
        if seg == ["backgrounds"] and m == "GET":
            return self.admin_backgrounds()
        if seg == ["backgrounds"] and m == "POST":
            return self.admin_bg_save(None)
        if len(seg) == 2 and seg[0] == "backgrounds" and seg[1].isdigit():
            if m == "PUT":
                return self.admin_bg_save(int(seg[1]))
            if m == "DELETE":
                return self.admin_bg_delete(int(seg[1]))
        if seg == ["library"] and m == "GET":
            return self.admin_library()
        if seg == ["library", "upload"] and m == "POST":
            return self.admin_library_upload()
        if seg == ["library", "items"] and m == "POST":
            return self.admin_lib_item_save(None)
        if len(seg) == 3 and seg[:2] == ["library", "items"] and seg[2].isdigit():
            if m == "PUT":
                return self.admin_lib_item_save(int(seg[2]))
            if m == "DELETE":
                return self.admin_lib_item_delete(int(seg[2]))
        if seg == ["library", "categories"] and m == "POST":
            return self.admin_lib_cat_save(None)
        if len(seg) == 3 and seg[:2] == ["library", "categories"] and seg[2].isdigit():
            if m == "PUT":
                return self.admin_lib_cat_save(int(seg[2]))
            if m == "DELETE":
                return self.admin_lib_cat_delete(int(seg[2]))
        if seg == ["settings"] and m == "GET":
            return self.admin_settings_get()
        if seg == ["settings"] and m == "PUT":
            return self.admin_settings_put()
        if seg == ["password"] and m == "POST":
            return self.admin_password(adm)
        return self._json(404, {"error": "not found"})

    def admin_login(self):
        ip = self._client_ip()
        # Two limits: one per source address, one per username, so neither a single noisy IP
        # nor a distributed run at one account can brute-force its way through.
        if not rate_ok("adminlogin:" + ip, 5, 900):
            return self._json(429, {"error": "Too many attempts — wait 15 minutes."},
                              [("Retry-After", "900")])
        d = self._read_json()
        username = (d.get("username") or "").strip()
        pw = d.get("password") or ""
        if not username or len(pw) > MAX_PW:
            return self._json(401, {"error": "Wrong username or password."})
        if not rate_ok("adminuser:" + username.lower(), 10, 900):
            return self._json(429, {"error": "Too many attempts — wait 15 minutes."},
                              [("Retry-After", "900")])
        conn = db()
        row = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        conn.close()
        if not row or not verify_pw(pw, row["pw_hash"], row["pw_salt"]):
            # One message for both cases: which half was wrong is not something to disclose.
            return self._json(401, {"error": "Wrong username or password."})
        token, csrf = create_admin_session(row["id"], ip, self.headers.get("User-Agent"))
        conn = db()
        conn.execute("UPDATE admins SET last_login=?, last_ip=? WHERE id=?", (now_iso(), ip, row["id"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "csrf": csrf,
                                "admin": {"id": row["id"], "username": row["username"]}},
                          self._set_admin_cookie(token))

    def admin_logout(self):
        tok = self._admin_token()
        if tok:
            conn = db()
            conn.execute("DELETE FROM admin_sessions WHERE token=?", (tok,))
            conn.commit()
            conn.close()
        return self._json(200, {"ok": True}, self._clear_admin_cookie())

    def admin_password(self, adm):
        d = self._read_json()
        current = d.get("current") or ""
        new = d.get("new") or ""
        if len(new) < 10:
            return self._json(400, {"error": "New password must be at least 10 characters."})
        if len(new) > MAX_PW:
            return self._json(400, {"error": "New password is too long (max %d)." % MAX_PW})
        conn = db()
        row = conn.execute("SELECT * FROM admins WHERE id=?", (adm["id"],)).fetchone()
        if not row or not verify_pw(current, row["pw_hash"], row["pw_salt"]):
            conn.close()
            return self._json(403, {"error": "Current password is wrong."})
        h, s = hash_pw(new)
        conn.execute("UPDATE admins SET pw_hash=?, pw_salt=? WHERE id=?", (h, s, adm["id"]))
        # Every other session for this admin dies with the old password; the one making the
        # change is kept so the panel does not log itself out mid-action.
        conn.execute("DELETE FROM admin_sessions WHERE admin_id=? AND token<>?",
                     (adm["id"], adm["_tok"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    # ---- dashboard ----
    def admin_overview(self):
        now = time.time()
        today = today_str()
        conn = db()
        one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
        total = one("SELECT COUNT(*) FROM users")
        online = one("SELECT COUNT(*) FROM users WHERE last_seen > ?", (now - 300,))
        focusing = one("SELECT COUNT(*) FROM users WHERE focusing=1 AND last_seen > ?", (now - 90,))
        active_today = one("SELECT COUNT(DISTINCT user_id) FROM stat_days WHERE day=? AND sessions>0",
                           (today,))
        week_ago = (today_date() - timedelta(days=7)).isoformat()
        active_week = one("SELECT COUNT(DISTINCT user_id) FROM stat_days WHERE day>=? AND sessions>0",
                          (week_ago,))
        new_week = one("SELECT COUNT(*) FROM users WHERE created_at >= ?",
                       ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),))
        recent = [
            {"id": r["id"], "name": display_name(r), "email": r["email"], "phone": r["phone"],
             "avatar": r["avatar"] or "🦊", "created_at": r["created_at"],
             "last_seen": r["last_seen"] or 0}
            # Named columns, not *: the dashboard shows a name and an avatar, and `SELECT *`
            # dragged eight settings blobs across to do it.
            for r in conn.execute(
                "SELECT id,name,email,phone,avatar,created_at,last_seen "
                "FROM users ORDER BY id DESC LIMIT 8")
        ]
        signups = []
        for i in range(13, -1, -1):
            d = (today_date() - timedelta(days=i)).isoformat()
            n = conn.execute("SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=?", (d,)).fetchone()[0]
            signups.append({"day": d, "count": n})
        totals = one("SELECT COALESCE(SUM(seconds),0) FROM stat_days")
        sess = one("SELECT COALESCE(SUM(sessions),0) FROM stat_days")
        counts = {
            "themes": one("SELECT COUNT(*) FROM themes"),
            "backgrounds": one("SELECT COUNT(*) FROM backgrounds"),
            "rooms": one("SELECT COUNT(*) FROM rooms"),
            "library": one("SELECT COUNT(*) FROM library_items"),
        }
        # How many accounts still haven't said what they study — those students only ever
        # see untargeted material, so it is worth a number on the dashboard.
        no_edu = one("SELECT COUNT(*) FROM users WHERE COALESCE(edu_stage,'')=''")
        conn.close()
        return self._json(200, {
            "users": {"total": total, "online": online, "focusing": focusing,
                      "activeToday": active_today, "activeWeek": active_week,
                      "newWeek": new_week, "noEducation": no_edu},
            "focus": {"totalMinutes": totals // 60, "totalSessions": sess},
            "counts": counts, "recent": recent, "signups": signups,
        })

    # ---- users ----
    def _user_prefs(self, row):
        """Non-sensitive preference summary for a user row. Never touches pw_hash/pw_salt."""
        try:
            s = json.loads(row["settings"] or "{}")
        except ValueError:
            s = {}
        bg = s.get("bg") if isinstance(s, dict) else None
        prefs = s.get("prefs") if isinstance(s, dict) else None
        bg = bg if isinstance(bg, dict) else {}
        prefs = prefs if isinstance(prefs, dict) else {}
        kind = "image" if bg.get("type") == "image" else "preset"
        return {
            "background": {
                "kind": kind,
                # An uploaded background is a data URL of a megabyte or more. The list view
                # only needs to say *that* there is one; the detail view sends the preview.
                "value": (bg.get("value") if kind == "preset" else None),
                "custom": kind == "image",
                "dim": bg.get("dim") or 0, "blur": bg.get("blur") or 0,
                "chosen": user_picked_bg(bg),
            },
            "theme": {"accent": prefs.get("accent") or "amber",
                      "appearance": "glass" if prefs.get("glass") else "classic",
                      "chosen": user_picked_theme(prefs)},
            "language": prefs.get("lang") or "en",
            "clock": "24h" if prefs.get("clock24") else "12h",
            "timerType": prefs.get("timerType") or "timer",
            "fullscreen": bool(prefs.get("fullscreen")),
        }

    def admin_users(self):
        q = parse_qs(urlparse(self.path).query)
        term = (q.get("q", [""])[0] or "").strip().lower()
        sort = (q.get("sort", ["created"])[0] or "created")
        direction = "ASC" if (q.get("dir", ["desc"])[0] or "").lower() == "asc" else "DESC"
        filt = (q.get("filter", ["all"])[0] or "all")
        try:
            limit = max(1, min(200, int(q.get("limit", ["50"])[0])))
            offset = max(0, int(q.get("offset", ["0"])[0]))
        except ValueError:
            limit, offset = 50, 0
        # Whitelist, never interpolation of caller input: `sort` picks a column, it can't be one.
        cols = {"created": "u.created_at", "name": "u.name", "email": "u.email",
                "phone": "u.phone", "id": "u.id", "seen": "u.last_seen", "minutes": "total_seconds"}
        order = cols.get(sort, "u.created_at")

        where, args = [], []
        if term:
            # COALESCE on every column now that email and phone can both legitimately be NULL —
            # a LIKE against NULL is NULL, which would quietly drop those accounts from results.
            # The phone term is normalised too, so searching "+98 912…" finds "0912…".
            where.append("(LOWER(COALESCE(u.email,'')) LIKE ? OR LOWER(COALESCE(u.name,'')) LIKE ? "
                         "OR COALESCE(u.phone,'') LIKE ?)")
            digits = re.sub(r"\D", "", term.translate(_DIGIT_MAP))
            args += ["%" + term + "%", "%" + term + "%",
                     "%" + (norm_phone(term) or digits or "x") + "%"]
        now = time.time()
        if filt == "online":
            where.append("u.last_seen > ?")
            args.append(now - 300)
        elif filt == "focusing":
            where.append("(u.focusing=1 AND u.last_seen > ?)")
            args.append(now - 90)
        elif filt == "new":
            where.append("u.created_at >= ?")
            args.append((datetime.now(timezone.utc) - timedelta(days=7)).isoformat())
        elif filt == "inactive":
            where.append("(u.last_seen IS NULL OR u.last_seen < ?)")
            args.append(now - 7 * 86400)
        elif filt == "noedu":
            where.append("COALESCE(u.edu_stage,'')=''")
        # Narrow to one shelf's worth of students — "everyone in یازدهم ریاضی" is the
        # question an admin has when they are about to publish material for them.
        stage = (q.get("stage", [""])[0] or "")
        if stage in EDU_STAGES:
            where.append("u.edu_stage=?")
            args.append(stage)
        grade = (q.get("grade", [""])[0] or "")
        if grade in SCHOOL_GRADES:
            where.append("u.edu_grade=?")
            args.append(grade)
        major = norm_major_text(q.get("major", [""])[0])
        if major:
            where.append("LOWER(TRIM(COALESCE(u.edu_major,'')))=?")
            args.append(major)
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        conn = db()
        base = ("SELECT u.*, "
                "(SELECT COALESCE(SUM(seconds),0) FROM stat_days s WHERE s.user_id=u.id) AS total_seconds, "
                "(SELECT COALESCE(SUM(sessions),0) FROM stat_days s WHERE s.user_id=u.id) AS total_sessions "
                "FROM users u" + clause)
        total = conn.execute("SELECT COUNT(*) FROM users u" + clause, args).fetchone()[0]
        rows = conn.execute(
            base + " ORDER BY %s %s LIMIT ? OFFSET ?" % (order, direction), args + [limit, offset]
        ).fetchall()
        conn.close()
        users = []
        for r in rows:
            users.append({
                "id": r["id"], "email": r["email"], "phone": r["phone"],
                "phoneVerified": bool(r["phone_verified"]),
                "name": display_name(r),
                "avatar": r["avatar"] or "🦊", "created_at": r["created_at"],
                "last_seen": r["last_seen"] or 0, "focusing": bool(r["focusing"]),
                "totalMinutes": (r["total_seconds"] or 0) // 60,
                "totalSessions": r["total_sessions"] or 0,
                "education": edu_of(r),
                "prefs": self._user_prefs(r),
            })
        return self._json(200, {"users": users, "total": total, "limit": limit, "offset": offset})

    def admin_user_detail(self, uid):
        conn = db()
        row = conn.execute(
            "SELECT u.*, "
            "(SELECT COALESCE(SUM(seconds),0) FROM stat_days s WHERE s.user_id=u.id) AS total_seconds, "
            "(SELECT COALESCE(SUM(sessions),0) FROM stat_days s WHERE s.user_id=u.id) AS total_sessions "
            "FROM users u WHERE u.id=?", (uid,)
        ).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "User not found."})
        subjects = [{"id": r["id"], "name": r["name"], "color": r["color"]}
                    for r in conn.execute("SELECT id,name,color FROM subjects WHERE user_id=? ORDER BY id", (uid,))]
        tasks = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(done),0) AS d FROM tasks WHERE user_id=?",
                             (uid,)).fetchone()
        rooms = [{"id": r["id"], "name": r["name"], "role": r["role"]}
                 for r in conn.execute(
                     "SELECT r.id,r.name,m.role FROM room_members m JOIN rooms r ON r.id=m.room_id "
                     "WHERE m.user_id=?", (uid,))]
        history = [{"day": r["day"], "minutes": (r["seconds"] or 0) // 60, "sessions": r["sessions"]}
                   for r in conn.execute(
                       "SELECT day,sessions,seconds FROM stat_days WHERE user_id=? ORDER BY day DESC LIMIT 14",
                       (uid,))]
        # What this student's shelf actually holds right now — the quickest way to check a
        # targeting rule is doing what it was meant to.
        edu = edu_of(row)
        lib_count = len(library_for_user(conn, edu)[1]) if library_enabled() else 0
        conn.close()
        prefs = self._user_prefs(row)
        # The user's own uploaded background, for the preview tile — sent only on the detail
        # view and only when it is small enough to be worth shipping.
        try:
            s = json.loads(row["settings"] or "{}")
            b = s.get("bg") if isinstance(s, dict) else None
            if isinstance(b, dict) and b.get("type") == "image" and isinstance(b.get("value"), str) \
                    and len(b["value"]) <= 2_000_000:
                prefs["background"]["preview"] = b["value"]
        except ValueError:
            pass
        return self._json(200, {"user": {
            "id": row["id"], "email": row["email"], "phone": row["phone"],
            "phoneVerified": bool(row["phone_verified"]),
            "hasPassword": bool(row["pw_hash"]),
            "name": row["name"] or "", "displayName": display_name(row),
            "avatar": row["avatar"] or "🦊", "created_at": row["created_at"],
            "last_seen": row["last_seen"] or 0, "focusing": bool(row["focusing"]),
            "totalMinutes": (row["total_seconds"] or 0) // 60,
            "totalSessions": row["total_sessions"] or 0,
            "education": edu, "libraryItems": lib_count,
            "stats": stats_summary(uid), "prefs": prefs, "subjects": subjects,
            "tasks": {"total": tasks["n"], "done": tasks["d"]}, "rooms": rooms, "history": history,
        }})

    def admin_user_update(self, uid):
        """Rename an account. Only `name` is editable from here on purpose.

        Phone is the identity an account signs in with and email is unique, so letting the
        panel rewrite either would be a way to take over someone else's login rather than a
        way to fix a typo. The name is display text and nothing authenticates against it.
        """
        d = self._read_json()
        if "name" not in d:
            return self._json(400, {"error": "Nothing to change."})
        # Same cleaning the user's own PATCH /api/profile applies, plus control characters
        # stripped so a name can't smuggle newlines into the panel's tables.
        name = re.sub(r"[\x00-\x1f\x7f]", "", str(d.get("name") or "")).strip()[:60]
        conn = db()
        row = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "User not found."})
        conn.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
        conn.commit()
        fresh = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        # An emptied name is legitimate — display_name() then falls back to the email local
        # part or the last digits of the phone, exactly as for someone who never set one.
        return self._json(200, {"ok": True, "id": uid, "name": name,
                                "displayName": display_name(fresh)})

    def admin_user_delete(self, uid):
        """Delete an account and everything belonging to it.

        Every child table declares ON DELETE CASCADE and db() turns foreign keys on, so this
        one statement also clears sessions (signing them out), tasks, subjects, stats, the
        session log, and their room memberships and assignments.

        One consequence is worth being explicit about: `rooms.owner_id` cascades too, so
        deleting someone who owns a room deletes that room for everyone in it. The counts
        below are gathered first so the panel can say precisely that before it happens.
        """
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "User not found."})
        owned = [dict(r) for r in conn.execute(
            "SELECT r.id, r.name, (SELECT COUNT(*) FROM room_members m WHERE m.room_id=r.id) AS members "
            "FROM rooms r WHERE r.owner_id=?", (uid,))]
        summary = {
            "name": display_name(row),
            "phone": row["phone"] or "",
            "rooms_deleted": owned,
            "sessions_logged": conn.execute(
                "SELECT COUNT(*) AS n FROM session_log WHERE user_id=?", (uid,)).fetchone()["n"],
        }
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "deleted": summary})

    # ---- themes ----
    def admin_themes(self):
        conn = db()
        rows = [theme_payload(r) for r in conn.execute("SELECT * FROM themes ORDER BY id")]
        conn.close()
        cfg = settings_map()
        return self._json(200, {"themes": rows, "default_theme": cfg.get("default_theme") or ""})

    def _clean_token(self, v, limit=80):
        """Sanitise a value that will be written into a CSS variable or a style attribute.

        Anything that could end the declaration, open a new rule, or escape into the
        surrounding markup is rejected outright rather than escaped — there is no legitimate
        colour or gradient that needs it. Parentheses stay allowed, because oklch(), rgba()
        and linear-gradient() are the normal case here; `url()` does not, so a stored value
        can never pull in an off-origin resource.
        """
        v = str(v or "").strip()[:limit]
        if not v:
            return ""
        if any(c in v for c in (";", "{", "}", "<", ">", "\\", '"', "'", "\n", "\r")):
            return ""
        low = v.lower()
        if any(t in low for t in ("url(", "expression(", "@import", "javascript:", "/*")):
            return ""
        if v.count("(") != v.count(")"):
            return ""
        return v

    def _theme_body(self):
        d = self._read_json()
        name = (d.get("name") or "").strip()[:60]
        if not name:
            return None, self._json(400, {"error": "Give the theme a name."})
        raw = d.get("tokens") or {}
        if not isinstance(raw, dict):
            return None, self._json(400, {"error": "Tokens must be an object."})
        allowed = ("accent", "accentBreak", "accentInk", "surface", "surface2", "ink",
                   "muted", "line", "hair", "field", "radius")
        tokens = {}
        for k in allowed:
            if k in raw:
                v = self._clean_token(raw[k])
                if v:
                    tokens[k] = v
        tokens["appearance"] = "glass" if (raw.get("appearance") == "glass") else "classic"
        if not tokens.get("accent"):
            return None, self._json(400, {"error": "A theme needs at least an accent colour."})
        base = GLASS_TOKENS if tokens["appearance"] == "glass" else CLASSIC_TOKENS
        for k, v in base.items():   # fill the gaps so a partial theme still renders completely
            tokens.setdefault(k, v)
        return {"name": name, "tokens": tokens, "enabled": bool(d.get("enabled", True))}, None

    def admin_theme_save(self, tid):
        body, err = self._theme_body()
        if err:
            return err
        ts = now_iso()
        conn = db()
        if tid is None:
            slug = self._unique_slug(conn, "themes", body["name"])
            cur = conn.execute(
                "INSERT INTO themes(name,slug,tokens,is_system,enabled,created_at,updated_at) "
                "VALUES(?,?,?,0,?,?,?)",
                (body["name"], slug, json.dumps(body["tokens"]), 1 if body["enabled"] else 0, ts, ts),
            )
            tid = cur.lastrowid
        else:
            if not conn.execute("SELECT 1 FROM themes WHERE id=?", (tid,)).fetchone():
                conn.close()
                return self._json(404, {"error": "Theme not found."})
            conn.execute("UPDATE themes SET name=?, tokens=?, enabled=?, updated_at=? WHERE id=?",
                         (body["name"], json.dumps(body["tokens"]),
                          1 if body["enabled"] else 0, ts, tid))
        conn.commit()
        row = conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone()
        conn.close()
        return self._json(200, {"ok": True, "theme": theme_payload(row)})

    def admin_theme_delete(self, tid):
        conn = db()
        row = conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "Theme not found."})
        if row["is_system"]:
            conn.close()
            return self._json(400, {"error": "This is a system theme — it can't be deleted."})
        if (settings_map().get("default_theme") or "") == str(tid):
            conn.close()
            return self._json(409, {"error": "This theme is the app default — pick another default first."})
        conn.execute("DELETE FROM themes WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

    # ---- backgrounds ----
    def _unique_slug(self, conn, table, name):
        base = re.sub(r"[^a-z0-9]+", "-", (name or "item").lower()).strip("-")[:40] or "item"
        slug, n = base, 2
        while conn.execute("SELECT 1 FROM %s WHERE slug=?" % table, (slug,)).fetchone():
            slug = "%s-%d" % (base, n)
            n += 1
        return slug

    def admin_backgrounds(self):
        conn = db()
        rows = [bg_payload(r) for r in conn.execute("SELECT * FROM backgrounds ORDER BY id")]
        conn.close()
        cfg = settings_map()
        return self._json(200, {"backgrounds": rows,
                                "web_default_background": cfg.get("web_default_background") or "",
                                "mobile_default_background": cfg.get("mobile_default_background") or ""})

    def admin_bg_save(self, bid):
        d = self._read_json()
        name = (d.get("name") or "").strip()[:60]
        if not name:
            return self._json(400, {"error": "Give the background a name."})
        kind = "image" if d.get("kind") == "image" else "preset"
        value = str(d.get("value") or "").strip()[:600]
        if not value:
            return self._json(400, {"error": "A background needs a gradient or an image."})
        if kind == "preset":
            if not self._clean_token(value, 600):
                return self._json(400, {"error": "That gradient isn't a valid CSS background value."})
        else:
            # Only paths this server produced. A caller-supplied URL would let the panel point
            # the whole app at an off-origin host, which the page CSP would then block anyway.
            if not re.match(r"^/media/backgrounds/[A-Za-z0-9._-]+$", value):
                return self._json(400, {"error": "Upload the image first — external URLs aren't allowed."})
        platform = d.get("platform")
        platform = platform if platform in ("both", "web", "mobile") else "both"
        desc = str(d.get("description") or "").strip()[:200]
        enabled = 1 if d.get("enabled", True) else 0
        ts = now_iso()
        conn = db()
        if bid is None:
            slug = self._unique_slug(conn, "backgrounds", name)
            cur = conn.execute(
                "INSERT INTO backgrounds(name,slug,kind,value,platform,enabled,description,"
                "is_system,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,?,?)",
                (name, slug, kind, value, platform, enabled, desc, ts, ts))
            bid = cur.lastrowid
        else:
            row = conn.execute("SELECT * FROM backgrounds WHERE id=?", (bid,)).fetchone()
            if not row:
                conn.close()
                return self._json(404, {"error": "Background not found."})
            # A seeded gradient's value is what the frontend still falls back to offline, so
            # renaming or retargeting it is fine but repointing it is not.
            if row["is_system"]:
                kind, value = row["kind"], row["value"]
            conn.execute(
                "UPDATE backgrounds SET name=?,kind=?,value=?,platform=?,enabled=?,description=?,"
                "updated_at=? WHERE id=?",
                (name, kind, value, platform, enabled, desc, ts, bid))
        conn.commit()
        row = conn.execute("SELECT * FROM backgrounds WHERE id=?", (bid,)).fetchone()
        conn.close()
        return self._json(200, {"ok": True, "background": bg_payload(row)})

    def admin_bg_delete(self, bid):
        conn = db()
        row = conn.execute("SELECT * FROM backgrounds WHERE id=?", (bid,)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "Background not found."})
        if row["is_system"]:
            conn.close()
            return self._json(400, {"error": "This is a built-in background — it can't be deleted."})
        cfg = settings_map()
        for key, label in (("web_default_background", "web"), ("mobile_default_background", "mobile")):
            if (cfg.get(key) or "") == str(bid):
                conn.close()
                return self._json(409, {"error": "This is the %s default — set another one first." % label})
        conn.execute("DELETE FROM backgrounds WHERE id=?", (bid,))
        conn.commit()
        conn.close()
        if row["kind"] == "image" and (row["value"] or "").startswith("/media/backgrounds/"):
            try:
                os.remove(os.path.join(MEDIA_DIR, os.path.basename(row["value"])))
            except OSError:
                pass   # the row is what matters; a leftover file is harmless
        return self._json(200, {"ok": True})

    def admin_bg_upload(self):
        """Accept a data: URL, verify it really is an image, and write it to disk.

        The app already moves images around as data URLs (that is how a user's own background
        syncs), so this reuses the same JSON pipeline rather than adding a multipart parser.
        What lands in the database is the path — the bytes stay on the filesystem.
        """
        d = self._read_json()
        blob, ext = decode_image(d.get("data") or "")
        if blob is None:
            return self._json(400, {"error": ext})     # `ext` carries the reason on failure
        os.makedirs(MEDIA_DIR, exist_ok=True)
        # Server-generated name: nothing from the request reaches the filesystem path, so a
        # crafted filename has no way to traverse out of the media directory.
        stem = secrets.token_urlsafe(12).replace("-", "_")
        fname = "%s.%s" % (stem, ext)
        with open(os.path.join(MEDIA_DIR, fname), "wb") as fh:
            fh.write(blob)
        # The swatch-sized copy, made in the admin's browser because nothing here can resize
        # an image. Optional: an older panel doesn't send one, and the picker then falls back
        # to the original exactly as it used to.
        thumb = d.get("thumb")
        if isinstance(thumb, str) and thumb.startswith("data:"):
            tblob, text = decode_image(thumb)
            if tblob is not None:
                try:
                    os.makedirs(THUMB_DIR, exist_ok=True)
                    with open(os.path.join(THUMB_DIR, stem + ".jpg"), "wb") as fh:
                        fh.write(tblob)
                    with _thumbs_lock:
                        _thumbs["at"] = 0.0     # make the next read pick it up immediately
                except OSError:
                    traceback.print_exc()       # a missing thumbnail is not worth failing on
        return self._json(200, {"ok": True, "path": "/media/backgrounds/" + fname,
                                "bytes": len(blob)})

    # ---- library ----
    def admin_library(self):
        """Everything on the shelf, plus who is out there to read it.

        The audience breakdown is one grouped count rather than a query per item: the panel
        works out an item's reach from it client-side, so adjusting a targeting dropdown can
        show "42 students" live without a round trip per keystroke.
        """
        conn = db()
        cats = [lib_category_payload(r) for r in conn.execute(
            "SELECT * FROM library_categories ORDER BY sort_order, name")]
        items = [lib_item_payload(r, True) for r in conn.execute(
            "SELECT * FROM library_items ORDER BY id DESC")]
        audience = [{"stage": r["edu_stage"] or "", "grade": r["edu_grade"] or "",
                     "major": norm_major_text(r["edu_major"]), "count": r["n"]}
                    for r in conn.execute(
                        "SELECT edu_stage,edu_grade,edu_major,COUNT(*) AS n FROM users "
                        "GROUP BY edu_stage,edu_grade,edu_major")]
        conn.close()
        return self._json(200, {
            "categories": cats, "items": items, "audience": audience,
            "enabled": library_enabled(),
            "vocab": {"stages": list(EDU_STAGES), "grades": list(SCHOOL_GRADES),
                      "majors": list(SCHOOL_MAJORS), "majorGrades": list(MAJOR_GRADES)},
            "maxBytes": LIBRARY_MAX_BYTES,
        })

    def _lib_target(self, d, default_stage="school"):
        """Who a shelf item or folder is aimed at. '' in a column means 'anyone'.

        Validated against the same key lists a student's own profile is: a targeting value
        that no account could ever hold would make a row invisible for reasons nothing in
        the panel could explain.
        """
        stage = d.get("stage")
        stage = stage if stage in ("all", "school", "uni") else default_stage
        grade = str(d.get("grade") or "").strip()
        major = " ".join(str(d.get("major") or "").split())[:UNI_MAJOR_MAX]
        if stage == "school":
            grade = grade if grade in SCHOOL_GRADES else ""
            major = major.lower() if major.lower() in SCHOOL_MAJORS else ""
        elif stage == "uni":
            grade = ""      # universities have no grade list to pick from
        else:
            grade, major = "", ""   # 'all' spans both stages, where neither column means the same thing
        return stage, grade, major

    def admin_library_upload(self):
        """Take the raw bytes of one file and put them on disk.

        Raw body rather than the data-URL JSON the background uploader uses: a 25 MB PDF
        would be a 33 MB string as base64, and there is no reason to pay that here. The
        CSRF header is still required — the check in admin_api() runs before this does.
        """
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0:
            return self._json(400, {"error": "No file was sent."})
        if n > LIBRARY_MAX_BYTES:
            return self._json(413, {"error": "Files are limited to %d MB."
                                    % (LIBRARY_MAX_BYTES // (1024 * 1024))})
        blob = self.rfile.read(n)
        if not blob:
            return self._json(400, {"error": "That file is empty."})
        # Header values are latin-1, and most of these filenames are Persian, so the client
        # percent-encodes the name and it is decoded here. It is a display label only —
        # nothing from it reaches the filesystem.
        raw_name = unquote(self.headers.get("X-File-Name") or "")
        name = re.sub(r"[\x00-\x1f\x7f]", "", raw_name).strip()[:LIBRARY_NAME_MAX]
        ext, mime = sniff_upload(blob, name)
        if not ext:
            return self._json(400, {"error": "Only PDF, Office documents, images, ePub, "
                                             "zip or plain-text files are accepted."})
        os.makedirs(LIBRARY_DIR, exist_ok=True)
        # Server-generated name, like the background uploader: a crafted filename has no
        # path to traverse with because it never becomes part of one.
        fname = "%s.%s" % (secrets.token_urlsafe(16).replace("-", "_"), ext)
        with open(os.path.join(LIBRARY_DIR, fname), "wb") as fh:
            fh.write(blob)
        return self._json(200, {"ok": True, "path": "/media/library/" + fname,
                                "name": name or ("material." + ext),
                                "size": len(blob), "mime": mime, "ext": ext})

    def _lib_drop_file(self, conn, path):
        """Remove an uploaded file once no row points at it any more.

        The check matters because nothing stops two items from being saved against the same
        upload — deleting one of them must not pull the bytes out from under the other. A
        file left behind is harmless; a file deleted early is a broken download.
        """
        if not (path or "").startswith("/media/library/"):
            return
        if conn.execute("SELECT 1 FROM library_items WHERE file_path=?", (path,)).fetchone():
            return
        try:
            os.remove(os.path.join(LIBRARY_DIR, os.path.basename(path)))
        except OSError:
            pass

    def admin_lib_item_save(self, iid):
        d = self._read_json()
        title = (d.get("title") or "").strip()[:LIBRARY_TITLE_MAX]
        if not title:
            return self._json(400, {"error": "Give this material a title."})
        desc = str(d.get("description") or "").strip()[:LIBRARY_DESC_MAX]
        stage, grade, major = self._lib_target(d)
        visible = 1 if d.get("visible", True) else 0
        cat = str(d.get("categoryId") or "").strip()
        cat = int(cat) if cat.isdigit() and int(cat) > 0 else None
        path = str(d.get("path") or "").strip()
        # Only paths this server wrote. A caller-supplied one would turn the download
        # endpoint into a way to read any file the process can open.
        if path and not re.match(r"^/media/library/[A-Za-z0-9._-]+$", path):
            return self._json(400, {"error": "Upload the file first."})
        fname = re.sub(r"[\x00-\x1f\x7f]", "", str(d.get("fileName") or "")).strip()[:LIBRARY_NAME_MAX]
        ts = now_iso()
        conn = db()
        if cat is not None and not conn.execute(
                "SELECT 1 FROM library_categories WHERE id=?", (cat,)).fetchone():
            conn.close()
            return self._json(400, {"error": "That category doesn't exist."})

        def stat_of(p):
            """Size and type read off the file itself, never taken from the request."""
            base = os.path.basename(p)
            full = os.path.join(LIBRARY_DIR, base)
            try:
                size = os.path.getsize(full)
            except OSError:
                return None, None
            return size, ext_mime(base.rsplit(".", 1)[-1].lower())

        if iid is None:
            if not path:
                conn.close()
                return self._json(400, {"error": "Upload a file first."})
            size, mime = stat_of(path)
            if size is None:
                conn.close()
                return self._json(400, {"error": "That upload is no longer on the server — try again."})
            cur = conn.execute(
                "INSERT INTO library_items(title,description,category_id,stage,grade,major,"
                "file_path,file_name,file_size,mime,visible,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (title, desc, cat, stage, grade, major, path, fname or os.path.basename(path),
                 size, mime, visible, ts, ts))
            iid = cur.lastrowid
        else:
            row = conn.execute("SELECT * FROM library_items WHERE id=?", (iid,)).fetchone()
            if not row:
                conn.close()
                return self._json(404, {"error": "That material isn't here any more."})
            old = row["file_path"]
            if path and path != old:
                size, mime = stat_of(path)
                if size is None:
                    conn.close()
                    return self._json(400, {"error": "That upload is no longer on the server — try again."})
            else:
                path, size, mime = old, row["file_size"], row["mime"]
            conn.execute(
                "UPDATE library_items SET title=?,description=?,category_id=?,stage=?,grade=?,"
                "major=?,file_path=?,file_name=?,file_size=?,mime=?,visible=?,updated_at=? WHERE id=?",
                (title, desc, cat, stage, grade, major, path, fname or row["file_name"],
                 size, mime, visible, ts, iid))
            if old != path:
                conn.commit()   # the row must already point at the new file before the old one goes
                self._lib_drop_file(conn, old)
        conn.commit()
        row = conn.execute("SELECT * FROM library_items WHERE id=?", (iid,)).fetchone()
        conn.close()
        return self._json(200, {"ok": True, "item": lib_item_payload(row, True)})

    def admin_lib_item_delete(self, iid):
        conn = db()
        row = conn.execute("SELECT * FROM library_items WHERE id=?", (iid,)).fetchone()
        if not row:
            conn.close()
            return self._json(404, {"error": "That material isn't here any more."})
        conn.execute("DELETE FROM library_items WHERE id=?", (iid,))
        conn.commit()
        self._lib_drop_file(conn, row["file_path"])
        conn.close()
        return self._json(200, {"ok": True})

    def admin_lib_cat_save(self, cid):
        d = self._read_json()
        name = (d.get("name") or "").strip()[:60]
        if not name:
            return self._json(400, {"error": "Give the category a name."})
        desc = str(d.get("description") or "").strip()[:LIBRARY_DESC_MAX]
        stage, grade, major = self._lib_target(d, default_stage="all")
        visible = 1 if d.get("visible", True) else 0
        try:
            order = max(0, min(999, int(d.get("sort") or 0)))
        except (TypeError, ValueError):
            order = 0
        ts = now_iso()
        conn = db()
        if cid is None:
            slug = self._unique_slug(conn, "library_categories", name)
            cur = conn.execute(
                "INSERT INTO library_categories(name,slug,description,stage,grade,major,visible,"
                "sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (name, slug, desc, stage, grade, major, visible, order, ts, ts))
            cid = cur.lastrowid
        else:
            if not conn.execute("SELECT 1 FROM library_categories WHERE id=?", (cid,)).fetchone():
                conn.close()
                return self._json(404, {"error": "That category isn't here any more."})
            conn.execute(
                "UPDATE library_categories SET name=?,description=?,stage=?,grade=?,major=?,"
                "visible=?,sort_order=?,updated_at=? WHERE id=?",
                (name, desc, stage, grade, major, visible, order, ts, cid))
        conn.commit()
        row = conn.execute("SELECT * FROM library_categories WHERE id=?", (cid,)).fetchone()
        conn.close()
        return self._json(200, {"ok": True, "category": lib_category_payload(row)})

    def admin_lib_cat_delete(self, cid):
        """Delete the folder, keep the material — it lands back in Uncategorized.

        The foreign key is ON DELETE SET NULL, so this never takes uploaded files with it;
        the count goes back in the response so the panel can say what was unfiled.
        """
        conn = db()
        if not conn.execute("SELECT 1 FROM library_categories WHERE id=?", (cid,)).fetchone():
            conn.close()
            return self._json(404, {"error": "That category isn't here any more."})
        n = conn.execute("SELECT COUNT(*) AS n FROM library_items WHERE category_id=?",
                         (cid,)).fetchone()["n"]
        conn.execute("DELETE FROM library_categories WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True, "unfiled": n})

    # ---- global settings ----
    def admin_settings_get(self):
        cfg = settings_map()
        conn = db()
        themes = [theme_payload(r) for r in conn.execute("SELECT * FROM themes WHERE enabled=1 ORDER BY id")]
        bgs = [bg_payload(r) for r in conn.execute("SELECT * FROM backgrounds WHERE enabled=1 ORDER BY id")]
        conn.close()
        return self._json(200, {"settings": {k: cfg.get(k, "") for k in SETTING_KEYS},
                                "themes": themes, "backgrounds": bgs,
                                "resolved": {"web": resolve_appearance("web"),
                                             "mobile": resolve_appearance("mobile")}})

    def admin_settings_put(self):
        d = self._read_json()
        incoming = d.get("settings", d)
        if not isinstance(incoming, dict):
            return self._json(400, {"error": "Expected a settings object."})
        conn = db()
        ts = now_iso()
        for k in SETTING_KEYS:
            if k not in incoming:
                continue
            v = str(incoming[k] if incoming[k] is not None else "").strip()[:100]
            # Every reference is validated against a real row, and every number against its
            # range, before it is stored — a bad id would otherwise silently break the app
            # for every user on the fallback path.
            if k == "default_theme":
                if v and not conn.execute("SELECT 1 FROM themes WHERE id=? AND enabled=1",
                                          (v if v.isdigit() else -1,)).fetchone():
                    conn.close()
                    return self._json(400, {"error": "That theme doesn't exist or is disabled."})
            elif k in ("web_default_background", "mobile_default_background"):
                plat = "mobile" if k.startswith("mobile") else "web"
                if v:
                    row = conn.execute("SELECT platform FROM backgrounds WHERE id=? AND enabled=1",
                                       (v if v.isdigit() else -1,)).fetchone()
                    if not row:
                        conn.close()
                        return self._json(400, {"error": "That background doesn't exist or is disabled."})
                    if row["platform"] not in ("both", plat):
                        conn.close()
                        return self._json(400, {"error": "That background isn't available on %s." % plat})
            elif k in ("default_dim", "default_blur"):
                try:
                    v = str(max(0, min(100, int(v or 0))))
                except ValueError:
                    v = "0"
            elif k == "default_language":
                v = v if v in ("en", "fa") else "en"
            elif k == "library_enabled":
                v = "0" if v in ("0", "false", "off", "no", "") else "1"
            conn.execute(
                "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (k, v, ts))
        conn.commit()
        conn.close()
        cfg = settings_map()
        return self._json(200, {"ok": True, "settings": {k: cfg.get(k, "") for k in SETTING_KEYS},
                                "resolved": {"web": resolve_appearance("web"),
                                             "mobile": resolve_appearance("mobile")}})


def main():
    init_db()
    purge_expired()  # clear anything already expired, then keep it tidy hourly
    threading.Thread(target=cleanup_loop, daemon=True).start()
    print("Study Planet server running:  http://localhost:%d" % PORT)
    if HOST not in ("127.0.0.1", "localhost"):
        print("Listening on:          %s:%d  (reachable from the LAN)" % (HOST, PORT))
    print("Database:              %s" % DB_PATH)
    print("Admin panel:           http://localhost:%d/admin" % PORT)
    if SMSIR_API_KEY and SMSIR_TEMPLATE_ID:
        print("Phone codes:           SMS.ir template %s, parameter {%s}"
              % (SMSIR_TEMPLATE_ID, SMSIR_PARAM))
    else:
        print("  ! Phone codes:       SMS.ir not configured — set SMSIR_API_KEY/SMSIR_TEMPLATE_ID "
              "or fill in smsir_credentials.txt")
    print("Press Ctrl+C to stop.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
