'use strict';
const grid = document.getElementById('grid');
window.snapcap.onPickerInit((items) => {
  grid.innerHTML = '';
  if (!items.length) grid.innerHTML = '<div class="empty">No capturable windows found.</div>';
  for (const it of items) {
    const el = document.createElement('div');
    el.className = 'item'; el.tabIndex = 0; el.title = it.name;
    const thumb = document.createElement('div'); thumb.className = 'thumb';
    const ti = document.createElement('img'); ti.src = it.thumb; thumb.appendChild(ti);
    const name = document.createElement('div'); name.className = 'name';
    if (it.icon) { const ic = document.createElement('img'); ic.src = it.icon; name.appendChild(ic); }
    name.appendChild(document.createTextNode(it.name));
    el.append(thumb, name);
    el.onclick = () => window.snapcap.pickWindow(it.id);
    el.onkeydown = (e) => { if (e.key === 'Enter') window.snapcap.pickWindow(it.id); };
    grid.appendChild(el);
  }
});
document.getElementById('cancel').onclick = () => window.close();
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') window.close(); });
