package com.kavach.app

import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.PixelFormat
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Parcel
import android.view.Gravity
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import rikka.shizuku.Shizuku
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.concurrent.thread
import kotlin.math.abs

/** Turned on once in Android's Accessibility settings. Whenever a call is active it shows a floating card and streams
 *  the microphone (the call on speaker) to Kavach. Test build: this is what proves whether the mic is audible in a call. */
class KavachListenerService : AccessibilityService() {
    private val server = "__KAVACH_SERVER__"
    private val key = "__KAVACH_KEY__"
    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient()
    private var inCall = false
    private var caller: WebSocket? = null
    private var receiver: WebSocket? = null
    @Volatile private var recording = false
    @Volatile private var playingUntil = 0L
    private var track: AudioTrack? = null
    private var card: LinearLayout? = null
    private var statusText: TextView? = null
    private var wordsText: TextView? = null
    private var risk = 0
    private var peak = 0
    @Volatile private var current = "starting"

    private val poll = object : Runnable {
        override fun run() {
            val mode = (getSystemService(Context.AUDIO_SERVICE) as AudioManager).mode
            val active = mode == AudioManager.MODE_IN_CALL
            if (active && !inCall) startCall() else if (!active && inCall) stopCall()
            if (inCall && shell != null) {
                val state = (shellCall(KavachShell.STATUS) ?: "").split("|")
                voiceInCall = state.getOrNull(1) == "yes"
                current = "Direct " + state[0] + if (state.size > 1) "  |  voice " + (if (voiceInCall) "in call" else "speaker") else ""
            }
            if (inCall) { statusText?.text = "$current  |  ${peak * 100 / 32767}%  |  risk $risk"; peak = 0 }
            main.postDelayed(this, 1000)
        }
    }

    override fun onServiceConnected() {
        main.post(poll)
        Shizuku.addBinderReceivedListenerSticky { askShizuku() }
    }

    private fun askShizuku() {
        try {
            if (Shizuku.pingBinder() && Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) Shizuku.requestPermission(1)
        } catch (_: Exception) {}
    }

    @Volatile private var voiceInCall = false
    @Volatile private var shellOut: java.io.OutputStream? = null
    private var takenOver = false
    private var takeButton: Button? = null

    private fun setTakeover(on: Boolean) {
        takenOver = on
        takeButton?.text = if (on) "Take back" else "Let Kavach take over"
        // Without a way into the call itself, the phone's speaker is the only way the caller can hear Kavach.
        if (!voiceInCall) (getSystemService(Context.AUDIO_SERVICE) as AudioManager).isSpeakerphoneOn = on
    }

    private fun shizukuReady() = try {
        Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    } catch (_: Exception) { false }

    private val voiceWriter = java.util.concurrent.Executors.newSingleThreadExecutor()
    private val shellArgs by lazy {
        Shizuku.UserServiceArgs(ComponentName(packageName, KavachShell::class.java.name))
            .processNameSuffix("shell").debuggable(false).version(1).daemon(false)
    }
    @Volatile private var shell: IBinder? = null
    @Volatile private var shellSocket: ServerSocket? = null
    private val shellConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            shell = binder
            val port = shellSocket?.localPort ?: return
            shellCall(KavachShell.START) { it.writeInt(port) }
        }
        override fun onServiceDisconnected(name: ComponentName?) { shell = null }
    }

    private fun shellCall(code: Int, write: (Parcel) -> Unit = {}): String? {
        val data = Parcel.obtain()
        val reply = Parcel.obtain()
        return try {
            write(data)
            shell?.transact(code, data, reply, 0)
            if (code == KavachShell.STATUS) reply.readString() else null
        } catch (_: Exception) { null } finally { data.recycle(); reply.recycle() }
    }

    // Reads the call itself through Shizuku. Returns false if that could not start, so the mic can be tried instead.
    private fun listenThroughShell(): Boolean {
        val server = try { ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")) } catch (_: Exception) { return false }
        server.soTimeout = 8000
        shellSocket = server
        current = "Shizuku connecting"
        main.post { try { Shizuku.bindUserService(shellArgs, shellConnection) } catch (e: Exception) { showWords("Shizuku: " + e.javaClass.simpleName) } }
        val socket = try { server.accept() } catch (_: Exception) { server.close(); shellSocket = null; return false }
        socket.use {
            val input = it.getInputStream()
            shellOut = it.getOutputStream()
            val buf = ByteArray(3200)
            while (recording) {
                val n = try { input.read(buf) } catch (_: Exception) { -1 }
                if (n < 0) break
                var i = 0
                while (i + 1 < n) {
                    val s = (buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xff)
                    if (abs(s) > peak) peak = abs(s)
                    i += 2
                }
                caller?.send(buf.copyOf(n).toByteString())
            }
        }
        shellOut = null
        server.close()
        shellSocket = null
        return true
    }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}
    override fun onDestroy() { main.removeCallbacks(poll); if (inCall) stopCall(); super.onDestroy() }

    private fun startCall() {
        inCall = true
        risk = 0
        showCard()
        val id = "apk-" + System.currentTimeMillis()
        val base = server.replace("https://", "wss://").trimEnd('/')
        caller = http.newWebSocket(Request.Builder().url("$base/ws/call/$id/caller?mode=live&key=$key").build(), Audio())
        receiver = http.newWebSocket(Request.Builder().url("$base/ws/call/$id/receiver?mode=live&key=$key").build(), Audio(true))
        val minOut = AudioTrack.getMinBufferSize(16000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        track = AudioTrack(AudioManager.STREAM_MUSIC, 16000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
            minOut * 4, AudioTrack.MODE_STREAM).also { it.play() }
        startMic()
    }

    private val sources = listOf(
        "RECOG" to MediaRecorder.AudioSource.VOICE_RECOGNITION,
        "MIC" to MediaRecorder.AudioSource.MIC,
        "COMM" to MediaRecorder.AudioSource.VOICE_COMMUNICATION,
        "CAM" to MediaRecorder.AudioSource.CAMCORDER,
        "RAW" to MediaRecorder.AudioSource.UNPROCESSED,
        "PERF" to MediaRecorder.AudioSource.VOICE_PERFORMANCE,
        "CALL" to MediaRecorder.AudioSource.VOICE_CALL,
        "DOWN" to MediaRecorder.AudioSource.VOICE_DOWNLINK,
        "UP" to MediaRecorder.AudioSource.VOICE_UPLINK,
    )

    // Test build: tries each audio source for a few seconds during the call, and stays on the first one that hears sound.
    private fun startMic() {
        recording = true
        thread {
            if (shizukuReady()) {
                showWords("Listening to the call directly. No speaker needed.")
                if (listenThroughShell()) return@thread
                showWords("Shizuku could not start. Trying the mic.")
            } else {
                askShizuku()
                showWords("Shizuku is not on or not allowed. Trying the mic.")
                Thread.sleep(2500)
            }
            val results = sources.map { it.first to "-" }.toMap(LinkedHashMap())
            var round = 0
            while (recording) {
                round++
                for ((name, source) in sources) {
                    if (!recording) break
                    current = "$name round $round"
                    showWords(results.entries.joinToString(" ") { "${it.key}:${it.value}" })
                    val best = listen(source, name) { results[name] = it }
                    results[name] = best
                    if (best == "HEARD") return@thread
                }
            }
        }
    }

    // Returns "HEARD" after streaming from a source that picks up sound, else its loudest % or "no" if Android refuses it.
    private fun listen(source: Int, name: String, onHeard: (String) -> Unit): String {
        val min = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = try {
            AudioRecord(source, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min, 6400))
        } catch (e: Exception) { return "no" }
        if (rec.state != AudioRecord.STATE_INITIALIZED) { rec.release(); return "no" }
        try { rec.startRecording() } catch (e: Exception) { rec.release(); return "no" }
        val buf = ByteArray(3200)
        val started = System.currentTimeMillis()
        var loudest = 0
        var loudChunks = 0
        var heard = false
        while (recording && (heard || System.currentTimeMillis() - started < 6000)) {
            val n = rec.read(buf, 0, buf.size)
            if (n <= 0) continue
            var chunk = 0
            var i = 0
            while (i + 1 < n) {
                val s = (buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xff)
                if (abs(s) > chunk) chunk = abs(s)
                i += 2
            }
            if (chunk > peak) peak = chunk
            // the first half second can hold a click from starting the recorder
            if (System.currentTimeMillis() - started > 500) {
                if (chunk > loudest) loudest = chunk
                if (chunk >= 300) loudChunks++
                if (!heard && loudChunks >= 3) { heard = true; current = "$name HEARD"; onHeard("HEARD") }
            }
            // Kavach's own voice must not be heard back as if the caller had said it
            val out = if (System.currentTimeMillis() < playingUntil) ByteArray(n) else buf.copyOf(n)
            caller?.send(out.toByteString())
        }
        try { rec.stop() } catch (_: Exception) {}
        rec.release()
        return if (heard) "HEARD" else "${loudest * 100 / 32767}%"
    }

    private fun stopCall() {
        inCall = false
        recording = false
        if (takenOver) setTakeover(false)
        if (shell != null) {
            shellCall(KavachShell.STOP)
            try { Shizuku.unbindUserService(shellArgs, shellConnection, true) } catch (_: Exception) {}
            shell = null
        }
        shellSocket?.let { try { it.close() } catch (_: Exception) {} }
        receiver?.send("{\"type\":\"end_call\"}")
        main.postDelayed({ caller?.close(1000, null); receiver?.close(1000, null) }, 1500)
        track?.let { try { it.stop(); it.release() } catch (_: Exception) {} }
        track = null
        card?.let { (getSystemService(WINDOW_SERVICE) as WindowManager).removeView(it) }
        card = null
    }

    private inner class Audio(val events: Boolean = false) : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (bytes.size < 2) return
            val source = bytes[0].toInt()
            // warning and family note on the receiver socket, the decoy's voice on the caller socket
            val wanted = if (events) source == 1 || source == 3 else source == 2
            if (!wanted) return
            val pcm = bytes.substring(1).toByteArray()
            val ms = pcm.size / 32L
            if (source == 2 && voiceInCall) {
                val out = shellOut
                if (out != null) { try { voiceWriter.execute { out.write(pcm) } } catch (_: Exception) {}; return }
            }
            playingUntil = maxOf(playingUntil, System.currentTimeMillis()) + ms
            track?.write(pcm, 0, pcm.size, AudioTrack.WRITE_NON_BLOCKING)
        }
        override fun onMessage(webSocket: WebSocket, text: String) {
            if (!events) return
            val ev = JSONObject(text)
            when (ev.optString("type")) {
                "detection" -> risk = ev.optDouble("risk_cum", ev.optDouble("risk", risk.toDouble())).toInt()
                "transcript" -> if (ev.optBoolean("final")) showWords(ev.optString("text"))
                "takeover" -> { val on = ev.optString("state") == "on"; main.post { setTakeover(on) } }
                "persona" -> if (ev.optString("text").isNotEmpty()) showWords("Kavach says: " + ev.optString("text"))
                "warning" -> if (ev.optString("state") == "speaking") showWords("This looks like a scam. " + ev.optString("text"))
            }
        }
        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            if (inCall) showWords("Cannot reach Kavach: " + t.javaClass.simpleName)
        }
    }

    private fun showWords(text: String) { main.post { wordsText?.text = text.takeLast(160) } }

    private fun showCard() {
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.parseColor("#E60F6F5A")); setPadding(28, 20, 28, 20) }
        statusText = TextView(this).apply { setTextColor(Color.WHITE); textSize = 15f; text = "Kavach  |  starting" }
        wordsText = TextView(this).apply { setTextColor(Color.WHITE); textSize = 13f; text = "Starting." }
        val take = Button(this).apply { text = "Let Kavach take over"; setOnClickListener { receiver?.send(if (takenOver) "{\"type\":\"takeback\"}" else "{\"type\":\"takeover\"}") } }
        takeButton = take
        box.addView(statusText); box.addView(wordsText); box.addView(take)
        val lp = WindowManager.LayoutParams(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL, PixelFormat.TRANSLUCENT)
        lp.gravity = Gravity.TOP
        lp.y = 120
        wm.addView(box, lp)
        card = box
    }
}
