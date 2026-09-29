package local.jarvis.monitor;
import android.app.admin.DeviceAdminReceiver;
import android.content.Context;
import android.content.Intent;
public final class Admin extends DeviceAdminReceiver {
    @Override public void onDisabled(Context c, Intent i) {
        c.getSharedPreferences("monitor", 0).edit().putBoolean("enabled", false).commit();
        c.stopService(new Intent(c, MonitorService.class));
    }
}
