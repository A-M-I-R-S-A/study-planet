# Focus — study timer with accounts, rooms & a study calendar

A Pomodoro study timer (timer, live clock, quotes, tasks, ambient sound,
choosable backgrounds, animated progress, English/Farsi) plus a Python backend
with **user accounts, study rooms, synced settings, a stats dashboard, and a
study calendar**.

## Run it

You need Python 3 (already installed). From this folder:

```bash
python server.py
```

Then open **http://localhost:8000**.

- `/`            → the timer app
- `/login`       → sign up / sign in
- `/dashboard`   → your stats, study calendar & personalized setup
- `/rooms`       → create / join study rooms

Set a different port with `PORT=9000 python server.py`.

## Features

- **Accounts** — email + password (PBKDF2-hashed), session cookies.
- **Synced everywhere** — settings, tasks, and stats live on your account; the
  timer pushes changes up and pulls them down on any device.
- **Study rooms** — create rooms, set them **public** (discoverable) or
  **private** (invite-only), and share an **invite link/code**. Each room shows
  a live focus leaderboard with a "focusing now" indicator.
- **One theme, all pages** — the background/appearance you pick in the timer is
  applied to the dashboard, rooms, and login pages too (`theme.js`).
- **Study calendar** — every finished focus session logs its minutes and the
  subject. The dashboard calendar shows a month at a glance; click any day to
  see exactly what you studied.
- **Timer or stopwatch** — a Pomodoro countdown or a count-up stopwatch.
  Starting either hides the other controls for a distraction-free view, and
  **pausing logs your time**, so a partial session is never lost.
- **Subjects** — create your study subjects on the dashboard; pick one on the
  timer and each subject shows its focus time for the day next to it.

## Files

| File             | Role |
|------------------|------|
| `server.py`      | Backend: static server + JSON API, SQLite, PBKDF2 auth, sessions. No third-party packages. |
| `index.html`     | The timer app (also works standalone/offline as a guest). |
| `login.html`     | Sign-up / sign-in. |
| `dashboard.html` | Stats, 14-day chart, study calendar, personalized setup, profile editor. |
| `rooms.html`     | Rooms: create, discover, join, room detail with leaderboard + invites. |
| `theme.js`       | Shared theme applied to every page. |
| `focus.db`       | SQLite database, created on first run (git-ignored). |

## API summary

Auth: `POST /api/signup` · `POST /api/login` · `POST /api/logout` · `GET /api/me`
· `PATCH /api/profile`
Data: `PUT /api/settings` · `PUT /api/tasks` · `POST /api/log` (records minutes +
subject; `session:0` on pause, `session:1` on completion) · `GET /api/stats` ·
`GET /api/calendar?month=YYYY-MM`
Subjects: `GET /api/subjects` · `POST /api/subjects` · `DELETE /api/subjects/<id>`
Rooms: `POST /api/rooms` · `GET /api/rooms` · `GET /api/rooms/public` ·
`POST /api/rooms/join` · `GET|DELETE /api/rooms/<id>` · `POST /api/rooms/<id>/leave`
· `POST /api/rooms/<id>/visibility` · `POST /api/heartbeat` (presence)

## Notes

- Passwords are stored hashed (PBKDF2-HMAC-SHA256, 200k iterations) — never plain text.
- Invites are share-links/codes (no email is sent).
- Runs on `127.0.0.1` for local use. To expose it publicly you'd put it behind a
  real web server (nginx etc.) with HTTPS.
