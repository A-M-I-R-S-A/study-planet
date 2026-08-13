package com.focus.app;

import android.Manifest;
import android.app.AppOpsManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.net.Uri;
import android.os.Build;
import android.os.Process;
import android.provider.Settings;
import android.util.Base64;

import androidx.core.app.NotificationManagerCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.ByteArrayOutputStream;
import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The bridge the web app talks to for the two things it cannot do itself: keep the session
 * ticking in the notification bar, and lock other apps out during a focus block.
 *
 * Every method is a no-op on the plain web, where {@code Capacitor.Plugins.Focus} is undefined.
 */
@CapacitorPlugin(
        name = "Focus",
        permissions = {
                @Permission(alias = "notifications", strings = {Manifest.permission.POST_NOTIFICATIONS})
        }
)
public class FocusPlugin extends Plugin {

    /** Set while the WebView is alive so the service can push notification-button changes back. */
    private static WeakReference<FocusPlugin> live = new WeakReference<>(null);

    @Override
    public void load() {
        live = new WeakReference<>(this);
    }

    @Override
    protected void handleOnDestroy() {
        if (live.get() == this) live = new WeakReference<>(null);
        super.handleOnDestroy();
    }

    /** Called from {@link FocusService} when Pause/Resume/End was tapped, or the block expired. */
    static void onNativeStateChanged(Context ctx) {
        FocusPlugin p = live.get();
        if (p == null) return;
        try {
            p.notifyListeners("timerState", p.stateOf(ctx));
        } catch (Exception ignored) {
        }
    }

    /* -------------------------------------------------------------------------- the timer */

    /**
     * Push the web app's clock into the service. Called on every start/pause/reset/phase change,
     * so the notification and the WebView never disagree about the session.
     */
    @PluginMethod
    public void sync(PluginCall call) {
        Context ctx = getContext();
        long now = System.currentTimeMillis();
        boolean running = Boolean.TRUE.equals(call.getBoolean("running", false));
        String type = call.getString("type", "timer");
        double remain = call.getDouble("remainingSec", 0d);
        double elapsed = call.getDouble("elapsedSec", 0d);

        FocusState.prefs(ctx).edit()
                .putBoolean(FocusState.K_KNOWN, true)
                .putBoolean(FocusState.K_RUNNING, running)
                .putBoolean(FocusState.K_CLEARED, false)
                .putString(FocusState.K_ENDED_BY, "")
                .putString(FocusState.K_TYPE, type)
                .putString(FocusState.K_MODE, call.getString("mode", "focus"))
                .putString(FocusState.K_LABEL, call.getString("label", ""))
                .putLong(FocusState.K_ENDS_AT, now + (long) (remain * 1000))
                .putLong(FocusState.K_REMAIN, (long) remain)
                .putLong(FocusState.K_ELAPSED, (long) elapsed)
                .putLong(FocusState.K_ANCHOR, now)
                .apply();

        FocusService.kick(ctx, FocusService.ACTION_SYNC);
        call.resolve(stateOf(ctx));
    }

    /** Tear the session down completely — no notification, no lock, nothing left to finalise. */
    @PluginMethod
    public void stop(PluginCall call) {
        Context ctx = getContext();
        FocusState.prefs(ctx).edit()
                .putBoolean(FocusState.K_KNOWN, false)
                .putBoolean(FocusState.K_RUNNING, false)
                .putBoolean(FocusState.K_CLEARED, false)
                .putLong(FocusState.K_REMAIN, 0)
                .putLong(FocusState.K_ELAPSED, 0)
                .apply();
        FocusService.halt(ctx);
        call.resolve();
    }

    /** What the service thinks is going on — the web app adopts this on every resume. */
    @PluginMethod
    public void getState(PluginCall call) {
        call.resolve(stateOf(getContext()));
    }

    private JSObject stateOf(Context ctx) {
        SharedPreferences p = FocusState.prefs(ctx);
        long now = System.currentTimeMillis();
        JSObject o = new JSObject();
        o.put("known", p.getBoolean(FocusState.K_KNOWN, false));
        o.put("running", p.getBoolean(FocusState.K_RUNNING, false));
        o.put("cleared", p.getBoolean(FocusState.K_CLEARED, false));
        o.put("endedBy", p.getString(FocusState.K_ENDED_BY, ""));
        o.put("type", p.getString(FocusState.K_TYPE, "timer"));
        o.put("mode", p.getString(FocusState.K_MODE, "focus"));
        o.put("label", p.getString(FocusState.K_LABEL, ""));
        o.put("remainingSec", FocusState.remainingSec(p, now));
        o.put("elapsedSec", FocusState.elapsedSec(p, now));
        o.put("rev", p.getInt(FocusState.K_REV, 0));
        return o;
    }

    /* ----------------------------------------------------------------------- the app lock */

    @PluginMethod
    public void getLockConfig(PluginCall call) {
        SharedPreferences p = FocusState.prefs(getContext());
        JSObject o = new JSObject();
        o.put("enabled", p.getBoolean(FocusState.K_LOCK_ON, false));
        o.put("duringBreaks", p.getBoolean(FocusState.K_LOCK_BREAKS, false));
        o.put("mute", p.getBoolean(FocusState.K_MUTE_ON, false));
        JSArray allowed = new JSArray();
        for (String pkg : FocusState.allowList(getContext())) allowed.put(pkg);
        o.put("allowed", allowed);
        call.resolve(o);
    }

    @PluginMethod
    public void setLockConfig(PluginCall call) {
        Context ctx = getContext();
        SharedPreferences.Editor e = FocusState.prefs(ctx).edit();
        if (call.hasOption("enabled")) e.putBoolean(FocusState.K_LOCK_ON, call.getBoolean("enabled", false));
        if (call.hasOption("duringBreaks")) e.putBoolean(FocusState.K_LOCK_BREAKS, call.getBoolean("duringBreaks", false));
        if (call.hasOption("mute")) e.putBoolean(FocusState.K_MUTE_ON, call.getBoolean("mute", false));
        if (call.hasOption("allowed")) {
            Set<String> pkgs = new HashSet<>();
            try {
                JSArray arr = call.getArray("allowed");
                if (arr != null) for (Object o : arr.toList()) if (o != null) pkgs.add(String.valueOf(o));
            } catch (Exception ignored) {
            }
            e.putStringSet(FocusState.K_ALLOW, pkgs);
        }
        e.apply();
        // No need to poke the service: it re-reads these on every tick, so a change made
        // mid-session takes effect within a second, and outside one there is nothing to poke.
        getLockConfig(call);
    }

    /**
     * Every launchable app on the device, for the allow-list picker. Icons come back as data
     * URLs so the WebView can render them without any file access.
     */
    @PluginMethod
    public void getInstalledApps(final PluginCall call) {
        final boolean withIcons = Boolean.TRUE.equals(call.getBoolean("icons", true));
        // Hundreds of icons to rasterise — never on the UI thread.
        new Thread(() -> {
            try {
                PackageManager pm = getContext().getPackageManager();
                Intent launchable = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
                List<ResolveInfo> found = pm.queryIntentActivities(launchable, 0);
                Set<String> seen = new HashSet<>();
                List<JSObject> out = new ArrayList<>();
                String self = getContext().getPackageName();

                for (ResolveInfo ri : found) {
                    if (ri.activityInfo == null) continue;
                    String pkg = ri.activityInfo.packageName;
                    if (pkg == null || pkg.equals(self) || !seen.add(pkg)) continue;
                    JSObject a = new JSObject();
                    a.put("package", pkg);
                    a.put("name", String.valueOf(ri.loadLabel(pm)));
                    a.put("system", isSystem(pm, pkg));
                    if (withIcons) {
                        String icon = iconDataUrl(ri.loadIcon(pm));
                        if (icon != null) a.put("icon", icon);
                    }
                    out.add(a);
                }
                Collections.sort(out, (x, y) ->
                        x.optString("name", "").compareToIgnoreCase(y.optString("name", "")));

                JSArray apps = new JSArray();
                for (JSObject a : out) apps.put(a);
                JSObject res = new JSObject();
                res.put("apps", apps);
                call.resolve(res);
            } catch (Exception e) {
                call.reject("Could not list installed apps: " + e.getMessage());
            }
        }).start();
    }

    private static boolean isSystem(PackageManager pm, String pkg) {
        try {
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            return (ai.flags & ApplicationInfo.FLAG_SYSTEM) != 0;
        } catch (Exception e) {
            return false;
        }
    }

    private static String iconDataUrl(Drawable d) {
        if (d == null) return null;
        try {
            int size = 96;
            Bitmap bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
            Canvas c = new Canvas(bmp);
            d.setBounds(0, 0, size, size);
            d.draw(c);
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            bmp.compress(Bitmap.CompressFormat.PNG, 100, bos);
            bmp.recycle();
            return "data:image/png;base64," + Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP);
        } catch (Exception e) {
            return null;
        }
    }

    /* ---------------------------------------------------------------------- permissions */

    /** The three grants the features need, so the UI can show only the missing ones. */
    @PluginMethod
    public void checkPerms(PluginCall call) {
        Context ctx = getContext();
        JSObject o = new JSObject();
        o.put("usage", hasUsageAccess(ctx));
        o.put("overlay", BlockOverlay.canDraw(ctx));
        o.put("notifications", NotificationManagerCompat.from(ctx).areNotificationsEnabled());
        o.put("battery", ignoringBatteryOptimizations(ctx));
        o.put("dnd", hasDndAccess(ctx));
        call.resolve(o);
    }

    /** Do Not Disturb access — the only sanctioned way to quiet other apps' notifications. */
    static boolean hasDndAccess(Context ctx) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return false;
        try {
            android.app.NotificationManager nm =
                    (android.app.NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            return nm != null && nm.isNotificationPolicyAccessGranted();
        } catch (Exception e) {
            return false;
        }
    }

    static boolean hasUsageAccess(Context ctx) {
        try {
            AppOpsManager ops = (AppOpsManager) ctx.getSystemService(Context.APP_OPS_SERVICE);
            if (ops == null) return false;
            int mode;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                mode = ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                        Process.myUid(), ctx.getPackageName());
            } else {
                mode = ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                        Process.myUid(), ctx.getPackageName());
            }
            if (mode == AppOpsManager.MODE_DEFAULT) {
                return ctx.checkCallingOrSelfPermission(
                        "android.permission.PACKAGE_USAGE_STATS") == PackageManager.PERMISSION_GRANTED;
            }
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    private static boolean ignoringBatteryOptimizations(Context ctx) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true;
        try {
            android.os.PowerManager pm = (android.os.PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
            return pm != null && pm.isIgnoringBatteryOptimizations(ctx.getPackageName());
        } catch (Exception e) {
            return true;
        }
    }

    /** Usage access and overlay are special grants — only reachable through a Settings screen. */
    @PluginMethod
    public void openUsageAccess(PluginCall call) {
        openSettings(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS), call);
    }

    @PluginMethod
    public void openOverlaySettings(PluginCall call) {
        Intent i = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                ? new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:" + getContext().getPackageName()))
                : new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:" + getContext().getPackageName()));
        openSettings(i, call);
    }

    @PluginMethod
    public void openBatterySettings(PluginCall call) {
        openSettings(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), call);
    }

    @PluginMethod
    public void openDndSettings(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            call.reject("This version of Android can't hand Do Not Disturb to an app.");
            return;
        }
        openSettings(new Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS), call);
    }

    @PluginMethod
    public void requestNotifications(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
                || getPermissionState("notifications") == com.getcapacitor.PermissionState.GRANTED) {
            checkPerms(call);
            return;
        }
        requestPermissionForAlias("notifications", call, "afterNotifications");
    }

    @PermissionCallback
    private void afterNotifications(PluginCall call) {
        checkPerms(call);
    }

    private void openSettings(Intent i, PluginCall call) {
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            call.resolve();
        } catch (Exception e) {
            call.reject("Could not open that settings screen on this device.");
        }
    }
}
