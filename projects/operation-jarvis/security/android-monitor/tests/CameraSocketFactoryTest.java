package local.jarvis.monitor;
import java.io.IOException;
import java.net.*;
public final class CameraSocketFactoryTest {
    static int checks;
    interface Attempt { void run() throws Exception; }
    static void blocked(Attempt a) throws Exception {
        checks++;
        try { a.run(); throw new AssertionError("Unexpected network access"); }
        catch (IOException expected) { /* No network I/O for rejected destinations. */ }
    }
    public static void main(String[] args) throws Exception {
        final CameraSocketFactory factory = new CameraSocketFactory("192.168.40.12");
        blocked(() -> new CameraSocketFactory("8.8.8.8"));
        blocked(() -> new CameraSocketFactory("camera.example"));
        blocked(() -> new CameraSocketFactory("192.168.40.999"));
        blocked(() -> factory.createSocket("camera.example",554));
        blocked(() -> factory.createSocket("192.168.40.13",554));
        blocked(() -> factory.createSocket("192.168.40.12",443));
        blocked(() -> factory.createSocket(InetAddress.getByName("127.0.0.1"),554));
        try (Socket socket = factory.createSocket()) {
            blocked(() -> socket.connect(new InetSocketAddress("127.0.0.1",554),1));
            blocked(() -> socket.connect(InetSocketAddress.createUnresolved("camera.example",554),1));
            blocked(() -> socket.connect(new InetSocketAddress("192.168.40.12",443),1));
            factory.interrupt();
            checks++; if (!socket.isClosed()) throw new AssertionError("Owned socket not closed");
        }
        System.out.println(checks + " socket guard assertions passed; no network connections made.");
    }
}
