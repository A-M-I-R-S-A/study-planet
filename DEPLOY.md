# Deploying Study Planet to study-planet.ir (cPanel + Passenger)

This host runs **cPanel** with **Setup Python App** (Phusion Passenger) and **Terminal**.
The backend is a standard-library `http.server` app, which Passenger can't run directly, so
`passenger_wsgi.py` bridges it. All routing, auth, and the static allow-list stay in
`server.py`, exercised exactly as when you run `python server.py` locally.

DNS for study-planet.ir already points at the host.

---

## 0. Before you start — the security fixes in this release

Two files that used to be downloadable are now blocked in code (`server.py` serves only a
short allow-list of asset types). **Verify this after deploy — step 6 — it is the most
important step.** In addition, the deploy below keeps secrets and the database out of the web
root entirely, so even a misconfigured host can't hand them out.

**Never upload these to the server** (they are also git-ignored):

- `admin_credentials.txt`, `smsir_credentials.txt`, `quotes_api_key.txt` → use env vars instead
- `focus.db`, `focus.db.bak-*` → production gets a fresh database
- `__pycache__/`, `.git/`, `.idea/`, `.claude/`, `mobile/node_modules/`, `mobile/www/`

**Rotate the admin password.** The old one sat in `admin_credentials.txt` in plaintext.
Pick a new one and set it via the env var in step 3 — don't reuse the old value.

---

## 1. Create the Python App (cPanel → Software → Setup Python App → Create)

| Field | Value |
|---|---|
| Python version | 3.9 or newer (any works — the app is pure stdlib) |
| Application root | `study` (a folder in your home dir, **outside** `public_html`) |
| Application URL | `study-planet.ir` (the domain root) |
| Application startup file | `passenger_wsgi.py` |
| Application entry point | `application` |

Click **Create**. cPanel makes a virtualenv and wires the domain to the app. There are **no
pip packages to install** — skip the requirements step.

> **Why "outside public_html" matters:** with the app root separate from the web docroot
> (cPanel's default), Apache can't serve your files directly — every request goes through
> `passenger_wsgi.py` → `server.py`, which enforces the allow-list. Step 6 confirms it.

---

## 2. Upload the app files

Into the **Application root** (`~/study`), via Terminal (`git clone`/`scp`) or cPanel File
Manager, upload exactly:

```
server.py
passenger_wsgi.py
index.html  login.html  dashboard.html  rooms.html  library.html  landing.html
about.html  contact.html
admin.html  admin-login.html
favicon.svg  i18n.js  theme.js  sw.js
```

`sw.js` is the service worker that keeps uploaded backgrounds on the device. It must sit at
the **site root** — a service worker can only control paths at or below its own URL, so
`/sw.js` is what gives it the whole site. It is registered by `theme.js`; if you leave it
out, backgrounds simply re-download each visit and nothing else changes.

That's the whole web app. The `media/` folders are created automatically the first time an
admin uploads a background or library file.

---

## 3. Set environment variables (Setup Python App → your app → Environment variables)

Add each, then **Save**:

| Variable | Value | Why |
|---|---|---|
| `SECURE_COOKIES` | `1` | HTTPS — session cookie gets the `Secure` flag |
| `TRUST_PROXY` | `1` | Read the real client IP from `X-Forwarded-For` (rate limits), and the real scheme from `X-Forwarded-Proto` |
| `FORCE_HTTPS` | `1` | Redirect `http://` to `https://` and send HSTS. **Requires `TRUST_PROXY=1`** — see below |
| `DAY_OFFSET_MIN` | `210` | Iran is UTC+3:30 — day boundary for streaks/calendar |
| `ADMIN_USERNAME` | `Amir` | Seeds the admin on first run |
| `ADMIN_PASSWORD` | *your NEW password* | Rotated — not the old plaintext one |
| `SMSIR_API_KEY` | *from your local `smsir_credentials.txt`* | Phone codes |
| `SMSIR_TEMPLATE_ID` | *from that file* | Phone codes |
| `SMSIR_PARAM` | *from that file* | Phone codes |
| `QUOTES_API_KEY` | *from your local `quotes_api_key.txt`* | Optional — hero quotes |
| `FOCUS_DB` | `/home/USER/study_data/focus.db` | Optional but recommended — keeps the DB out of any web-served path (create the folder first: `mkdir -p ~/study_data`) |

Copy the SMS/quotes values out of your local `.txt` files into these fields; don't upload the
files. Env vars win over the files, and the files won't be present in production anyway.

### Locking the site to HTTPS

A certificate being installed is not the same as HTTPS being *used*. Until you do this, the
site answers on plain `http://` too, and — because `SECURE_COOKIES=1` above marks the session
cookie `Secure` — anyone who lands there **cannot stay signed in**: the browser throws the
cookie away. Two layers, both worth having:

1. **cPanel → Domains → study-planet.ir → Force HTTPS Redirect: on.** Apache answers the
   redirect before the request ever reaches Python. This is the one that matters.
2. **`FORCE_HTTPS=1` + `TRUST_PROXY=1`** (the table above). `server.py` redirects anything
   that still arrives over http — 301 for GET/HEAD, 308 for writes so the body survives — and
   adds `Strict-Transport-Security` to HTTPS responses, which is what stops browsers from
   trying http again for a year. It's the backstop for a host-level setting getting flipped.

**`FORCE_HTTPS` without `TRUST_PROXY` is refused on purpose.** The app only ever speaks plain
HTTP to Passenger, so `X-Forwarded-Proto` is its only view of the real scheme, and
`TRUST_PROXY` is what makes it trust that header. Set one without the other and every request
would look insecure — including the HTTPS ones — so the redirect would point https at itself
forever. The server disables the flag and logs `! FORCE_HTTPS ignored:` instead of doing that.

Mind the one-way door: HSTS is a promise to browsers that lasts a year. Confirm HTTPS works
(step 5) *before* turning `FORCE_HTTPS` on. If the certificate later lapses, visitors who
already have the header get an error page with no "proceed anyway" — renew, don't wait.

---

## 4. Start it

In Setup Python App, click **Restart**. The first start:

- creates the database (fresh, empty),
- seeds the admin from `ADMIN_USERNAME`/`ADMIN_PASSWORD`,
- starts the hourly cleanup thread.

The app's own log (Setup Python App shows the path, usually `~/study/stderr.log`) will print
the same startup lines you see locally.

---

## 5. First smoke test (browser)

- `https://study-planet.ir/` → the timer
- `https://study-planet.ir/landing` → the public landing page
- `https://study-planet.ir/login` → sign-in; request a code and confirm the SMS arrives
- `https://study-planet.ir/admin` → sign in with the new admin credentials

If pages load but the SMS never comes, re-check the three `SMSIR_*` values and restart.

Then confirm the HTTPS lock from step 3 is actually on:

```bash
curl -sI http://study-planet.ir/ | head -2      # want: 301, Location: https://study-planet.ir/
curl -sI https://study-planet.ir/ | grep -i strict-transport   # want: max-age=31536000
```

A `200` on the first line means neither layer is redirecting: re-check the cPanel toggle, and
look for `! FORCE_HTTPS ignored:` in `stderr.log` (that means `TRUST_PROXY` is unset).

---

## 6. Verify the leaks are closed (do NOT skip)

From your own machine or the host Terminal, every one of these must print **404**:

```bash
for p in admin_credentials.txt smsir_credentials.txt quotes_api_key.txt \
         focus.db focus.db.bak-preotp server.py README.md \
         media/library/anything.pdf admin.html; do
  printf '%s -> ' "$p"
  curl -s -o /dev/null -w '%{http_code}\n' "https://study-planet.ir/$p"
done
```

Expected: `404` on every line. If any line returns `200`, Apache is serving the app directory
directly (the app root is inside the web docroot). Fix it by recreating the app with the root
**outside** `public_html`, or — as a stopgap — drop this `.htaccess` in the served directory:

```apache
<FilesMatch "\.(py|pyc|db|txt|md|bak)$">
  Require all denied
</FilesMatch>
RedirectMatch 404 ^/(media/library|focus\.db)
```

Because secrets live in env vars and the DB is under `~/study_data` (step 3), a `200` here is
still not catastrophic — but it must be fixed before you consider the launch done.

---

## 7. After launch

- **Change the admin password** from the panel's Admin Account screen too, so it isn't only
  in the env var. There is no role column on `users`, so no normal account can become admin.
- **Back up** `~/study_data/focus.db` **and** `~/study/media/` together — the database only
  stores file *paths*, so media must travel with it.
- **Updating the app:** upload the changed files, then click **Restart** in Setup Python App.
  Passenger also restarts if you `touch ~/study/tmp/restart.txt`.
- **Logs:** Setup Python App → your app → the log path, or `tail -f ~/study/stderr.log`.

---

## Notes on the mobile app

The site root (`/`) serves the **landing page**; the timer app lives at `/app`. `landing.html`
links out to the web app (its `LINKS.web`, already `/app`) and the Android APK (edit the
`LINKS` object at the top of its script).

The Capacitor shell remote-loads `server.url` from `mobile/capacitor.config.json`, which is
already **`https://study-planet.ir/app`** — the timer route, **not** the site root, which is
now the landing page. Keep it on `https://`: only the debug overlay at
`mobile/android/app/src/debug/AndroidManifest.xml` sets `usesCleartextTraffic`, so a
**release** APK pointed at an `http://` URL loads nothing at all on Android 9+.

That overlay is why the old dev-LAN-IP builds worked over plain http. If a phone is still
loading the app over http, it is running one of those debug builds — the fix is installing
the current APK, not a config change. `server.url` is baked in at build time, so any edit to
it means a rebuild.
