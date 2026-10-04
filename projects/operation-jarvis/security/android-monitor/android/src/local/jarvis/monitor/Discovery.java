package local.jarvis.monitor;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.os.SystemClock;
import java.net.InetAddress;

/** Exact-service IPv4 discovery on the polling worker, not Android 6's wedged NSD.
 * Only routing hints: the paired TLS pin and original SAN identity stay immutable.
 */
public final class Discovery {
    private final WifiManager wifi;
    private final String service;
    private volatile boolean closed;
    private volatile String endpoint;
    private long nextRefresh;
    private long last;
    public Discovery(Context context, String pin) {
        if (!pin.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("Invalid certificate pin");
        service = "JARVIS-" + pin.substring(0, 32) + "._jarvis-monitor._tcp.local";
        wifi = (WifiManager)context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
    }
    public String endpoint() {
        if (closed) return null;
        long now = SystemClock.elapsedRealtime();
        if (now < last || now >= nextRefresh) {
            nextRefresh = now + 30000;
            try {
                int ip = wifi.getConnectionInfo().getIpAddress();
                InetAddress local = InetAddress.getByAddress(new byte[]{(byte)ip, (byte)(ip >> 8),
                    (byte)(ip >> 16), (byte)(ip >> 24)});
                MdnsDiscovery.Endpoint found = MdnsDiscovery.resolve(service, local);
                if (found != null && !closed)
                    endpoint = "https://" + found.address + ":" + found.port + "/v1/presence";
            } catch (Exception ignored) {
                // No addresses, tokens or network exception text in logs.
            }
        }
        last = now;
        return closed ? null : endpoint;
    }
    public boolean hasRoute() { return endpoint != null; }
    public void close() { closed = true; endpoint = null; }
}
