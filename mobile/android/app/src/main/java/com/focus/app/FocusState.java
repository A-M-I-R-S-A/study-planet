package com.focus.app;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/**
 * The timer + app-lock state shared by the WebView bridge ({@link FocusPlugin}) and the
 * {@link FocusService} foreground service.
 *
 * SharedPreferences is the single source of truth deliberately: the WebView can be destroyed
 * (app closed / swiped away) while the service keeps running, and the service itself can be
 * restarted by the OS. Both sides read and write the same keys, so whoever is alive can always
 * reconstruct the session.
 *
 * The clock is stored as wall-clock anchors ({@code endsAt} / {@code anchorTs}) rather than a
 * counted-down number, so nothing drifts while a process is suspended.
 */
final class FocusState {
    static final String PREFS = "focus_state";

    /* ---- timer ---- */
    static final String K_KNOWN = "known";          // a session exists (running, paused or just ended)
    static final String K_RUNNING = "running";
    static final String K_CLEARED = "cleared";      // ended out here -> the web app must finalise it
    static final String K_ENDED_BY = "endedBy";     // "user" (notification End) | "expired"
    static final String K_TYPE = "type";            // "timer" | "stopwatch"
    static final String K_MODE = "mode";            // "focus" | "short" | "long"
    static final String K_ENDS_AT = "endsAt";       // epoch ms the countdown hits zero
    static final String K_REMAIN = "remainSec";     // seconds left, valid while paused
    static final String K_ELAPSED = "elapsedSec";   // stopwatch seconds at anchorTs
    static final String K_ANCHOR = "anchorTs";      // epoch ms the two values above were measured
    static final String K_LABEL = "label";          // subject name, else the phase name
    static final String K_REV = "rev";              // bumped by the notification buttons only

    /* ---- app lock ---- */
    static final String K_LOCK_ON = "lockEnabled";
    static final String K_LOCK_BREAKS = "lockDuringBreaks";
    static final String K_ALLOW = "allowList";

    /* ---- silencing other apps' notifications ----
     * Blocking app launches does nothing about notifications: they are a separate channel,
     * and the only sanctioned way to quiet them is Do Not Disturb. K_MUTE_APPLIED records
     * that *we* turned DND on, so a user who already had it on keeps it when the session
     * ends. */
    static final String K_MUTE_ON = "muteEnabled";
    static final String K_MUTE_APPLIED = "muteApplied";

    private FocusState() {}

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static Set<String> allowList(Context c) {
        Set<String> s = prefs(c).getStringSet(K_ALLOW, null);
        return s == null ? Collections.<String>emptySet() : new HashSet<>(s);
    }

    static void setAllowList(Context c, Set<String> pkgs) {
        prefs(c).edit().putStringSet(K_ALLOW, new HashSet<>(pkgs)).apply();
    }

    /** Seconds left on the countdown right now, or 0 once it has expired. */
    static long remainingSec(SharedPreferences p, long now) {
        if (!p.getBoolean(K_RUNNING, false)) return Math.max(0, p.getLong(K_REMAIN, 0));
        long ms = p.getLong(K_ENDS_AT, 0) - now;
        return ms <= 0 ? 0 : (ms + 999) / 1000;
    }

    /** Stopwatch seconds right now (the stored value plus the time since it was anchored). */
    static long elapsedSec(SharedPreferences p, long now) {
        long base = p.getLong(K_ELAPSED, 0);
        if (!p.getBoolean(K_RUNNING, false)) return Math.max(0, base);
        long since = (now - p.getLong(K_ANCHOR, now)) / 1000;
        return Math.max(0, base + Math.max(0, since));
    }

    static String clock(long totalSec) {
        if (totalSec < 0) totalSec = 0;
        long h = totalSec / 3600, m = (totalSec % 3600) / 60, s = totalSec % 60;
        return h > 0 ? String.format("%d:%02d:%02d", h, m, s) : String.format("%02d:%02d", m, s);
    }
}
