// The hidden WebView that owns the microphone, the speaker and the socket to the Kavach server (web/bridge.html).
// Everything you see is drawn by React Native; this only moves sound and relays messages.
import React, { forwardRef, useImperativeHandle, useRef } from 'react';
import { WebView, WebViewMessageEvent } from 'react-native-webview';

// react-native-webview 14 types WebView as a plain function component, which rejects `ref` under React 19's types;
// at runtime it takes a ref fine, so this one component is typed loosely.
const RNWebView = WebView as unknown as React.ComponentType<any>;
import type { Command } from './bridge';

export type BridgeHandle = { send: (c: Command) => void };
type Props = { uri: string; onMessage: (m: any) => void };

export const AudioBridge = forwardRef<BridgeHandle, Props>(({ uri, onMessage }, ref) => {
  const web = useRef<any>(null);
  useImperativeHandle(ref, () => ({
    send: (c) => web.current?.injectJavaScript(`window.kavach && window.kavach.cmd(${JSON.stringify(c)}); true;`),
  }));
  return (
    <RNWebView
      ref={web}
      source={{ uri }}
      originWhitelist={['*']}
      javaScriptEnabled
      domStorageEnabled
      mediaPlaybackRequiresUserAction={false}
      allowsInlineMediaPlayback
      mediaCapturePermissionGrantType="grant"
      onMessage={(e: WebViewMessageEvent) => {
        try { onMessage(JSON.parse(e.nativeEvent.data)); } catch { /* ignore non-JSON */ }
      }}
      style={{ position: 'absolute', width: 2, height: 2, opacity: 0.01 }}
    />
  );
});
