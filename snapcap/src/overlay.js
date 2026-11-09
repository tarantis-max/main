'use strict';
// Region selector drawn over a frozen screenshot of one display.
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const hint = document.getElementById('hint');

let cfg = null;
let img = null;
let mouse = { x: -1, y: -1 };
let start = null;   // drag start (CSS px)
let sel = null;     // {x,y,width,height} CSS px

window.snapcap.onOverlayInit((c) => {
  cfg = c;
  img = new Image();
  img.onload = () => { resize(); draw(); };
  img.src = c.image;
  hint.innerHTML = c.purpose === 'record'
    ? 'Drag to choose the area to <b>record</b> · Click for full screen · Esc to cancel'
    : 'Drag to <b>capture</b> a region · Click for full screen · Esc to cancel';
});

function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(window.innerWidth * dpr);
  canvas.height = Math.round(window.innerHeight * dpr);
  canvas.style.width = window.innerWidth + 'px';
  canvas.style.height = window.innerHeight + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', () => { resize(); draw(); });

function rectFrom(a, b) {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
}

function draw() {
  if (!img) return;
  const W = window.innerWidth, H = window.innerHeight;
  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(img, 0, 0, W, H);
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  if (sel && sel.width > 0 && sel.height > 0) {
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    ctx.rect(sel.x, sel.y, sel.width, sel.height);
    ctx.fill('evenodd');
    ctx.strokeStyle = cfg.purpose === 'record' ? '#ff3b30' : '#ffb020';
    ctx.lineWidth = 2;
    ctx.setLineDash(cfg.purpose === 'record' ? [6, 4] : []);
    ctx.strokeRect(sel.x + 0.5, sel.y + 0.5, sel.width, sel.height);
    ctx.setLineDash([]);
    label(`${Math.round(sel.width * cfg.scaleFactor)} × ${Math.round(sel.height * cfg.scaleFactor)}`, sel.x, sel.y - 26 < 0 ? sel.y + 6 : sel.y - 26);
  } else {
    ctx.fillRect(0, 0, W, H);
  }
  if (mouse.x >= 0) {
    // crosshair
    ctx.strokeStyle = 'rgba(255,176,32,0.8)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, mouse.y + 0.5); ctx.lineTo(W, mouse.y + 0.5);
    ctx.moveTo(mouse.x + 0.5, 0); ctx.lineTo(mouse.x + 0.5, H);
    ctx.stroke();
    magnifier();
  }
}

function label(text, x, y) {
  ctx.font = '12px system-ui, sans-serif';
  const w = ctx.measureText(text).width + 14;
  ctx.fillStyle = 'rgba(20,22,28,0.9)';
  roundRect(x, y, w, 20, 4); ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.fillText(text, x + 7, y + 14);
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function magnifier() {
  const size = 120, zoom = 8;
  const W = window.innerWidth, H = window.innerHeight;
  let mx = mouse.x + 24, my = mouse.y + 24;
  if (mx + size > W) mx = mouse.x - size - 24;
  if (my + size + 22 > H) my = mouse.y - size - 46;
  const sx = img.naturalWidth / W, sy = img.naturalHeight / H;
  const srcW = size / zoom * sx, srcH = size / zoom * sy;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.beginPath(); ctx.rect(mx, my, size, size); ctx.clip();
  ctx.drawImage(img, mouse.x * sx - srcW / 2, mouse.y * sy - srcH / 2, srcW, srcH, mx, my, size, size);
  ctx.strokeStyle = 'rgba(255,176,32,0.9)';
  ctx.beginPath();
  ctx.moveTo(mx + size / 2, my); ctx.lineTo(mx + size / 2, my + size);
  ctx.moveTo(mx, my + size / 2); ctx.lineTo(mx + size, my + size / 2);
  ctx.stroke();
  ctx.restore();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.strokeRect(mx, my, size, size);
  // pixel colour + position
  const c = document.createElement('canvas'); c.width = c.height = 1;
  const cx = c.getContext('2d');
  cx.drawImage(img, Math.floor(mouse.x * sx), Math.floor(mouse.y * sy), 1, 1, 0, 0, 1, 1);
  const [r, g, b] = cx.getImageData(0, 0, 1, 1).data;
  const hex = '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('').toUpperCase();
  label(`${Math.round(mouse.x * cfg.scaleFactor)}, ${Math.round(mouse.y * cfg.scaleFactor)}  ${hex}`, mx, my + size + 2);
}

window.addEventListener('mousemove', (e) => {
  mouse = { x: e.clientX, y: e.clientY };
  if (start) sel = rectFrom(start, mouse);
  hint.style.display = start ? 'none' : '';
  requestAnimationFrame(draw);
});
window.addEventListener('mouseleave', () => { mouse = { x: -1, y: -1 }; requestAnimationFrame(draw); });

window.addEventListener('mousedown', (e) => {
  if (e.button === 2) return cancel();
  if (e.button !== 0) return;
  start = { x: e.clientX, y: e.clientY };
  sel = null;
});

window.addEventListener('mouseup', (e) => {
  if (!start || e.button !== 0) return;
  const r = rectFrom(start, { x: e.clientX, y: e.clientY });
  start = null;
  // A click (no real drag) captures the whole display.
  commit(r.width < 4 || r.height < 4 ? null : r);
});

window.addEventListener('contextmenu', (e) => e.preventDefault());

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') cancel();
  if (e.key === 'Enter') commit(sel && sel.width >= 4 && sel.height >= 4 ? sel : null);
});

function commit(rect) {
  window.snapcap.overlaySelect({ displayId: cfg.displayId, rect, purpose: cfg.purpose });
}
function cancel() { window.snapcap.overlayCancel(); }
