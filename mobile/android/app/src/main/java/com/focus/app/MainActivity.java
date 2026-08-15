package com.focus.app;

import android.app.DownloadManager;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.widget.Toast;

import com.getcapacitor.BridgeActivity;

import java.net.URLDecoder;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Registered before super so the bridge picks them up while building the WebView.
        registerPlugin(FocusPlugin.class);
        registerPlugin(MusicPlugin.class);
        super.onCreate(savedInstanceState);
        wireDownloads();   // after super: the WebView only exists once the bridge is built
    }

    /* ---- library downloads ----
       A WebView has no download of its own. When a page navigates to something that comes
       back as an attachment — or to any type the WebView can't render, a PDF included —
       Android hands it to the WebView's DownloadListener, and with none set the navigation
       is dropped without a word. That is why the library's Download button did nothing in
       the app while working in a browser.

       Passing the URL to Android's DownloadManager is the whole fix, and it brings the
       progress notification, the retry and the tap-to-open that a browser download has. */
    private void wireDownloads() {
        if (getBridge() == null || getBridge().getWebView() == null) return;
        getBridge().getWebView().setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String disposition,
                                        String mimeType, long contentLength) {
                download(url, userAgent, disposition, mimeType);
            }
        });
    }

    private void download(String url, String userAgent, String disposition, String mimeType) {
        String name = fileName(url, disposition, mimeType);
        try {
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            // Library files sit behind the session cookie. DownloadManager makes its own
            // request, outside the WebView, so the cookie has to be carried over by hand —
            // without this every download would save the "not signed in" JSON instead.
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) req.addRequestHeader("Cookie", cookie);
            if (userAgent != null) req.addRequestHeader("User-Agent", userAgent);
            if (mimeType != null) req.setMimeType(mimeType);
            req.setTitle(name);
            req.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            // The public Downloads folder needs no permission from Android 10 on. Below
            // that it would mean asking for storage access in the middle of a tap, so those
            // devices get the app's own external folder instead — same notification, same
            // tap-to-open, no prompt.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            } else {
                req.setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, name);
            }
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm == null) throw new IllegalStateException("DownloadManager unavailable");
            dm.enqueue(req);
            Toast.makeText(this, getString(R.string.dl_started, name), Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            // A failed download must say so: the whole bug being fixed here was one that
            // failed in silence.
            Toast.makeText(this, R.string.dl_failed, Toast.LENGTH_LONG).show();
        }
    }

    private static final Pattern RFC5987 =
            Pattern.compile("filename\\*\\s*=\\s*UTF-8''([^;]+)", Pattern.CASE_INSENSITIVE);

    /** What to save the file as.
     *
     * The RFC 5987 field is read first because it is the only one that survives a Persian
     * filename; URLUtil reads the plain `filename=` beside it, which the server has had to
     * strip down to ASCII. Whatever comes out is treated as untrusted: DownloadManager
     * wants a bare name, so anything that could climb out of the download directory is
     * replaced rather than relied on to be harmless.
     */
    private String fileName(String url, String disposition, String mimeType) {
        String name = null;
        if (disposition != null) {
            Matcher m = RFC5987.matcher(disposition);
            if (m.find()) {
                try {
                    name = URLDecoder.decode(m.group(1).trim(), "UTF-8");
                } catch (Exception ignored) {
                    // fall through to the ASCII field below
                }
            }
        }
        if (name == null || name.trim().isEmpty()) {
            name = URLUtil.guessFileName(url, disposition, mimeType);
        }
        name = name.replaceAll("[\\\\/:*?\"<>|\\x00-\\x1f]", "_").trim();
        if (name.isEmpty() || name.equals(".") || name.equals("..")) name = "download";
        return name;
    }
}
