package com.focus.app;

import android.content.Context;
import android.content.Intent;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.ref.WeakReference;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashSet;
import java.util.Set;

/**
 * Downloads tracks to the app's own storage and hands them to {@link MusicService} to play.
 *
 * The download runs here in native code rather than in the page, which means it is not subject
 * to the page's Content-Security-Policy — the WebView could not fetch a remote host under
 * {@code connect-src 'self'} anyway. The catalogue of tracks lives in the web layer; this side
 * only ever sees an id, a name and a URL.
 */
@CapacitorPlugin(name = "Music")
public class MusicPlugin extends Plugin {

    private static WeakReference<MusicPlugin> live = new WeakReference<>(null);

    /** Ids currently downloading, so a second tap doesn't start a parallel fetch. */
    private static final Set<String> inFlight = new HashSet<>();

    @Override
    public void load() {
        live = new WeakReference<>(this);
    }

    @Override
    protected void handleOnDestroy() {
        if (live.get() == this) live = new WeakReference<>(null);
        super.handleOnDestroy();
    }

    /** Called from {@link MusicService} whenever playback state changes, including from the
     *  notification's own buttons. */
    static void onNativeStateChanged() {
        MusicPlugin p = live.get();
        if (p == null) return;
        try {
            p.notifyListeners("musicState", p.state());
        } catch (Exception ignored) {
        }
    }

    /* ------------------------------------------------------------------------- state */

    @PluginMethod
    public void getState(PluginCall call) {
        call.resolve(state());
    }

    private JSObject state() {
        JSObject o = new JSObject();
        o.put("id", MusicService.currentId());
        o.put("name", MusicService.currentName());
        o.put("playing", MusicService.isPlaying());
        o.put("loaded", MusicService.isLoaded());
        o.put("volume", MusicService.currentVolume());
        return o;
    }

    /** Whether a given track is already on disk, and how big it is. */
    @PluginMethod
    public void isDownloaded(PluginCall call) {
        String id = call.getString("id", "");
        File f = fileFor(getContext(), id);
        JSObject o = new JSObject();
        o.put("id", id);
        o.put("downloaded", f != null && f.exists() && f.length() > 0);
        o.put("bytes", f != null && f.exists() ? f.length() : 0);
        o.put("downloading", inFlight.contains(id));
        call.resolve(o);
    }

    /* ---------------------------------------------------------------------- download */

    @PluginMethod
    public void download(final PluginCall call) {
        final String id = call.getString("id", "");
        final String url = call.getString("url", "");
        if (id.isEmpty() || url.isEmpty()) {
            call.reject("A track needs both an id and a url.");
            return;
        }
        final File target = fileFor(getContext(), id);
        if (target == null) {
            call.reject("Could not open the app's music folder.");
            return;
        }
        if (target.exists() && target.length() > 0) {
            JSObject o = new JSObject();
            o.put("id", id);
            o.put("downloaded", true);
            o.put("bytes", target.length());
            call.resolve(o);
            return;
        }
        synchronized (inFlight) {
            if (inFlight.contains(id)) {
                call.reject("That track is already downloading.");
                return;
            }
            inFlight.add(id);
        }

        new Thread(() -> {
            // Write to a .part file first so a half-finished download can never be mistaken
            // for a playable track if the app dies mid-fetch.
            File part = new File(target.getPath() + ".part");
            HttpURLConnection conn = null;
            InputStream in = null;
            FileOutputStream out = null;
            try {
                conn = (HttpURLConnection) new URL(url).openConnection();
                conn.setConnectTimeout(20000);
                conn.setReadTimeout(30000);
                conn.setInstanceFollowRedirects(true);
                conn.connect();
                int code = conn.getResponseCode();
                if (code < 200 || code >= 300) throw new Exception("server said " + code);

                long total = conn.getContentLength();
                in = conn.getInputStream();
                out = new FileOutputStream(part);
                byte[] buf = new byte[16 * 1024];
                long got = 0;
                int lastPct = -1;
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    got += n;
                    int pct = total > 0 ? (int) (got * 100 / total) : -1;
                    if (pct != lastPct) {
                        lastPct = pct;
                        emitProgress(id, pct, got, total);
                    }
                }
                out.flush();
                out.close();
                out = null;
                if (part.length() <= 0) throw new Exception("empty file");
                if (target.exists() && !target.delete()) throw new Exception("could not replace the old file");
                if (!part.renameTo(target)) throw new Exception("could not save the download");

                JSObject o = new JSObject();
                o.put("id", id);
                o.put("downloaded", true);
                o.put("bytes", target.length());
                call.resolve(o);
            } catch (Exception e) {
                call.reject("Could not download that track: " + e.getMessage());
            } finally {
                close(out);
                close(in);
                if (conn != null) try { conn.disconnect(); } catch (Exception ignored) { }
                if (part.exists()) part.delete();
                synchronized (inFlight) {
                    inFlight.remove(id);
                }
            }
        }).start();
    }

    private void emitProgress(String id, int pct, long got, long total) {
        try {
            JSObject o = new JSObject();
            o.put("id", id);
            o.put("percent", pct);
            o.put("bytes", got);
            o.put("total", total);
            notifyListeners("musicDownload", o);
        } catch (Exception ignored) {
        }
    }

    /** Throw a downloaded track away again. */
    @PluginMethod
    public void remove(PluginCall call) {
        String id = call.getString("id", "");
        if (id.equals(MusicService.currentId())) MusicService.halt(getContext());
        File f = fileFor(getContext(), id);
        if (f != null && f.exists()) f.delete();
        isDownloaded(call);
    }

    /* ---------------------------------------------------------------------- playback */

    @PluginMethod
    public void play(PluginCall call) {
        String id = call.getString("id", "");
        File f = fileFor(getContext(), id);
        if (f == null || !f.exists() || f.length() <= 0) {
            call.reject("That track hasn't been downloaded yet.");
            return;
        }
        Intent i = new Intent(getContext(), MusicService.class)
                .setAction(MusicService.ACTION_PLAY)
                .putExtra(MusicService.EX_ID, id)
                .putExtra(MusicService.EX_NAME, call.getString("name", id))
                .putExtra(MusicService.EX_PATH, f.getAbsolutePath());
        if (call.hasOption("volume")) i.putExtra(MusicService.EX_VOL, call.getInt("volume", 45));
        MusicService.send(getContext(), i);
        call.resolve(state());
    }

    @PluginMethod
    public void pause(PluginCall call) {
        kick(MusicService.ACTION_PAUSE);
        call.resolve(state());
    }

    @PluginMethod
    public void resume(PluginCall call) {
        kick(MusicService.ACTION_RESUME);
        call.resolve(state());
    }

    @PluginMethod
    public void stop(PluginCall call) {
        MusicService.halt(getContext());
        call.resolve(state());
    }

    @PluginMethod
    public void setVolume(PluginCall call) {
        if (!MusicService.isLoaded()) {
            call.resolve(state());
            return;
        }
        Intent i = new Intent(getContext(), MusicService.class)
                .setAction(MusicService.ACTION_VOLUME)
                .putExtra(MusicService.EX_VOL, call.getInt("volume", 45));
        MusicService.send(getContext(), i);
        call.resolve(state());
    }

    private void kick(String action) {
        if (!MusicService.isLoaded()) return;   // nothing loaded: don't spin the service up
        MusicService.send(getContext(), new Intent(getContext(), MusicService.class).setAction(action));
    }

    /* ------------------------------------------------------------------------- files */

    private static File fileFor(Context ctx, String id) {
        String safe = id == null ? "" : id.replaceAll("[^A-Za-z0-9_-]", "");
        if (safe.isEmpty()) return null;
        File dir = new File(ctx.getFilesDir(), "music");
        if (!dir.exists() && !dir.mkdirs()) return null;
        return new File(dir, safe + ".mp3");
    }

    private static void close(java.io.Closeable c) {
        if (c == null) return;
        try {
            c.close();
        } catch (Exception ignored) {
        }
    }
}
