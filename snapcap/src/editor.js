'use strict';
/* SnapCap image editor.
 * Document = base image (canvas) + list of vector annotation objects.
 * Objects stay editable; Save writes a flattened PNG plus a JSON sidecar. */

const $ = (s) => document.querySelector(s);
const api = window.snapcap || null;
const captureId = new URLSearchParams(location.search).get('id');

const canvas = $('#canvas');
const ctx = canvas.getContext('2d');
const scroller = $('#scroller');
const textEditor = $('#textEditor');
const SIZER_PAD = 24;
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

const PALETTE = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#007aff', '#af52de', '#ff2d55', '#5ac8fa', '#ffffff', '#8e8e93', '#000000'];

const RECT_LIKE = new Set(['rect', 'ellipse', 'highlight', 'blur', 'spotlight', 'magnify']);
const LINE_LIKE = new Set(['line', 'arrow']);

const DEFAULTS = {
  arrow: { color: '#ff3b30', width: 6, shadow: true },
  line: { color: '#ff3b30', width: 4, shadow: true },
  rect: { color: '#ff3b30', fill: 'none', width: 4, shadow: true },
  ellipse: { color: '#ff3b30', fill: 'none', width: 4, shadow: true },
  text: { color: '#ffffff', fill: '#ff3b30', fontSize: 28, shadow: true },
  step: { color: '#ffffff', fill: '#ff3b30', fontSize: 24, shadow: true },
  highlight: { color: '#ffcc00' },
  pen: { color: '#ff3b30', width: 5, shadow: false },
  blur: { amount: 12 },
  spotlight: { amount: 55 },
  magnify: { color: '#ffffff', width: 4, zoom: 2, shadow: true },
};
const PROPS = {
  arrow: ['color', 'width', 'shadow'], line: ['color', 'width', 'shadow'],
  rect: ['color', 'fill', 'width', 'shadow'], ellipse: ['color', 'fill', 'width', 'shadow'],
  text: ['color', 'fill', 'fontSize', 'shadow'], step: ['color', 'fill', 'fontSize', 'shadow'],
  highlight: ['color'], pen: ['color', 'width', 'shadow'], blur: ['amount'], spotlight: ['amount'],
  magnify: ['color', 'width', 'zoom', 'shadow'], crop: ['crop'], select: [],
};
const TOOL_KEYS = { v: 'select', a: 'arrow', l: 'line', r: 'rect', e: 'ellipse', t: 'text', n: 'step', h: 'highlight', p: 'pen', b: 'blur', s: 'spotlight', m: 'magnify', c: 'crop' };

// ---------- state ----------
let base = null;          // HTMLCanvasElement
let savedBase = null;     // base as last written to disk
let objects = [];
let selected = null;
let tool = 'select';
let zoom = 1;
let fitMode = true;
let undoStack = [], redoStack = [];
let drag = null;          // active pointer interaction
let cropRect = null;
let editing = null;       // text object being edited
let editSnap = null;
let sliderSnap = null;
let dirty = false;
let autosaveTimer = null;
let seq = 1;

const uid = () => 'o' + (seq++) + Math.random().toString(36).slice(2, 6);
const clone = (v) => JSON.parse(JSON.stringify(v));

// ---------- geometry helpers ----------
function norm(o) {
  return { x: Math.min(o.x, o.x + o.w), y: Math.min(o.y, o.y + o.h), w: Math.abs(o.w), h: Math.abs(o.h) };
}
function normalizeObj(o) { if (RECT_LIKE.has(o.type)) Object.assign(o, norm(o)); }
function distToSeg(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const L = dx * dx + dy * dy;
  let t = L ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / L : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}
function textBox(o) {
  const lines = (o.text || ' ').split('\n');
  ctx.save();
  ctx.font = `600 ${o.fontSize}px ${FONT}`;
  const tw = Math.max(o.fontSize * 0.6, ...lines.map((l) => ctx.measureText(l || ' ').width));
  ctx.restore();
  const lh = o.fontSize * 1.25;
  const pad = o.fill !== 'none' ? Math.round(o.fontSize * 0.45) : 0;
  return { x: o.x, y: o.y, w: tw + pad * 2, h: lines.length * lh + pad * 2, pad, lh, lines };
}
function stepRadius(o) { return o.fontSize * 0.9; }
function bounds(o) {
  if (RECT_LIKE.has(o.type)) return norm(o);
  if (LINE_LIKE.has(o.type)) return { x: Math.min(o.x1, o.x2), y: Math.min(o.y1, o.y2), w: Math.abs(o.x2 - o.x1), h: Math.abs(o.y2 - o.y1) };
  if (o.type === 'pen') {
    const xs = o.points.map((p) => p[0]), ys = o.points.map((p) => p[1]);
    const x = Math.min(...xs), y = Math.min(...ys);
    return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
  }
  if (o.type === 'text') { const b = textBox(o); return { x: b.x, y: b.y, w: b.w, h: b.h }; }
  if (o.type === 'step') { const r = stepRadius(o); return { x: o.x - r, y: o.y - r, w: r * 2, h: r * 2 }; }
  return { x: 0, y: 0, w: 0, h: 0 };
}

function hit(o, p) {
  const tol = 6 / zoom;
  const half = (o.width || 0) / 2;
  if (o.type === 'rect' || o.type === 'ellipse') {
    const r = norm(o);
    if (o.type === 'rect') {
      const inside = p.x >= r.x - tol && p.x <= r.x + r.w + tol && p.y >= r.y - tol && p.y <= r.y + r.h + tol;
      if (!inside) return false;
      if (o.fill !== 'none') return true;
      const inner = p.x > r.x + half + tol && p.x < r.x + r.w - half - tol && p.y > r.y + half + tol && p.y < r.y + r.h - half - tol;
      return !inner;
    }
    const rx = r.w / 2, ry = r.h / 2;
    if (rx < 1 || ry < 1) return false;
    const d = Math.hypot((p.x - r.x - rx) / rx, (p.y - r.y - ry) / ry);
    if (o.fill !== 'none') return d <= 1 + tol / Math.min(rx, ry);
    return Math.abs(d - 1) * Math.min(rx, ry) <= tol + half;
  }
  if (LINE_LIKE.has(o.type)) return distToSeg(p, { x: o.x1, y: o.y1 }, { x: o.x2, y: o.y2 }) <= tol + half;
  if (o.type === 'pen') {
    for (let i = 1; i < o.points.length; i++) {
      const a = { x: o.points[i - 1][0], y: o.points[i - 1][1] }, b = { x: o.points[i][0], y: o.points[i][1] };
      if (distToSeg(p, a, b) <= tol + half) return true;
    }
    return o.points.length === 1 && Math.hypot(p.x - o.points[0][0], p.y - o.points[0][1]) <= tol + half;
  }
  if (o.type === 'step') return Math.hypot(p.x - o.x, p.y - o.y) <= stepRadius(o) + tol;
  const b = bounds(o);
  return p.x >= b.x - tol && p.x <= b.x + b.w + tol && p.y >= b.y - tol && p.y <= b.y + b.h + tol;
}

function handlesFor(o) {
  if (!o) return [];
  if (RECT_LIKE.has(o.type)) {
    const r = norm(o);
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    return [
      { id: 'nw', x: r.x, y: r.y }, { id: 'n', x: cx, y: r.y }, { id: 'ne', x: r.x + r.w, y: r.y },
      { id: 'e', x: r.x + r.w, y: cy }, { id: 'se', x: r.x + r.w, y: r.y + r.h }, { id: 's', x: cx, y: r.y + r.h },
      { id: 'sw', x: r.x, y: r.y + r.h }, { id: 'w', x: r.x, y: cy },
    ];
  }
  if (LINE_LIKE.has(o.type)) return [{ id: 'p1', x: o.x1, y: o.y1 }, { id: 'p2', x: o.x2, y: o.y2 }];
  return [];
}
function hitHandle(o, p) {
  const tol = 7 / zoom;
  return handlesFor(o).find((h) => Math.abs(h.x - p.x) <= tol && Math.abs(h.y - p.y) <= tol) || null;
}
const CURSORS = { nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize', n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', p1: 'move', p2: 'move' };

// ---------- drawing ----------
function withShadow(c, o, fn) {
  c.save();
  if (o.shadow) {
    const k = c.getTransform().a; // shadows are in device px; scale them with the image
    c.shadowColor = 'rgba(0,0,0,0.45)';
    c.shadowBlur = 8 * k;
    c.shadowOffsetX = 2 * k;
    c.shadowOffsetY = 3 * k;
  }
  fn();
  c.restore();
}

function roundRectPath(c, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  c.beginPath();
  c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
}

// Copy the already-rendered pixels under a rect (image coords) into a scratch canvas.
function grabRendered(c, x, y, w, h, outW, outH) {
  const k = c.getTransform().a;
  const t = document.createElement('canvas');
  t.width = Math.max(1, Math.round(outW)); t.height = Math.max(1, Math.round(outH));
  const tc = t.getContext('2d');
  tc.imageSmoothingEnabled = true;
  tc.drawImage(c.canvas, x * k, y * k, w * k, h * k, 0, 0, t.width, t.height);
  return t;
}

function clampToImage(r) {
  const x = Math.max(0, r.x), y = Math.max(0, r.y);
  return { x, y, w: Math.min(base.width, r.x + r.w) - x, h: Math.min(base.height, r.y + r.h) - y };
}

function drawObject(c, o, opts = {}) {
  c.lineJoin = 'round';
  c.lineCap = 'round';
  switch (o.type) {
    case 'rect': {
      const r = norm(o);
      withShadow(c, o, () => {
        if (o.fill !== 'none') { c.fillStyle = o.fill; c.fillRect(r.x, r.y, r.w, r.h); }
        if (o.width > 0) { c.strokeStyle = o.color; c.lineWidth = o.width; c.lineJoin = 'miter'; c.strokeRect(r.x, r.y, r.w, r.h); }
      });
      break;
    }
    case 'ellipse': {
      const r = norm(o);
      withShadow(c, o, () => {
        c.beginPath();
        c.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2, r.h / 2, 0, 0, Math.PI * 2);
        if (o.fill !== 'none') { c.fillStyle = o.fill; c.fill(); }
        if (o.width > 0) { c.strokeStyle = o.color; c.lineWidth = o.width; c.stroke(); }
      });
      break;
    }
    case 'line':
      withShadow(c, o, () => {
        c.strokeStyle = o.color; c.lineWidth = o.width;
        c.beginPath(); c.moveTo(o.x1, o.y1); c.lineTo(o.x2, o.y2); c.stroke();
      });
      break;
    case 'arrow': {
      const dx = o.x2 - o.x1, dy = o.y2 - o.y1;
      const len = Math.hypot(dx, dy);
      if (len < 1) break;
      const ang = Math.atan2(dy, dx);
      const head = Math.min(len, Math.max(14, o.width * 3.4));
      const hw = head * 0.62;
      const bx = o.x2 - Math.cos(ang) * head, by = o.y2 - Math.sin(ang) * head;
      // Tapered shaft + head as one polygon so the shadow is drawn once.
      const tail = Math.max(1, o.width * 0.35), neck = o.width / 2;
      const nx = -Math.sin(ang), ny = Math.cos(ang);
      withShadow(c, o, () => {
        c.fillStyle = o.color;
        c.beginPath();
        c.moveTo(o.x1 + nx * tail, o.y1 + ny * tail);
        c.lineTo(bx + nx * neck, by + ny * neck);
        c.lineTo(bx + nx * hw, by + ny * hw);
        c.lineTo(o.x2, o.y2);
        c.lineTo(bx - nx * hw, by - ny * hw);
        c.lineTo(bx - nx * neck, by - ny * neck);
        c.lineTo(o.x1 - nx * tail, o.y1 - ny * tail);
        c.closePath();
        c.fill();
      });
      break;
    }
    case 'pen':
      withShadow(c, o, () => {
        c.strokeStyle = o.color; c.lineWidth = o.width;
        const pts = o.points;
        c.beginPath();
        c.moveTo(pts[0][0], pts[0][1]);
        if (pts.length === 1) c.lineTo(pts[0][0] + 0.01, pts[0][1]);
        for (let i = 1; i < pts.length - 1; i++) {
          const mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
          c.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
        }
        if (pts.length > 1) c.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
        c.stroke();
      });
      break;
    case 'highlight': {
      const r = norm(o);
      c.save();
      c.globalCompositeOperation = 'multiply';
      c.fillStyle = o.color;
      c.fillRect(r.x, r.y, r.w, r.h);
      c.restore();
      break;
    }
    case 'blur': {
      const r = clampToImage(norm(o));
      if (r.w < 1 || r.h < 1) break;
      const block = Math.max(2, o.amount);
      const small = grabRendered(c, r.x, r.y, r.w, r.h, Math.ceil(r.w / block), Math.ceil(r.h / block));
      c.save();
      c.imageSmoothingEnabled = false;
      c.drawImage(small, r.x, r.y, r.w, r.h);
      c.restore();
      break;
    }
    case 'spotlight': {
      const r = norm(o);
      c.save();
      c.fillStyle = `rgba(0,0,0,${Math.min(0.9, o.amount / 100)})`;
      c.beginPath();
      c.rect(0, 0, base.width, base.height);
      c.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2, r.h / 2, 0, 0, Math.PI * 2);
      c.fill('evenodd');
      c.restore();
      break;
    }
    case 'magnify': {
      const r = norm(o);
      if (r.w < 2 || r.h < 2) break;
      const z = o.zoom || 2;
      const sw = r.w / z, sh = r.h / z;
      const k = c.getTransform().a;
      const src = grabRendered(c, r.x + (r.w - sw) / 2, r.y + (r.h - sh) / 2, sw, sh, r.w * k, r.h * k);
      const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      withShadow(c, o, () => {
        c.beginPath(); c.ellipse(cx, cy, r.w / 2, r.h / 2, 0, 0, Math.PI * 2);
        c.fillStyle = '#000'; c.fill();
      });
      c.save();
      c.beginPath(); c.ellipse(cx, cy, r.w / 2, r.h / 2, 0, 0, Math.PI * 2); c.clip();
      c.drawImage(src, r.x, r.y, r.w, r.h);
      c.restore();
      if (o.width > 0) {
        c.save();
        c.strokeStyle = o.color; c.lineWidth = o.width;
        c.beginPath(); c.ellipse(cx, cy, r.w / 2, r.h / 2, 0, 0, Math.PI * 2); c.stroke();
        c.restore();
      }
      break;
    }
    case 'text': {
      const b = textBox(o);
      if (o.fill !== 'none') {
        withShadow(c, o, () => { roundRectPath(c, b.x, b.y, b.w, b.h, o.fontSize * 0.3); c.fillStyle = o.fill; c.fill(); });
      }
      if (opts.noText) break;
      const drawText = () => {
        c.font = `600 ${o.fontSize}px ${FONT}`;
        c.textBaseline = 'top';
        c.fillStyle = o.color;
        b.lines.forEach((l, i) => c.fillText(l, b.x + b.pad, b.y + b.pad + i * b.lh + (b.lh - o.fontSize) / 2));
      };
      if (o.fill === 'none') withShadow(c, o, drawText); else { c.save(); drawText(); c.restore(); }
      break;
    }
    case 'step': {
      const r = stepRadius(o);
      withShadow(c, o, () => {
        c.beginPath(); c.arc(o.x, o.y, r, 0, Math.PI * 2);
        c.fillStyle = o.fill !== 'none' ? o.fill : '#ff3b30'; c.fill();
      });
      c.save();
      c.font = `700 ${o.fontSize}px ${FONT}`;
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillStyle = o.color;
      c.fillText(String(o.n), o.x, o.y + o.fontSize * 0.04);
      c.restore();
      break;
    }
  }
}

function drawScene(c, { skipId } = {}) {
  c.drawImage(base, 0, 0);
  for (const o of objects) drawObject(c, o, o.id === skipId ? { noText: true } : {});
}

function exportCanvas(background) {
  const out = document.createElement('canvas');
  out.width = base.width; out.height = base.height;
  const c = out.getContext('2d');
  if (background) { c.fillStyle = background; c.fillRect(0, 0, out.width, out.height); }
  drawScene(c);
  return out;
}

// ---------- view ----------
function backingScale() {
  const dpr = window.devicePixelRatio || 1;
  let s = zoom * dpr;
  const maxDim = 16000, maxArea = 60e6;
  s = Math.min(s, maxDim / base.width, maxDim / base.height, Math.sqrt(maxArea / (base.width * base.height)));
  return s;
}

function layout() {
  if (!base) return;
  if (fitMode) {
    const aw = scroller.clientWidth - SIZER_PAD * 2, ah = scroller.clientHeight - SIZER_PAD * 2;
    zoom = Math.max(0.05, Math.min(1, aw / base.width, ah / base.height));
  }
  const s = backingScale();
  canvas.width = Math.round(base.width * s);
  canvas.height = Math.round(base.height * s);
  canvas.style.width = Math.round(base.width * zoom) + 'px';
  canvas.style.height = Math.round(base.height * zoom) + 'px';
  $('#zoomLabel').textContent = Math.round(zoom * 100) + '%';
  if (editing) positionTextEditor();
  render();
}

function setZoom(z) {
  fitMode = false;
  zoom = Math.max(0.05, Math.min(8, z));
  layout();
}

let renderQueued = false;
function render() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderNow(); });
}

function renderNow() {
  if (!base) return;
  const s = canvas.width / base.width;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(s, 0, 0, s, 0, 0);
  ctx.imageSmoothingEnabled = zoom < 1;
  drawScene(ctx, { skipId: editing && editing.id });

  const px = 1 / zoom;
  if (selected && !editing) {
    const b = bounds(selected);
    ctx.save();
    ctx.setLineDash([4 * px, 3 * px]);
    ctx.lineWidth = px;
    ctx.strokeStyle = '#ffb020';
    if (!RECT_LIKE.has(selected.type) && !LINE_LIKE.has(selected.type)) {
      ctx.strokeRect(b.x - 4 * px, b.y - 4 * px, b.w + 8 * px, b.h + 8 * px);
    }
    ctx.setLineDash([]);
    for (const h of handlesFor(selected)) {
      ctx.fillStyle = '#fff'; ctx.strokeStyle = '#ffb020'; ctx.lineWidth = 1.5 * px;
      ctx.fillRect(h.x - 4 * px, h.y - 4 * px, 8 * px, 8 * px);
      ctx.strokeRect(h.x - 4 * px, h.y - 4 * px, 8 * px, 8 * px);
    }
    ctx.restore();
  }
  if (tool === 'crop' && cropRect) {
    const r = norm(cropRect);
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.beginPath(); ctx.rect(0, 0, base.width, base.height); ctx.rect(r.x, r.y, r.w, r.h); ctx.fill('evenodd');
    ctx.strokeStyle = '#ffb020'; ctx.lineWidth = 1.5 * px; ctx.strokeRect(r.x, r.y, r.w, r.h);
    ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = px;
    ctx.beginPath();
    for (let i = 1; i < 3; i++) {
      ctx.moveTo(r.x + r.w * i / 3, r.y); ctx.lineTo(r.x + r.w * i / 3, r.y + r.h);
      ctx.moveTo(r.x, r.y + r.h * i / 3); ctx.lineTo(r.x + r.w, r.y + r.h * i / 3);
    }
    ctx.stroke();
    ctx.restore();
  }
  updateInfo();
}

// ---------- undo ----------
const snapshot = () => ({ base, objects: JSON.stringify(objects), sel: selected && selected.id });
function restore(s) {
  base = s.base;
  objects = JSON.parse(s.objects);
  selected = objects.find((o) => o.id === s.sel) || null;
  layout();
  refreshProps();
  changed();
}
function pushUndo(s = snapshot()) {
  undoStack.push(s);
  if (undoStack.length > 200) undoStack.shift();
  redoStack = [];
  changed();
}
function undo() { commitText(); if (!undoStack.length) return; redoStack.push(snapshot()); restore(undoStack.pop()); }
function redo() { commitText(); if (!redoStack.length) return; undoStack.push(snapshot()); restore(redoStack.pop()); }

function changed() {
  dirty = true;
  if (api && captureId) {
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => save(true), 1500);
  }
}

// ---------- pointer interaction ----------
function toImage(e) {
  const r = canvas.getBoundingClientRect();
  return { x: (e.clientX - r.left) / zoom, y: (e.clientY - r.top) / zoom };
}
function topHit(p) {
  for (let i = objects.length - 1; i >= 0; i--) if (hit(objects[i], p)) return objects[i];
  return null;
}
function newObject(type, extra) {
  const o = { id: uid(), type, ...clone(DEFAULTS[type]), ...extra };
  objects.push(o);
  return o;
}
function nextStep() { return objects.filter((o) => o.type === 'step').reduce((m, o) => Math.max(m, o.n), 0) + 1; }

canvas.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || !base) return;
  if (editing) { commitText(); return; }
  canvas.setPointerCapture(e.pointerId);
  const p = toImage(e);
  const snap = snapshot();

  // Handles of the selected object work in every tool.
  const h = selected && tool !== 'crop' ? hitHandle(selected, p) : null;
  if (h) { drag = { kind: 'resize', handle: h.id, start: p, orig: clone(selected), snap }; return; }

  switch (tool) {
    case 'select': {
      const o = topHit(p);
      selected = o;
      refreshProps();
      if (o) drag = { kind: 'move', start: p, orig: clone(o), snap };
      render();
      return;
    }
    case 'crop':
      cropRect = { x: p.x, y: p.y, w: 0, h: 0 };
      drag = { kind: 'crop', start: p };
      return;
    case 'text': {
      const o = topHit(p);
      if (o && o.type === 'text') { selected = o; startText(o, snap); return; }
      const t = newObject('text', { x: p.x, y: p.y - DEFAULTS.text.fontSize * 0.6, text: '' });
      selected = t;
      startText(t, snap);
      return;
    }
    case 'step': {
      const o = newObject('step', { x: p.x, y: p.y, n: nextStep() });
      selected = o;
      drag = { kind: 'move', start: p, orig: clone(o), snap, created: true };
      refreshProps();
      render();
      return;
    }
    case 'pen': {
      const o = newObject('pen', { points: [[p.x, p.y]] });
      selected = o;
      drag = { kind: 'pen', obj: o, snap };
      render();
      return;
    }
    case 'arrow': case 'line': {
      const o = newObject(tool, { x1: p.x, y1: p.y, x2: p.x, y2: p.y });
      selected = o;
      drag = { kind: 'create', obj: o, start: p, snap };
      return;
    }
    default: { // rect-like tools
      const o = newObject(tool, { x: p.x, y: p.y, w: 0, h: 0 });
      selected = o;
      drag = { kind: 'create', obj: o, start: p, snap };
    }
  }
});

canvas.addEventListener('pointermove', (e) => {
  if (!base) return;
  const p = toImage(e);
  if (!drag) { updateCursor(p); return; }
  const dx = p.x - (drag.start ? drag.start.x : 0), dy = p.y - (drag.start ? drag.start.y : 0);
  if (drag.kind === 'move') {
    moveObject(selected, drag.orig, dx, dy);
    drag.moved = drag.moved || Math.abs(dx) + Math.abs(dy) > 0;
  } else if (drag.kind === 'resize') {
    resizeObject(selected, drag.orig, drag.handle, p, e.shiftKey);
    drag.moved = true;
  } else if (drag.kind === 'create') {
    const o = drag.obj;
    if (LINE_LIKE.has(o.type)) {
      let x2 = p.x, y2 = p.y;
      if (e.shiftKey) { // snap to 45°
        const ang = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4);
        const len = Math.hypot(dx, dy);
        x2 = drag.start.x + Math.cos(ang) * len; y2 = drag.start.y + Math.sin(ang) * len;
      }
      o.x2 = x2; o.y2 = y2;
    } else {
      let w = dx, h = dy;
      if (e.shiftKey) { const m = Math.max(Math.abs(w), Math.abs(h)); w = Math.sign(w || 1) * m; h = Math.sign(h || 1) * m; }
      o.w = w; o.h = h;
    }
  } else if (drag.kind === 'pen') {
    const pts = drag.obj.points, last = pts[pts.length - 1];
    if (Math.hypot(p.x - last[0], p.y - last[1]) > 1.5 / zoom) pts.push([p.x, p.y]);
  } else if (drag.kind === 'crop') {
    cropRect.w = p.x - drag.start.x; cropRect.h = p.y - drag.start.y;
    if (e.shiftKey) { const m = Math.max(Math.abs(cropRect.w), Math.abs(cropRect.h)); cropRect.w = Math.sign(cropRect.w || 1) * m; cropRect.h = Math.sign(cropRect.h || 1) * m; }
  }
  render();
});

function endDrag() {
  if (!drag) return;
  const d = drag; drag = null;
  if (d.kind === 'create') {
    const o = d.obj;
    const size = LINE_LIKE.has(o.type) ? Math.hypot(o.x2 - o.x1, o.y2 - o.y1) : Math.min(Math.abs(o.w), Math.abs(o.h));
    if (size < 3) {
      if (o.type === 'magnify') { Object.assign(o, { x: o.x - 90, y: o.y - 90, w: 180, h: 180 }); pushUndo(d.snap); }
      else { objects.splice(objects.indexOf(o), 1); selected = null; }
    } else { normalizeObj(o); pushUndo(d.snap); }
  } else if (d.kind === 'pen') {
    pushUndo(d.snap);
  } else if (d.kind === 'move' || d.kind === 'resize') {
    if (selected) normalizeObj(selected);
    if (d.moved || d.created) pushUndo(d.snap);
  } else if (d.kind === 'crop') {
    const r = norm(cropRect);
    if (r.w < 3 || r.h < 3) cropRect = null;
  }
  refreshProps();
  render();
}
// Stop the canvas from taking focus (it would blur the text editor mid-edit).
canvas.addEventListener('mousedown', (e) => e.preventDefault());
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);

canvas.addEventListener('dblclick', (e) => {
  const o = topHit(toImage(e));
  if (o && o.type === 'text') { selected = o; startText(o, snapshot()); }
});

function updateCursor(p) {
  const h = selected ? hitHandle(selected, p) : null;
  if (h) canvas.style.cursor = CURSORS[h.id];
  else if (tool === 'select') canvas.style.cursor = topHit(p) ? 'move' : 'default';
  else if (tool === 'text') canvas.style.cursor = 'text';
  else canvas.style.cursor = 'crosshair';
}

function moveObject(o, orig, dx, dy) {
  if (RECT_LIKE.has(o.type) || o.type === 'text' || o.type === 'step') { o.x = orig.x + dx; o.y = orig.y + dy; }
  else if (LINE_LIKE.has(o.type)) { o.x1 = orig.x1 + dx; o.y1 = orig.y1 + dy; o.x2 = orig.x2 + dx; o.y2 = orig.y2 + dy; }
  else if (o.type === 'pen') o.points = orig.points.map(([x, y]) => [x + dx, y + dy]);
}

function resizeObject(o, orig, handle, p, shift) {
  if (handle === 'p1' || handle === 'p2') {
    const k = handle === 'p1' ? ['x1', 'y1', 'x2', 'y2'] : ['x2', 'y2', 'x1', 'y1'];
    let x = p.x, y = p.y;
    if (shift) {
      const ax = orig[k[2]], ay = orig[k[3]];
      const ang = Math.round(Math.atan2(y - ay, x - ax) / (Math.PI / 4)) * (Math.PI / 4);
      const len = Math.hypot(x - ax, y - ay);
      x = ax + Math.cos(ang) * len; y = ay + Math.sin(ang) * len;
    }
    o[k[0]] = x; o[k[1]] = y;
    return;
  }
  const r = norm(orig);
  let x1 = r.x, y1 = r.y, x2 = r.x + r.w, y2 = r.y + r.h;
  if (handle.includes('w')) x1 = p.x;
  if (handle.includes('e')) x2 = p.x;
  if (handle.includes('n')) y1 = p.y;
  if (handle.includes('s')) y2 = p.y;
  if (shift && handle.length === 2) { // keep aspect ratio on corners
    const ar = r.w / Math.max(1, r.h);
    const w = x2 - x1, h = y2 - y1;
    if (Math.abs(w) / ar > Math.abs(h)) { const nh = Math.sign(h || 1) * Math.abs(w) / ar; if (handle.includes('n')) y1 = y2 - nh; else y2 = y1 + nh; }
    else { const nw = Math.sign(w || 1) * Math.abs(h) * ar; if (handle.includes('w')) x1 = x2 - nw; else x2 = x1 + nw; }
  }
  o.x = x1; o.y = y1; o.w = x2 - x1; o.h = y2 - y1;
}

// ---------- text editing ----------
function startText(o, snap) {
  editing = o;
  editSnap = { snap, before: o.text };
  textEditor.value = o.text;
  textEditor.style.display = 'block';
  positionTextEditor();
  refreshProps();
  render();
  textEditor.focus();
  textEditor.select();
  setTimeout(() => { if (editing === o && document.activeElement !== textEditor) textEditor.focus(); }, 0);
}
function positionTextEditor() {
  const o = editing;
  const b = textBox({ ...o, text: textEditor.value });
  Object.assign(textEditor.style, {
    left: (SIZER_PAD + (b.x + b.pad) * zoom) + 'px',
    top: (SIZER_PAD + (b.y + b.pad) * zoom) + 'px',
    width: ((b.w - b.pad * 2) * zoom + o.fontSize * zoom) + 'px',
    height: (b.lines.length * b.lh * zoom + 4) + 'px',
    fontSize: (o.fontSize * zoom) + 'px',
    lineHeight: (b.lh * zoom) + 'px',
    color: o.color,
  });
}
textEditor.addEventListener('input', () => { if (editing) { editing.text = textEditor.value; positionTextEditor(); render(); } });
textEditor.addEventListener('keydown', (e) => {
  e.stopPropagation();
  if (e.key === 'Escape' || (e.key === 'Enter' && (e.ctrlKey || e.metaKey))) { e.preventDefault(); commitText(); }
});
textEditor.addEventListener('blur', () => commitText());

function commitText() {
  if (!editing) return;
  const o = editing;
  editing = null;
  o.text = textEditor.value.replace(/\s+$/, '');
  textEditor.blur(); // release keyboard focus so tool shortcuts work again
  textEditor.style.display = 'none';
  if (!o.text.trim()) {
    objects.splice(objects.indexOf(o), 1);
    if (selected === o) selected = null;
    if (editSnap.before) pushUndo(editSnap.snap); // removed an existing text
  } else if (o.text !== editSnap.before) {
    pushUndo(editSnap.snap);
  }
  editSnap = null;
  refreshProps();
  render();
}

// ---------- image operations (keep objects editable by mapping their geometry) ----------
function mapObjects(f, s = 1) {
  for (const o of objects) {
    if (RECT_LIKE.has(o.type)) {
      const r = norm(o);
      const a = f(r.x, r.y), b = f(r.x + r.w, r.y + r.h);
      Object.assign(o, { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(b[0] - a[0]), h: Math.abs(b[1] - a[1]) });
      if (o.width) o.width *= s;
      if (o.type === 'blur') o.amount = Math.max(2, Math.round(o.amount * s));
    } else if (LINE_LIKE.has(o.type)) {
      [o.x1, o.y1] = f(o.x1, o.y1); [o.x2, o.y2] = f(o.x2, o.y2); o.width *= s;
    } else if (o.type === 'pen') {
      o.points = o.points.map(([x, y]) => f(x, y)); o.width *= s;
    } else if (o.type === 'text') {
      const b = textBox(o);
      const c = [f(b.x, b.y), f(b.x + b.w, b.y), f(b.x, b.y + b.h), f(b.x + b.w, b.y + b.h)];
      o.fontSize *= s;
      o.x = Math.min(...c.map((q) => q[0])); o.y = Math.min(...c.map((q) => q[1]));
    } else if (o.type === 'step') {
      [o.x, o.y] = f(o.x, o.y); o.fontSize *= s;
    }
  }
}

function newBase(w, h, draw) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
  draw(c.getContext('2d'), c);
  return c;
}

function imageOp(fn) {
  commitText();
  const snap = snapshot();
  fn();
  pushUndo(snap);
  layout();
  refreshProps();
}

const ops = {
  rotateR: () => imageOp(() => {
    const W = base.width, H = base.height, old = base;
    base = newBase(H, W, (c) => { c.translate(H, 0); c.rotate(Math.PI / 2); c.drawImage(old, 0, 0); });
    mapObjects((x, y) => [H - y, x]);
  }),
  rotateL: () => imageOp(() => {
    const W = base.width, H = base.height, old = base;
    base = newBase(H, W, (c) => { c.translate(0, W); c.rotate(-Math.PI / 2); c.drawImage(old, 0, 0); });
    mapObjects((x, y) => [y, W - x]);
  }),
  flipH: () => imageOp(() => {
    const W = base.width, old = base;
    base = newBase(W, base.height, (c) => { c.translate(W, 0); c.scale(-1, 1); c.drawImage(old, 0, 0); });
    mapObjects((x, y) => [W - x, y]);
  }),
  flipV: () => imageOp(() => {
    const H = base.height, old = base;
    base = newBase(base.width, H, (c) => { c.translate(0, H); c.scale(1, -1); c.drawImage(old, 0, 0); });
    mapObjects((x, y) => [x, H - y]);
  }),
  crop: (r) => imageOp(() => {
    const old = base;
    base = newBase(r.w, r.h, (c) => c.drawImage(old, -r.x, -r.y));
    mapObjects((x, y) => [x - r.x, y - r.y]);
  }),
  async resize() {
    const v = await modal('Resize image', [
      { name: 'w', label: 'Width (px)', type: 'number', value: base.width, min: 1, max: 20000 },
      { name: 'h', label: 'Height (px)', type: 'number', value: base.height, min: 1, max: 20000 },
      { name: 'lock', label: 'Keep proportions', type: 'checkbox', value: true },
    ], (form) => {
      const ar = base.width / base.height;
      form.w.addEventListener('input', () => { if (form.lock.checked) form.h.value = Math.max(1, Math.round(form.w.value / ar)); });
      form.h.addEventListener('input', () => { if (form.lock.checked) form.w.value = Math.max(1, Math.round(form.h.value * ar)); });
    });
    if (!v) return;
    const w = Math.max(1, Math.round(+v.w)), h = Math.max(1, Math.round(+v.h));
    if (w === base.width && h === base.height) return;
    imageOp(() => {
      const sx = w / base.width, sy = h / base.height, old = base;
      base = newBase(w, h, (c) => { c.imageSmoothingQuality = 'high'; c.drawImage(old, 0, 0, w, h); });
      mapObjects((x, y) => [x * sx, y * sy], Math.sqrt(sx * sy));
    });
  },
  async border() {
    const v = await modal('Add border', [
      { name: 'size', label: 'Width (px)', type: 'number', value: 6, min: 1, max: 500 },
      { name: 'color', label: 'Color', type: 'color', value: '#000000' },
    ]);
    if (!v) return;
    const b = Math.max(1, Math.round(+v.size));
    imageOp(() => {
      const old = base;
      base = newBase(old.width + b * 2, old.height + b * 2, (c, cv) => { c.fillStyle = v.color; c.fillRect(0, 0, cv.width, cv.height); c.drawImage(old, b, b); });
      mapObjects((x, y) => [x + b, y + b]);
    });
  },
  async shadow() {
    const v = await modal('Add drop shadow', [
      { name: 'blur', label: 'Softness (px)', type: 'number', value: 24, min: 0, max: 200 },
      { name: 'offset', label: 'Offset (px)', type: 'number', value: 10, min: 0, max: 200 },
      { name: 'opacity', label: 'Opacity (%)', type: 'number', value: 45, min: 0, max: 100 },
    ]);
    if (!v) return;
    const blur = Math.max(0, +v.blur), off = Math.max(0, +v.offset);
    const pad = Math.ceil(blur * 1.5);
    imageOp(() => {
      const old = base;
      base = newBase(old.width + pad * 2 + off, old.height + pad * 2 + off, (c) => {
        c.shadowColor = `rgba(0,0,0,${Math.min(1, Math.max(0, +v.opacity / 100))})`;
        c.shadowBlur = blur; c.shadowOffsetX = off; c.shadowOffsetY = off;
        c.fillStyle = '#fff';
        c.fillRect(pad, pad, old.width, old.height);
        c.shadowColor = 'transparent';
        c.drawImage(old, pad, pad);
      });
      mapObjects((x, y) => [x + pad, y + pad]);
    });
  },
};

function applyCrop() {
  if (!cropRect) return;
  const r = clampToImage(norm(cropRect));
  cropRect = null;
  if (r.w >= 1 && r.h >= 1) {
    ops.crop({ x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) });
    fitMode = true; layout();
  }
  setTool('select');
}

// ---------- object commands ----------
function deleteSelected() {
  if (!selected) return;
  const snap = snapshot();
  objects.splice(objects.indexOf(selected), 1);
  selected = null;
  pushUndo(snap); refreshProps(); render();
}
function duplicateSelected() {
  if (!selected) return;
  const snap = snapshot();
  const c = clone(selected); c.id = uid();
  moveObject(c, clone(c), 16, 16);
  if (c.type === 'step') c.n = nextStep();
  objects.push(c); selected = c;
  pushUndo(snap); refreshProps(); render();
}
function reorder(front) {
  if (!selected) return;
  const snap = snapshot();
  objects.splice(objects.indexOf(selected), 1);
  if (front) objects.push(selected); else objects.unshift(selected);
  pushUndo(snap); render();
}
function nudge(dx, dy) {
  if (!selected) return;
  const snap = snapshot();
  moveObject(selected, clone(selected), dx, dy);
  pushUndo(snap); render();
}

// ---------- output ----------
async function save(silent) {
  clearTimeout(autosaveTimer);
  commitText();
  const output = exportCanvas().toDataURL('image/png');
  if (!api) { // browser mode: download
    const a = document.createElement('a'); a.href = output; a.download = 'snapcap.png'; a.click();
    dirty = false; return;
  }
  await api.saveCapture({
    id: captureId, output,
    base: base !== savedBase ? base.toDataURL('image/png') : null,
    objects,
  });
  savedBase = base;
  dirty = false;
  if (!silent) toast('Saved to library');
}

async function exportAs() {
  commitText();
  const png = exportCanvas().toDataURL('image/png');
  if (!api) { const a = document.createElement('a'); a.href = png; a.download = 'snapcap.png'; a.click(); return; }
  const flat = exportCanvas('#ffffff');
  const file = await api.saveAs({
    suggested: captureId || 'snapcap',
    dataUrls: { png, jpeg: flat.toDataURL('image/jpeg', 0.92), webp: exportCanvas().toDataURL('image/webp', 0.95) },
  });
  if (file) toast('Exported ' + file.split(/[\\/]/).pop());
}

async function copyImage() {
  commitText();
  const out = exportCanvas();
  if (api) { await api.copyImage(out.toDataURL('image/png')); toast('Copied to clipboard'); return; }
  out.toBlob(async (blob) => {
    try { await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]); toast('Copied to clipboard'); }
    catch { toast('Clipboard not available'); }
  });
}

// ---------- UI: tools & properties ----------
function setTool(t) {
  commitText();
  if (tool === 'crop' && t !== 'crop') cropRect = null;
  tool = t;
  document.querySelectorAll('#tools button').forEach((b) => b.classList.toggle('active', b.dataset.tool === t));
  if (t !== 'select' && selected && t !== selected.type) selected = null;
  refreshProps();
  render();
}

function buildSwatches(el, key, withNone) {
  el.innerHTML = '';
  const colors = withNone ? ['none', ...PALETTE.slice(0, 10)] : PALETTE;
  for (const c of colors) {
    const b = document.createElement('button');
    b.className = 'swatch' + (c === 'none' ? ' none' : '');
    b.dataset.value = c;
    b.title = c === 'none' ? 'No fill' : c;
    if (c !== 'none') b.style.background = c;
    b.onclick = () => setProp(key, c);
    el.appendChild(b);
  }
  const custom = document.createElement('label');
  custom.className = 'swatch custom'; custom.title = 'Custom color';
  const input = document.createElement('input'); input.type = 'color';
  input.addEventListener('change', () => setProp(key, input.value));
  custom.appendChild(input);
  el.appendChild(custom);
}

function currentTarget() {
  // Selected object if any, else the active tool's defaults.
  if (selected) return { type: selected.type, values: selected, isObj: true };
  if (DEFAULTS[tool]) return { type: tool, values: DEFAULTS[tool], isObj: false };
  return { type: tool, values: {}, isObj: false };
}

function setProp(key, value, { coalesce } = {}) {
  const t = currentTarget();
  if (DEFAULTS[t.type]) DEFAULTS[t.type][key] = value;
  if (t.isObj) {
    if (coalesce) { if (!sliderSnap) sliderSnap = snapshot(); }
    else pushUndo();
    selected[key] = value;
    if (editing === selected) positionTextEditor();
  }
  refreshProps();
  render();
}

function refreshProps() {
  const t = currentTarget();
  const props = PROPS[t.type] || [];
  document.querySelectorAll('.prop').forEach((el) => {
    const f = el.dataset.for;
    el.hidden = f === 'object' ? !selected : !props.includes(f);
  });
  const names = { select: 'Select', arrow: 'Arrow', line: 'Line', rect: 'Shape', ellipse: 'Ellipse', text: 'Text', step: 'Step', highlight: 'Highlight', pen: 'Pen', blur: 'Blur', spotlight: 'Spotlight', magnify: 'Magnify', crop: 'Crop' };
  $('#propsTitle').textContent = names[t.type] || 'Properties';
  const v = t.values;
  for (const [key, el] of [['color', '#colorSwatches'], ['fill', '#fillSwatches']]) {
    document.querySelectorAll(el + ' .swatch').forEach((s) => s.classList.toggle('selected', s.dataset.value === v[key]));
  }
  if (v.width != null) { $('#width').value = v.width; $('#widthOut').textContent = Math.round(v.width); }
  if (v.fontSize != null) { $('#fontSize').value = v.fontSize; $('#fontOut').textContent = Math.round(v.fontSize); }
  if (v.amount != null) { $('#amount').value = v.amount; $('#amountOut').textContent = v.amount; }
  if (v.zoom != null) { $('#magZoom').value = v.zoom; $('#zoomOut').textContent = v.zoom + '×'; }
  if (v.shadow != null) $('#shadow').checked = !!v.shadow;
}

function updateInfo() {
  if (!base) return;
  let s = `Image: ${base.width} × ${base.height}px\nObjects: ${objects.length}`;
  if (selected) { const b = bounds(selected); s += `\nSelection: ${Math.round(b.w)} × ${Math.round(b.h)} at ${Math.round(b.x)}, ${Math.round(b.y)}`; }
  if (tool === 'crop' && cropRect) { const r = norm(cropRect); s += `\nCrop: ${Math.round(r.w)} × ${Math.round(r.h)}`; }
  $('#info').textContent = s;
}

for (const [id, key] of [['#width', 'width'], ['#fontSize', 'fontSize'], ['#amount', 'amount'], ['#magZoom', 'zoom']]) {
  const el = $(id);
  el.addEventListener('input', () => setProp(key, +el.value, { coalesce: true }));
  el.addEventListener('change', () => { if (sliderSnap) { pushUndo(sliderSnap); sliderSnap = null; } });
}
$('#shadow').addEventListener('change', (e) => setProp('shadow', e.target.checked));
$('#cropApply').onclick = applyCrop;
$('#cropCancel').onclick = () => { cropRect = null; setTool('select'); };

document.querySelectorAll('#tools button').forEach((b) => { b.onclick = () => setTool(b.dataset.tool); });

const commands = {
  undo, redo, save: () => save(false), saveAs: exportAs, copy: copyImage,
  zoomIn: () => setZoom(zoom * 1.25), zoomOut: () => setZoom(zoom / 1.25), zoomFit: () => { fitMode = true; layout(); },
  duplicate: duplicateSelected, delete: deleteSelected, front: () => reorder(true), back: () => reorder(false),
  rotateL: ops.rotateL, rotateR: ops.rotateR, flipH: ops.flipH, flipV: ops.flipV,
  resize: ops.resize, border: ops.border, shadow: ops.shadow,
};
document.querySelectorAll('[data-cmd]').forEach((b) => { b.onclick = () => commands[b.dataset.cmd](); });

// ---------- keyboard ----------
window.addEventListener('keydown', (e) => {
  if (!$('#modal').hidden) return;
  const ae = document.activeElement;
  if (ae && ae.tagName === 'INPUT' && /^(text|number|color)$/.test(ae.type)) return;
  const mod = e.ctrlKey || e.metaKey;
  const k = e.key.toLowerCase();
  if (mod) {
    if (k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); redo(); }
    else if (k === 's') { e.preventDefault(); e.shiftKey ? exportAs() : save(false); }
    else if (k === 'c') { e.preventDefault(); copyImage(); }
    else if (k === 'd') { e.preventDefault(); duplicateSelected(); }
    else if (k === '=' || k === '+') { e.preventDefault(); commands.zoomIn(); }
    else if (k === '-') { e.preventDefault(); commands.zoomOut(); }
    else if (k === '0') { e.preventDefault(); commands.zoomFit(); }
    return;
  }
  if (k === 'delete' || k === 'backspace') { e.preventDefault(); deleteSelected(); return; }
  if (k === 'escape') { if (tool === 'crop') { cropRect = null; setTool('select'); } else { selected = null; refreshProps(); render(); } return; }
  if (k === 'enter' && tool === 'crop') { applyCrop(); return; }
  if (e.key.startsWith('Arrow') && selected) {
    e.preventDefault();
    const step = e.shiftKey ? 10 : 1;
    nudge(e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0, e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0);
    return;
  }
  if (TOOL_KEYS[k] && !e.altKey) setTool(TOOL_KEYS[k]);
});

scroller.addEventListener('wheel', (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  setZoom(zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
}, { passive: false });

window.addEventListener('resize', () => { if (fitMode) layout(); });
window.addEventListener('beforeunload', () => { if (dirty && api && captureId) save(true); });

// ---------- modal & toast ----------
function modal(title, fields, setup) {
  return new Promise((resolve) => {
    const m = $('#modal'), body = $('#modalBody'), form = $('#modalForm');
    $('#modalTitle').textContent = title;
    body.innerHTML = '';
    for (const f of fields) {
      const label = document.createElement('label');
      label.textContent = f.label;
      const input = document.createElement('input');
      input.name = f.name; input.type = f.type;
      if (f.type === 'checkbox') input.checked = !!f.value; else input.value = f.value;
      if (f.min != null) input.min = f.min;
      if (f.max != null) input.max = f.max;
      label.appendChild(input);
      body.appendChild(label);
    }
    if (setup) setup(form.elements);
    m.hidden = false;
    const first = body.querySelector('input'); if (first) { first.focus(); first.select && first.select(); }
    const done = (val) => { m.hidden = true; form.onsubmit = null; $('#modalCancel').onclick = null; m.onkeydown = null; resolve(val); };
    form.onsubmit = (e) => {
      e.preventDefault();
      const out = {};
      for (const f of fields) { const el = form.elements[f.name]; out[f.name] = f.type === 'checkbox' ? el.checked : el.value; }
      done(out);
    };
    $('#modalCancel').onclick = () => done(null);
    m.onkeydown = (e) => { if (e.key === 'Escape') done(null); };
  });
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}

// ---------- loading ----------
function loadImage(src) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; });
}
function imageToCanvas(img) { return newBase(img.naturalWidth, img.naturalHeight, (c) => c.drawImage(img, 0, 0)); }

async function openDocument(baseSrc, objs = []) {
  base = imageToCanvas(await loadImage(baseSrc));
  savedBase = base;
  objects = objs;
  seq = objects.length + 1;
  for (const o of objects) if (!o.id) o.id = uid();
  selected = null; undoStack = []; redoStack = []; dirty = false;
  fitMode = true;
  layout();
  refreshProps();
}

// Browser mode (no Electron): open images by paste or drop.
function openFile(file) {
  const r = new FileReader();
  r.onload = () => openDocument(r.result);
  r.readAsDataURL(file);
}
window.addEventListener('paste', (e) => {
  if (api || editing) return;
  const item = [...(e.clipboardData && e.clipboardData.items || [])].find((i) => i.type.startsWith('image/'));
  if (item) openFile(item.getAsFile());
});
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => {
  e.preventDefault();
  if (api) return;
  const f = [...e.dataTransfer.files].find((x) => x.type.startsWith('image/'));
  if (f) openFile(f);
});

function demoImage() {
  return newBase(1200, 750, (c, cv) => {
    const g = c.createLinearGradient(0, 0, cv.width, cv.height);
    g.addColorStop(0, '#dfe7f5'); g.addColorStop(1, '#f7f2e8');
    c.fillStyle = g; c.fillRect(0, 0, cv.width, cv.height);
    c.fillStyle = '#ffffff'; c.fillRect(80, 80, 1040, 590);
    c.fillStyle = '#2b5cd8'; c.fillRect(80, 80, 1040, 60);
    c.fillStyle = '#fff'; c.font = '600 24px ' + FONT; c.fillText('Example window — paste or drop an image to edit it', 110, 120);
    c.fillStyle = '#333'; c.font = '18px ' + FONT;
    for (let i = 0; i < 12; i++) c.fillText('Lorem ipsum dolor sit amet, consectetur adipiscing elit. Line ' + (i + 1), 120, 190 + i * 36);
  }).toDataURL();
}

(async function init() {
  buildSwatches($('#colorSwatches'), 'color', false);
  buildSwatches($('#fillSwatches'), 'fill', true);
  setTool('select');
  try {
    if (api && captureId) {
      const doc = await api.loadCapture(captureId);
      await openDocument(doc.base, doc.objects);
      document.title = 'SnapCap Editor — ' + captureId;
    } else {
      await openDocument(demoImage());
    }
  } catch (err) {
    toast('Could not open capture: ' + err.message);
  }
})();

// exposed for automated tests
window.__snapcap = { get objects() { return objects; }, get base() { return base; }, setTool, exportCanvas, ops, undo, redo };
