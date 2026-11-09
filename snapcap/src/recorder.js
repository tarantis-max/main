'use strict';
// Screen recorder: captures a display, crops to the selected region on a canvas,
// mixes optional microphone / system audio, and encodes with MediaRecorder.
const bar = document.getElementById('bar');
const timeEl = document.getElementById('time');
const statusEl = document.getElementById('status');
const pauseBtn = document.getElementById('pause');
const stopBtn = document.getElementById('stop');
const cancelBtn = document.getElementById('cancel');
const video = document.getElementById('v');

let recorder = null;
let chunks = [];
let streams = [];
let elapsed = 0, lastTick = 0, timer = null;
let cancelled = false;
let mime = '';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function pickMime() {
  const candidates = [
    'video/mp4;codecs=avc1.640028,mp4a.40.2',
    'video/mp4;codecs=avc1,mp4a',
    'video/mp4',
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm',
  ];
  return candidates.find((m) => MediaRecorder.isTypeSupported(m)) || '';
}

window.snapcap.onRecorderInit(async (cfg) => {
  try {
    await run(cfg);
  } catch (err) {
    stopStreams();
    window.snapcap.recorderError(String(err && err.message || err));
  }
});

async function run(cfg) {
  const sf = cfg.scaleFactor;
  const display = await navigator.mediaDevices.getDisplayMedia({
    video: {
      width: { ideal: Math.round(cfg.displaySize.width * sf) },
      height: { ideal: Math.round(cfg.displaySize.height * sf) },
      frameRate: { ideal: 30, max: 30 },
    },
    audio: !!cfg.systemAudio,
  });
  streams.push(display);

  let mic = null;
  if (cfg.mic) {
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      streams.push(mic);
    } catch { statusEl.textContent = 'Mic unavailable'; }
  }

  video.srcObject = display;
  await video.play();

  // Crop region (CSS px -> captured video px)
  const vw = video.videoWidth, vh = video.videoHeight;
  const kx = vw / cfg.displaySize.width, ky = vh / cfg.displaySize.height;
  const r = cfg.region;
  const sx = Math.round(r.x * kx), sy = Math.round(r.y * ky);
  // H.264 needs even dimensions
  const outW = Math.max(2, Math.round(r.width * kx) & ~1);
  const outH = Math.max(2, Math.round(r.height * ky) & ~1);

  const canvas = document.createElement('canvas');
  canvas.width = outW; canvas.height = outH;
  const ctx = canvas.getContext('2d', { alpha: false });
  const drawFrame = () => {
    ctx.drawImage(video, sx, sy, outW, outH, 0, 0, outW, outH);
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(drawFrame);
  };
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(drawFrame);
  else setInterval(drawFrame, 1000 / 30);
  drawFrame();

  const out = canvas.captureStream(30);

  // Audio: mix system + mic when both are present.
  const audioTracks = [...display.getAudioTracks(), ...(mic ? mic.getAudioTracks() : [])];
  if (audioTracks.length === 1) {
    out.addTrack(audioTracks[0]);
  } else if (audioTracks.length > 1) {
    const ac = new AudioContext();
    const dest = ac.createMediaStreamDestination();
    for (const t of audioTracks) ac.createMediaStreamSource(new MediaStream([t])).connect(dest);
    out.addTrack(dest.stream.getAudioTracks()[0]);
  }

  if (cfg.countdown) {
    for (let i = 3; i > 0; i--) { statusEl.textContent = `Recording in ${i}…`; await sleep(1000); }
    if (cancelled) return;
  }

  mime = pickMime();
  recorder = new MediaRecorder(out, { mimeType: mime || undefined, videoBitsPerSecond: 8_000_000 });
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  recorder.onstop = onStop;
  recorder.start(1000);

  bar.classList.add('recording');
  statusEl.textContent = `${outW}×${outH}` + (audioTracks.length ? ' · audio' : '');
  lastTick = performance.now();
  timer = setInterval(tick, 250);

  // If the user stops sharing from the OS UI, finish cleanly.
  display.getVideoTracks()[0].addEventListener('ended', () => stop());
}

function tick() {
  const now = performance.now();
  if (recorder && recorder.state === 'recording') elapsed += now - lastTick;
  lastTick = now;
  const s = Math.floor(elapsed / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  timeEl.textContent = (h ? h + ':' : '') + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
}

function stopStreams() {
  for (const s of streams) for (const t of s.getTracks()) t.stop();
  streams = [];
}

function stop() {
  clearInterval(timer);
  if (recorder && recorder.state !== 'inactive') recorder.stop();
  else { stopStreams(); window.snapcap.closeRecorder(); }
}

async function onStop() {
  stopStreams();
  if (cancelled) return window.snapcap.closeRecorder();
  statusEl.textContent = 'Saving…';
  const blob = new Blob(chunks, { type: mime || 'video/webm' });
  const ext = (mime || '').startsWith('video/mp4') ? 'mp4' : 'webm';
  await window.snapcap.saveRecording({ buffer: await blob.arrayBuffer(), ext });
}

pauseBtn.onclick = () => {
  if (!recorder) return;
  if (recorder.state === 'recording') {
    recorder.pause(); bar.classList.add('paused'); pauseBtn.textContent = 'Resume';
  } else if (recorder.state === 'paused') {
    recorder.resume(); bar.classList.remove('paused'); pauseBtn.textContent = 'Pause'; lastTick = performance.now();
  }
};
stopBtn.onclick = stop;
window.snapcap.onRecorderStop(() => stop());
cancelBtn.onclick = () => { cancelled = true; stop(); };
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') cancelBtn.onclick(); });
