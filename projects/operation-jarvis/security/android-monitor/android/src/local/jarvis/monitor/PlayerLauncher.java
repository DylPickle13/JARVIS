package local.jarvis.monitor;

import android.content.Context;
import android.content.Intent;
import java.io.File;

/** Intent contains only a component, never a camera URL or credentials. */
final class PlayerLauncher {
    static boolean configured(Context c) { return new File(c.getFilesDir(), "player.json").isFile(); }
    static Intent intent(Context c) {
        if (configured(c) && c.getSharedPreferences("monitor", 0).getBoolean("native_player", true))
            return new Intent(c, ViewerActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        Intent i = c.getPackageManager().getLaunchIntentForPackage("com.alexvas.dvr");
        if (i != null) {
            i.setPackage(null);
            i.addFlags(Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
        }
        return i;
    }
}
