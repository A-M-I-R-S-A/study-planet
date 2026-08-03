# Focus — study timer with accounts

A Pomodoro study timer (timer, live clock, quotes, tasks, ambient sound,
choosable backgrounds, animated progress, English/Farsi) with a small
Python backend that adds **user accounts, synced settings, and a stats
dashboard**.

## Run it

You need Python 3 (already installed). From this folder:

```bash
python server.py
```

Then open **http://localhost:8000** in your browser.

- `http://localhost:8000/`          → the timer app
- `http://localhost:8000/login`     → sign up / sign in
- `http://localhost:8000/dashboard` → your stats & personalized setup

Set a different port with `PORT=9000 python server.py`.

## How it fits together

| File             | Role |
|------------------|------|
| `server.py`      | Backend: static file server + JSON API, SQLite storage, PBKDF2 password hashing, session cookies. No third-party packages. |
| `index.html`     | The timer app. Works standalone (guest, saves to the browser); when served by `server.py` and signed in, it syncs settings/tasks and records finished focus sessions to your account. |
| `login.html`     | Email + password sign-up / sign-in. |
| `dashboard.html` | The user page: streak, total focus time, sessions, a 14-day chart, your personalized setup, and a profile editor. |
| `focus.db`       | SQLite database, created automatically on first run (git-ignored). |

## Notes

- Passwords are stored hashed (PBKDF2-HMAC-SHA256, 200k iterations) — never in plain text.
- Opening `index.html` directly from disk still works as a guest (no server, saves locally).
- This runs on `127.0.0.1` for local use. To expose it on your network or the
  internet you'd put it behind a real web server (e.g. nginx) and enable HTTPS.
