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
import os, json, time, base64, hmac, hashlib, secrets, sqlite3
from datetime import datetime, timezone, date, timedelta
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "focus.db")
PORT = int(os.environ.get("PORT", "8000"))
PBKDF_ITER = 200_000
SESSION_DAYS = 30


# ---------------------------------------------------------------- database ----
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = db()
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
          topic      TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        """
    )
    for col, ddl in (("focusing", "INTEGER DEFAULT 0"), ("last_seen", "REAL DEFAULT 0")):
        if not any(r["name"] == col for r in conn.execute("PRAGMA table_info(users)")):
            conn.execute("ALTER TABLE users ADD COLUMN %s %s" % (col, ddl))
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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


def compute_streak(by):
    streak = 0
    d = date.today()
    if by.get(d.isoformat(), {}).get("sessions", 0) == 0:
        d = d - timedelta(days=1)  # today still pending -> count from yesterday
    while by.get(d.isoformat(), {}).get("sessions", 0) > 0:
        streak += 1
        d -= timedelta(days=1)
    return streak


def stats_summary(uid):
    conn = db()
    rows = conn.execute(
        "SELECT day,sessions,minutes FROM stat_days WHERE user_id=? ORDER BY day", (uid,)
    ).fetchall()
    conn.close()
    by = {r["day"]: {"sessions": r["sessions"], "minutes": r["minutes"]} for r in rows}
    today = date.today().isoformat()
    history = []
    for i in range(13, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        cell = by.get(d, {})
        history.append(
            {"day": d, "minutes": cell.get("minutes", 0), "sessions": cell.get("sessions", 0)}
        )
    return {
        "today": by.get(today, {"sessions": 0, "minutes": 0}),
        "totalSessions": sum(r["sessions"] for r in rows),
        "totalMinutes": sum(r["minutes"] for r in rows),
        "streak": compute_streak(by),
        "bestMinutes": max((r["minutes"] for r in rows), default=0),
        "activeDays": len([r for r in rows if r["sessions"] > 0]),
        "history": history,
    }


# ---------------------------------------------------------------- handler ----
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.command, self.path))

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

    def _set_cookie(self, token):
        return [("Set-Cookie",
                 "sid=%s; HttpOnly; SameSite=Lax; Path=/; Max-Age=%d" % (token, SESSION_DAYS * 86400))]

    def _clear_cookie(self):
        return [("Set-Cookie", "sid=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")]

    # -- routing --
    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith("/api/"):
            return self.api()
        clean = p.rstrip("/") or "/"
        pretty = {"/login": "/login.html", "/dashboard": "/dashboard.html",
                  "/rooms": "/rooms.html", "/app": "/index.html"}
        if clean in pretty:
            self.path = pretty[clean]
        if self.path.endswith((".py", ".db")):
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
            if p == "/api/rooms/join" and m == "POST":
                return self.room_join()
            if p == "/api/heartbeat" and m == "POST":
                return self.heartbeat()
            if p == "/api/calendar" and m == "GET":
                return self.calendar()
            seg = [x for x in p.split("/") if x]
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
        except Exception as e:
            return self._json(500, {"error": str(e)})

    # -- endpoints --
    def signup(self):
        d = self._read_json()
        email = (d.get("email") or "").strip().lower()
        pw = d.get("password") or ""
        name = (d.get("name") or "").strip() or (email.split("@")[0] if "@" in email else "")
        if "@" not in email or "." not in email.split("@")[-1]:
            return self._json(400, {"error": "Please enter a valid email address."})
        if len(pw) < 6:
            return self._json(400, {"error": "Password must be at least 6 characters."})
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
        d = self._read_json()
        email = (d.get("email") or "").strip().lower()
        pw = d.get("password") or ""
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
        topic = (d.get("topic") or "").strip()[:200]
        today = date.today().isoformat()
        conn = db()
        conn.execute(
            "INSERT INTO stat_days(user_id,day,sessions,minutes) VALUES(?,?,1,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET sessions=sessions+1, minutes=minutes+?",
            (u["id"], today, mins, mins),
        )
        conn.execute(
            "INSERT INTO session_log(user_id,day,minutes,topic,created_at) VALUES(?,?,?,?,?)",
            (u["id"], today, mins, topic, now_iso()),
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

    def room_create(self):
        u = self._user()
        if not u:
            return self._json(401, {"error": "Not signed in."})
        d = self._read_json()
        name = (d.get("name") or "").strip()[:60] or "Study room"
        vis = "public" if d.get("visibility") == "public" else "private"
        code = secrets.token_urlsafe(6)
        conn = db()
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
        today = date.today().isoformat()
        rows = conn.execute(
            "SELECT u.id,u.name,u.email,u.avatar,u.focusing,u.last_seen,mm.role "
            "FROM room_members mm JOIN users u ON u.id=mm.user_id WHERE mm.room_id=?",
            (rid,),
        ).fetchall()
        members = []
        for r in rows:
            td = conn.execute(
                "SELECT minutes FROM stat_days WHERE user_id=? AND day=?", (r["id"], today)
            ).fetchone()
            members.append({
                "id": r["id"], "name": r["name"] or r["email"].split("@")[0],
                "avatar": r["avatar"] or "🦊", "role": r["role"],
                "todayMinutes": (td["minutes"] if td else 0),
                "focusing": bool(r["focusing"]) and self._recent(r["last_seen"]),
                "me": r["id"] == u["id"],
            })
        members.sort(key=lambda x: -x["todayMinutes"])
        conn.close()
        return self._json(200, {
            "room": {"id": room["id"], "name": room["name"], "visibility": room["visibility"],
                     "code": room["code"], "isOwner": room["owner_id"] == u["id"], "isMember": bool(mem)},
            "members": members})

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
        conn.execute(
            "INSERT OR IGNORE INTO room_members(room_id,user_id,role,joined_at) VALUES(?,?,'member',?)",
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
        month = (q.get("month", [None])[0]) or date.today().strftime("%Y-%m")
        conn = db()
        rows = conn.execute(
            "SELECT day,minutes,topic FROM session_log WHERE user_id=? AND day LIKE ? ORDER BY created_at",
            (u["id"], month + "-%"),
        ).fetchall()
        days = {}
        for r in rows:
            cell = days.setdefault(r["day"], {"day": r["day"], "minutes": 0, "sessions": 0, "topics": []})
            cell["minutes"] += r["minutes"]
            cell["sessions"] += 1
            if r["topic"]:
                cell["topics"].append(r["topic"])
        conn.close()
        return self._json(200, {"month": month, "days": list(days.values())})


def main():
    init_db()
    print("Focus server running:  http://localhost:%d" % PORT)
    print("Database:              %s" % DB_PATH)
    print("Press Ctrl+C to stop.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
