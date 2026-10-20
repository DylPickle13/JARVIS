package local.jarvis.monitor;
import android.app.admin.DeviceAdminReceiver;
import android.content.Context;
import android.content.Intent;
public final class Admin extends DeviceAdminReceiver {
    private void resumeIfEnabled(Context c) {
        // Permission is a prerequisite, not the owner's automation switch.
        // Never clear reservations or re-enable deliberate Off. The service's
        // permission gate withholds actions while ordinary recovery continues.
        if (c.getSharedPreferences("monitor", 0).getBoolean("enabled", false))
            c.startService(new Intent(c, MonitorService.class));
    }
    @Override public void onDisabled(Context c, Intent i) {
        MonitorService.status = "Screen-lock permission missing; owner enable setting preserved";
        resumeIfEnabled(c);
    }
    @Override public void onEnabled(Context c, Intent i) {
        resumeIfEnabled(c);
    }
}
