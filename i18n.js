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
      brand: "Study Planet",
      login_title: "Study Planet — Sign in",
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

      /* -- signing in with a texted code --
         The number is the account: one field, one code, and the server decides on the way
         back whether that was a sign-in or the start of a new account. */
      phone: "Mobile number",
      phone_why: "We'll text you a 5-digit code. That's all you need to sign in.",
      send_code: "Send code",
      code: "Verification code",
      verify: "Verify",
      change_number: "Change number",
      resend: "Send a new code",
      resend_in: "You can ask for another in %ss",
      code_sent: "We texted a 5-digit code to %s",
      code_resent: "A new code is on its way.",
      registering_for: "Creating your account for %s",
      use_password: "Sign in with a password instead",
      use_code: "Sign in with a texted code instead",
      email_or_phone: "Email or mobile number",
      optional_suffix: "— optional",
      pw_why: "Only if you'd also like to sign in with a password. A texted code always works.",
      sending: "Sending the code…",
      sending_again: "Sending a new code…",
      checking: "Checking…",
      creating: "Creating your account…",
      bad_phone: "Enter your mobile number, e.g. 09121234567.",
      bad_code: "Type the 5-digit code from the text.",
      bad_email: "That email doesn't look right — or leave it empty.",
      short_pw: "A password needs at least 6 characters — or leave it empty.",
      need_name: "What should we call you?",
      need_both: "Fill in both boxes.",

      /* -- what you study --
         The keys (school/uni, elementary/7…12, biology/math/fanni) are what the server
         stores and what library targeting matches on; only the labels below change with
         the language, so a translation can never orphan someone's grade. */
      edu_q: "What are you studying?",
      edu_school: "School",
      edu_uni: "University",
      edu_school_sub: "Grades 1–12",
      edu_uni_sub: "Any field",
      edu_grade: "Grade",
      edu_major: "Major",
      edu_pick: "Choose…",
      edu_uni_major: "Your field of study",
      edu_uni_major_ph: "e.g. Computer Engineering",
      edu_no_major: "Majors start at 10th grade — nothing to pick yet.",
      edu_why: "This is how we know which study material to put on your shelf.",
      edu_need_stage: "Pick school or university.",
      edu_need_grade: "Pick your grade.",
      edu_need_major: "Pick your major.",
      edu_need_uni_major: "Type what you study.",
      g_elementary: "Elementary",
      g_7: "7th grade", g_8: "8th grade", g_9: "9th grade",
      g_10: "10th grade", g_11: "11th grade", g_12: "12th grade",
      m_biology: "Biology", m_math: "Math", m_fanni: "Technical",
      m_none: "No major yet",

      /* -- library -- */
      library: "Library",
      library_sub: "Study material chosen for you",
      lib_loading: "Opening your library…",
      lib_empty: "Nothing here yet — material for your grade will appear as it's added.",
      lib_empty_edu: "Tell us what you study and your material will show up here.",
      lib_set_edu: "Set what you study",
      lib_off: "The library is closed right now.",
      lib_other: "Other material",
      lib_open: "Open",
      lib_download: "Download",
      lib_files_one: "%s file",
      lib_files_many: "%s files",
      lib_shelf_for: "Your shelf · %s",
      lib_everyone: "For everyone",
      edu_saved: "Saved ✓",

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
      invite_fine: "Only you can see this link. Anyone you send it to can join — even a private room.",
      joining: "Redeeming your invite…",
      room_settings: "Room settings",
      owner_only: "owner only",
      room_desc_label: "Room description",
      room_desc_ph: "What is this room for? Say what you're all working towards.",
      save_desc: "Save description",
      desc_saved: "Description saved.",
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
      you: "you",

      /* -- room owner: members & assigned work -- */
      confirm_remove: "Remove %s from the room?",
      removed_ok: "%s was removed.",
      remove_name: "Remove %s",
      assign_to_name: "Assign a task to %s",
      assigned_work: "Assigned work",
      task_label: "Task",
      task_ph: "What should they work on?",
      assign_to: "Assign to",
      suggested_time: "Suggested time",
      minutes_ph: "minutes — optional",
      deadline_opt: "Deadline — optional",
      assign_task: "Assign task",
      task_assigned: "Task assigned ✓",
      write_task: "Write what the task is.",
      pick_person: "Pick who it's for.",
      remove_task: "Delete this task",
      n_open: "%s still open",
      no_tasks_owner: "Nothing assigned yet — give someone their first task above.",
      no_tasks_you: "Nothing assigned to you yet."
    },

    fa: {
      /* -- login -- */
      brand: "استادی پلنت",
      login_title: "استادی پلنت — ورود",
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

      /* -- ورود با کد پیامکی -- */
      phone: "شمارهٔ موبایل",
      phone_why: "یک کد ۵ رقمی برایت پیامک می‌کنیم. برای ورود همین کافی است.",
      send_code: "ارسال کد",
      code: "کد تأیید",
      verify: "تأیید",
      change_number: "تغییر شماره",
      resend: "ارسال کد جدید",
      resend_in: "%s ثانیه تا درخواست کد بعدی",
      code_sent: "کد ۵ رقمی به %s پیامک شد",
      code_resent: "کد جدید ارسال شد.",
      registering_for: "ساخت حساب برای %s",
      use_password: "ورود با رمز عبور",
      use_code: "ورود با کد پیامکی",
      email_or_phone: "ایمیل یا شمارهٔ موبایل",
      optional_suffix: "— اختیاری",
      pw_why: "فقط اگر می‌خواهی با رمز عبور هم وارد شوی. کد پیامکی همیشه کار می‌کند.",
      sending: "در حال ارسال کد…",
      sending_again: "در حال ارسال کد جدید…",
      checking: "در حال بررسی…",
      creating: "در حال ساخت حساب…",
      bad_phone: "شمارهٔ موبایلت را وارد کن، مثلاً ۰۹۱۲۱۲۳۴۵۶۷.",
      bad_code: "کد ۵ رقمی داخل پیامک را وارد کن.",
      bad_email: "ایمیل درست به‌نظر نمی‌رسد — یا خالی بگذارش.",
      short_pw: "رمز عبور باید حداقل ۶ کاراکتر باشد — یا خالی بگذارش.",
      need_name: "شما را چه صدا کنیم؟",
      need_both: "هر دو کادر را پر کن.",

      /* -- رشته و پایه -- */
      edu_q: "چه چیزی می‌خوانی؟",
      edu_school: "مدرسه",
      edu_uni: "دانشگاه",
      edu_school_sub: "دبستان تا دوازدهم",
      edu_uni_sub: "هر رشته‌ای",
      edu_grade: "پایه",
      edu_major: "رشته",
      edu_pick: "انتخاب کن…",
      edu_uni_major: "رشتهٔ تحصیلی",
      edu_uni_major_ph: "مثلاً مهندسی کامپیوتر",
      edu_no_major: "انتخاب رشته از پایهٔ دهم شروع می‌شود.",
      edu_why: "از روی همین می‌فهمیم چه جزوه‌هایی را در کتابخانه‌ات بگذاریم.",
      edu_need_stage: "مدرسه یا دانشگاه را انتخاب کن.",
      edu_need_grade: "پایه‌ات را انتخاب کن.",
      edu_need_major: "رشته‌ات را انتخاب کن.",
      edu_need_uni_major: "رشته‌ات را بنویس.",
      g_elementary: "دبستان",
      g_7: "هفتم", g_8: "هشتم", g_9: "نهم",
      g_10: "دهم", g_11: "یازدهم", g_12: "دوازدهم",
      m_biology: "تجربی", m_math: "ریاضی", m_fanni: "فنی",
      m_none: "بدون رشته",

      /* -- کتابخانه -- */
      library: "کتابخانه",
      library_sub: "جزوه‌ها و منابعی که برای تو انتخاب شده",
      lib_loading: "در حال باز کردن کتابخانه…",
      lib_empty: "فعلاً چیزی اینجا نیست — هر جزوه‌ای که برای پایه‌ات اضافه شود همین‌جا می‌آید.",
      lib_empty_edu: "بگو چه می‌خوانی تا منابعت اینجا بیاید.",
      lib_set_edu: "رشته و پایه‌ات را مشخص کن",
      lib_off: "کتابخانه فعلاً بسته است.",
      lib_other: "منابع دیگر",
      lib_open: "باز کردن",
      lib_download: "دانلود",
      lib_files_one: "%s فایل",
      lib_files_many: "%s فایل",
      lib_shelf_for: "قفسهٔ تو · %s",
      lib_everyone: "برای همه",
      edu_saved: "ذخیره شد ✓",

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
      invite_fine: "فقط شما این لینک را می‌بینید. هر کسی که برایش بفرستی می‌تواند بپیوندد — حتی به روم خصوصی.",
      joining: "در حال پیوستن با لینک دعوت…",
      room_settings: "تنظیمات روم",
      owner_only: "فقط سازنده",
      room_desc_label: "توضیح روم",
      room_desc_ph: "این روم برای چیست؟ بنویس روی چه چیزی کار می‌کنید.",
      save_desc: "ذخیرهٔ توضیح",
      desc_saved: "توضیح ذخیره شد.",
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
      you: "شما",

      /* -- room owner: members & assigned work -- */
      confirm_remove: "%s از روم حذف شود؟",
      removed_ok: "%s حذف شد.",
      remove_name: "حذف %s",
      assign_to_name: "واگذاری کار به %s",
      assigned_work: "کارهای واگذارشده",
      task_label: "کار",
      task_ph: "چه کاری انجام دهد؟",
      assign_to: "واگذاری به",
      suggested_time: "زمان پیشنهادی",
      minutes_ph: "دقیقه — اختیاری",
      deadline_opt: "مهلت — اختیاری",
      assign_task: "واگذاری کار",
      task_assigned: "کار واگذار شد ✓",
      write_task: "بنویس کار چیست.",
      pick_person: "انتخاب کن برای چه کسی است.",
      remove_task: "حذف این کار",
      n_open: "%s کار باز",
      no_tasks_owner: "هنوز کاری واگذار نشده — از بالا اولین کار را بده.",
      no_tasks_you: "هنوز کاری به شما واگذار نشده."
    }
  };

  /* Server messages arrive as English prose. Map the ones a user actually meets;
     anything unmapped falls through to the server's own wording. */
  var SERVER_ERRORS = {
    "Please enter a valid email address.": "یک ایمیل معتبر وارد کن.",
    "Password must be at least 6 characters.": "رمز عبور باید حداقل ۶ کاراکتر باشد.",
    "That email is already registered.": "این ایمیل قبلاً ثبت شده است.",
    "Wrong email or password.": "ایمیل یا رمز عبور اشتباه است.",
    /* -- ورود با کد پیامکی -- */
    "Enter a valid mobile number.": "یک شمارهٔ موبایل معتبر وارد کن.",
    "Too many code requests from this network — try again later.":
      "درخواست کد از این شبکه زیاد بوده — بعداً دوباره امتحان کن.",
    "A code was just sent — wait a moment before asking for another.":
      "همین حالا یک کد فرستاده شد — کمی صبر کن و بعد کد تازه بخواه.",
    "Too many codes requested for this number — try again in an hour.":
      "برای این شماره کد زیادی درخواست شده — یک ساعت دیگر امتحان کن.",
    "Couldn't send the code — check the number and try again.":
      "کد ارسال نشد — شماره را بررسی کن و دوباره تلاش کن.",
    "SMS is not configured on the server.": "سرویس پیامک روی سرور تنظیم نشده است.",
    "Ask for a code first.": "اول درخواست کد بده.",
    "That code was already used — ask for a new one.": "این کد قبلاً استفاده شده — کد تازه بخواه.",
    "That code has expired — ask for a new one.": "این کد منقضی شده — کد تازه بخواه.",
    "Too many wrong codes — ask for a new one.": "کد اشتباه زیاد وارد شد — کد تازه بخواه.",
    "That code isn't right.": "این کد درست نیست.",
    "Verify your phone number again — that step expired.":
      "شماره‌ات را دوباره تأیید کن — این مرحله منقضی شد.",
    "That number already has an account — sign in instead.":
      "این شماره قبلاً حساب دارد — به‌جای ثبت‌نام وارد شو.",
    "This account signs in with a code — ask for one instead.":
      "این حساب با کد پیامکی وارد می‌شود — درخواست کد بده.",
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
    "Only the owner can remove people.": "فقط سازنده می‌تواند کسی را حذف کند.",
    "You can't remove yourself — delete the room instead.": "نمی‌توانی خودت را حذف کنی — به‌جای آن روم را حذف کن.",
    "That person isn't in this room.": "این شخص در این روم نیست.",
    "Only the owner can assign tasks.": "فقط سازنده می‌تواند کار واگذار کند.",
    "Only the owner can remove assigned tasks.": "فقط سازنده می‌تواند کارهای واگذارشده را حذف کند.",
    "Write what the task is.": "بنویس کار چیست.",
    "That isn't your task.": "این کار شما نیست.",
    "Task not found.": "کار پیدا نشد.",
    "This room has too many assigned tasks — clear some first.": "کارهای واگذارشدهٔ این روم زیاد است — اول چند تا را پاک کن.",
    "This room is full — it already has 10 people.": "این روم پُر است — همین حالا ۱۰ نفر در آن هستند.",
    "Give the subject a name.": "برای درس یک نام بنویس.",
    "Request too large.": "حجم درخواست زیاد است.",
    "not found": "پیدا نشد."
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

  /* ---- education labels ----
     One place turns the stored keys into words, so the login form, the dashboard card,
     the library header and the admin panel can never disagree about what "fanni" or
     "elementary" is called. An unknown key comes back as itself rather than blank —
     a value the server grew and this file hasn't caught up with should still be legible. */
  var GRADES = ["elementary", "7", "8", "9", "10", "11", "12"];
  var MAJORS = ["biology", "math", "fanni"];
  var MAJOR_GRADES = ["10", "11", "12"];
  function eduGrade(g) { return g ? t("g_" + g) : ""; }
  function eduMajor(m) { return m ? t("m_" + m) : ""; }
  /* The one-line description of a student: "11th grade · Math", "University · Physics". */
  function eduLabel(edu) {
    edu = edu || {};
    if (edu.stage === "uni") return edu.major ? t("edu_uni") + " · " + edu.major : t("edu_uni");
    if (edu.stage !== "school") return "";
    var parts = [];
    if (edu.grade) parts.push(eduGrade(edu.grade));
    if (edu.major) parts.push(eduMajor(edu.major));
    return parts.join(" · ") || t("edu_school");
  }
  function hasMajor(grade) { return MAJOR_GRADES.indexOf(String(grade)) >= 0; }

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
    eduGrade: eduGrade, eduMajor: eduMajor, eduLabel: eduLabel, hasMajor: hasMajor,
    GRADES: GRADES, MAJORS: MAJORS,
    durSecs: durSecs, durMins: durMins, durCompact: durCompact, unitLabel: unitLabel,
    get lang() { return lang; }
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { apply(); });
  else apply();
})();
