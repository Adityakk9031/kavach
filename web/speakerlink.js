// Logic for the Listener page (a real phone call on speaker, laptop listening). Pure, so it is unit-tested in Node.
//
// The laptop microphone hears the phone's speaker (the scammer). Anything Kavach itself plays out loud next to the
// phone would be picked up by that same microphone and transcribed as if the scammer had said it, and the persona
// would then answer itself. So the page is half-duplex: while Kavach speaks into the room, the microphone stream
// is replaced by silence, and for a short tail afterwards (the room's echo).

export class MicGate {
  constructor(tailMs = 400) {
    this.tailMs = tailMs;
    this.heldUntil = 0;
  }

  // Call for every microphone chunk. Returns true if this chunk must be sent as silence.
  //  personaPlaying      the takeover voice is coming out of the speaker next to the phone
  //  warningPlaying      the family-voice warning is playing
  //  warningOnSameSpeaker the warning goes to the SAME output as the persona (no separate headphones), so the
  //                       microphone would hear it too
  shouldMute({ personaPlaying, warningPlaying, warningOnSameSpeaker }, now) {
    const speaking = personaPlaying || (warningOnSameSpeaker && warningPlaying);
    if (speaking) this.heldUntil = now + this.tailMs;
    return speaking || now < this.heldUntil;
  }
}

export function silenceLike(buf) {
  return new ArrayBuffer(buf.byteLength); // zero-filled: digital silence the same length as the chunk
}
