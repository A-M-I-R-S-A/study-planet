package com.focus.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

/**
 * Plays one downloaded track on a loop.
 *
 * It lives in a foreground service rather than in the page because WebView audio is suspended
 * as soon as the screen locks — which is exactly when a study session wants its music. The
 * player also takes a partial wake lock, so the CPU stays up between buffers with the screen
 * off. Only ever one track at a time; starting another replaces it.
 */
public class MusicService extends Service {

    static final String ACTION_PLAY = "com.focus.app.action.MUSIC_PLAY";
    static final String ACTION_PAUSE = "com.focus.app.action.MUSIC_PAUSE";
    static final String ACTION_RESUME = "com.focus.app.action.MUSIC_RESUME";
    static final String ACTION_STOP = "com.focus.app.action.MUSIC_STOP";
    static final String ACTION_VOLUME = "com.focus.app.action.MUSIC_VOLUME";

    static final String EX_ID = "id", EX_NAME = "name", EX_PATH = "path", EX_VOL = "vol";

    private static final String CH_MUSIC = "focus_music";
    private static final int NOTIF_ID = 1003;

    /* Statics, so the plugin can answer getState() whether or not the service is up. */
    private static String curId = "", curName = "";
    private static boolean playing = false;
    private static int volume = 45;

    private MediaPlayer player;
    private NotificationManager nm;
    private AudioManager am;
    private AudioManager.OnAudioFocusChangeListener focusListener;

    static String currentId() { return curId; }

    static String currentName() { return curName; }

    static boolean isPlaying() { return playing; }

    static int currentVolume() { return volume; }

    /** True while a track is loaded, playing or paused — i.e. the notification is up. */
    static boolean isLoaded() { return !curId.isEmpty(); }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // A foreground service has to post its notification within seconds of starting, on
        // every path in — including the null-intent restart handed back after a process kill.
        startForegroundSafely(buildNotification());

        String action = intent == null ? null : intent.getAction();
        if (ACTION_PLAY.equals(action)) {
            if (intent.hasExtra(EX_VOL)) volume = clampVol(intent.getIntExtra(EX_VOL, volume));
            start(intent.getStringExtra(EX_ID), intent.getStringExtra(EX_NAME), intent.getStringExtra(EX_PATH));
        } else if (ACTION_PAUSE.equals(action)) {
            pause();
        } else if (ACTION_RESUME.equals(action)) {
            resume();
        } else if (ACTION_VOLUME.equals(action)) {
            applyVolume(clampVol(intent.getIntExtra(EX_VOL, volume)));
        } else if (ACTION_STOP.equals(action)) {
            shutdown();
            return START_NOT_STICKY;
        }

        // Nothing loaded (e.g. the OS restarted us with no intent): there is no track to pick
        // back up, so drop the notification rather than leave a dead one sitting there.
        if (curId.isEmpty()) {
            shutdown();
            return START_NOT_STICKY;
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        release();
        playing = false;
        curId = "";
        curName = "";
        super.onDestroy();
    }

    /* ------------------------------------------------------------------------- playback */

    private void start(String id, String name, String path) {
        if (id == null || path == null) {
            shutdown();
            return;
        }
        release();
        curId = id;
        curName = name == null ? "" : name;
        playing = false;
        try {
            player = new MediaPlayer();
            player.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build());
            player.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
            player.setDataSource(path);
            player.setLooping(true);
            player.setOnPreparedListener(mp -> {
                applyGain();
                requestFocus();
                mp.start();
                playing = true;
                push();
            });
            player.setOnErrorListener((mp, what, extra) -> {
                shutdown();
                return true;
            });
            player.prepareAsync();
            push();
        } catch (Exception e) {
            shutdown();
        }
    }

    private void pause() {
        try {
            if (player != null && player.isPlaying()) player.pause();
        } catch (Exception ignored) {
        }
        playing = false;
        push();
    }

    private void resume() {
        if (player == null) return;
        try {
            requestFocus();
            player.start();
            playing = true;
        } catch (Exception ignored) {
        }
        push();
    }

    private void applyVolume(int v) {
        volume = v;
        applyGain();
        // No push(): the notification says nothing about volume, and the page already knows.
    }

    private void applyGain() {
        try {
            // Matches the web mixer's ceiling so a downloaded track and a synthesised one sit
            // at the same level for a given slider position.
            float g = Math.max(0f, Math.min(1f, volume / 100f)) * 0.6f;
            if (player != null) player.setVolume(g, g);
        } catch (Exception ignored) {
        }
    }

    private static int clampVol(int v) {
        return Math.max(0, Math.min(100, v));
    }

    private void release() {
        abandonFocus();
        if (player == null) return;
        try {
            player.reset();
            player.release();
        } catch (Exception ignored) {
        }
        player = null;
    }

    private void shutdown() {
        release();
        playing = false;
        curId = "";
        curName = "";
        push();
        try {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE);
        } catch (Exception ignored) {
        }
        stopSelf();
    }

    /* -------------------------------------------------------------------- audio focus */

    private void requestFocus() {
        if (am == null) return;
        try {
            if (focusListener == null) {
                focusListener = change -> {
                    // A call or another player took over: pause rather than talk over it.
                    if (change == AudioManager.AUDIOFOCUS_LOSS
                            || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) pause();
                };
            }
            am.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN);
        } catch (Exception ignored) {
        }
    }

    private void abandonFocus() {
        try {
            if (am != null && focusListener != null) am.abandonAudioFocus(focusListener);
        } catch (Exception ignored) {
        }
    }

    /* ------------------------------------------------------------------ notification */

    /** Refresh the notification and let the page know, wherever the change came from. */
    private void push() {
        try {
            if (!curId.isEmpty()) {
                Notification n = buildNotification();
                if (n != null && nm != null) nm.notify(NOTIF_ID, n);
            }
        } catch (Exception ignored) {
        }
        MusicPlugin.onNativeStateChanged();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel ch = new NotificationChannel(
                CH_MUSIC, getString(R.string.ch_music), NotificationManager.IMPORTANCE_LOW);
        ch.setDescription(getString(R.string.ch_music_desc));
        ch.setShowBadge(false);
        ch.setSound(null, null);
        nm.createNotificationChannel(ch);
    }

    private void startForegroundSafely(Notification n) {
        if (n == null) return;
        try {
            int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
                    : 0;
            ServiceCompat.startForeground(this, NOTIF_ID, n, type);
        } catch (Exception ignored) {
        }
    }

    private Notification buildNotification() {
        String title = curName.isEmpty() ? getString(R.string.ch_music) : curName;
        PendingIntent open = PendingIntent.getActivity(this, 2,
                new Intent(this, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                flags(PendingIntent.FLAG_UPDATE_CURRENT));

        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CH_MUSIC)
                .setSmallIcon(R.drawable.ic_stat_focus)
                .setContentTitle(title)
                .setContentText(getString(playing ? R.string.music_playing : R.string.music_paused))
                .setContentIntent(open)
                .setOngoing(playing)
                .setSilent(true)
                .setShowWhen(false)
                .setOnlyAlertOnce(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setCategory(NotificationCompat.CATEGORY_TRANSPORT);

        if (playing) b.addAction(0, getString(R.string.act_pause), pi(ACTION_PAUSE, 21));
        else b.addAction(0, getString(R.string.act_resume), pi(ACTION_RESUME, 22));
        b.addAction(0, getString(R.string.act_stop), pi(ACTION_STOP, 23));
        return b.build();
    }

    private PendingIntent pi(String action, int rq) {
        Intent i = new Intent(this, MusicService.class).setAction(action);
        return PendingIntent.getService(this, rq, i, flags(PendingIntent.FLAG_UPDATE_CURRENT));
    }

    private static int flags(int base) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                ? base | PendingIntent.FLAG_IMMUTABLE
                : base;
    }

    /* ---------------------------------------------------------------------- launching */

    static void send(Context ctx, Intent i) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i);
            else ctx.startService(i);
        } catch (Exception ignored) {
            // e.g. a background start blocked on Android 12+ — nothing plays, nothing breaks
        }
    }

    static void halt(Context ctx) {
        try {
            ctx.stopService(new Intent(ctx, MusicService.class));
        } catch (Exception ignored) {
        }
        playing = false;
        curId = "";
        curName = "";
    }
}
