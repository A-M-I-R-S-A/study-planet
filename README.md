# Study Planet — study timer with accounts, rooms & a study calendar

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
- `/landing`     → the public landing page ("Study Planet")
- `/login`       → sign up / sign in
- `/dashboard`   → your stats, study calendar & personalized setup
- `/rooms`       → create / join study rooms

Set a different port with `PORT=9000 python server.py`.

## Features

- **Accounts** — your mobile number is the account. Signing in means typing the
  number and the 5-digit code texted to it (SMS.ir); the same screen turns into
  registration when the number is new. **Email is optional** — give one or don't,
  nothing in the app needs it. A password is optional too: set one and
  `POST /api/login` works by phone or email, skip it and the code is the only way
  in. Passwords are PBKDF2-hashed; sessions are cookies, as before.
- **Synced everywhere** — settings, tasks, and stats live on your account; the
  timer pushes changes up and pulls them down on any device.
- **Study rooms** — create rooms, set them **public** (discoverable) or
  **private** (invite-only), and share an **invite link/code**. Each room shows
  a live focus leaderboard with a "focusing now" indicator.
- **Room owners run the room** — write a description, remove members, and assign
  work to anyone in the room with an optional deadline and a suggested length.
  The invite link is the owner's alone; nobody else is even told the code.
  Assigned work lands in the assignee's timer task panel with a **Let's do it**
  button that sets the timer to the suggested length.
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
- **Library** — sign-up asks what you study: school (دبستان through دوازدهم,
  plus a رشته — تجربی / ریاضی / فنی — from دهم up) or university with your own
  field typed in. `/library` then shows only the material the admin published
  for that grade and major, in the categories the admin arranged. You can change
  what you study any time from the library page itself.

## Files

| File             | Role |
|------------------|------|
| `server.py`      | Backend: static server + JSON API, SQLite, PBKDF2 auth, sessions. No third-party packages. |
| `index.html`     | The timer app (also works standalone/offline as a guest). |
| `login.html`     | Sign-up / sign-in. |
| `dashboard.html` | Stats, 14-day chart, study calendar, personalized setup, profile editor. |
| `rooms.html`     | Rooms: create, discover, join, room detail with leaderboard, owner controls + invites. |
| `library.html`   | The student's shelf: material published for their grade and major, plus an editor for changing what they study. |
| `landing.html`   | Public landing page — the pitch plus the two links out (web app, Android APK). Self-contained: no `theme.js`/`i18n.js`, so it can also be hosted on its own. Edit the `LINKS` object at the top of its script to set the two URLs. |
| `theme.js`       | Shared theme applied to every page. |
| `focus.db`       | SQLite database, created on first run (git-ignored). |

## API summary

Auth: `POST /api/auth/otp/request` `{phone}` · `POST /api/auth/otp/verify`
`{phone,code}` (known number → signed in; new number → `{ticket}`) ·
`POST /api/signup` `{phone,ticket,name?,education?,email?,password?}` ·
`POST /api/login` `{phone|email,password}` · `POST /api/logout` · `GET /api/me`
· `PATCH /api/profile` (send `email:""` to remove an email)
Data: `PUT /api/settings` · `PUT /api/tasks` · `POST /api/log` (records `seconds`
— or legacy `minutes` — plus subject; `session:0` on pause, `session:1` on
completion) · `GET /api/stats` · `GET /api/calendar?month=YYYY-MM`
Subjects: `GET /api/subjects` · `POST /api/subjects` · `DELETE /api/subjects/<id>`
Rooms: `POST /api/rooms` · `GET /api/rooms` · `GET /api/rooms/public` ·
`GET /api/rooms/current` (your room, live co-focus roster + your assigned tasks) ·
`POST /api/rooms/join` ·
`GET|DELETE /api/rooms/<id>` · `POST /api/rooms/<id>/leave` ·
`POST /api/rooms/<id>/visibility` · `POST /api/heartbeat` (presence)
Room owner: `POST /api/rooms/<id>/description` · `POST /api/rooms/<id>/kick` `{user_id}` ·
`GET|POST /api/rooms/<id>/tasks` `{user_id,text,due?,suggestMin?}` ·
`PATCH|DELETE /api/rooms/<id>/tasks/<taskId>`
Appearance: `GET /api/appearance?platform=web|mobile` (resolved theme + background)
Library: `GET /api/library` (this student's shelf: categories + items) ·
`GET /api/library/file/<id>` (the file itself, `?dl=1` to download rather than open —
re-checks the targeting on every request; admins may fetch any of them)
Admin: `POST /api/admin/login` · `POST /api/admin/logout` · `GET /api/admin/me` ·
`GET /api/admin/overview` · `GET /api/admin/users` · `GET /api/admin/users/<id>` ·
`GET|POST /api/admin/themes` · `PUT|DELETE /api/admin/themes/<id>` ·
`GET|POST /api/admin/backgrounds` · `PUT|DELETE /api/admin/backgrounds/<id>` ·
`POST /api/admin/backgrounds/upload` · `GET|PUT /api/admin/settings` ·
`POST /api/admin/password`
Admin library: `GET /api/admin/library` (items, categories, and a grouped count of
students to work reach out from) · `POST /api/admin/library/upload` (raw file bytes,
name in `X-File-Name`) · `POST /api/admin/library/items` ·
`PUT|DELETE /api/admin/library/items/<id>` · `POST /api/admin/library/categories` ·
`PUT|DELETE /api/admin/library/categories/<id>`

## Room owners

Whoever creates a room owns it. The owner's panel on `/rooms?room=<id>` adds four things
members don't see:

| Control | What it does |
|---|---|
| Room description | Up to 400 characters under the room title — everyone in the room reads it |
| Remove | Takes a member out of the room, along with the tasks they were assigned |
| Assign work | A task for anyone in the room, with an optional deadline and a suggested length |
| Invite link | Shown **only** to the owner |

**Assigned work is not the timer's task list.** `PUT /api/tasks` replaces the personal
checklist wholesale from the browser's own storage, so an assignment kept there would be
deleted by the assignee's next sync. Assignments live in their own `room_tasks` table,
which is also what lets them carry a deadline and a suggested time. Members see only what
was assigned to them and can tick it off; the owner sees the whole room's list, ordered by
deadline with overdue items first.

**Assigned work shows up on the timer.** The timer's Tasks panel lists what you've been
given under **Assigned to you**, above your own list, with its deadline (overdue marked)
and suggested length. Ticking one there reports straight back to the room, so the owner
sees the progress. They arrive on the `/api/rooms/current` poll the timer already makes
every 30 seconds, so the panel costs no extra request.

Each one has a **Let's do it** button:

| The task | What the button does |
|---|---|
| Came with a suggested time | Sets the timer to it and **waits** — add more with `+`, then press start |
| Came with no suggested time | Starts the timer straight away |

Setting the timer writes the focus length itself (`cfg.focusMin`), exactly as if you had
dialled the `+`/`−` stepper to that number — which is what lets you raise it afterwards, and
does mean the suggestion becomes your focus length until you change it again. Suggestions
above 90 minutes clamp to 90, the longest a block can be. "Let's do it" won't interrupt a
session already running; pause or finish first.

**Only the owner has the code.** The invite code used to be sent to every member of a room
and simply hidden in the page. Now the server omits it from `GET /api/rooms/<id>` and
`GET /api/rooms` for anyone but the owner, so a member can't read it out of the response
and pass it on. Every owner action is authorised server-side against `rooms.owner_id` —
the hidden buttons are a convenience, never the control.

**Invite links survive sign-in.** Opening `/rooms?join=<code>` while signed out sends you
to `/login?next=/rooms?join=<code>` and completes the join once you're in; before, the code
was dropped at that redirect and the link silently did nothing. `next` is honoured only for
same-site paths (one leading `/`), so it can't be turned into an open redirect. A join that
fails now says why — full room, already in another room, bad code — instead of dropping you
on the room list. Pasting the whole invite **link** into the code box works too.

## Admin panel

Open **http://localhost:8000/admin**. It has its own login, separate from user accounts:
there is no role column on `users`, so no ordinary account can ever be promoted into it.

**First run.** The initial admin is seeded from `ADMIN_USERNAME`/`ADMIN_PASSWORD` if they
are set, otherwise from `admin_credentials.txt` next to `server.py` (git-ignored, same
pattern as `quotes_api_key.txt`). The password is PBKDF2-hashed into the `admins` table on
that first start and the file is never read again — change the password from the panel's
**Admin Account** screen, then delete the file.

| Section | What it does |
|---|---|
| Dashboard | Total / online / focusing / active users, 14-day sign-up chart, newest accounts |
| Users | Search, filter, sort, and open any user's profile, stats and preferences |
| Themes | Create, edit, preview and delete themes; pick the app default |
| Backgrounds | Add gradients, upload images, set target platform, enable/disable |
| Library | Upload study material, aim it at a stage/grade/major, arrange it in categories, publish or hide |
| App Settings | Default theme, **separate web and mobile backgrounds**, dim/blur, language |
| Admin Account | Change password, review session policy |

**Appearance priority.** Every page resolves the same three steps, server-side:

```text
user's own preference  →  admin default for that platform  →  built-in fallback
```

A global default therefore reaches everyone who never chose for themselves and **never
overwrites someone who did**. "Chose" means an explicit pick (`chosen`/`themeChosen`, set
the moment a swatch, image, accent or appearance is tapped); accounts predating those flags
are read by content instead, so an uploaded image or any non-default preset still counts.

**Web vs mobile.** `web_default_background` and `mobile_default_background` are independent,
and a background can be marked web-only, mobile-only or both. Platform detection reuses what
the app already had — the Capacitor shell on Android, and the 640px breakpoint the pages'
own CSS switches on — rather than introducing a second notion of "mobile".

Themes are rows of design tokens written into the CSS variables every page already reads
(`--accent`, `--surface`, `--ink`, `--muted`, `--line`, …), so a theme change needs no
stylesheet edit. Uploaded backgrounds are written to `media/backgrounds/` and only their
path is stored in the database.

### The library

Every piece of material is aimed at three things — **who** (school / university /
everyone), **which grade**, and **which major** — and an empty grade or major means
*any*. One upload can therefore serve a single class, a whole major across grades, or the
entire school, without a row per combination. The editor shows how many students match
**as you change the dropdowns**, so a mistargeted upload is visible before it is saved.

Nothing reaches a student until you switch it on. There are three independent switches, and
the outermost one wins:

| Switch | Effect |
|---|---|
| **Library open to students** | Closes the whole shelf at once, leaving every item's own setting untouched |
| **Category visible** | Hides the category *and everything filed under it* — build a term behind it, then publish in one move |
| **Item visible** | Hides that one piece of material |

Categories are yours to arrange: name, description, display order, and their own audience
note. Deleting one never deletes material — its items move to **Uncategorized**.

Accepted uploads are PDF, Word/PowerPoint/Excel, ePub, zip, plain text and images, up to
25 MB, and the type is decided by the file's **actual bytes** rather than its name or the
type the browser declares. Files are written to `media/library/` and are **never served as
static files**: `/api/library/file/<id>` is the only route to them, and it re-checks that
the material targets the caller on every request. Someone it isn't meant for gets the same
404 a missing file gets — whether material exists for another grade isn't disclosed.

If a file ever goes missing from `media/library/` while its row survives — a database
restored without its media folder, a copy between machines, a stray cleanup — the item is
**hidden from students** rather than left as a card that 404s when tapped, and the admin's
list flags it **⚠ file missing** with a one-tap way to re-upload. Back up `media/` alongside
`focus.db`: the database only stores paths.

**On the Android app**, downloads go through Android's `DownloadManager` — a WebView has no
download of its own, so `MainActivity` registers the `DownloadListener` that makes the
button work and carries the session cookie over to it (see MOBILE.md). The app shows a
single **Download** action, because a WebView can't render a PDF and `target="_blank"`
there would hand the URL to the system browser, which isn't signed in.

Majors start at دهم, matching the real system, so the major picker doesn't appear for
lower grades and material aimed at نهم reaches every ninth-grader. University fields are
free text, matched ignoring case and extra spacing; leave a category's field empty to
reach every university student. The **Users** table gains a *Studying* column and a grade
filter, and each user's detail says how many items are on their shelf right now — the
quickest way to confirm a targeting rule does what you meant.

## Notes

- Passwords are stored hashed (PBKDF2-HMAC-SHA256, 200k iterations) — never plain text.
  Admin passwords use the same scheme, and the panel never loads a hash or a salt.
- **Admin session security** — its own `asid` cookie (HttpOnly, `SameSite=Strict`,
  `Secure` under `SECURE_COOKIES=1`), an 8-hour absolute cap and a 60-minute inactivity
  cutoff (`ADMIN_SESSION_HOURS` / `ADMIN_IDLE_MINUTES`), both enforced server-side on
  every request. Mutating admin calls additionally require a per-session CSRF token in
  an `X-Admin-CSRF` header. Admin sign-in is rate-limited per IP *and* per username.
  Unauthenticated `/api/admin/*` calls return **404**, not 401, so the admin surface
  can't be enumerated; `admin.html` is never served as a static file.
- **Phone codes** — the SMS.ir key lives only on the server (`SMSIR_API_KEY` /
  `SMSIR_TEMPLATE_ID` / `SMSIR_PARAM`, or `smsir_credentials.txt`, git-ignored like
  the other secrets); the browser calls `/api/auth/otp/*` here and never api.sms.ir,
  which the pages' `connect-src 'self'` CSP enforces anyway. Codes are 5 digits,
  valid for 5 minutes, single-use, stored salted-hashed, and killed after 5 wrong
  guesses. A number can be texted once every 90 seconds and 5 times an hour; one
  network can ask for 20 an hour and make 30 verify attempts per 10 minutes.
  Requesting a code never says whether the number has an account — that only comes
  back after the code checks out, i.e. to whoever is holding the phone.
  Set `OTP_ECHO=1` in development to print codes to the server console *instead of*
  texting them (the API call is skipped entirely, so no credit is spent).
- Invites are share-links/codes (no email is sent).
- Runs on `127.0.0.1` for local use. To expose it publicly you'd put it behind a
  real web server (nginx etc.) with HTTPS. When you do, start it with
  `SECURE_COOKIES=1` so the session cookie carries the `Secure` flag, plus
  `FORCE_HTTPS=1` and `TRUST_PROXY=1` so plain-HTTP requests are redirected
  (301 for GET/HEAD, 308 for writes) and HTTPS responses carry HSTS. Both are off
  by default — local runs have no TLS — and `FORCE_HTTPS` refuses to act without
  `TRUST_PROXY`, since `X-Forwarded-Proto` is the only thing that tells the two
  schemes apart from in here.
- Security headers (CSP, `X-Frame-Options`, `X-Content-Type-Options`,
  `Referrer-Policy`) are sent on every response; request bodies are capped at 8 MB
  and passwords at 128 chars; dotfiles/`.git`/`__pycache__` and directory listings
  are never served. Login, sign-up and every code request/attempt are rate-limited
  per IP (set `TRUST_PROXY=1` behind a proxy so the real client IP is used).
- **Days & time zone** — streaks, the calendar and per-day stats are bucketed on
  UTC by default, so behaviour doesn't depend on where the server runs. Set
  `DAY_OFFSET_MIN` to your users' UTC offset in minutes to move the day boundary
  (e.g. `DAY_OFFSET_MIN=210` for Iran, `60` for CET, `-480` for US Pacific).
  Logged focus time is capped at 24 h per day as a sanity guard.
