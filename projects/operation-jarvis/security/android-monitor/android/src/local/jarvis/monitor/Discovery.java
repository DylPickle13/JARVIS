package local.jarvis.monitor;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Handler;
import android.os.Looper;
import java.net.Inet4Address;
import java.net.InetAddress;

/** Discovery supplies routing hints only. Client still authenticates the paired certificate. */
public final class Discovery {
    private final NsdManager manager;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final String name;
    private NsdManager.DiscoveryListener listener;
    private boolean closed, resolving;
    private int generation;
    private volatile String address;
    private volatile int port;
    private final Runnable refresh = new Runnable() { public void run() {
        if (closed) return;
        stop();
        main.postDelayed(new Runnable() { public void run() { start(); } }, 1000);
        main.postDelayed(this, 30000);
    }};

    public Discovery(Context context, String pin) {
        if (!pin.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("Invalid certificate pin");
        name = "JARVIS-" + pin.substring(0, 32);
        manager = (NsdManager)context.getSystemService(Context.NSD_SERVICE);
        start();
        main.postDelayed(refresh, 30000);
    }
    public synchronized String endpoint() {
        return address == null ? null : "https://" + address + ":" + port + "/v1/presence";
    }
    private void start() {
        if (closed || listener != null) return;
        final int epoch = ++generation;
        listener = new NsdManager.DiscoveryListener() {
            public void onDiscoveryStarted(String t) {}
            public void onDiscoveryStopped(String t) {}
            public void onStartDiscoveryFailed(String t, int e) {
                main.post(new Runnable() { public void run() { if (epoch == generation) stop(); } });
            }
            public void onStopDiscoveryFailed(String t, int e) {}
            public void onServiceLost(final NsdServiceInfo info) {
                main.post(new Runnable() { public void run() {
                    if (epoch == generation && name.equals(info.getServiceName())) {
                        synchronized (Discovery.this) { address = null; }
                    }
                }});
            }
            public void onServiceFound(final NsdServiceInfo info) {
                main.post(new Runnable() { public void run() {
                    if (closed || epoch != generation || resolving || !name.equals(info.getServiceName())) return;
                    resolving = true;
                    try { manager.resolveService(info, new NsdManager.ResolveListener() {
                        public void onResolveFailed(NsdServiceInfo s, int e) {
                            main.post(new Runnable() { public void run() { if (epoch == generation) resolving = false; } });
                        }
                        public void onServiceResolved(final NsdServiceInfo s) {
                            main.post(new Runnable() { public void run() {
                                if (closed || epoch != generation) return;
                                resolving = false;
                                InetAddress host = s.getHost();
                                if (!name.equals(s.getServiceName()) || !(host instanceof Inet4Address) ||
                                    !host.isSiteLocalAddress() || s.getPort() < 1 || s.getPort() > 65535) return;
                                synchronized (Discovery.this) { address = host.getHostAddress(); port = s.getPort(); }
                            }});
                        }
                    }); } catch (RuntimeException e) { resolving = false; }
                }});
            }
        };
        try { manager.discoverServices("_jarvis-monitor._tcp.", NsdManager.PROTOCOL_DNS_SD, listener); }
        catch (RuntimeException e) { stop(); }
    }
    private void stop() {
        ++generation;
        resolving = false;
        if (listener != null) {
            try { manager.stopServiceDiscovery(listener); } catch (RuntimeException ignored) {}
            listener = null;
        }
    }
    public void close() {
        closed = true;
        main.removeCallbacksAndMessages(null);
        stop();
        synchronized (this) { address = null; }
    }
}
