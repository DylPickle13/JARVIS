package local.jarvis.monitor;

import java.io.IOException;
import java.net.*;
import javax.net.SocketFactory;

/** Enforces the single configured LAN destination even if a library URI parser regresses.
 * No DNS names, redirects to other peers, public destinations, or unbounded connects.
 */
final class CameraSocketFactory extends SocketFactory {
    private final String host;
    private final InetAddress address;
    private volatile Socket current;
    /** Owner's long-press reconnect test: close only this viewer's RTSP socket. */
    void interrupt() throws IOException { Socket socket = current; if (socket != null) socket.close(); }
    CameraSocketFactory(String host) throws IOException {
        if (!PlayerConfig.valid(host, 554, "/stream2", "test", "test"))
            throw new IOException("Invalid camera address");
        this.host = host;
        String[] parts = host.split("\\.");
        if (parts.length != 4) throw new IOException("Invalid camera address");
        byte[] bytes = new byte[4];
        try { for (int i=0; i<4; i++) bytes[i] = (byte)Integer.parseInt(parts[i]); }
        catch (Exception e) { throw new IOException("Invalid camera address"); }
        address = InetAddress.getByAddress(bytes);
    }
    @Override public Socket createSocket() {
        Socket socket = new Socket() {
            @Override public void connect(SocketAddress endpoint) throws IOException { connect(endpoint, 5000); }
            @Override public void connect(SocketAddress endpoint, int timeout) throws IOException {
                if (!(endpoint instanceof InetSocketAddress)) throw new IOException("Camera destination blocked");
                InetSocketAddress target = (InetSocketAddress)endpoint;
                if (target.getPort() != 554 || !address.equals(target.getAddress()))
                    throw new IOException("Camera destination blocked");
                super.connect(endpoint, timeout <= 0 ? 5000 : Math.min(timeout, 5000));
            }
        };
        current = socket;
        return socket;
    }
    private Socket connected(InetAddress target, int port, InetAddress local, int localPort) throws IOException {
        if (port != 554 || !address.equals(target)) throw new IOException("Camera destination blocked");
        Socket socket = createSocket();
        try {
            if (local != null) socket.bind(new InetSocketAddress(local, localPort));
            socket.connect(new InetSocketAddress(address, 554), 5000);
            return socket;
        } catch (IOException e) { socket.close(); throw e; }
    }
    @Override public Socket createSocket(String target, int port) throws IOException {
        return createSocket(target, port, null, 0);
    }
    @Override public Socket createSocket(String target, int port, InetAddress local, int localPort) throws IOException {
        if (!host.equals(target)) throw new IOException("Camera destination blocked");
        return connected(address, port, local, localPort);
    }
    @Override public Socket createSocket(InetAddress target, int port) throws IOException {
        return connected(target, port, null, 0);
    }
    @Override public Socket createSocket(InetAddress target, int port, InetAddress local, int localPort) throws IOException {
        return connected(target, port, local, localPort);
    }
}
