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
    rose: "linear-gradient(180deg,#3a2028,#160a10)"
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
  function apply() {
    var bg = get("ff_bg", { type: "preset", value: "warm", dim: 0 });
    var prefs = get("ff_prefs", { lang: "en" });
    var el = layers();
    if (bg && bg.type === "image") { el.style.background = ""; el.style.backgroundImage = "url(" + bg.value + ")"; }
    else { el.style.background = BGS[bg && bg.value] || BGS.warm; }
    document.getElementById("themeScrim").style.opacity = (((bg && bg.dim) || 0) / 100);
    var lang = (prefs && prefs.lang) || "en";
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }
  window.FocusTheme = { apply: apply, BGS: BGS };
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
