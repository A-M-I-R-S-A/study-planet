package com.focus.app;

import android.content.Context;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.os.Build;
import android.provider.Settings;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;

/**
 * The full-screen "stay focused" panel drawn on top of a blocked app.
 *
 * A window overlay is used rather than launching an Activity because Android 10+ blocks
 * background activity starts, which is exactly the situation here — the decision to block
 * happens inside a service while another app is in front.
 */
final class BlockOverlay {
    private final Context ctx;
    private final WindowManager wm;
    private View view;
    private TextView timeView, msgView;

    BlockOverlay(Context ctx) {
        this.ctx = ctx;
        this.wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
    }

    static boolean canDraw(Context c) {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(c);
    }

    boolean isShowing() {
        return view != null;
    }

    /**
     * @param appLabel the app being blocked, shown so the panel does not feel like a crash
     * @param time     remaining time on the session, or null to hide the clock
     */
    void show(String appLabel, String time) {
        if (view != null) {
            update(appLabel, time);
            return;
        }
        if (!canDraw(ctx) || wm == null) return;

        View v = LayoutInflater.from(ctx).inflate(R.layout.overlay_block, null);
        timeView = v.findViewById(R.id.blockTime);
        msgView = v.findViewById(R.id.blockMsg);

        v.findViewById(R.id.blockOpen).setOnClickListener(x -> {
            hide();
            Intent open = new Intent(ctx, MainActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            ctx.startActivity(open);
        });
        v.findViewById(R.id.blockHome).setOnClickListener(x -> {
            hide();
            goHome();
        });
        // Back dismisses to the home screen rather than back into the blocked app, and never
        // traps the user behind a window they cannot close.
        v.setFocusableInTouchMode(true);
        v.setOnKeyListener((view, keyCode, event) -> {
            if (keyCode == android.view.KeyEvent.KEYCODE_BACK) {
                hide();
                goHome();
                return true;
            }
            return false;
        });

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
                type,
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.CENTER;

        try {
            wm.addView(v, lp);
            view = v;
            update(appLabel, time);
        } catch (Exception ignored) {
            // permission revoked between the check and the add, or the window already exists
            view = null;
        }
    }

    void update(String appLabel, String time) {
        if (view == null) return;
        if (msgView != null) {
            msgView.setText(appLabel == null || appLabel.isEmpty()
                    ? ctx.getString(R.string.block_msg_generic)
                    : ctx.getString(R.string.block_msg, appLabel));
        }
        if (timeView != null) {
            timeView.setText(time == null ? "" : time);
            timeView.setVisibility(time == null ? View.GONE : View.VISIBLE);
        }
    }

    void hide() {
        if (view == null) return;
        try {
            wm.removeView(view);
        } catch (Exception ignored) {
        }
        view = null;
        timeView = null;
        msgView = null;
    }

    private void goHome() {
        try {
            ctx.startActivity(new Intent(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_HOME)
                    .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception ignored) {
        }
    }
}
