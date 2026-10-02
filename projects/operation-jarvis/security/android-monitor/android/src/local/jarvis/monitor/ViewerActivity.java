package local.jarvis.monitor;

import android.app.Activity;
import android.app.KeyguardManager;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.io.*;
import org.json.JSONObject;
import com.google.android.exoplayer2.*;
import com.google.android.exoplayer2.analytics.AnalyticsListener;
import com.google.android.exoplayer2.decoder.DecoderCounters;
import com.google.android.exoplayer2.source.rtsp.RtspMediaSource;
import com.google.android.exoplayer2.trackselection.DefaultTrackSelector;
import com.google.android.exoplayer2.video.VideoSize;

/** Isolated :video process. One bounded RTSP/TCP player, native hardware surface.
 * No ad SDK, WebView, frame bitmaps, recording, audio, or credential-bearing Intent.
 */
public final class ViewerActivity extends Activity {
    private final Handler handler = new Handler();
    private final StreamHealth health = new StreamHealth();
    private SurfaceView surface;
    private TextView status;
    private ExoPlayer player;
    private CameraSocketFactory transport;
    private boolean resumed, retryPending;
    private int generation, decoded, displayed, opens, releases;
    private long lastSample;
    private int lastDisplayed;
    private String phase = "Stopped", decoder = "pending";
    private final Runnable retry = new Runnable() { public void run() {
        retryPending = false;
        if (resumed && unlocked()) open();
    }};
    private final Runnable sample = new Runnable() { public void run() {
        if (!resumed || player == null) return;
        if (!unlocked()) { close(); show("Paused while locked"); return; }
        DecoderCounters counters = player.getVideoDecoderCounters();
        if (counters != null) {
            counters.ensureUpdated();
            displayed = counters.renderedOutputBufferCount;
            decoded = displayed + counters.skippedOutputBufferCount + counters.droppedBufferCount;
        }
        long now = SystemClock.elapsedRealtime();
        if (health.stalled(displayed, now)) { failed(); return; }
        if (displayed > 0) {
            long interval = now - lastSample;
            int fps = interval > 0 ? (int)Math.max(0, (displayed - lastDisplayed) * 1000L / interval) : 0;
            show("Front door · H264 / TCP · " + fps + " fps");
        }
        lastSample = now; lastDisplayed = displayed;
        handler.postDelayed(this, 2000);
    }};
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        // The Java RTSP implementation strips URI user-info before requests.
        // Disable library diagnostics as an additional guard against URI logging.
        com.google.android.exoplayer2.util.Log.setLogger(new PlayerDiagnostics());
        com.google.android.exoplayer2.util.Log.setLogLevel(com.google.android.exoplayer2.util.Log.LOG_LEVEL_ALL);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON |
            WindowManager.LayoutParams.FLAG_FULLSCREEN);
        FrameLayout layout = new FrameLayout(this);
        layout.setBackgroundColor(0xff000000);
        surface = new SurfaceView(this);
        layout.addView(surface, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        status = new TextView(this); status.setTextColor(0xffffffff); status.setTextSize(16);
        status.setBackgroundColor(0x88000000); status.setPadding(16, 8, 16, 8);
        layout.addView(status, new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.LEFT));
        status.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            if (player == null && resumed && unlocked()) { health.reset(); open(); }
        }});
        status.setOnLongClickListener(new View.OnLongClickListener() { public boolean onLongClick(View v) {
            if (transport == null || !resumed || !unlocked()) return false;
            try { transport.interrupt(); } catch (IOException e) { failed(); }
            return true;
        }});
        setContentView(layout);
        show("Starting private camera viewer");
    }
    private boolean unlocked() {
        KeyguardManager k = (KeyguardManager)getSystemService(KEYGUARD_SERVICE);
        return ((PowerManager)getSystemService(POWER_SERVICE)).isInteractive() && !k.isKeyguardLocked();
    }
    @Override public void onResume() {
        super.onResume(); resumed = true; health.reset();
        if (unlocked()) open(); else show("Unlock to view camera");
    }
    @Override public void onPause() { resumed = false; close(); show("Paused"); super.onPause(); }
    @Override public void onDestroy() { close(); super.onDestroy(); }
    private Uri source() throws Exception {
        File file = new File(getFilesDir(), "player.json");
        if (file.length() < 1 || file.length() > 4096) throw new Exception();
        byte[] data = new byte[(int)file.length()];
        DataInputStream in = new DataInputStream(new FileInputStream(file));
        try { in.readFully(data); } finally { in.close(); }
        JSONObject c = new JSONObject(new String(data, "UTF-8"));
        String host = c.getString("host"), path = c.getString("path"), user = c.getString("username"), password = c.getString("password");
        int port = c.getInt("port");
        if (c.getInt("version") != 1 || !PlayerConfig.valid(host, port, path, user, password)) throw new Exception();
        return Uri.parse("rtsp://" + Uri.encode(user) + ":" + Uri.encode(password) + "@" + host + ":" + port + path);
    }
    private void open() {
        close();
        if (!resumed || !unlocked()) return;
        final int epoch = generation;
        show("Connecting to camera…");
        try {
            Uri uri = source();
            PlayerDiagnostics.reset();
            DefaultTrackSelector selector = new DefaultTrackSelector(this);
            selector.setParameters(selector.buildUponParameters().setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, true));
            player = new ExoPlayer.Builder(this).setTrackSelector(selector)
                .setLoadControl(new DefaultLoadControl.Builder()
                    .setBufferDurationsMs(500, 1500, 250, 500)
                    .setTargetBufferBytes(2 * 1024 * 1024)
                    .setPrioritizeTimeOverSizeThresholds(false).build()).build();
            player.setVideoSurfaceView(surface);
            player.addListener(new Player.Listener() {
                @Override public void onPlayerError(PlaybackException error) {
                    if (epoch == generation && resumed) failed();
                }
                @Override public void onPlaybackStateChanged(int state) {
                    if (epoch == generation && resumed && state == Player.STATE_ENDED) failed();
                }
                @Override public void onVideoSizeChanged(VideoSize size) {
                    if (epoch != generation || size.width <= 0 || size.height <= 0) return;
                    int w = getResources().getDisplayMetrics().widthPixels;
                    int h = getResources().getDisplayMetrics().heightPixels;
                    double aspect = (double)size.width * size.pixelWidthHeightRatio / size.height;
                    if ((double)w / h > aspect) w = (int)(h * aspect); else h = (int)(w / aspect);
                    surface.setLayoutParams(new FrameLayout.LayoutParams(w, h, Gravity.CENTER));
                }
            });
            player.addAnalyticsListener(new AnalyticsListener() {
                @Override public void onVideoDecoderInitialized(EventTime eventTime, String name,
                        long initializedTimestampMs, long initializationDurationMs) {
                    if (epoch == generation) decoder = name;
                }
            });
            transport = new CameraSocketFactory(uri.getHost());
            RtspMediaSource media = new RtspMediaSource.Factory().setForceUseRtpTcp(true)
                .setSocketFactory(transport).setTimeoutMs(5000).setDebugLoggingEnabled(true)
                .createMediaSource(new MediaItem.Builder().setUri(uri).setMediaId("private-doorbell").build());
            player.setMediaSource(media);
            decoded = displayed = lastDisplayed = 0; decoder = "pending";
            lastSample = SystemClock.elapsedRealtime(); health.opened(lastSample);
            player.prepare(); player.play(); opens++;
            handler.postDelayed(sample, 2000);
        } catch (Exception e) { failed(); } // Never print exception/URI/credentials.
    }
    private void failed() {
        if (retryPending) return;
        close();
        long delay = health.retryDelay();
        if (!resumed || !unlocked()) { show("Paused"); return; }
        if (delay < 0) { show("Camera unavailable · tap here to retry"); return; }
        show("Camera interrupted · reconnecting in " + delay / 1000 + "s");
        retryPending = true;
        handler.postDelayed(retry, delay);
    }
    private void close() {
        generation++;
        handler.removeCallbacksAndMessages(null); retryPending = false;
        if (player != null) {
            player.release(); player = null; releases++;
        }
        transport = null;
    }
    private void show(String text) { phase = text; status.setText(text); }
    @Override public void dump(String prefix, FileDescriptor fd, PrintWriter out, String[] args) {
        super.dump(prefix, fd, out, args);
        out.println(prefix + "viewer resumed=" + resumed + " activePlayer=" + (player != null));
        out.println(prefix + "viewer decoded=" + decoded + " displayed=" + displayed + " decoder=" + decoder);
        out.println(prefix + "viewer opens=" + opens + " releases=" + releases + " retryPending=" + retryPending);
        out.println(prefix + "viewer phase=" + phase);
        out.println(prefix + "viewer protocol=" + PlayerDiagnostics.protocol + " videoSDP=" + PlayerDiagnostics.sdpVideoTracks);
    }
}
