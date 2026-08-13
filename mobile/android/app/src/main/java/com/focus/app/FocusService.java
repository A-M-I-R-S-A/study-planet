package com.focus.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.pm.ServiceInfo;
import android.media.RingtoneManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.telecom.TelecomManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Keeps a study session alive outside the WebView.
 *
 * Two jobs, both of which the web app cannot do on its own:
 *   1. Runs the timer in the notification bar. The countdown lives in the notification and keeps
 *      ticking after the app is closed or swiped away, and the "time's up" alert fires from here
 *      rather than from a JS timer the OS has suspended.
 *   2. Enforces the app lock. While a focus block runs it watches which app is in front and
 *      covers anything outside the user's allow list with {@link BlockOverlay}.
 *
 * The service never owns the clock — {@link FocusState} does. Everything here is derived from the
 * stored wall-clock anchors, so a restarted service picks the session straight back up.
 */
public class FocusService extends Service {

    static final String ACTION_SYNC = "com.focus.app.action.SYNC";
    static final String ACTION_PAUSE = "com.focus.app.action.PAUSE";
    static final String ACTION_RESUME = "com.focus.app.action.RESUME";
    static final String ACTION_STOP = "com.focus.app.action.STOP";

    private static final String CH_TIMER = "focus_timer";
    private static final String CH_ALERT = "focus_alert";
    private static final int NOTIF_ID = 1001;
    private static final int ALERT_ID = 1002;
    private static final long TICK_MS = 1000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private BlockOverlay overlay;
    private NotificationManager nm;
    private Set<String> systemAllow;      // launcher / dialer / system UI — never blockable
    private boolean ticking;

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            pump();
            if (ticking) handler.postDelayed(this, TICK_MS);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        overlay = new BlockOverlay(this);
        createChannels();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Must post a notification within a few seconds of being started, on every path —
        // including the null-intent restart the OS hands back after killing the process.
        startForegroundSafely(buildNotification());

        String action = intent == null ? null : intent.getAction();
        if (ACTION_PAUSE.equals(action)) applyPause();
        else if (ACTION_RESUME.equals(action)) applyResume();
        else if (ACTION_STOP.equals(action)) applyStop();

        SharedPreferences p = FocusState.prefs(this);
        if (!p.getBoolean(FocusState.K_KNOWN, false)) {
            shutdown();
            return START_NOT_STICKY;
        }
        if (!ticking) {
            ticking = true;
            handler.post(tick);
        } else {
            pump();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        ticking = false;
        handler.removeCallbacksAndMessages(null);
        if (overlay != null) overlay.hide();
        releaseMute();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /* ------------------------------------------------------------------ state transitions */

    /** Notification "Pause": freeze the remaining time so the anchors stay truthful. */
    private void applyPause() {
        SharedPreferences p = FocusState.prefs(this);
        if (!p.getBoolean(FocusState.K_RUNNING, false)) return;
        long now = System.currentTimeMillis();
        p.edit()
                .putBoolean(FocusState.K_RUNNING, false)
                .putLong(FocusState.K_REMAIN, FocusState.remainingSec(p, now))
                .putLong(FocusState.K_ELAPSED, FocusState.elapsedSec(p, now))
                .putLong(FocusState.K_ANCHOR, now)
                .putInt(FocusState.K_REV, p.getInt(FocusState.K_REV, 0) + 1)
                .apply();
        if (overlay != null) overlay.hide();
        FocusPlugin.onNativeStateChanged(this);
    }

    private void applyResume() {
        SharedPreferences p = FocusState.prefs(this);
        if (p.getBoolean(FocusState.K_RUNNING, false)) return;
        long now = System.currentTimeMillis();
        long remain = Math.max(0, p.getLong(FocusState.K_REMAIN, 0));
        if ("timer".equals(p.getString(FocusState.K_TYPE, "timer")) && remain <= 0) return;
        p.edit()
                .putBoolean(FocusState.K_RUNNING, true)
                .putBoolean(FocusState.K_CLEARED, false)
                .putLong(FocusState.K_ENDS_AT, now + remain * 1000L)
                .putLong(FocusState.K_ANCHOR, now)
                .putInt(FocusState.K_REV, p.getInt(FocusState.K_REV, 0) + 1)
                .apply();
        FocusPlugin.onNativeStateChanged(this);
    }

    /**
     * Notification "End": stop the clock but keep the record around, flagged as cleared, so the
     * web app can log the finished session the next time it opens.
     */
    private void applyStop() {
        SharedPreferences p = FocusState.prefs(this);
        long now = System.currentTimeMillis();
        p.edit()
                .putBoolean(FocusState.K_RUNNING, false)
                .putBoolean(FocusState.K_CLEARED, true)
                .putString(FocusState.K_ENDED_BY, "user")
                .putLong(FocusState.K_REMAIN, FocusState.remainingSec(p, now))
                .putLong(FocusState.K_ELAPSED, FocusState.elapsedSec(p, now))
                .putLong(FocusState.K_ANCHOR, now)
                .putInt(FocusState.K_REV, p.getInt(FocusState.K_REV, 0) + 1)
                .apply();
        FocusPlugin.onNativeStateChanged(this);
        shutdown();
    }

    /** The countdown reached zero while we, not the WebView, were the ones still running. */
    private void onExpired(SharedPreferences p) {
        p.edit()
                .putBoolean(FocusState.K_RUNNING, false)
                .putBoolean(FocusState.K_CLEARED, true)
                .putString(FocusState.K_ENDED_BY, "expired")
                .putLong(FocusState.K_REMAIN, 0)
                .putLong(FocusState.K_ANCHOR, System.currentTimeMillis())
                .putInt(FocusState.K_REV, p.getInt(FocusState.K_REV, 0) + 1)
                .apply();
        if (overlay != null) overlay.hide();
        alertDone(p.getString(FocusState.K_MODE, "focus"));
        FocusPlugin.onNativeStateChanged(this);
    }

    private void shutdown() {
        ticking = false;
        handler.removeCallbacksAndMessages(null);
        if (overlay != null) overlay.hide();
        releaseMute();
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    /* ------------------------------------------------------------------------ the 1s pump */

    private void pump() {
        SharedPreferences p = FocusState.prefs(this);
        if (!p.getBoolean(FocusState.K_KNOWN, false)) {
            shutdown();
            return;
        }
        boolean running = p.getBoolean(FocusState.K_RUNNING, false);
        boolean countdown = "timer".equals(p.getString(FocusState.K_TYPE, "timer"));
        if (running && countdown && System.currentTimeMillis() >= p.getLong(FocusState.K_ENDS_AT, 0)) {
            onExpired(p);
            running = false;
        }
        Notification n = buildNotification();
        if (n != null) nm.notify(NOTIF_ID, n);
        enforceLock(p, running);
        enforceMute(p, running);
    }

    /* --------------------------------------------------------------------------- app lock */

    /**
     * Silence other apps for the duration of a focus block.
     *
     * Blocking an app from opening does nothing about its notifications — those arrive on a
     * different channel entirely, which is what Do Not Disturb is for. PRIORITY rather than
     * NONE so alarms and whatever the user has already whitelisted (repeat callers, starred
     * contacts) still get through; silencing those in a study app would be overreach.
     */
    private void enforceMute(SharedPreferences p, boolean running) {
        boolean want = p.getBoolean(FocusState.K_MUTE_ON, false)
                && running
                && (focusBlock(p) || p.getBoolean(FocusState.K_LOCK_BREAKS, false));
        boolean applied = p.getBoolean(FocusState.K_MUTE_APPLIED, false);
        if (want == applied) return;
        if (!canMute()) return;
        try {
            if (want) {
                // Don't touch it if the user already had DND on — then it isn't ours to lift.
                if (nm.getCurrentInterruptionFilter() != NotificationManager.INTERRUPTION_FILTER_ALL) return;
                nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_PRIORITY);
            } else {
                nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL);
            }
            p.edit().putBoolean(FocusState.K_MUTE_APPLIED, want).apply();
        } catch (Exception ignored) {
        }
    }

    /** Hand back Do Not Disturb whatever happens to the session — a study app must never
     *  leave the phone silent after it has stopped running. */
    private void releaseMute() {
        SharedPreferences p = FocusState.prefs(this);
        if (!p.getBoolean(FocusState.K_MUTE_APPLIED, false)) return;
        try {
            if (canMute()) nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL);
        } catch (Exception ignored) {
        }
        p.edit().putBoolean(FocusState.K_MUTE_APPLIED, false).apply();
    }

    private boolean canMute() {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && nm != null && nm.isNotificationPolicyAccessGranted();
    }

    /** A stopwatch is always focus time, the same rule the web app's isFocusBlock() uses. */
    private static boolean focusBlock(SharedPreferences p) {
        return "focus".equals(p.getString(FocusState.K_MODE, "focus"))
                || "stopwatch".equals(p.getString(FocusState.K_TYPE, "timer"));
    }

    private void enforceLock(SharedPreferences p, boolean running) {
        boolean on = p.getBoolean(FocusState.K_LOCK_ON, false);
        boolean breaksToo = p.getBoolean(FocusState.K_LOCK_BREAKS, false);
        boolean focusBlock = focusBlock(p);
        boolean active = on && running && (focusBlock || breaksToo);

        if (!active || !hasUsageAccess() || !BlockOverlay.canDraw(this)) {
            if (overlay != null) overlay.hide();
            return;
        }
        String pkg = foregroundPackage();
        if (pkg == null || allowed(pkg)) {
            if (overlay != null) overlay.hide();
            return;
        }
        long now = System.currentTimeMillis();
        String time = "timer".equals(p.getString(FocusState.K_TYPE, "timer"))
                ? FocusState.clock(FocusState.remainingSec(p, now))
                : FocusState.clock(FocusState.elapsedSec(p, now));
        overlay.show(appLabel(pkg), time);
    }

    private boolean allowed(String pkg) {
        if (getPackageName().equals(pkg)) return true;
        if (systemAllow == null) systemAllow = buildSystemAllow();
        if (systemAllow.contains(pkg)) return true;
        return FocusState.allowList(this).contains(pkg);
    }

    /**
     * Packages that must never be blocked whatever the user picked: the home screen (otherwise
     * there is no way out), the system UI, and the phone app so an emergency call is always
     * reachable.
     */
    private Set<String> buildSystemAllow() {
        Set<String> s = new HashSet<>();
        s.add("com.android.systemui");
        s.add("android");
        PackageManager pm = getPackageManager();
        try {
            Intent home = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME);
            for (ResolveInfo ri : pm.queryIntentActivities(home, PackageManager.MATCH_DEFAULT_ONLY)) {
                if (ri.activityInfo != null) s.add(ri.activityInfo.packageName);
            }
        } catch (Exception ignored) {
        }
        try {
            TelecomManager tm = (TelecomManager) getSystemService(Context.TELECOM_SERVICE);
            if (tm != null && tm.getDefaultDialerPackage() != null) s.add(tm.getDefaultDialerPackage());
        } catch (Exception ignored) {
        }
        try {
            Intent dial = new Intent(Intent.ACTION_DIAL);
            for (ResolveInfo ri : pm.queryIntentActivities(dial, PackageManager.MATCH_DEFAULT_ONLY)) {
                if (ri.activityInfo != null) s.add(ri.activityInfo.packageName);
            }
        } catch (Exception ignored) {
        }
        return s;
    }

    /** Most recently resumed activity's package, via the usage-events stream. */
    private String foregroundPackage() {
        try {
            UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) return null;
            long now = System.currentTimeMillis();
            UsageEvents events = usm.queryEvents(now - 60_000L, now + 1_000L);
            UsageEvents.Event e = new UsageEvents.Event();
            String pkg = null;
            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                if (e.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND) pkg = e.getPackageName();
            }
            return pkg;
        } catch (Exception ex) {
            return null;
        }
    }

    private boolean hasUsageAccess() {
        return FocusPlugin.hasUsageAccess(this);
    }

    private String appLabel(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            return pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString();
        } catch (Exception e) {
            return pkg;
        }
    }

    /* ---------------------------------------------------------------------- notifications */

    private void createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel timer = new NotificationChannel(
                CH_TIMER, getString(R.string.ch_timer), NotificationManager.IMPORTANCE_LOW);
        timer.setDescription(getString(R.string.ch_timer_desc));
        timer.setShowBadge(false);
        timer.setSound(null, null);
        nm.createNotificationChannel(timer);

        NotificationChannel alert = new NotificationChannel(
                CH_ALERT, getString(R.string.ch_alert), NotificationManager.IMPORTANCE_HIGH);
        alert.setDescription(getString(R.string.ch_alert_desc));
        nm.createNotificationChannel(alert);
    }

    private void startForegroundSafely(Notification n) {
        if (n == null) return;
        try {
            int type = Build.VERSION.SDK_INT >= 34
                    ? ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                    : 0;
            ServiceCompat.startForeground(this, NOTIF_ID, n, type);
        } catch (Exception ignored) {
        }
    }

    private Notification buildNotification() {
        SharedPreferences p = FocusState.prefs(this);
        long now = System.currentTimeMillis();
        boolean running = p.getBoolean(FocusState.K_RUNNING, false);
        boolean countdown = "timer".equals(p.getString(FocusState.K_TYPE, "timer"));
        String mode = p.getString(FocusState.K_MODE, "focus");
        String label = p.getString(FocusState.K_LABEL, "");

        long secs = countdown ? FocusState.remainingSec(p, now) : FocusState.elapsedSec(p, now);
        String clock = FocusState.clock(secs);
        String phase = getString("short".equals(mode) ? R.string.phase_short
                : "long".equals(mode) ? R.string.phase_long : R.string.phase_focus);
        String title = label.isEmpty() ? phase : label;
        String text = running
                ? getString(countdown ? R.string.notif_left : R.string.notif_elapsed, clock, phase)
                : getString(R.string.notif_paused, clock);

        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                flags(PendingIntent.FLAG_UPDATE_CURRENT));

        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CH_TIMER)
                .setSmallIcon(R.drawable.ic_stat_focus)
                .setContentTitle(title)
                .setContentText(text)
                .setContentIntent(open)
                .setOngoing(running)
                .setSilent(true)
                .setShowWhen(false)
                .setOnlyAlertOnce(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setCategory(NotificationCompat.CATEGORY_STOPWATCH);

        if (running) {
            b.addAction(0, getString(R.string.act_pause), servicePi(ACTION_PAUSE, 11));
        } else {
            b.addAction(0, getString(R.string.act_resume), servicePi(ACTION_RESUME, 12));
        }
        b.addAction(0, getString(R.string.act_end), servicePi(ACTION_STOP, 13));
        return b.build();
    }

    private PendingIntent servicePi(String action, int rq) {
        Intent i = new Intent(this, FocusService.class).setAction(action);
        return PendingIntent.getService(this, rq, i, flags(PendingIntent.FLAG_UPDATE_CURRENT));
    }

    private static int flags(int base) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                ? base | PendingIntent.FLAG_IMMUTABLE
                : base;
    }

    /** The separate, audible "block is over" alert. */
    private void alertDone(String mode) {
        PendingIntent open = PendingIntent.getActivity(this, 1,
                new Intent(this, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                flags(PendingIntent.FLAG_UPDATE_CURRENT));
        Notification n = new NotificationCompat.Builder(this, CH_ALERT)
                .setSmallIcon(R.drawable.ic_stat_focus)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString("focus".equals(mode) ? R.string.done_focus : R.string.done_break))
                .setContentIntent(open)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setDefaults(NotificationCompat.DEFAULT_VIBRATE)
                .setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION))
                .build();
        nm.notify(ALERT_ID, n);
    }

    /* -------------------------------------------------------------------------- launching */

    static void kick(Context ctx, String action) {
        Intent i = new Intent(ctx, FocusService.class).setAction(action);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i);
            else ctx.startService(i);
        } catch (Exception ignored) {
            // e.g. a background start blocked on Android 12+ — the web app keeps its own clock
        }
    }

    /**
     * Tear it down. Deliberately not a {@link #kick}: starting the service only to have it stop
     * itself would flash a notification on screen. Stopping it drops the notification with it.
     */
    static void halt(Context ctx) {
        try {
            ctx.stopService(new Intent(ctx, FocusService.class));
        } catch (Exception ignored) {
        }
    }
}
