/* Shared English/Persian strings for login, dashboard and rooms.
   (index.html carries its own dictionary inline; this covers the other three pages.)

   Markup opts in with attributes:
     data-i18n="key"        -> element textContent
     data-i18n-ph="key"     -> input placeholder
     data-i18n-title="key"  -> title attribute
   Script-generated text calls FocusI18n.t("key").

   Language lives in ff_prefs.lang, the same key the timer writes, so a switch made
   here is the one the timer picks up. */
(function () {
  "use strict";

  var DICT = {
    en: {
      /* -- login -- */
      login_title: "Focus — Sign in",
      login_tag: "Your sessions, streaks & settings — saved to your account.",
      sign_in: "Sign in",
      create_account: "Create account",
      name: "Name",
      name_ph: "What should we call you?",
      email: "Email",
      password: "Password",
      back_timer: "← Back to the timer",
      generic_error: "Something went wrong.",
      signing_in: "Success — taking you in…",
      no_server: "Couldn't reach the server.",

      /* -- shared nav -- */
      timer: "Timer",
      rooms: "Rooms",
      dashboard: "Dashboard",
      sign_out: "Sign out",
      lang_switch: "English",

      /* -- dashboard -- */
      loading_dash: "Loading your dashboard…",
      no_server_running: "Couldn't reach the server. Is it running?",
      greet: "Hey, %s.",
      hero_today: "%s focused today.",
      vs_best: "of your best day",
      ribbon: "Last 90 days",
      subjects: "Subjects",
      subjects_sub: "· focus time today",
      subject_ph: "Add a subject (e.g. Calculus)",
      add: "Add",
      subjects_empty: "No subjects yet — add your first above, then pick it on the timer.",
      delete: "Delete",
      confirm_del_subject: "Delete subject “%s”? Past sessions keep their history.",
      last14: "Last 14 days · focus minutes",
      chart_empty: "No focus sessions yet — start a timer and your history will grow here.",
      calendar: "Study calendar",
      prev_month: "Previous month",
      next_month: "Next month",
      pick_day: "Pick a day to see what you studied.",
      nothing_on: "Nothing on %s.",
      no_notes: "No study notes recorded this day.",
      setup: "Your personalized setup",
      profile: "Profile",
      display_name: "Display name",
      your_name: "Your name",
      avatar: "Avatar",
      save: "Save",
      saved: "Saved ✓",
      error: "Error",
      streak: "🔥 Streak",
      day: " day",
      days: " days",
      total_focus: "Total focus",
      sessions: "Sessions",
      today: "Today",
      best_day: "Best day",
      active_days: "Active days",
      sess_short: " sess",
      u_h: "h", u_m: "m", u_s: "s",
      session_one: "session",
      session_many: "sessions",
      background: "Background",
      appearance: "Appearance",
      ap_classic: "Classic",
      ap_glass: "Glass",
      language: "Language",
      focus_length: "Focus length",
      breaks: "Breaks",
      progress_style: "Progress style",
      end_chime: "End chime",
      on: "On",
      off: "Off",
      min: "min",
      custom_image: "Custom image",
      bg_warm: "Warm", bg_midnight: "Midnight", bg_forest: "Forest", bg_ocean: "Ocean",
      bg_plum: "Plum", bg_slate: "Slate", bg_ember: "Ember", bg_rose: "Rose",
      bg_sand: "Sand", bg_mint: "Mint", bg_indigo: "Indigo", bg_crimson: "Crimson",
      bg_moss: "Moss", bg_charcoal: "Charcoal",
      prog_bar: "▬ Bar", prog_rabbit: "🐇 Rabbit → 🥕", prog_rocket: "🚀 Rocket → 🌙", prog_runner: "🏃 Runner → 🏁",
      dow: ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"],

      /* -- rooms -- */
      study_rooms: "Study Rooms",
      rooms_tagline: "Focus together · climb the leaderboard",
      loading_rooms: "Loading rooms…",
      create_room: "Create a room",
      create_hint: "up to 10 people · one room at a time",
      room_name_ph: "Name your room — e.g. Finals Grind",
      private: "Private",
      public: "Public",
      create: "＋ Create",
      your_rooms: "Your rooms",
      discover: "Discover public rooms",
      code_ph: "Have an invite code? Paste it here",
      join: "Join",
      all_rooms: "← All rooms",
      leaderboard: "Today's leaderboard",
      by_minutes: "by focus minutes",
      invite: "Invite",
      copy_link: "Copy link",
      copied: "Copied ✓",
      copied_msg: "Invite link copied!",
      invite_fine: "Anyone with this link can join — even a private room.",
      room_settings: "Room settings",
      owner_only: "owner only",
      delete_room: "Delete room",
      leave_room: "Leave room",
      confirm_del_room: "Delete this room for everyone?",
      name_your_room: "Give your room a name.",
      paste_code: "Paste an invite code.",
      failed: "Failed",
      not_found: "Not found",
      could_not_join: "Could not join.",
      room_unavailable: "Room unavailable",
      no_rooms: "No rooms yet — create one above, or join a public room below.",
      no_public: "No public rooms yet. Make one public for others to find!",
      owner_chip: "★ owner",
      open_arrow: "Open →",
      open: "Open",
      full: "Full",
      joined: "joined",
      here: "here",
      focusing_now: "focusing now",
      nobody_focusing: "· nobody focusing yet",
      idle: "idle",
      owner: "owner",
      you: "you"
    },

    fa: {
      /* -- login -- */
      login_title: "فوکوس — ورود",
      login_tag: "جلسه‌ها، رکوردها و تنظیمات شما — ذخیره‌شده در حساب کاربری.",
      sign_in: "ورود",
      create_account: "ساخت حساب",
      name: "نام",
      name_ph: "شما را چه صدا کنیم؟",
      email: "ایمیل",
      password: "رمز عبور",
      back_timer: "→ بازگشت به تایمر",
      generic_error: "مشکلی پیش آمد.",
      signing_in: "انجام شد — در حال ورود…",
      no_server: "ارتباط با سرور برقرار نشد.",

      /* -- shared nav -- */
      timer: "تایمر",
      rooms: "روم‌ها",
      dashboard: "داشبورد",
      sign_out: "خروج",
      lang_switch: "فارسی",

      /* -- dashboard -- */
      loading_dash: "در حال بارگذاری داشبورد…",
      no_server_running: "ارتباط با سرور برقرار نشد. آیا سرور روشن است؟",
      subjects: "درس‌ها",
      subjects_sub: "· زمان تمرکز امروز",
      subject_ph: "افزودن درس (مثلاً ریاضی)",
      add: "افزودن",
      subjects_empty: "هنوز درسی ثبت نشده — اولین درس را بالا اضافه کن، بعد در تایمر انتخابش کن.",
      delete: "حذف",
      confirm_del_subject: "درس «%s» حذف شود؟ جلسه‌های گذشته حفظ می‌شوند.",
      last14: "۱۴ روز اخیر · دقیقه‌های تمرکز",
      chart_empty: "هنوز جلسه‌ای ثبت نشده — یک تایمر شروع کن تا تاریخچه‌ات اینجا شکل بگیرد.",
      calendar: "تقویم مطالعه",
      prev_month: "ماه قبل",
      next_month: "ماه بعد",
      pick_day: "یک روز را انتخاب کن تا ببینی چه خوانده‌ای.",
      nothing_on: "در %s چیزی ثبت نشده.",
      no_notes: "برای این روز یادداشتی ثبت نشده.",
      setup: "تنظیمات شخصی شما",
      profile: "پروفایل",
      display_name: "نام نمایشی",
      your_name: "نام شما",
      avatar: "آواتار",
      save: "ذخیره",
      saved: "ذخیره شد ✓",
      error: "خطا",
      streak: "🔥 روزهای پیاپی",
      day: " روز",
      days: " روز",
      total_focus: "کل تمرکز",
      sessions: "جلسه‌ها",
      today: "امروز",
      best_day: "بهترین روز",
      active_days: "روزهای فعال",
      sess_short: " جلسه",
      u_h: "ساعت", u_m: "دقیقه", u_s: "ثانیه",
      session_one: "جلسه",
      session_many: "جلسه",
      greet: "سلام %s.",
      hero_today: "%s تمرکز امروز.",
      vs_best: "از بهترین روزت",
      ribbon: "۹۰ روز گذشته",
      background: "پس‌زمینه",
      appearance: "ظاهر",
      ap_classic: "کلاسیک",
      ap_glass: "شیشه‌ای",
      language: "زبان",
      focus_length: "مدت تمرکز",
      breaks: "استراحت‌ها",
      progress_style: "نمایش پیشرفت",
      end_chime: "صدای پایان",
      on: "روشن",
      off: "خاموش",
      min: "دقیقه",
      custom_image: "تصویر دلخواه",
      bg_warm: "گرم", bg_midnight: "نیمه‌شب", bg_forest: "جنگل", bg_ocean: "اقیانوس",
      bg_plum: "آلو", bg_slate: "سنگی", bg_ember: "اخگر", bg_rose: "رز",
      bg_sand: "شنی", bg_mint: "نعنایی", bg_indigo: "نیلی", bg_crimson: "زرشکی",
      bg_moss: "خزه‌ای", bg_charcoal: "زغالی",
      prog_bar: "▬ نوار", prog_rabbit: "🐇 خرگوش → 🥕", prog_rocket: "🚀 موشک → 🌙", prog_runner: "🏃 دونده → 🏁",
      dow: ["ی", "د", "س", "چ", "پ", "ج", "ش"],

      /* -- rooms -- */
      study_rooms: "روم‌های مطالعه",
      rooms_tagline: "با هم تمرکز کنید · در جدول بالا بروید",
      loading_rooms: "در حال بارگذاری روم‌ها…",
      create_room: "ساخت روم",
      create_hint: "تا ۱۰ نفر · هر بار فقط یک روم",
      room_name_ph: "برای روم اسم بگذار — مثلاً شب امتحان",
      private: "خصوصی",
      public: "عمومی",
      create: "＋ ساختن",
      your_rooms: "روم‌های شما",
      discover: "روم‌های عمومی",
      code_ph: "کد دعوت داری؟ اینجا بچسبان",
      join: "پیوستن",
      all_rooms: "→ همهٔ روم‌ها",
      leaderboard: "جدول امروز",
      by_minutes: "بر اساس دقیقه‌های تمرکز",
      invite: "دعوت",
      copy_link: "کپی لینک",
      copied: "کپی شد ✓",
      copied_msg: "لینک دعوت کپی شد!",
      invite_fine: "هر کسی این لینک را داشته باشد می‌تواند بپیوندد — حتی به روم خصوصی.",
      room_settings: "تنظیمات روم",
      owner_only: "فقط سازنده",
      delete_room: "حذف روم",
      leave_room: "خروج از روم",
      confirm_del_room: "این روم برای همه حذف شود؟",
      name_your_room: "برای روم یک اسم بنویس.",
      paste_code: "کد دعوت را وارد کن.",
      failed: "ناموفق",
      not_found: "پیدا نشد",
      could_not_join: "پیوستن ممکن نشد.",
      room_unavailable: "این روم در دسترس نیست",
      no_rooms: "هنوز رومی نداری — یکی بالا بساز، یا به یک روم عمومی بپیوند.",
      no_public: "هنوز روم عمومی‌ای نیست. یکی از روم‌هایت را عمومی کن تا بقیه پیدایش کنند!",
      owner_chip: "★ سازنده",
      open_arrow: "باز کردن →",
      open: "باز کردن",
      full: "پُر",
      joined: "عضو",
      here: "نفر اینجا",
      focusing_now: "در حال تمرکز",
      nobody_focusing: "· هنوز کسی در حال تمرکز نیست",
      idle: "آرام",
      owner: "سازنده",
      you: "شما"
    }
  };

  /* Server messages arrive as English prose. Map the ones a user actually meets;
     anything unmapped falls through to the server's own wording. */
  var SERVER_ERRORS = {
    "Please enter a valid email address.": "یک ایمیل معتبر وارد کن.",
    "Password must be at least 6 characters.": "رمز عبور باید حداقل ۶ کاراکتر باشد.",
    "That email is already registered.": "این ایمیل قبلاً ثبت شده است.",
    "Wrong email or password.": "ایمیل یا رمز عبور اشتباه است.",
    "Not signed in.": "وارد نشده‌اید.",
    "Something went wrong.": "مشکلی پیش آمد.",
    "Too many attempts — wait a few minutes and try again.": "تلاش‌های زیاد — چند دقیقه صبر کن و دوباره امتحان کن.",
    "Too many sign-ups from this network — try again later.": "ثبت‌نام‌های زیاد از این شبکه — بعداً دوباره امتحان کن.",
    "Room not found.": "روم پیدا نشد.",
    "Room not found — check the invite code.": "روم پیدا نشد — کد دعوت را بررسی کن.",
    "This room is private.": "این روم خصوصی است.",
    "You're already in a room — leave it before creating a new one.": "همین حالا در یک روم هستی — اول از آن خارج شو.",
    "You can only be in one room at a time — leave your current room first.": "هر بار فقط می‌توانی در یک روم باشی — اول از روم فعلی خارج شو.",
    "Owners can't leave — delete the room instead.": "سازنده نمی‌تواند خارج شود — به‌جای آن روم را حذف کن.",
    "Only the owner can delete this room.": "فقط سازنده می‌تواند این روم را حذف کند.",
    "Only the owner can change this.": "فقط سازنده می‌تواند این را تغییر دهد.",
    "Give the subject a name.": "برای درس یک نام بنویس.",
    "Request too large.": "حجم درخواست زیاد است."
  };

  var FA_DIG = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

  function get(k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }

  var lang = (get("ff_prefs", {}) || {}).lang === "fa" ? "fa" : "en";

  function t(key) {
    var v = DICT[lang][key];
    return v === undefined ? (DICT.en[key] === undefined ? key : DICT.en[key]) : v;
  }
  /* "%s" placeholder fill, so word order stays translatable */
  function tf(key, val) { return t(key).replace("%s", val); }
  /* Persian digits for any number shown to the user */
  function num(v) { return lang === "fa" ? String(v).replace(/[0-9]/g, function (d) { return FA_DIG[+d]; }) : String(v); }
  function locale() { return lang === "fa" ? "fa-IR" : undefined; }

  /* Durations. English keeps the tight "1h 20m"; Persian has no accepted one-letter
     abbreviations, so it spells the units out and needs a space before each. */
  function unit(n, key) { return num(n) + unitLabel(key); }
  /* The unit on its own, carrying the space Persian needs, for the few places that style the
     number and its unit separately. */
  function unitLabel(key) { return (lang === "fa" ? " " : "") + t(key); }
  function durSecs(secs) {
    secs = Math.max(0, Math.round(secs || 0));
    if (secs < 60) return secs ? "<" + unit(1, "u_m") : unit(0, "u_m");
    return durMins(Math.floor(secs / 60));
  }
  function durMins(mins) {
    mins = Math.max(0, Math.round(mins || 0));
    var h = Math.floor(mins / 60), m = mins % 60;
    if (h && m) return unit(h, "u_h") + " " + unit(m, "u_m");
    return h ? unit(h, "u_h") : unit(m, "u_m");
  }
  /* One unit only, for boxes too small for two -- the calendar squares are a seventh of the
     grid, and spelled-out Persian needs three times the room "1h 20m" does. Tapping the day
     shows the exact figure underneath. */
  function durCompact(mins) {
    mins = Math.max(0, Math.round(mins || 0));
    return mins < 60 ? unit(mins, "u_m") : unit(Math.round(mins / 60), "u_h");
  }
  function serverError(text) { return (lang === "fa" && SERVER_ERRORS[text]) || text; }

  function apply(root) {
    root = root || document;
    root.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-ph]").forEach(function (el) { el.placeholder = t(el.dataset.i18nPh); });
    root.querySelectorAll("[data-i18n-title]").forEach(function (el) { el.title = t(el.dataset.i18nTitle); });
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }

  /* Persist the switch, then reload so every generated string, date and
     number is rebuilt in the new language rather than half-translated.
     PUT /api/settings replaces the whole blob, so merge into what the
     account already has instead of sending prefs alone. */
  function setLang(next) {
    lang = next === "fa" ? "fa" : "en";
    var prefs = get("ff_prefs", {}) || {};
    prefs.lang = lang;
    try { localStorage.setItem("ff_prefs", JSON.stringify(prefs)); } catch (e) {}
    var done = function () { location.reload(); };
    fetch("/api/me", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.user) return done();
        var s = j.settings || {};
        s.prefs = s.prefs || {};
        s.prefs.lang = lang;
        return fetch("/api/settings", {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings: s })
        }).then(done, done);
      })
      .catch(done);
  }

  function toggle() { setLang(lang === "en" ? "fa" : "en"); }

  window.FocusI18n = {
    t: t, tf: tf, num: num, apply: apply, setLang: setLang, toggle: toggle,
    locale: locale, serverError: serverError,
    durSecs: durSecs, durMins: durMins, durCompact: durCompact, unitLabel: unitLabel,
    get lang() { return lang; }
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { apply(); });
  else apply();
})();
