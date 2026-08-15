/* Shared theme: applies the user's chosen background + language/direction to any page.
   Reads the same localStorage the timer app writes (ff_bg, ff_prefs), then refreshes
   from the signed-in account so a theme change in one place shows up everywhere.

   Appearance now resolves in three steps, the same order the server applies in
   /api/appearance:  the user's own pick  ->  the admin default for this platform  ->
   the built-in fallback below. A global default therefore reaches everyone who never
   chose for themselves, and never overwrites someone who did. */
(function () {
  "use strict";
  var BGS = {
    midnight: "linear-gradient(180deg,#1f2838,#0d1420)",
    indigo: "linear-gradient(180deg,#232a4a,#0d1024)",
  };
  // The accent the user picked on the timer page, so buttons match on every other page too.
  // Only the focus tone is used here -- nothing outside the timer has a break state.
  var ACCENTS = {
    amber: "oklch(0.7 0.12 62)", coral: "oklch(0.71 0.14 40)", rose: "oklch(0.68 0.15 15)",
    violet: "oklch(0.66 0.16 300)", sky: "oklch(0.7 0.13 235)", green: "oklch(0.7 0.14 150)"
  };
  var defaults = null;   // filled from /api/appearance; null means "no server / not loaded yet"

  function get(k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }

  /* Which platform is this? The app already had two signals for it -- the Capacitor shell on
     Android, and the 640px breakpoint every page's CSS uses -- so this reads those rather than
     adding a third notion of "mobile" that could disagree with the layout on screen. */
  function platform() {
    if (window.Capacitor) return "mobile";
    return (window.innerWidth || 1024) <= 640 ? "mobile" : "web";
  }

  /* Did the user actually choose, or are we looking at the shipped default? Kept in step with
     user_picked_bg()/user_picked_theme() in server.py -- both sides have to agree, or a global
     default would apply on one page and not the next. */
  function chosenBg(bg) {
    if (!bg || !bg.value) return false;
    if (bg.chosen) return true;
    if (bg.type === "image") return true;
    return !(bg.value === "midnight" && !bg.dim && !bg.blur);
  }
  function chosenTheme(p) {
    if (!p) return false;
    return !!(p.themeChosen || (p.accent && p.accent !== "amber") || p.glass);
  }

  function layers() {
    var bg = document.getElementById("themeBg");
    if (!bg) {
      bg = document.createElement("div");
      bg.id = "themeBg";
      bg.style.cssText = "position:fixed;inset:0;z-index:-2;background-size:cover;background-position:center";
      document.body.appendChild(bg);
      var sc = document.createElement("div");
      sc.id = "themeScrim";
      sc.style.cssText = "position:fixed;inset:0;z-index:-1;background:#000;opacity:0;transition:opacity .3s";
      document.body.appendChild(sc);
    }
    return bg;
  }
  /* Acrylic blur on the background layer. A blurred fixed layer fades out at the viewport
     edges, because the filter has nothing beyond them to sample -- scaling it up pushes that
     soft margin off-screen. Kept in step with applyBg() in index.html. */
  var BLUR_MAX_PX = 32;
  function blurLayer(el, pct) {
    pct = Math.max(0, Math.min(100, Number(pct) || 0));
    var px = pct / 100 * BLUR_MAX_PX;
    el.style.filter = px ? "blur(" + px.toFixed(1) + "px)" : "";
    el.style.transform = px ? "scale(1.12)" : "";
  }

  /* Paint an admin theme's tokens onto the page. Every page already reads its colours from
     these variables, so writing them here is all a theme has to do -- there is no per-page
     stylesheet to touch. Both naming schemes are set: the dashboard uses --surface/--surface-2,
     the timer and login pages use --cream/--cream2 for the same two surfaces. */
  var TOKEN_VARS = {
    accent: ["--accent"], accentInk: ["--accent-ink"],
    surface: ["--surface", "--cream"], surface2: ["--surface-2", "--cream2"],
    ink: ["--ink"], muted: ["--muted"], line: ["--line"], hair: ["--hair"],
    field: ["--field"], radius: ["--radius"]
  };
  function applyThemeTokens(theme) {
    if (!theme || !theme.tokens) return;
    var t = theme.tokens, root = document.documentElement;
    for (var key in TOKEN_VARS) {
      var v = t[key];
      if (!v || /[;{}<>]/.test(v)) continue;   // never let a stored value close the declaration
      for (var i = 0; i < TOKEN_VARS[key].length; i++) root.style.setProperty(TOKEN_VARS[key][i], v);
    }
    root.classList.toggle("glass", t.appearance === "glass");
  }

  function apply() {
    var bg = get("ff_bg", { type: "preset", value: "midnight", dim: 0 });
    var prefs = get("ff_prefs", { lang: "en" });
    var el = layers();

    // ---- background: user pick -> admin default for this platform -> built-in ----
    var useBg = bg, dim = (bg && bg.dim) || 0, blur = (bg && bg.blur) || 0;
    if (!chosenBg(bg) && defaults && defaults.background) {
      var d = defaults.background;
      useBg = { type: d.kind === "image" ? "image" : "preset", value: d.value };
      dim = defaults.dim || 0;
      blur = defaults.blur || 0;
    }
    // An admin preset arrives as the CSS value itself; a locally stored one is a key into BGS.
    var css = (useBg && useBg.type === "preset")
      ? (BGS[useBg.value] || (/[(#]/.test(useBg.value || "") ? useBg.value : BGS.midnight))
      : null;
    if (useBg && useBg.type === "image") { el.style.background = ""; el.style.backgroundImage = "url(" + useBg.value + ")"; }
    else { el.style.background = css; }
    // Both branches above write the `background` shorthand, which resets background-size and
    // background-position along with it -- so they have to go back on afterwards. Without this
    // a photo fell back to `auto` at the top-left corner and came out cropped on every page but
    // the timer, which re-applies them the same way.
    el.style.backgroundSize = "cover";
    el.style.backgroundPosition = "center";
    el.style.backgroundRepeat = "no-repeat";
    blurLayer(el, blur);
    document.getElementById("themeScrim").style.opacity = (dim / 100);

    // ---- theme: same three steps ----
    if (!chosenTheme(prefs) && defaults && defaults.theme) {
      applyThemeTokens(defaults.theme);
    } else {
      document.documentElement.style.setProperty("--accent", ACCENTS[prefs && prefs.accent] || ACCENTS.amber);
      // Appearance, picked on the timer page. Absent means Classic, so accounts saved before the
      // setting existed keep the surfaces they had.
      document.documentElement.classList.toggle("glass", !!(prefs && prefs.glass));
    }

    // Carry the timer page's "top of screen" choice onto every other screen in the app, so
    // opening the dashboard mid-session doesn't pop the system bar back into view.
    if (window.Capacitor) {
      var fs = !!(prefs && prefs.fullscreen);
      document.documentElement.classList.toggle("fs", fs);
      var sb = window.Capacitor.Plugins && window.Capacitor.Plugins.StatusBar;
      if (sb) { try { if (fs) sb.hide(); else { sb.show(); sb.setOverlaysWebView({ overlay: true }); sb.setStyle({ style: "DARK" }); } } catch (e) {} }
    }
    var lang = (prefs && prefs.lang) || (defaults && defaults.language) || "en";
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }
  // Inside the Android app the WebView draws under the system bars, so the pages guarantee a
  // minimum top inset off this class -- see the html.native rule in each page's CSS.
  if (window.Capacitor) document.documentElement.classList.add("native");

  window.FocusTheme = {
    apply: apply, BGS: BGS, ACCENTS: ACCENTS, platform: platform,
    chosenBg: chosenBg, chosenTheme: chosenTheme,
    defaults: function () { return defaults; }
  };
  if (document.body) apply(); else document.addEventListener("DOMContentLoaded", apply);

  // The account's own settings first (so a signed-in device catches up with itself), then the
  // resolved defaults. Each repaints as it lands; both are optional and fail quietly offline.
  try {
    fetch("/api/me", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (j && j.user && j.settings) {
          if (j.settings.bg) localStorage.setItem("ff_bg", JSON.stringify(j.settings.bg));
          if (j.settings.prefs) localStorage.setItem("ff_prefs", JSON.stringify(j.settings.prefs));
          apply();
        }
      })
      .catch(function () {});
    fetch("/api/appearance?platform=" + platform(), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        defaults = j;
        // Admin-managed presets join the built-in map so a background added in the panel is a
        // real option here too, not just on the timer's own swatch row.
        (j.backgrounds || []).forEach(function (b) { if (b.kind === "preset") BGS[b.slug] = b.value; });
        apply();
      })
      .catch(function () {});

    /* Keep uploaded backgrounds on the device. sw.js caches /media/backgrounds/ and leaves
       every other request to the network, so the pages themselves are never held in a cache
       that could outlive a deploy. Registered from here because this file is the one every
       page showing a background already loads. Silently absent where service workers are
       not available (an insecure origin, or a WebView without them) -- the images simply
       come from the network as before.
       Registered immediately rather than from window's "load": that event waits on the
       Google Fonts stylesheet, which on a network that cannot reach fonts.googleapis.com
       never resolves -- so a "load" handler would never run for the very users this is
       meant to help. register() is async and delays nothing. */
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    }
  } catch (e) {}
})();
