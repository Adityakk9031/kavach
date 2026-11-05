package com.kavach.app

import android.content.Context
import android.content.ContextWrapper
import android.content.AttributionSource
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Binder
import android.os.Build
import android.os.Parcel
import java.net.Socket
import kotlin.concurrent.thread
import kotlin.math.abs

/** Runs through Shizuku with shell-level access, which ordinary apps do not have. Reads the call audio directly
 *  (the far side only, so the caller's words and not the user's) and sends it to the app over a local socket. */
class KavachShell : Binder() {
    @Volatile private var status = "starting"
    @Volatile private var running = false
    @Volatile private var source_ = ""
    @Volatile private var voice = "wait"

    override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
        when (code) {
            START -> { val port = data.readInt(); if (!running) { running = true; thread { capture(port) } } }
            STATUS -> reply?.writeString(if (source_.isEmpty()) status else "$source_|$voice")
            STOP -> running = false
            DESTROY -> { running = false; System.exit(0) }
            else -> return super.onTransact(code, data, reply, flags)
        }
        return true
    }

    private fun capture(port: Int) {
        try {
            Socket("127.0.0.1", port).use { socket ->
                val out = socket.getOutputStream()
                startVoice(socket)
                val failures = StringBuilder()
                while (running) {
                    for ((name, source) in SOURCES) {
                        if (!running) break
                        val rec = try { open(source) } catch (e: Throwable) { failures.append("$name:${e.javaClass.simpleName} "); status = failures.toString(); null } ?: continue
                        try {
                            source_ = name
                            rec.startRecording()
                            val buf = ByteArray(3200)
                            val started = System.currentTimeMillis()
                            var heard = false
                            while (running && (heard || System.currentTimeMillis() - started < 8000)) {
                                val n = rec.read(buf, 0, buf.size)
                                if (n <= 0) continue
                                var i = 0
                                while (i + 1 < n) {
                                    val s = (buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xff)
                                    if (abs(s) >= 100) heard = true
                                    i += 2
                                }
                                out.write(buf, 0, n)
                            }
                        } finally {
                            try { rec.stop() } catch (_: Exception) {}
                            rec.release()
                        }
                    }
                }
            }
        } catch (e: Throwable) {
            status = "stopped: ${e.javaClass.simpleName}"
        }
        running = false
    }

    // Kavach's voice, read from the same socket, goes into the call itself where the phone allows it.
    private fun startVoice(socket: Socket) {
        val track = try { openVoiceTrack() } catch (e: Throwable) { voice = "no:" + (e.cause ?: e).javaClass.simpleName; null } ?: return
        voice = "yes"
        thread {
            try {
                track.play()
                val input = socket.getInputStream()
                val buf = ByteArray(3200)
                while (running) {
                    val n = input.read(buf)
                    if (n < 0) break
                    track.write(buf, 0, n)
                }
            } catch (_: Exception) {
            } finally {
                try { track.stop() } catch (_: Exception) {}
                track.release()
            }
        }
    }

    private fun openVoiceTrack(): AudioTrack {
        if (Build.VERSION.SDK_INT < 33) throw UnsupportedOperationException()
        val audio = ShellContext().getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val allowed = AudioManager::class.java.getMethod("isPstnCallAudioInterceptable").invoke(audio) as Boolean
        if (!allowed) throw UnsupportedOperationException()
        val format = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(16000)
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build()
        return AudioManager::class.java.getMethod("getCallUplinkInjectionAudioTrack", AudioFormat::class.java).invoke(audio, format) as AudioTrack
    }

    private fun open(source: Int): AudioRecord {
        val format = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(16000)
            .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build()
        val min = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val builder = AudioRecord.Builder().setAudioSource(source).setAudioFormat(format).setBufferSizeInBytes(8 * min)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) builder.setContext(ShellContext())
        val rec = builder.build()
        if (rec.state != AudioRecord.STATE_INITIALIZED) { rec.release(); throw IllegalStateException("not initialized") }
        return rec
    }

    // Android checks who is recording against the context: this says "the shell", which is what this process really is.
    private class ShellContext : ContextWrapper(systemContext()) {
        override fun getPackageName() = "com.android.shell"
        override fun getOpPackageName() = "com.android.shell"
        override fun getAttributionTag(): String? = null
        override fun getAttributionSource(): AttributionSource =
            AttributionSource.Builder(android.os.Process.myUid()).setPackageName("com.android.shell").build()
        override fun getApplicationContext(): Context = this
    }

    companion object {
        const val START = 1
        const val STATUS = 2
        const val STOP = 3
        const val DESTROY = 16777115 // Shizuku's own code for ending a user service
        val SOURCES = listOf("DOWNLINK" to MediaRecorder.AudioSource.VOICE_DOWNLINK, "CALL" to MediaRecorder.AudioSource.VOICE_CALL)

        private fun systemContext(): Context {
            val cls = Class.forName("android.app.ActivityThread")
            val current = cls.getDeclaredMethod("currentActivityThread").apply { isAccessible = true }.invoke(null)
                ?: cls.getDeclaredMethod("systemMain").apply { isAccessible = true }.invoke(null)
            return cls.getDeclaredMethod("getSystemContext").apply { isAccessible = true }.invoke(current) as Context
        }
    }
}
