import { useCallback, useEffect, useRef, useState } from 'react';

/* Voice-message recorder. MediaRecorder captures the mic (WebM/Opus in Chrome),
   then the clip is decoded and re-encoded as 16 kHz mono 16-bit WAV: small
   (~32 KB/s), plays everywhere, and is a format Gemini transcribes reliably. */

export const MAX_VOICE_MS = 60_000;
export const MIN_VOICE_MS = 700;

export interface VoiceClip {
  dataUrl: string;
  durationMs: number;
}

export const voiceSupported = () =>
  typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';

function encodeWav(samples: Float32Array, rate: number): ArrayBuffer {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF');
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, 'WAVE');
  str(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, 'data');
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return buf;
}

async function toWavDataUrl(blob: Blob): Promise<VoiceClip> {
  const raw = await blob.arrayBuffer();
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(raw);
    const rate = 16000;
    const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
    const src = off.createBufferSource();
    src.buffer = decoded;
    src.connect(off.destination);
    src.start();
    const mono = await off.startRendering();
    const wav = encodeWav(mono.getChannelData(0), rate);
    const b64 = btoa(Array.from(new Uint8Array(wav), (c) => String.fromCharCode(c)).join(''));
    return { dataUrl: `data:audio/wav;base64,${b64}`, durationMs: Math.round(decoded.duration * 1000) };
  } finally {
    void ctx.close();
  }
}

export function useVoiceRecorder(onClip: (clip: VoiceClip) => void, onError: (kind: 'blocked' | 'short' | 'failed') => void) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const started = useRef(0);
  const discard = useRef(false);
  const timer = useRef(0);
  const cbs = useRef({ onClip, onError });
  cbs.current = { onClip, onError };

  const cleanup = () => {
    window.clearInterval(timer.current);
    stream.current?.getTracks().forEach((tr) => tr.stop());
    stream.current = null;
    rec.current = null;
    setRecording(false);
    setElapsed(0);
  };

  const stop = useCallback(() => {
    if (rec.current?.state === 'recording') rec.current.stop();
  }, []);

  const cancel = useCallback(() => {
    discard.current = true;
    stop();
  }, [stop]);

  const start = useCallback(async () => {
    if (rec.current) return;
    let s: MediaStream;
    try {
      s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      cbs.current.onError('blocked');
      return;
    }
    const chunks: Blob[] = [];
    const r = new MediaRecorder(s);
    stream.current = s;
    rec.current = r;
    discard.current = false;
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = async () => {
      const ms = Date.now() - started.current;
      const dropped = discard.current;
      cleanup();
      if (dropped) return;
      if (ms < MIN_VOICE_MS) {
        cbs.current.onError('short');
        return;
      }
      try {
        cbs.current.onClip(await toWavDataUrl(new Blob(chunks, { type: r.mimeType })));
      } catch {
        cbs.current.onError('failed');
      }
    };
    started.current = Date.now();
    r.start(250);
    setRecording(true);
    timer.current = window.setInterval(() => {
      const ms = Date.now() - started.current;
      setElapsed(ms);
      if (ms >= MAX_VOICE_MS) stop();
    }, 200);
  }, [stop]);

  useEffect(() => () => {
    discard.current = true;
    if (rec.current?.state === 'recording') rec.current.stop();
  }, []);

  return { recording, elapsed, start, stop, cancel, supported: voiceSupported() };
}
