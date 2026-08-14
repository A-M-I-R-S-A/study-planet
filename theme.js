/* Shared theme: applies the user's chosen background + language/direction to any page.
   Reads the same localStorage the timer app writes (ff_bg, ff_prefs), then refreshes
   from the signed-in account so a theme change in one place shows up everywhere. */
(function () {
  "use strict";
  var BGS = {
    warm: "linear-gradient(180deg,#887326EB,#382C1F,#1F2838),#16303a",
    midnight: "linear-gradient(180deg,#1f2838,#0d1420)",
    forest: "linear-gradient(180deg,#1c3a2e,#0b1a14)",
    ocean: "linear-gradient(180deg,#123246,#06131f)",
    plum: "linear-gradient(180deg,#2a1f38,#140d1c)",
    slate: "linear-gradient(180deg,#2a2f38,#111418)",
    ember: "linear-gradient(180deg,#3a2418,#160b08)",
    rose: "linear-gradient(180deg,#3a2028,#160a10)",
    sand: "linear-gradient(180deg,#4a3a28,#1d1610)",
    mint: "linear-gradient(180deg,#1e3a38,#0a1a19)",
    indigo: "linear-gradient(180deg,#232a4a,#0d1024)",
    crimson: "linear-gradient(180deg,#3d1c22,#170a0c)",
    moss: "linear-gradient(180deg,#2f3a24,#131a0e)",
    charcoal: "linear-gradient(180deg,#2c2c2e,#0b0b0c)"
  };
  // The accent the user picked on the timer page, so buttons match on every other page too.
  // Only the focus tone is used here -- nothing outside the timer has a break state.
  var ACCENTS = {
    amber: "oklch(0.7 0.12 62)", coral: "oklch(0.71 0.14 40)", rose: "oklch(0.68 0.15 15)",
    violet: "oklch(0.66 0.16 300)", sky: "oklch(0.7 0.13 235)", green: "oklch(0.7 0.14 150)"
  };
  function get(k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }
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
  function apply() {
    var bg = get("ff_bg", { type: "preset", value: "warm", dim: 0 });
    var prefs = get("ff_prefs", { lang: "en" });
    var el = layers();
    if (bg && bg.type === "image") { el.style.background = ""; el.style.backgroundImage = "url(" + bg.value + ")"; }
    else { el.style.background = BGS[bg && bg.value] || BGS.warm; }
    // Both branches above write the `background` shorthand, which resets background-size and
    // background-position along with it -- so they have to go back on afterwards. Without this
    // a photo fell back to `auto` at the top-left corner and came out cropped on every page but
    // the timer, which re-applies them the same way.
    el.style.backgroundSize = "cover";
    el.style.backgroundPosition = "center";
    el.style.backgroundRepeat = "no-repeat";
    blurLayer(el, (bg && bg.blur) || 0);
    document.getElementById("themeScrim").style.opacity = (((bg && bg.dim) || 0) / 100);
    document.documentElement.style.setProperty("--accent", ACCENTS[prefs && prefs.accent] || ACCENTS.amber);
    // Appearance, picked on the timer page. Absent means Classic, so accounts saved before the
    // setting existed keep the surfaces they had.
    document.documentElement.classList.toggle("glass", !!(prefs && prefs.glass));
    // Carry the timer page's "top of screen" choice onto every other screen in the app, so
    // opening the dashboard mid-session doesn't pop the system bar back into view.
    if (window.Capacitor) {
      var fs = !!(prefs && prefs.fullscreen);
      document.documentElement.classList.toggle("fs", fs);
      var sb = window.Capacitor.Plugins && window.Capacitor.Plugins.StatusBar;
      if (sb) { try { if (fs) sb.hide(); else { sb.show(); sb.setOverlaysWebView({ overlay: true }); sb.setStyle({ style: "DARK" }); } } catch (e) {} }
    }
    var lang = (prefs && prefs.lang) || "en";
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }
  // Inside the Android app the WebView draws under the system bars, so the pages guarantee a
  // minimum top inset off this class -- see the html.native rule in each page's CSS.
  if (window.Capacitor) document.documentElement.classList.add("native");

  window.FocusTheme = { apply: apply, BGS: BGS, ACCENTS: ACCENTS };
  if (document.body) apply(); else document.addEventListener("DOMContentLoaded", apply);
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
  } catch (e) {}
})();
