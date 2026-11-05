package com.kavach.app

import android.content.Context
import android.content.ContextWrapper
import android.content.AttributionSource
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
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
    private var savedCallVolume = -1

    override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
        when (code) {
            START -> { val port = data.readInt(); if (!running) { running = true; thread { capture(port) } } }
            STATUS -> reply?.writeString(if (source_.isEmpty()) status else "$source_|$voice")
            STOP -> running = false
            SPEAKER -> try {
                (ShellContext().getSystemService(Context.AUDIO_SERVICE) as AudioManager).isSpeakerphoneOn = data.readInt() == 1
            } catch (_: Throwable) {}
            SILENCE -> {
                val on = data.readInt() == 1
                reply?.writeString(try {
                    val audio = ShellContext().getSystemService(Context.AUDIO_SERVICE) as AudioManager
                    val stream = AudioManager.STREAM_VOICE_CALL
                    audio.adjustStreamVolume(stream, if (on) AudioManager.ADJUST_MUTE else AudioManager.ADJUST_UNMUTE, 0)
                    if (!on && savedCallVolume >= 0) { audio.setStreamVolume(stream, savedCallVolume, 0); savedCallVolume = -1 }
                    when {
                        audio.isStreamMute(stream) == on -> "ok"
                        // Some phones refuse a call mute: the lowest call volume still lets the warning be heard over the caller
                        on -> {
                            savedCallVolume = audio.getStreamVolume(stream)
                            audio.setStreamVolume(stream, audio.getStreamMinVolume(stream), 0)
                            "lowered"
                        }
                        else -> "refused"
                    }
                } catch (e: Throwable) { e.javaClass.simpleName })
            }
            MUTE -> try {
                (ShellContext().getSystemService(Context.AUDIO_SERVICE) as AudioManager).isMicrophoneMute = data.readInt() == 1
            } catch (_: Throwable) {}
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
        val (track, route) = try { openVoiceTrack() } catch (e: Throwable) { voice = "no " + e.message; null } ?: return
        thread {
            try {
                track.write(ByteArray(1280), 0, 1280, AudioTrack.WRITE_NON_BLOCKING)
                track.play()
                Thread.sleep(200)
                voice = "yes $route>" + track.routedDevice?.type
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

    // Two routes into the call, by phone: its telephony output, or the call redirection Android 13 added. A track with
    // the wrong settings can quietly play on the speaker instead, so the card shows the route and where it really went.
    private fun openVoiceTrack(): Pair<AudioTrack, String> {
        val failures = ArrayList<String>()
        val context = ShellContext()
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val format = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(16000)
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build()
        val min = AudioTrack.getMinBufferSize(16000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        fun builder() = AudioTrack.Builder().setAudioFormat(format).setBufferSizeInBytes(maxOf(min, 6400))
            .setTransferMode(AudioTrack.MODE_STREAM).also { if (Build.VERSION.SDK_INT >= 34) it.setContext(context) }
        try {
            val tx = audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).firstOrNull { it.type == AudioDeviceInfo.TYPE_TELEPHONY }
                ?: throw IllegalStateException("no output")
            val track = builder().setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()).build()
            if (track.state != AudioTrack.STATE_INITIALIZED || !track.setPreferredDevice(tx)) { track.release(); throw IllegalStateException("refused") }
            return track to "telephony"
        } catch (e: Throwable) { failures += "tel=" + reason(e) }
        try {
            if (Build.VERSION.SDK_INT < 33) throw IllegalStateException("android")
            val allowed = AudioManager::class.java.getMethod("isPstnCallAudioInterceptable").invoke(audio) as Boolean
            if (!allowed) throw IllegalStateException("not supported")
            val int = Int::class.javaPrimitiveType
            val attributes = AudioAttributes.Builder().setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).also {
                AudioAttributes.Builder::class.java.getMethod("setSystemUsage", int).invoke(it, USAGE_CALL_ASSISTANT)
            }.build()
            val b = builder().setAudioAttributes(attributes)
            AudioTrack.Builder::class.java.getMethod("setCallRedirectionMode", int).invoke(b, CALL_REDIRECT_PSTN)
            val track = b.build()
            if (track.state != AudioTrack.STATE_INITIALIZED) { track.release(); throw IllegalStateException("refused") }
            return track to "redirect"
        } catch (e: Throwable) { failures += "pstn=" + reason(e) }
        throw IllegalStateException(failures.joinToString(" "))
    }

    private fun reason(e: Throwable): String = ((e.cause ?: e).message ?: (e.cause ?: e).javaClass.simpleName).take(30)

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
        const val SPEAKER = 4
        const val MUTE = 5
        const val SILENCE = 6
        const val USAGE_CALL_ASSISTANT = 17
        const val CALL_REDIRECT_PSTN = 1
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
