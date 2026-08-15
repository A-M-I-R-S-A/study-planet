# Study Planet on Android (Capacitor)

This wraps the existing web app in a native Android shell with **Capacitor**. No rewrite —
the same HTML/JS runs inside a WebView, plus native notifications for the session-end alert.

---

## Architecture decision: remote-load vs bundled

There are two ways to ship, and they differ in **how auth works**:

| | Bundled (default here) | Remote-load (recommended once hosted) |
|---|---|---|
| Web files | copied into `mobile/www/` and shipped in the APK | loaded live from your server |
| Origin | `https://localhost` (app) | your domain (same origin as the API) |
| **Cookie auth** | breaks (API is a different origin) → **guest mode only** | **works** (same origin) — no code changes |
| Accounts / rooms / sync | ❌ until you add an API base + token auth | ✅ |
| Offline | ✅ (guest timer) | ❌ |

**Recommendation:** ship **bundled** now to see the timer on a device, then flip to
**remote-load** once `server.py` is hosted over HTTPS. Remote-load keeps the existing
cookie auth and pretty routes working with zero frontend changes, and the Play Store is
fine with it.

To switch to remote-load later, add your URL to `mobile/capacitor.config.json`:
```json
"server": { "androidScheme": "https", "url": "https://focus.yourdomain.com" }
```

---

## Prerequisites
- **Node.js ≥ 22** — Capacitor 8's CLI requires it (Node 18 fails with `EBADENGINE`).
  Android Studio does **not** include Node.
- **Android Studio** + an emulator or a physical device with USB debugging.
- **JDK 17+** (bundled with recent Android Studio).
- **Google Play Console** account ($25 one-time) — only needed to publish.

> **Run the Node/Capacitor steps on the same OS as Android Studio.** If Studio is the
> Windows app (SDK under `%LOCALAPPDATA%\Android\Sdk`), do everything in **Windows
> PowerShell** — `npx cap open android` then launches Studio directly. Running from WSL
> against a Windows Studio install adds needless friction (and WSL's conda Node here is 18).

---

## First build (bundled guest preview)

From the `mobile/` folder:

```bash
cd mobile
npm install @capacitor/core @capacitor/cli @capacitor/android @capacitor/local-notifications @capacitor/status-bar @capacitor/splash-screen @capacitor/app
npm run copy            # copies the web files into mobile/www/
npx cap add android     # generates the native Android project (mobile/android/)
npx cap sync android
npx cap open android    # opens the project in Android Studio
```

Then in Android Studio press **Run** to install on your device/emulator. You'll get the
timer, tasks, background image, and settings (guest mode). Sign-in/rooms need the hosted
backend (see below).

After any change to the web files, re-run:
```bash
npm run sync            # = copy-www + cap sync android
```

---

## Wire up the native pieces

### Notifications (the key mobile feature)
The frontend already calls Capacitor `LocalNotifications` when present (see `Native` in
`index.html`) — it schedules the "time's up" alert at the block's end time so it fires
even if Android suspended the WebView. To activate it:

1. Plugin is installed by the `npm install` above.
2. On **Android 13+**, the `POST_NOTIFICATIONS` runtime permission is required. The app
   requests it on launch (`Native.init()` → `requestPermissions()`); confirm the prompt.
3. Test: start a 1-minute focus timer, background the app, wait — you should get the alert.

### Timer in the notification bar (`FocusService`)
The session runs as a **foreground service**, so it keeps counting after the app is closed or
swiped off the recents list. The notification shows the remaining time and the phase, and carries
**Pause / Resume / End** buttons; the "time's up" alert fires from here too.

- The service never owns the clock. `FocusState` stores wall-clock anchors (`endsAt`, `anchorTs`)
  in SharedPreferences and both sides derive from them, so a suspended WebView or a restarted
  service picks the same session back up with no drift.
- The web app pushes state on every start/pause/reset/phase change (`Bar.push()` in `index.html`)
  and adopts the service's state on every return to the foreground (`Bar.adopt()`) — that's how a
  Pause tapped in the notification shows up on screen.
- Focus time that accrued while the WebView was dead is billed on the way back in, from the
  `ff_anchor` record the page rewrites every second.
- `@capacitor/local-notifications` is left alone but its end-of-block alert is **skipped** when the
  plugin is present, otherwise two alerts fire a second apart.
- Nothing here runs on the plain web — `Capacitor.Plugins.Focus` is undefined there and every call
  is a no-op.

**Battery savers.** Some OEM skins (Xiaomi, Oppo, Samsung) kill foreground services anyway.
Settings offers the "Ignore battery saver" grant for this; on those phones the user may also have
to pin the app in the vendor's own battery screen.

### App lock (`Settings → App lock`)
Optional, off by default. While a focus block runs, opening an app outside the user's allow list
covers it with a full-screen reminder (`BlockOverlay`) offering **Back to Study Planet** or **home**.

- The service polls the foreground app once a second via `UsageStatsManager` and draws the panel as
  a `TYPE_APPLICATION_OVERLAY` window — an Activity can't be used, because Android 10+ blocks
  background activity starts, which is exactly this situation.
- Two **special-access** grants are needed, and neither is a runtime dialog — both open a Settings
  screen: **Usage access** (`PACKAGE_USAGE_STATS`) and **Display over other apps**
  (`SYSTEM_ALERT_WINDOW`). The settings section shows a row with an "Allow" button for whichever
  is missing and re-checks when the app regains focus.
- The launcher, the system UI, the dialer and Study Planet itself are **always** allowed, whatever the
  user picked — otherwise there'd be no way out and no way to call anyone.
- "Keep blocking during breaks" is a separate toggle; by default breaks are unlocked.
- The app picker lists every launchable app with its icon (rasterised natively, handed over as
  `data:` URLs — the CSP already allows `img-src data:`).

> **Play Store:** `QUERY_ALL_PACKAGES` needs a declaration in Play Console (the app-blocking /
> device-security justification). Without it the listing is rejected. If you'd rather avoid the
> declaration, the alternative is an `AccessibilityService` — which has a stricter review of its own.

### Status bar & splash (polish)
```bash
npm install @capacitor/status-bar @capacitor/splash-screen
```
Style them to the app's dark theme (`#16303a`) — configure in `capacitor.config.json` /
Android Studio, or call the plugins on startup.

### Library downloads (`MainActivity`)

A WebView has **no download of its own**. When the page navigates to something that comes
back as an attachment — or to any type the WebView can't render, a PDF included — Android
offers it to the WebView's `DownloadListener`, and if none is set the navigation is dropped
without a word. That is exactly what a missing listener looked like: the library's
**Download** button worked in a browser and did nothing at all in the app.

`MainActivity.wireDownloads()` sets one, and hands the URL to Android's `DownloadManager`,
which brings the progress notification, the retry and the tap-to-open a browser download
has. Two details matter:

- **The cookie is carried over by hand.** `DownloadManager` makes its own request outside
  the WebView, so without `addRequestHeader("Cookie", …)` from `CookieManager` every
  download would save the "Not signed in." JSON instead of the file.
- **The filename comes from `filename*=UTF-8''`.** `URLUtil.guessFileName` reads the plain
  `filename=` beside it, which the server has had to strip to ASCII — so a Persian name
  would arrive as underscores.

Below Android 10 the file goes to the app's own external folder rather than the public
Downloads directory, which keeps a storage-permission prompt out of the middle of a tap.

There is a matching web-side rule in `library.html`: inside the shell there is one WebView
and no tabs, and Capacitor hands a `target="_blank"` URL to the **system browser**, which
carries none of the session's cookies. So the app shows a single **Download** action while
the web keeps both Open and Download.

> This is native code — a page refresh won't pick it up. Rebuild and reinstall the app from
> Android Studio after pulling this change.

### App icon & splash image
Use Capacitor's asset generator (put a 1024×1024 `icon.png` and `splash.png` in
`mobile/assets/`):
```bash
npm install -D @capacitor/assets
npx capacitor-assets generate --android
```

---

## Backend (required for the full app)
The app's accounts/rooms/sync need `server.py` reachable over **HTTPS**:
- Host it behind nginx + HTTPS (Let's Encrypt); launch with
  `SECURE_COOKIES=1 TRUST_PROXY=1 DAY_OFFSET_MIN=<your offset> python server.py`.
- Point the app at it via the remote-load `server.url` above (simplest, keeps cookie auth),
  **or** keep bundled and switch the backend to token auth + CORS (larger change).

---

## Publish to Google Play
- [ ] Set a real `appId` (e.g. `com.yourname.focus`) in `capacitor.config.json` **before** `cap add android`
- [ ] Bump `versionCode` / `versionName` in `mobile/android/app/build.gradle`
- [ ] Target a recent Android API level (Play requirement)
- [ ] Build a signed **AAB** (Build → Generate Signed Bundle) and enable **Play App Signing**
- [ ] Create the app in Play Console → **Data safety** form, content rating, **privacy policy URL**
      (you collect a **phone number** — declare it under *Personal info → Phone number*, used for
      account creation and sign-in — plus usage data, and an **optional** email address)
- [ ] Upload to the **internal testing** track first, then promote to production

> Android-only for now. iOS later needs a Mac + Xcode + Apple Developer Program ($99/yr)
> and usually a bit more native integration to pass App Store review.

---

## What changed in the web app for mobile
- **Timer is now wall-clock anchored** (`syncTimer` in `index.html`) — it no longer drifts
  or freezes when the app is backgrounded; it catches up on resume.
- **Session-end native notification** hook (`Native`) — inert on the web, active in the app.
- **`Bar`** — pushes the session to the notification-bar service and adopts it back on resume.
  App-only; `Bar.on` is false everywhere else.
- **`Lock`** — the App lock settings section and app picker. The whole `#lockSec` block stays
  `hidden` unless the native plugin is there, so the web app looks exactly as it did.
- **Safe-area insets** (notch / gesture bar) + `viewport-fit=cover` + `theme-color` on all pages.
- Background-image uploads are downscaled and persist to the account (done earlier).
