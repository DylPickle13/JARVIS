package local.jarvis.monitor;
import android.app.*;
import android.app.admin.DevicePolicyManager;
import android.content.*;
import android.net.*;
import android.net.wifi.WifiManager;
import android.os.*;
import org.json.JSONObject;

public final class MonitorService extends Service {
    public static volatile String status = "Stopped";
    public static volatile long lastContact = 0;
    private final Handler main = new Handler();
    private HandlerThread thread;
    private Handler worker;
    private SharedPreferences prefs;
    private Client client;
    private Policy policy;
    private PowerManager.WakeLock cpu;
    private WifiManager.WifiLock wifi;
    private boolean destroyed;
    private volatile long retryAt;
    private int failures, networkFailures;
    private long testingUntil;
    private String shown = "";
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            final long began = SystemClock.elapsedRealtime();
            if (began < retryAt) {
                // Back off network/actions, not charger handling. Release locks
                // promptly on battery rather than holding them for the retry cap.
                main.post(new Runnable() { @Override public void run() { if (!destroyed) locks(powered()); }});
                worker.postDelayed(poll, Math.min(1000, retryAt - began)); return;
            }
            String state = "unknown";
            double age = Double.NaN;
            String text = "Unavailable / stale — unchanged";
            try {
                ConnectivityManager cm = (ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE);
                NetworkInfo n = cm.getActiveNetworkInfo();
                if (n == null || !n.isConnected() || n.getType() != ConnectivityManager.TYPE_WIFI)
                    throw new Exception("Wi-Fi unavailable");
                if (client == null) client = new Client(MonitorService.this);
                JSONObject r = client.poll();
                if (r.getInt("version") != 2 || !"computer-display".equals(r.getString("source")))
                    throw new Exception("Computer-display protocol required");
                state = r.getString("state");
                age = r.isNull("ageSeconds") ? Double.NaN : r.getDouble("ageSeconds");
                age += (SystemClock.elapsedRealtime() - began) / 1000.0;
                lastContact = SystemClock.elapsedRealtime();
                networkFailures = 0;
                if (age >= 0 && age <= 15 && (state.equals("nearby") || state.equals("away")))
                    text = "Following computer display over Wi-Fi / TLS — " + state;
                else if ("awaiting-transition".equals(r.optString("reason")))
                    text = "Connected / waiting for first computer wake/sleep — unchanged";
                else if ("transition-pending".equals(r.optString("reason")))
                    text = "Connected / computer transition pending — unchanged";
                else text = "Connected / computer state unavailable — unchanged";
            } catch (Exception e) {
                // No raw exception text, tokens, URLs or request headers in logs/notifications.
                state = "unknown"; age = Double.NaN;
                retryAt = SystemClock.elapsedRealtime() + DisplayRecovery.delay(networkFailures);
                if (networkFailures < 4) networkFailures++;
            }
            final String s = state, t = text;
            final double a = age;
            final long fetched = SystemClock.elapsedRealtime();
            main.post(new Runnable() { @Override public void run() {
                if (destroyed) return;
                tick(s, a + (SystemClock.elapsedRealtime() - fetched) / 1000.0, t);
                if (!destroyed) worker.postDelayed(poll, 1000);
            }});
        }
    };
    @Override public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("monitor", 0);
        PowerManager pm = (PowerManager)getSystemService(POWER_SERVICE);
        cpu = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "JarvisMonitor:poll");
        wifi = ((WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE))
            .createWifiLock(WifiManager.WIFI_MODE_FULL, "JarvisMonitor:wifi");
        startForeground(1, notification("Starting"));
        if (!prefs.getBoolean("enabled", false)) {
            update("Disabled by owner"); stopSelf(); return;
        }
        if (prefs.getBoolean("pending", false)) retryAt = SystemClock.elapsedRealtime() + 60000;
        policy = new Policy(prefs.getString("applied", ""));
        try { client = new Client(this); }
        catch (Exception e) { fail(); }
        thread = new HandlerThread("presence-network"); thread.start();
        worker = new Handler(thread.getLooper());
        worker.post(poll);
    }
    @Override public int onStartCommand(Intent i, int flags, int id) {
        if (i == null || !"local.jarvis.monitor.SELF_TEST".equals(i.getAction())) {
            if (worker != null && prefs.getBoolean("enabled", false)) {
                if (powered()) {
                    locks(true);
                    // The existing poll chain resumes with the CPU awake. Do not
                    // enqueue another chain if a request is already in flight.
                }
            }
            return START_STICKY;
        }
        if ("local.jarvis.monitor.SELF_TEST".equals(i.getAction()) && worker != null) {
            // Explicit UI-only test. Does not change backend presence or other automations.
            testingUntil = SystemClock.elapsedRealtime() + 15000;
            update("Screen test: sleep, then wake after 8 seconds");
            try {
                if (!powered()) throw new Exception();
                locks(true);
                admin().lockNow();
                main.postDelayed(new Runnable() { @Override public void run() {
                    if (!destroyed) { try { wake(); } catch (Exception e) { fail(); } }
                }}, 8000);
            } catch (Exception e) { fail(); }
        }
        return START_STICKY;
    }
    private boolean powered() {
        Intent b = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        return b != null && b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0;
    }
    private void locks(boolean powered) {
        if (powered) {
            if (!cpu.isHeld()) cpu.acquire();
            if (!wifi.isHeld()) wifi.acquire();
        } else {
            if (cpu.isHeld()) cpu.release();
            if (wifi.isHeld()) wifi.release();
        }
    }
    private DevicePolicyManager admin() { return (DevicePolicyManager)getSystemService(DEVICE_POLICY_SERVICE); }
    private void tick(String state, double age, String text) {
        if (!prefs.getBoolean("enabled", false)) { stopSelf(); return; }
        boolean power = powered();
        locks(power);
        long now = SystemClock.elapsedRealtime();
        if (now < testingUntil || now < retryAt) return;
        if (prefs.getBoolean("pending", false)) {
            if (!DisplayRecovery.admitted(state, age, power)) { update(text); return; }
            PowerManager pm = (PowerManager)getSystemService(POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager)getSystemService(KEYGUARD_SERVICE);
            boolean matched = DisplayRecovery.observed(state, pm.isInteractive(), keyguard.isKeyguardLocked());
            SharedPreferences.Editor edit = prefs.edit().putBoolean("pending", false);
            if (matched) edit.putString("applied", state); else edit.remove("applied");
            if (!edit.commit()) { fail(); return; }
            policy = new Policy(matched ? state : "");
            if (matched) failures = 0;
            else {
                retryAt = now + DisplayRecovery.delay(failures);
                if (failures < 4) failures++;
            }
            update(matched ? "Screen state reconciled with computer — " + state : "Screen state observed; awaiting fresh computer decision");
            return; // Never replay an old action in the reconciliation tick.
        }
        String action = policy.consider(state, age, SystemClock.elapsedRealtime(), power);
        update(power ? text : "Paused: connect a wall charger");
        if (action.equals("none")) return;
        if (!admin().isAdminActive(new ComponentName(this, Admin.class))) { fail(); return; }
        // Durable reservation. Recovery observes screen/keyguard state first,
        // then only a fresh completed Mac decision may authorize another action.
        if (!prefs.edit().putBoolean("pending", true).commit()) { fail(); return; }
        try {
            if (action.equals("sleep")) admin().lockNow(); else wake();
            // Dispatch is not readback. A later poll checks actual state. Pace
            // unresolved operations even across failures and process restarts.
            retryAt = SystemClock.elapsedRealtime() + 5000;
        } catch (Exception e) { fail(); }
    }
    @Override protected void dump(java.io.FileDescriptor fd, java.io.PrintWriter out, String[] args) {
        out.println("enabled=" + prefs.getBoolean("enabled", false));
        out.println("pending=" + prefs.getBoolean("pending", false));
        out.println("status=" + status);
        out.println("nativePlayer=" + (PlayerLauncher.configured(this) && prefs.getBoolean("native_player", true)));
        out.println("discoveryRoute=" + (client != null && client.hasDiscoveryRoute()));
        out.println("lastContactAgeSeconds=" + (lastContact == 0 ? -1 :
            (SystemClock.elapsedRealtime() - lastContact) / 1000));
    }
    private void wake() {
        PowerManager pm = (PowerManager)getSystemService(POWER_SERVICE);
        PowerManager.WakeLock screen = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK |
            PowerManager.ACQUIRE_CAUSES_WAKEUP, "JarvisMonitor:wake");
        screen.acquire(4000);
        KeyguardManager k = (KeyguardManager)getSystemService(KEYGUARD_SERVICE);
        if (!k.isKeyguardSecure()) {
            startActivity(new Intent(this, WakeActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        }
    }
    private Notification notification(String text) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this).setSmallIcon(android.R.drawable.ic_lock_idle_lock)
            .setContentTitle("JARVIS Monitor").setContentText(text).setContentIntent(open)
            .setOngoing(true).setOnlyAlertOnce(true).build();
    }
    private void update(String text) {
        status = text;
        if (!shown.equals(text)) {
            shown = text;
            ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(1, notification(text));
        }
    }
    private void fail() {
        retryAt = SystemClock.elapsedRealtime() + DisplayRecovery.delay(failures);
        if (failures < 4) failures++;
        update("Waiting for device permission/state recovery — owner enable setting preserved");
    }
    @Override public void onDestroy() {
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        if (client != null) client.close();
        if (worker != null) worker.removeCallbacksAndMessages(null);
        if (thread != null) thread.quitSafely();
        locks(false);
        stopForeground(true);
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent i) { return null; }
}
