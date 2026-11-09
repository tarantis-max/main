'use strict';
const api = window.snapcap;
const grid = document.getElementById('grid');

document.querySelectorAll('.mode').forEach((b) => { b.onclick = () => api.capture(b.dataset.mode); });
document.getElementById('import').onclick = () => api.importImages();
document.getElementById('folder').onclick = () => api.openFolder();

const BOOL_OPTS = ['copyAfterCapture', 'openEditor', 'recordMic', 'recordSystemAudio', 'recordCountdown'];

async function init() {
  const { settings, hotkeys, platform } = await api.getSettings();
  document.querySelectorAll('kbd[data-key]').forEach((k) => { k.textContent = hotkeys[k.dataset.key].join(' / '); });
  const delay = document.getElementById('delay');
  delay.value = String(settings.delay);
  delay.onchange = () => api.setSettings({ delay: +delay.value });
  for (const key of BOOL_OPTS) {
    const el = document.getElementById(key);
    el.checked = !!settings[key];
    el.onchange = () => api.setSettings({ [key]: el.checked });
  }
  if (platform !== 'win32') document.getElementById('sysAudioWrap').style.display = 'none';
  refresh();
}

function fmtDate(ms) {
  return new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
function fmtSize(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.round(b / 1024) + ' KB'; }

async function refresh() {
  const items = await api.listLibrary();
  grid.innerHTML = '';
  if (!items.length) {
    grid.innerHTML = '<div class="empty">No captures yet. Press a capture button or a hotkey above.</div>';
    return;
  }
  for (const it of items) {
    const card = document.createElement('div');
    card.className = 'card';
    card.title = it.file;
    const thumb = document.createElement('div'); thumb.className = 'thumb';
    if (it.type === 'image') {
      const img = document.createElement('img'); img.loading = 'lazy'; img.src = it.url; thumb.appendChild(img);
    } else {
      const v = document.createElement('video'); v.src = it.url; v.preload = 'metadata'; v.muted = true; thumb.appendChild(v);
      const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = 'VIDEO'; thumb.appendChild(badge);
    }
    const meta = document.createElement('div'); meta.className = 'meta';
    const t = document.createElement('span'); t.className = 't'; t.textContent = `${fmtDate(it.mtime)} · ${fmtSize(it.size)}`;
    const reveal = document.createElement('button'); reveal.textContent = '📁'; reveal.title = 'Show in folder';
    reveal.onclick = (e) => { e.stopPropagation(); api.revealItem(it); };
    const del = document.createElement('button'); del.textContent = '🗑'; del.title = 'Delete'; del.className = 'danger';
    del.onclick = async (e) => { e.stopPropagation(); if (await api.deleteItem(it)) refresh(); };
    meta.append(t, reveal, del);
    card.append(thumb, meta);
    card.onclick = () => api.openItem(it);
    grid.appendChild(card);
  }
}

api.onLibraryChanged(refresh);
api.onHotkeysFailed((keys) => {
  const w = document.getElementById('warn');
  w.style.display = 'block';
  w.textContent = `These hotkeys are in use by another app and were not registered: ${keys.join(', ')}. Use the buttons or the tray menu instead.`;
});
init();
