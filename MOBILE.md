# Focus on Android (Capacitor)

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

### Status bar & splash (polish)
```bash
npm install @capacitor/status-bar @capacitor/splash-screen
```
Style them to the app's dark theme (`#16303a`) — configure in `capacitor.config.json` /
Android Studio, or call the plugins on startup.

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
- [ ] Create the app in Play Console → **Data safety** form, content rating, **privacy policy URL** (you collect email + usage)
- [ ] Upload to the **internal testing** track first, then promote to production

> Android-only for now. iOS later needs a Mac + Xcode + Apple Developer Program ($99/yr)
> and usually a bit more native integration to pass App Store review.

---

## What changed in the web app for mobile
- **Timer is now wall-clock anchored** (`syncTimer` in `index.html`) — it no longer drifts
  or freezes when the app is backgrounded; it catches up on resume.
- **Session-end native notification** hook (`Native`) — inert on the web, active in the app.
- **Safe-area insets** (notch / gesture bar) + `viewport-fit=cover` + `theme-color` on all pages.
- Background-image uploads are downscaled and persist to the account (done earlier).
