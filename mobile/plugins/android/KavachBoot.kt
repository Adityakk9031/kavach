package com.kavach.app

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.provider.Settings
import java.io.File

/** The two phone settings Kavach may change once a family member has finished "Full protection" setup (which gives it the
 *  WRITE_SECURE_SETTINGS permission): Wireless debugging, and Kavach's own call-protection switch. Nothing else. */
object KavachSecure {
    fun granted(c: Context) = c.checkSelfPermission(android.Manifest.permission.WRITE_SECURE_SETTINGS) == PackageManager.PERMISSION_GRANTED

    fun wirelessIsOn(c: Context) = try { Settings.Global.getInt(c.contentResolver, "adb_wifi_enabled", 0) == 1 } catch (_: Exception) { false }

    fun wirelessOn(c: Context): Boolean =
        granted(c) && try { Settings.Global.putInt(c.contentResolver, "adb_wifi_enabled", 1) } catch (_: Exception) { false }

    /** Puts Kavach back in the list of switched-on accessibility services. Only done for a person who switched it on
     *  themselves at least once (the service leaves that mark), so it never turns it on for someone who never chose it. */
    fun keepAccessibilityOn(c: Context): Boolean {
        if (!granted(c) || !File(c.filesDir, "kavach-pro.flag").exists()) return false
        val me = ComponentName(c.packageName, "com.kavach.app.KavachListenerService").flattenToString()
        return try {
            val now = Settings.Secure.getString(c.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: ""
            if (now.split(':').any { it == me }) return true
            Settings.Secure.putString(c.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, if (now.isEmpty()) me else "$now:$me") &&
                Settings.Secure.putInt(c.contentResolver, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
        } catch (_: Exception) { false }
    }
}

/** After the phone restarts: keep Kavach's call protection on, and get Wireless debugging ready so that restarting Shizuku
 *  is one tap. Does nothing unless the family finished the Full protection setup. */
class KavachBoot : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (!KavachSecure.granted(context)) return
        KavachSecure.keepAccessibilityOn(context)
        KavachSecure.wirelessOn(context)
    }
}
