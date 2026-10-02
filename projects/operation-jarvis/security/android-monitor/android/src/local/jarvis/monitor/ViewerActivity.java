package local.jarvis.monitor;

import android.app.Activity;
import android.app.KeyguardManager;
import android.net.Uri;
import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.InsetDrawable;
import android.graphics.drawable.RippleDrawable;
import android.media.AudioManager;
import com.google.android.exoplayer2.audio.AudioAttributes;
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

/** Isolated :video process. One bounded RTSP/TCP player, hardware decoding and optional GPU dewarping.
 * Owner-selected listen-only audio defaults on while foreground/unlocked. No microphone,
 * ad SDK, WebView, frame bitmaps, recording, or credential-bearing Intent.
 */
public final class ViewerActivity extends Activity {
    private final Handler handler = new Handler();
    private final StreamHealth health = new StreamHealth();
    private SurfaceView surface;
    private FrameLayout layout;
    private DewarpView dewarp;
    private Surface decoderSurface;
    private ImageButton lensButton;
    private final ViewerIcon lensIcon = new ViewerIcon(true), audioIcon = new ViewerIcon(false);
    private int lensMode, outputGeneration, glFrameBase, presented, lastPresented;
    private boolean lensFallback;
    private TextView status;
    private ImageButton audioButton;
    private AudioManager audioManager;
    private final ListenAudioPolicy audio = new ListenAudioPolicy();
    private boolean audioFocusHeld, audioReceiverRegistered, audioDisabled, tracksKnown;
    private int audioRendered;
    private String audioDecoder = "pending";
    private final AudioManager.OnAudioFocusChangeListener focusListener =
        new AudioManager.OnAudioFocusChangeListener() { public void onAudioFocusChange(int change) {
            // Loss, transient loss and duck all require another explicit tap. Gain never unmutes.
            if (change != AudioManager.AUDIOFOCUS_GAIN) muteAudio();
        }};
    private final BroadcastReceiver audioReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) { close(); stopOutput(); show("Paused"); }
            else if (AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(intent.getAction())) muteAudio();
        }
    };
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
        DecoderCounters audioCounters = player.getAudioDecoderCounters();
        if (audioCounters != null) {
            audioCounters.ensureUpdated(); audioRendered = audioCounters.renderedOutputBufferCount;
        }
        long now = SystemClock.elapsedRealtime();
        presented = dewarp == null ? displayed : Math.max(0, dewarp.frames() - glFrameBase);
        if (health.stalled(presented, now)) { failed(); return; }
        if (presented > 0) {
            long interval = now - lastSample;
            int fps = interval > 0 ? (int)Math.max(0, (presented - lastPresented) * 1000L / interval) : 0;
            show("Front door · H264 / TCP · " + fps + " fps");
        }
        lastSample = now; lastDisplayed = displayed; lastPresented = presented;
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
        layout = new FrameLayout(this);
        layout.setBackgroundColor(0xff000000);
        lensMode = DewarpView.readMode(this);
        lensButton = iconButton(lensIcon);
        lensButton.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            if (!resumed || !unlocked() || dewarp == null || decoderSurface == null) return;
            lensMode = DewarpModel.next(lensMode);
            dewarp.mode(lensMode); DewarpView.saveMode(ViewerActivity.this, lensMode); updateLensButton();
        }});
        layout.addView(lensButton, iconLayout(Gravity.TOP | Gravity.LEFT));
        updateLensButton();
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
        audioManager = (AudioManager)getSystemService(AUDIO_SERVICE);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        audioButton = iconButton(audioIcon);
        audioButton.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { toggleAudio(); }});
        layout.addView(audioButton, iconLayout(Gravity.TOP | Gravity.RIGHT));
        updateAudioButton();
        setContentView(layout);
        show("Starting private camera viewer");
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private ImageButton iconButton(ViewerIcon icon) {
        final ImageButton button = new ImageButton(this);
        button.setImageDrawable(icon); button.setScaleType(ImageView.ScaleType.FIT_CENTER);
        button.setMinimumWidth(0); button.setMinimumHeight(0);
        GradientDrawable circle = new GradientDrawable(); circle.setShape(GradientDrawable.OVAL);
        circle.setColor(0x66000000); circle.setStroke(dp(1), 0x44ffffff);
        GradientDrawable mask = new GradientDrawable(); mask.setShape(GradientDrawable.OVAL); mask.setColor(0xffffffff);
        button.setBackground(new InsetDrawable(new RippleDrawable(ColorStateList.valueOf(0x55ffffff),
            circle, mask), dp(8)));
        // Background assignment can replace View padding; set the 24dp glyph inset last.
        button.setPadding(dp(12), dp(12), dp(12), dp(12));
        button.setOnLongClickListener(new View.OnLongClickListener() { public boolean onLongClick(View v) {
            Toast.makeText(ViewerActivity.this, button.getContentDescription(), Toast.LENGTH_SHORT).show();
            return true;
        }});
        return button;
    }
    private FrameLayout.LayoutParams iconLayout(int gravity) {
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(dp(48), dp(48), gravity);
        params.setMargins(dp(8), dp(8), dp(8), dp(8));
        return params;
    }
    private boolean unlocked() {
        KeyguardManager k = (KeyguardManager)getSystemService(KEYGUARD_SERVICE);
        return ((PowerManager)getSystemService(POWER_SERVICE)).isInteractive() && !k.isKeyguardLocked();
    }
    @Override public void onResume() {
        super.onResume(); resumed = true; health.reset(); audioDisabled = false; audio.reset();
        IntentFilter filter = new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        registerReceiver(audioReceiver, filter); audioReceiverRegistered = true;
        lensFallback = false;
        if (unlocked()) startOutput(); else show("Unlock to view camera");
    }
    @Override public void onPause() {
        resumed = false; close(); stopOutput(); show("Paused");
        if (audioReceiverRegistered) { unregisterReceiver(audioReceiver); audioReceiverRegistered = false; }
        super.onPause();
    }
    @Override public void onDestroy() { close(); stopOutput(); super.onDestroy(); }
    private void updateLensButton() {
        lensIcon.state(lensFallback ? 0 : lensMode);
        lensButton.setContentDescription(lensFallback ? "Lens correction unavailable" :
            "Lens correction: " + DewarpModel.label(lensMode) + "; tap to change");
        lensButton.setEnabled(resumed && !lensFallback && decoderSurface != null);
        lensButton.setAlpha(lensButton.isEnabled() ? 1f : 0.35f);
    }
    private void startOutput() {
        stopOutput();
        final int token = outputGeneration;
        dewarp = new DewarpView(this, lensMode, new DewarpView.Listener() {
            public void ready(Surface output) {
                if (token != outputGeneration || !resumed || !unlocked()) return;
                decoderSurface = output; updateLensButton(); open();
            }
            public void failed() {
                if (token == outputGeneration && resumed) fallbackOutput();
            }
        });
        surface = dewarp;
        layout.addView(surface, 0, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        handler.postDelayed(new Runnable() { public void run() {
            if (token == outputGeneration && resumed && decoderSurface == null) fallbackOutput();
        }}, 8000);
    }
    private void stopOutput() {
        outputGeneration++; decoderSurface = null;
        if (dewarp != null) { dewarp.shutdown(); dewarp = null; }
        if (surface != null) { layout.removeView(surface); surface = null; }
        updateLensButton();
    }
    private void fallbackOutput() {
        close(); stopOutput(); lensFallback = true;
        surface = new SurfaceView(this);
        layout.addView(surface, 0, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        updateLensButton(); failed(); // Original rendering, same bounded reconnect budget.
    }
    private void updateAudioButton() {
        if (audioButton == null) return;
        audioIcon.state(audio.listening() ? 1 : 0);
        audioButton.setContentDescription(audio.available() ?
            (audio.listening() ? "Mute camera audio" : "Unmute camera audio") : "Camera audio unavailable");
        audioButton.setEnabled(resumed && player != null && audio.available());
        audioButton.setAlpha(audioButton.isEnabled() ? 1f : 0.35f);
    }
    private void muteAudio() { audio.mute(); silenceAudio(); }
    private void silenceAudio() {
        if (player != null) player.setVolume(0f);
        if (audioFocusHeld) { audioFocusHeld = false; audioManager.abandonAudioFocus(focusListener); }
        updateAudioButton();
    }
    private void toggleAudio() {
        if (audio.listening()) { muteAudio(); return; }
        startAudio(true);
    }
    private void startAudio(boolean explicit) {
        if (!resumed || !unlocked() || player == null || !audio.available()) { muteAudio(); return; }
        boolean granted = audioManager.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC,
            AudioManager.AUDIOFOCUS_GAIN) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        audioFocusHeld = granted;
        if (audio.unmute(resumed && unlocked() && player != null, granted)) player.setVolume(1f);
        else {
            muteAudio();
            if (explicit) Toast.makeText(this, "Audio unavailable right now", Toast.LENGTH_SHORT).show();
        }
        updateAudioButton();
    }
    private static boolean audioFailure(PlaybackException error) {
        if (!(error instanceof ExoPlaybackException)) return false;
        ExoPlaybackException ex = (ExoPlaybackException)error;
        return ex.type == ExoPlaybackException.TYPE_RENDERER &&
            ((ex.rendererFormat != null && ex.rendererFormat.sampleMimeType != null &&
              ex.rendererFormat.sampleMimeType.startsWith("audio/")) ||
             "MediaCodecAudioRenderer".equals(ex.rendererName));
    }
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
        if (surface == null || (!lensFallback && decoderSurface == null)) return;
        close();
        if (!resumed || !unlocked()) return;
        final int epoch = generation;
        show("Connecting to camera…");
        try {
            Uri uri = source();
            PlayerDiagnostics.reset();
            DefaultTrackSelector selector = new DefaultTrackSelector(this);
            // Select audio from the outset: changing RTSP tracks mid-session can restart video.
            // Wait for a supported track and granted focus before enabling volume.
            selector.setParameters(selector.buildUponParameters().setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, audioDisabled));
            player = new ExoPlayer.Builder(this).setTrackSelector(selector)
                .setLoadControl(new DefaultLoadControl.Builder()
                    .setBufferDurationsMs(500, 1500, 250, 500)
                    .setTargetBufferBytes(2 * 1024 * 1024)
                    .setPrioritizeTimeOverSizeThresholds(false).build()).build();
            player.setVolume(0f); // Before prepare/play: never an initial audible burst.
            player.setAudioAttributes(new AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), false); // Focus is managed below.
            if (dewarp != null) player.setVideoSurface(decoderSurface);
            else player.setVideoSurfaceView(surface);
            player.addListener(new Player.Listener() {
                @Override public void onPlayerError(PlaybackException error) {
                    if (epoch != generation || !resumed) return;
                    // One-way fallback for this foreground session; use the existing bounded retry budget.
                    if (audioFailure(error)) audioDisabled = true;
                    failed();
                }
                @Override public void onTracksChanged(Tracks tracks) {
                    if (epoch != generation) return;
                    tracksKnown = !tracks.isEmpty();
                    audio.tracks(!audioDisabled && tracks.isTypeSupported(C.TRACK_TYPE_AUDIO) &&
                        tracks.isTypeSelected(C.TRACK_TYPE_AUDIO));
                    if (!audio.available()) silenceAudio();
                    else if (audio.autoRequested()) startAudio(false);
                    updateAudioButton();
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
                    if (dewarp != null) dewarp.aspect((float)aspect);
                    surface.setLayoutParams(new FrameLayout.LayoutParams(w, h, Gravity.CENTER));
                }
            });
            player.addAnalyticsListener(new AnalyticsListener() {
                @Override public void onVideoDecoderInitialized(EventTime eventTime, String name,
                        long initializedTimestampMs, long initializationDurationMs) {
                    if (epoch == generation) decoder = name;
                }
                @Override public void onAudioDecoderInitialized(EventTime eventTime, String name,
                        long initializedTimestampMs, long initializationDurationMs) {
                    if (epoch == generation && name.matches("[A-Za-z0-9_.-]{1,128}")) audioDecoder = name;
                }
            });
            transport = new CameraSocketFactory(uri.getHost());
            RtspMediaSource media = new RtspMediaSource.Factory().setForceUseRtpTcp(true)
                .setSocketFactory(transport).setTimeoutMs(5000).setDebugLoggingEnabled(true)
                .createMediaSource(new MediaItem.Builder().setUri(uri).setMediaId("private-doorbell").build());
            player.setMediaSource(media);
            decoded = displayed = lastDisplayed = audioRendered = presented = lastPresented = 0;
            glFrameBase = dewarp == null ? 0 : dewarp.frames();
            decoder = audioDecoder = "pending";
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
        silenceAudio(); audio.closed(); tracksKnown = false;
        if (player != null) {
            player.release(); player = null; releases++;
        }
        transport = null; updateAudioButton();
    }
    private void show(String text) { phase = text; status.setText(text); }
    @Override public void dump(String prefix, FileDescriptor fd, PrintWriter out, String[] args) {
        super.dump(prefix, fd, out, args);
        out.println(prefix + "viewer resumed=" + resumed + " activePlayer=" + (player != null));
        out.println(prefix + "viewer decoded=" + decoded + " displayed=" + displayed + " decoder=" + decoder);
        out.println(prefix + "viewer opens=" + opens + " releases=" + releases + " retryPending=" + retryPending);
        out.println(prefix + "viewer phase=" + phase);
        out.println(prefix + "viewer audioAvailable=" + audio.available() + " audioMuted=" + !audio.listening() +
            " audioFocus=" + audioFocusHeld + " audioDisabled=" + audioDisabled);
        out.println(prefix + "viewer audioRendered=" + audioRendered + " audioDecoder=" + audioDecoder +
            " audioVolume=" + (player == null ? 0f : player.getVolume()));
        out.println(prefix + "viewer lens=" + DewarpModel.label(lensMode) + " lensFallback=" + lensFallback +
            " glActive=" + (dewarp != null && dewarp.live()) + " glFrames=" + (dewarp == null ? 0 : dewarp.frames()) +
            " presented=" + presented);
        out.println(prefix + "viewer protocol=" + PlayerDiagnostics.protocol + " videoSDP=" + PlayerDiagnostics.sdpVideoTracks);
    }
}
