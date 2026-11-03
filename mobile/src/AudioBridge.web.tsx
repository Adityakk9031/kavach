// Web / Mac version of the audio bridge: the same hidden audio page, in an iframe that is allowed to use the microphone.
import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import type { Command } from './bridge';

export type BridgeHandle = { send: (c: Command) => void };
type Props = { uri: string; onMessage: (m: any) => void };

export const AudioBridge = forwardRef<BridgeHandle, Props>(({ uri, onMessage }, ref) => {
  const frame = useRef<any>(null);
  useImperativeHandle(ref, () => ({
    send: (c) => frame.current?.contentWindow?.postMessage({ kavachCmd: c }, '*'),
  }));
  useEffect(() => {
    const origin = new URL(uri).origin;
    const handler = (e: MessageEvent) => {
      if (e.origin !== origin || typeof e.data !== 'string') return;
      try { onMessage(JSON.parse(e.data)); } catch { /* ignore non-JSON */ }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [uri, onMessage]);
  return React.createElement('iframe', {
    ref: frame, src: uri, allow: 'microphone; autoplay',
    style: { position: 'absolute', width: 2, height: 2, opacity: 0.01, border: 0 },
  });
});
