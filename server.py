#!/usr/bin/env python3
"""
Focus — backend server (Python standard library only, no pip installs).

Run:   python server.py         (defaults to http://localhost:8000)
       PORT=9000 python server.py

Serves the static frontend (index.html, login.html, dashboard.html) and a small
JSON API backed by SQLite (focus.db, created automatically next to this file).

Endpoints
  POST /api/signup            {email,password,name?}      -> sets session cookie
  POST /api/login             {email,password}            -> sets session cookie
  POST /api/logout                                        -> clears session
  GET  /api/me                                            -> {user, settings, tasks, stats}
  GET  /api/stats                                         -> stats summary
  PUT  /api/settings          {settings:{...}}            -> save personalized settings
  PUT  /api/tasks             {tasks:[{text,done}...]}    -> replace task list
  POST /api/session-complete  {minutes}                   -> record a finished focus session
  PATCH /api/profile          {name?, avatar?}            -> update profile
"""
import os, json, time, base64, hmac, hashlib, secrets, sqlite3, traceback, threading
from datetime import datetime, timezone, date, timedelta
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, urlencode

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "focus.db")
PORT = int(os.environ.get("PORT", "8000"))
# Bind address. Defaults to loopback so the server is not exposed by accident; set
# HOST=0.0.0.0 to reach it from other devices on the LAN (e.g. the Android app in dev).
HOST = os.environ.get("HOST", "127.0.0.1")
PBKDF_ITER = 200_000
SESSION_DAYS = 30
ROOM_MAX = 10  # max members per room; a user may be in only one room at a time
MAX_BODY = 8 * 1024 * 1024   # cap request bodies (bytes): stops memory-exhaustion reads,
                             # still roomy for background-image data URLs synced via /api/settings
MAX_PW = 128                 # cap password length so PBKDF2 hashing cost stays bounded
# Set SECURE_COOKIES=1 when serving over HTTPS so the session cookie gets the Secure flag.
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "").lower() in ("1", "true", "yes", "on")
# "Study day" boundary. Days (streaks, calendar, per-day stats) are bucketed on UTC shifted
# by DAY_OFFSET_MIN minutes, so behaviour is the same wherever the server runs. 0 = UTC;
# e.g. 210 for Iran (UTC+3:30), 60 for CET, -480 for US Pacific. Set it to your users' zone.
DAY_OFFSET_MIN = int(os.environ.get("DAY_OFFSET_MIN", "0"))
MAX_DAY_SECONDS = 24 * 3600   # per-user daily ceiling on logged focus time (anti-inflation sanity cap)
STREAK_MIN_SECONDS = 45 * 60  # a day has to reach this much focus time to count toward the streak

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
_quotes = {"at": 0.0, "items": []}
_quotes_lock = threading.Lock()


def fetch_quotes():
    """One quote per category. Returns [] on failure -- callers fall back to the cache."""
    import urllib.request
    out, seen = [], set()
    for cat in QUOTES_CATEGORIES:
        req = urllib.request.Request(
            QUOTES_URL + "?" + urlencode({"categories": cat}),
            headers={"X-Api-Key": QUOTES_API_KEY},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
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
    """Pool of quotes, refreshed at most every QUOTES_TTL. Never raises."""
    now = time.time()
    with _quotes_lock:
        fresh = (now - _quotes["at"]) < QUOTES_TTL and _quotes["items"]
        if fresh or not QUOTES_API_KEY:
            return _quotes["items"]
        got = fetch_quotes()
        if got:
            _quotes["items"] = got
            _quotes["at"] = now
        else:
            # keep serving the stale pool, but retry sooner than a full TTL
            _quotes["at"] = now - QUOTES_TTL + 300
        return _quotes["items"]

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


# ---------------------------------------------------------------- database ----
def db():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # wait, don't fail, if another writer holds the lock
    return conn


def init_db():
    conn = db()
    conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer (and vice versa)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          email      TEXT UNIQUE NOT NULL,
          name       TEXT,
          avatar     TEXT DEFAULT '🦊',
          pw_hash    TEXT NOT NULL,
          pw_salt    TEXT NOT NULL,
          settings   TEXT DEFAULT '{}',
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
        """
    )
    for col, ddl in (("focusing", "INTEGER DEFAULT 0"), ("last_seen", "REAL DEFAULT 0")):
        if not any(r["name"] == col for r in conn.execute("PRAGMA table_info(users)")):
            conn.execute("ALTER TABLE users ADD COLUMN %s %s" % (col, ddl))
    if not any(r["name"] == "subject_id" for r in conn.execute("PRAGMA table_info(session_log)")):
        conn.execute("ALTER TABLE session_log ADD COLUMN subject_id INTEGER")
    # second-level precision: add `seconds` and backfill from the older minute counts
    for tbl in ("stat_days", "session_log"):
        if not any(r["name"] == "seconds" for r in conn.execute("PRAGMA table_info(%s)" % tbl)):
            conn.execute("ALTER TABLE %s ADD COLUMN seconds INTEGER DEFAULT 0" % tbl)
            conn.execute("UPDATE %s SET seconds=minutes*60 WHERE seconds=0 AND minutes>0" % tbl)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today_date():
    """Current 'study day' as a date — UTC shifted by DAY_OFFSET_MIN (0 = UTC)."""
    return (datetime.now(timezone.utc) + timedelta(minutes=DAY_OFFSET_MIN)).date()


def today_str():
    return today_date().isoformat()


# ------------------------------------------------- rate limiting + upkeep ----
# Set TRUST_PROXY=1 only when behind a reverse proxy you control, so the client
# IP is read from X-Forwarded-For instead of the (proxy's) socket address.
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes", "on")
_rl_lock = threading.Lock()
_rl_hits = {}  # key -> [timestamps]; trimmed on access and hourly by purge_expired()


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


def purge_expired():
    """Delete expired sessions and drop stale rate-limit entries. At startup + hourly."""
    try:
        conn = db()
        conn.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        conn.commit()
        conn.close()
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


def user_from_token(token):
    if not token:
        return None
    conn = db()
    row = conn.execute(
        "SELECT s.expires AS _exp, u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,),
    ).fetchone()
    conn.close()
    if not row or row["_exp"] < time.time():
        return None
    return row


# ------------------------------------------------------------- serializers ----
def public_user(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "avatar": row["avatar"] or "🦊",
        "created_at": row["created_at"],
    }


def get_tasks(uid):
    conn = db()
    rows = conn.execute(
        "SELECT id,text,done FROM tasks WHERE user_id=? ORDER BY id", (uid,)
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "text": r["text"], "done": bool(r["done"])} for r in rows]


def subjects_for(uid):
    conn = db()
    today = today_str()
    rows = conn.execute("SELECT id,name,color FROM subjects WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    out = []
    for r in rows:
        tm = conn.execute(
            "SELECT COALESCE(SUM(seconds),0) AS s FROM session_log WHERE user_id=? AND day=? AND subject_id=?",
            (uid, today, r["id"]),
        ).fetchone()
        out.append({"id": r["id"], "name": r["name"], "color": r["color"],
                    "todayMinutes": tm["s"] // 60, "todaySeconds": tm["s"]})
    conn.close()
    return out


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
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.command, self.path))

    def version_string(self):
        return "Focus"  # don't advertise the Python/stdlib version in the Server header

    def end_headers(self):
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        # Without this the pages carry only Last-Modified, so clients (notably the Android
        # WebView) invent a heuristic freshness window and serve a stale copy for hours --
        # deployed changes silently never arrive. "no-cache" still allows conditional
        # requests, so unchanged files come back as a cheap 304 rather than a full re-download.
        # It also keeps per-user HTML (dashboard, rooms) out of shared caches.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

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

    def _client_ip(self):
        if TRUST_PROXY:
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "?"

    def _set_cookie(self, token):
        sec = "; Secure" if SECURE_COOKIES else ""
        return [("Set-Cookie",
                 "sid=%s; HttpOnly; SameSite=Lax; Path=/%s; Max-Age=%d" % (token, sec, SESSION_DAYS * 86400))]

    def _clear_cookie(self):
        sec = "; Secure" if SECURE_COOKIES else ""
        return [("Set-Cookie", "sid=; HttpOnly; SameSite=Lax; Path=/%s; Max-Age=0" % sec)]

    # -- routing --
    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith("/api/"):
            return self.api()
        # Never serve dotfiles/dot-directories (.git, .gitignore, .env, …) or bytecode caches.
        # Decode first so a percent-encoded dot (%2e) can't slip past the check.
        dp = unquote(p)
        if any(seg.startswith(".") or seg == "__pycache__" for seg in dp.split("/") if seg):
            return self._json(404, {"error": "not found"})
        clean = p.rstrip("/") or "/"
        pretty = {"/login": "/login.html", "/dashboard": "/dashboard.html",
                  "/rooms": "/rooms.html", "/app": "/index.html"}
        if clean in pretty:
            self.path = pretty[clean]
        if self.path.endswith((".py", ".pyc", ".db")):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        return self.api()

    def do_PUT(self):
        return self.api()

    def do_PATCH(self):
        return self.api()

    def do_DELETE(self):
        return self.api()

    def api(self):
        p = urlparse(self.path).path
        m = self.command
        if int(self.headers.get("Content-Length", 0) or 0) > MAX_BODY:
            return self._json(413, {"error": "Request too large."})
        try:
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
            return self._json(404, {"error": "not found"})
        except Exception:
            traceback.print_exc()  # log the detail server-side, don't leak it to the client
            return self._json(500, {"error": "Something went wrong."})

    # -- endpoints --
    def signup(self):
        if not rate_ok("signup:" + self._client_ip(), 8, 3600):
            return self._json(429, {"error": "Too many sign-ups from this network — try again later."},
                              [("Retry-After", "3600")])
        d = self._read_json()
        email = (d.get("email") or "").strip().lower()
        pw = d.get("password") or ""
        name = (d.get("name") or "").strip() or (email.split("@")[0] if "@" in email else "")
        if "@" not in email or "." not in email.split("@")[-1]:
            return self._json(400, {"error": "Please enter a valid email address."})
        if len(pw) < 6:
            return self._json(400, {"error": "Password must be at least 6 characters."})
        if len(pw) > MAX_PW:
            return self._json(400, {"error": "Password is too long (max %d characters)." % MAX_PW})
        conn = db()
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            conn.close()
            return self._json(409, {"error": "That email is already registered."})
        h, s = hash_pw(pw)
        cur = conn.execute(
            "INSERT INTO users(email,name,pw_hash,pw_salt,created_at) VALUES(?,?,?,?,?)",
            (email, name, h, s, now_iso()),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
        token = create_session(uid)
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        return self._json(200, {"ok": True, "user": public_user(row)}, self._set_cookie(token))

    def login(self):
        if not rate_ok("login:" + self._client_ip(), 15, 300):
            return self._json(429, {"error": "Too many attempts — wait a few minutes and try again."},
                              [("Retry-After", "300")])
        d = self._read_json()
        email = (d.get("email") or "").strip().lower()
        pw = d.get("password") or ""
        if len(pw) > MAX_PW:  # reject before the costly PBKDF2 hash; don't reveal which field was wrong
            return self._json(401, {"error": "Wrong email or password."})
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
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
            "settings": json.loads(u["settings"] or "{}"),
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
        conn = db()
        conn.execute("UPDATE users SET settings=? WHERE id=?", (json.dumps(settings), u["id"]))
        conn.commit()
        conn.close()
        return self._json(200, {"ok": True})

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
        conn = db()
        conn.execute("UPDATE users SET name=?, avatar=? WHERE id=?", (name, avatar, u["id"]))
        row = conn.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.commit()
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
        rows = conn.execute(
            "SELECT u.id,u.name,u.email,u.avatar,u.focusing,u.last_seen,mm.role "
            "FROM room_members mm JOIN users u ON u.id=mm.user_id WHERE mm.room_id=?",
            (rid,),
        ).fetchall()
        me_member = False
        members = []
        for r in rows:
            td = conn.execute(
                "SELECT seconds FROM stat_days WHERE user_id=? AND day=?", (r["id"], today)
            ).fetchone()
            secs = (td["seconds"] if td and td["seconds"] else 0)
            mine = r["id"] == u["id"]
            me_member = me_member or mine
            members.append({
                "id": r["id"], "name": r["name"] or r["email"].split("@")[0],
                "avatar": r["avatar"] or "🦊", "role": r["role"],
                "todaySeconds": secs, "todayMinutes": secs // 60,
                "focusing": bool(r["focusing"]) and self._recent(r["last_seen"]),
                "me": mine,
            })
        members.sort(key=lambda x: -x["todaySeconds"])
        return {
            "room": {"id": room["id"], "name": room["name"], "visibility": room["visibility"],
                     "code": room["code"], "isOwner": room["owner_id"] == u["id"], "isMember": me_member},
            "members": members}

    def room_create(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        name = (d.get("name") or "").strip()[:60] or "Study room"
        vis = "public" if d.get("visibility") == "public" else "private"
        code = secrets.token_urlsafe(6)
        conn = db()
        if self._current_room(conn, u["id"]) is not None:
            conn.close()
            return self._json(409, {"error": "You're already in a room — leave it before creating a new one."})
        cur = conn.execute(
            "INSERT INTO rooms(name,owner_id,visibility,code,created_at) VALUES(?,?,?,?,?)",
            (name, u["id"], vis, code, now_iso()),
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
            "SELECT r.id,r.name,r.visibility,r.code,r.owner_id, "
            "(SELECT COUNT(*) FROM room_members m2 WHERE m2.room_id=r.id) AS members "
            "FROM rooms r JOIN room_members m ON m.room_id=r.id WHERE m.user_id=? "
            "ORDER BY r.created_at DESC",
            (u["id"],),
        ).fetchall()
        conn.close()
        return self._json(200, {"rooms": [
            {"id": r["id"], "name": r["name"], "visibility": r["visibility"],
             "code": r["code"], "members": r["members"], "isOwner": r["owner_id"] == u["id"]}
            for r in rows]})

    def rooms_public(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        conn = db()
        rows = conn.execute(
            "SELECT r.id,r.name,r.owner_id, COUNT(m.user_id) AS members, "
            "MAX(CASE WHEN m.user_id=? THEN 1 ELSE 0 END) AS joined "
            "FROM rooms r LEFT JOIN room_members m ON m.room_id=r.id "
            "WHERE r.visibility='public' GROUP BY r.id ORDER BY members DESC LIMIT 50",
            (u["id"],),
        ).fetchall()
        conn.close()
        return self._json(200, {"rooms": [
            {"id": r["id"], "name": r["name"], "members": r["members"], "joined": bool(r["joined"])}
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
            room = conn.execute("SELECT * FROM rooms WHERE code=?", (str(d["code"]).strip(),)).fetchone()
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

    def heartbeat(self):
        u = self._user()
        if not u:
            return self._json(200, {"ok": False})
        d = self._read_json()
        f = 1 if d.get("focusing") else 0
        conn = db()
        conn.execute("UPDATE users SET focusing=?, last_seen=? WHERE id=?", (f, time.time(), u["id"]))
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


def main():
    init_db()
    purge_expired()  # clear anything already expired, then keep it tidy hourly
    threading.Thread(target=cleanup_loop, daemon=True).start()
    print("Focus server running:  http://localhost:%d" % PORT)
    if HOST not in ("127.0.0.1", "localhost"):
        print("Listening on:          %s:%d  (reachable from the LAN)" % (HOST, PORT))
    print("Database:              %s" % DB_PATH)
    print("Press Ctrl+C to stop.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
