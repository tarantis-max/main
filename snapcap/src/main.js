'use strict';
const {
  app, BrowserWindow, globalShortcut, desktopCapturer, screen, ipcMain,
  Tray, Menu, nativeImage, clipboard, dialog, shell, session, systemPreferences, Notification,
} = require('electron');
const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');

// ---------- paths & settings ----------
const LIB_DIR = path.join(app.getPath('pictures'), 'SnapCap');
const META_DIR = path.join(LIB_DIR, '.snapcap');
const SETTINGS_FILE = path.join(app.getPath('userData'), 'settings.json');
const ICON = path.join(__dirname, '..', 'assets', 'icon.png');

const DEFAULT_SETTINGS = {
  delay: 0,               // seconds before capture
  copyAfterCapture: true, // put every capture on the clipboard
  openEditor: true,       // open the editor after an image capture
  recordMic: false,
  recordSystemAudio: false, // Windows only
  recordCountdown: true,
};
let settings = { ...DEFAULT_SETTINGS };

const HOTKEYS = {
  region: ['PrintScreen', 'Alt+Shift+1'],
  window: ['Alt+Shift+2'],
  fullscreen: ['Alt+Shift+3'],
  record: ['Alt+Shift+4'],
};

function loadSettings() {
  try { settings = { ...DEFAULT_SETTINGS, ...JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')) }; } catch { /* first run */ }
}
function saveSettings() {
  fs.mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true });
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
}
function ensureDirs() { fs.mkdirSync(META_DIR, { recursive: true }); }

function newId(prefix) {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${prefix}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${Math.random().toString(36).slice(2, 6)}`;
}

// ---------- windows ----------
let launcher = null;
let tray = null;
let overlays = [];
let recorderWin = null;
let pickerWin = null;
let busy = false;
let pendingSource = null; // desktopCapturer source handed to getDisplayMedia
const editors = new Map(); // id -> BrowserWindow

const webPrefs = (extra = {}) => ({
  preload: path.join(__dirname, 'preload.js'),
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: false,
  ...extra,
});

function createLauncher() {
  launcher = new BrowserWindow({
    width: 920, height: 640, minWidth: 640, minHeight: 420,
    title: 'SnapCap', icon: ICON, show: false, backgroundColor: '#16181d',
    webPreferences: webPrefs(),
  });
  launcher.setMenuBarVisibility(false);
  launcher.loadFile(path.join(__dirname, 'launcher.html'));
  launcher.once('ready-to-show', () => launcher.show());
  launcher.on('close', (e) => {
    if (!app.isQuitting) { e.preventDefault(); launcher.hide(); }
  });
}

function showLauncher() {
  if (!launcher) createLauncher();
  launcher.show();
  launcher.focus();
  launcher.webContents.send('library:changed');
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(ICON).resize({ width: 16, height: 16 }));
  tray.setToolTip('SnapCap');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Capture Region', accelerator: HOTKEYS.region[1], click: () => startCapture('region') },
    { label: 'Capture Window', accelerator: HOTKEYS.window[0], click: () => startCapture('window') },
    { label: 'Capture Full Screen', accelerator: HOTKEYS.fullscreen[0], click: () => startCapture('fullscreen') },
    { label: 'Record Video', accelerator: HOTKEYS.record[0], click: () => startCapture('record') },
    { type: 'separator' },
    { label: 'Open SnapCap', click: showLauncher },
    { label: 'Open Library Folder', click: () => shell.openPath(LIB_DIR) },
    { type: 'separator' },
    { label: 'Quit', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
  tray.on('click', showLauncher);
}

function registerHotkeys() {
  const failed = [];
  for (const [mode, keys] of Object.entries(HOTKEYS)) {
    for (const k of keys) {
      try {
        if (!globalShortcut.register(k, () => startCapture(mode))) failed.push(k);
      } catch { failed.push(k); }
    }
  }
  return failed;
}

// ---------- capture helpers ----------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function grabDisplays() {
  const displays = screen.getAllDisplays();
  let maxW = 0, maxH = 0;
  for (const d of displays) {
    maxW = Math.max(maxW, Math.round(d.size.width * d.scaleFactor));
    maxH = Math.max(maxH, Math.round(d.size.height * d.scaleFactor));
  }
  const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: maxW, height: maxH } });
  return displays.map((d, i) => {
    const src = sources.find((s) => String(s.display_id) === String(d.id)) || sources[i] || sources[0];
    return { display: d, source: src, image: src.thumbnail };
  });
}

function displayUnderCursor() {
  return screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
}

async function hideOwnWindows() {
  const hidden = [];
  for (const w of [launcher, ...editors.values()]) {
    if (w && !w.isDestroyed() && w.isVisible() && !w.isMinimized()) { w.hide(); hidden.push(w); }
  }
  if (hidden.length) await sleep(250); // let the compositor repaint without our windows
  return hidden;
}

function restoreWindows(list) { for (const w of list) if (!w.isDestroyed()) w.showInactive(); }

async function countdown(seconds) {
  if (!seconds) return;
  if (Notification.isSupported()) {
    new Notification({ title: 'SnapCap', body: `Capturing in ${seconds} seconds…`, silent: true }).show();
  }
  await sleep(seconds * 1000);
}

function checkPermission() {
  if (process.platform !== 'darwin') return true;
  const status = systemPreferences.getMediaAccessStatus('screen');
  if (status === 'granted') return true;
  dialog.showMessageBox({
    type: 'warning',
    message: 'SnapCap needs Screen Recording permission.',
    detail: 'Open System Settings → Privacy & Security → Screen Recording, enable SnapCap, then restart SnapCap.',
    buttons: ['Open Settings', 'Cancel'],
  }).then(({ response }) => {
    if (response === 0) shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture');
  });
  return false;
}

async function startCapture(mode) {
  if (mode === 'record' && recorderWin) { recorderWin.webContents.send('recorder:stop'); return; } // hotkey toggles
  if (busy) return;
  if (!checkPermission()) return;
  busy = true;
  let hidden = [];
  try {
    hidden = await hideOwnWindows();
    if (mode !== 'record') await countdown(settings.delay);
    if (mode === 'fullscreen') {
      const grabs = await grabDisplays();
      const target = displayUnderCursor();
      const g = grabs.find((x) => x.display.id === target.id) || grabs[0];
      await finishImageCapture(g.image);
      busy = false;
    } else if (mode === 'window') {
      await openWindowPicker();
    } else {
      await openOverlays(mode === 'record' ? 'record' : 'image');
    }
  } catch (err) {
    busy = false;
    restoreWindows(hidden);
    dialog.showErrorBox('Capture failed', String(err && err.stack || err));
  }
}

// ---------- region overlay ----------
async function openOverlays(purpose) {
  const grabs = await grabDisplays();
  overlays = grabs.map(({ display, image }) => {
    const b = display.bounds;
    const win = new BrowserWindow({
      x: b.x, y: b.y, width: b.width, height: b.height,
      frame: false, transparent: false, resizable: false, movable: false,
      skipTaskbar: true, alwaysOnTop: true, fullscreenable: false, hasShadow: false,
      enableLargerThanScreen: true, show: false, backgroundColor: '#000000',
      webPreferences: webPrefs(),
    });
    win.setAlwaysOnTop(true, 'screen-saver');
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.setBounds(b);
    win.__display = display;
    win.__image = image;
    win.loadFile(path.join(__dirname, 'overlay.html'));
    win.webContents.once('did-finish-load', () => {
      win.webContents.send('overlay:init', {
        purpose,
        displayId: display.id,
        image: image.toDataURL(),
        width: b.width, height: b.height,
        scaleFactor: display.scaleFactor,
      });
    });
    return win;
  });
  // show after content loads so the user never sees a black flash
  await Promise.all(overlays.map((w) => new Promise((res) => w.webContents.once('did-finish-load', res))));
  await sleep(60);
  const cursorDisplay = displayUnderCursor();
  for (const w of overlays) {
    w.show();
    if (w.__display.id === cursorDisplay.id) w.focus();
  }
}

function closeOverlays() {
  for (const w of overlays) if (!w.isDestroyed()) w.destroy();
  overlays = [];
}

ipcMain.on('overlay:cancel', () => { closeOverlays(); busy = false; });

ipcMain.on('overlay:select', async (_e, { displayId, rect, purpose }) => {
  const win = overlays.find((w) => w.__display.id === displayId);
  if (!win) return;
  const display = win.__display;
  const img = win.__image;
  closeOverlays();
  if (purpose === 'record') {
    await startRecording(display, rect);
    return;
  }
  const sx = img.getSize().width / display.bounds.width;
  const sy = img.getSize().height / display.bounds.height;
  const crop = rect
    ? { x: Math.round(rect.x * sx), y: Math.round(rect.y * sy), width: Math.max(1, Math.round(rect.width * sx)), height: Math.max(1, Math.round(rect.height * sy)) }
    : null;
  await finishImageCapture(crop ? img.crop(crop) : img);
  busy = false;
});

// ---------- window picker ----------
async function openWindowPicker() {
  const sources = await desktopCapturer.getSources({
    types: ['window'], thumbnailSize: { width: 3840, height: 2160 }, fetchWindowIcons: true,
  });
  const list = sources
    .filter((s) => s.name && !/^SnapCap/.test(s.name) && !s.thumbnail.isEmpty())
    .map((s) => ({ id: s.id, name: s.name, icon: s.appIcon ? s.appIcon.toDataURL() : null }));
  pickerWin = new BrowserWindow({
    width: 900, height: 620, title: 'SnapCap — Choose a window', icon: ICON,
    alwaysOnTop: true, show: false, backgroundColor: '#16181d', webPreferences: webPrefs(),
  });
  pickerWin.setMenuBarVisibility(false);
  pickerWin.__sources = sources;
  pickerWin.loadFile(path.join(__dirname, 'picker.html'));
  pickerWin.webContents.once('did-finish-load', () => {
    const items = list.map((l) => {
      const s = sources.find((x) => x.id === l.id);
      return { ...l, thumb: s.thumbnail.resize({ width: 320 }).toDataURL() };
    });
    pickerWin.webContents.send('picker:init', items);
    pickerWin.show();
  });
  pickerWin.on('closed', () => { pickerWin = null; busy = false; });
}

ipcMain.on('picker:choose', async (_e, id) => {
  if (!pickerWin) return;
  const src = pickerWin.__sources.find((s) => s.id === id);
  pickerWin.destroy();
  pickerWin = null;
  if (src) await finishImageCapture(src.thumbnail);
  busy = false;
});

// ---------- image capture output ----------
async function finishImageCapture(image) {
  ensureDirs();
  const id = newId('img');
  const png = image.toPNG();
  fs.writeFileSync(path.join(LIB_DIR, `${id}.png`), png);
  fs.writeFileSync(path.join(META_DIR, `${id}.base.png`), png);
  if (settings.copyAfterCapture) clipboard.writeImage(image);
  if (launcher && !launcher.isDestroyed()) launcher.webContents.send('library:changed');
  if (settings.openEditor) openEditor(id);
  else if (Notification.isSupported()) new Notification({ title: 'SnapCap', body: 'Capture saved' + (settings.copyAfterCapture ? ' and copied' : '') }).show();
  return id;
}

// ---------- editor ----------
function openEditor(id) {
  const existing = editors.get(id);
  if (existing && !existing.isDestroyed()) { existing.show(); existing.focus(); return; }
  const work = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea;
  const win = new BrowserWindow({
    width: Math.min(1400, work.width - 40), height: Math.min(900, work.height - 40),
    x: work.x + 20, y: work.y + 20, title: 'SnapCap Editor', icon: ICON,
    backgroundColor: '#16181d', show: false, webPreferences: webPrefs(),
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, 'editor.html'), { query: { id } });
  win.once('ready-to-show', () => { win.show(); win.focus(); });
  win.on('closed', () => editors.delete(id));
  editors.set(id, win);
}

ipcMain.handle('editor:load', (_e, id) => {
  const metaFile = path.join(META_DIR, `${id}.json`);
  const baseFile = path.join(META_DIR, `${id}.base.png`);
  const outFile = path.join(LIB_DIR, `${id}.png`);
  const src = fs.existsSync(baseFile) ? baseFile : outFile;
  if (!fs.existsSync(src)) throw new Error('Capture not found: ' + id);
  let objects = [];
  try { objects = JSON.parse(fs.readFileSync(metaFile, 'utf8')).objects || []; } catch { /* none yet */ }
  return { id, base: 'data:image/png;base64,' + fs.readFileSync(src).toString('base64'), objects };
});

function dataUrlToBuffer(url) { return Buffer.from(url.slice(url.indexOf(',') + 1), 'base64'); }

ipcMain.handle('editor:save', (_e, { id, output, base, objects }) => {
  ensureDirs();
  fs.writeFileSync(path.join(LIB_DIR, `${id}.png`), dataUrlToBuffer(output));
  if (base) fs.writeFileSync(path.join(META_DIR, `${id}.base.png`), dataUrlToBuffer(base));
  fs.writeFileSync(path.join(META_DIR, `${id}.json`), JSON.stringify({ version: 1, objects }));
  if (launcher && !launcher.isDestroyed()) launcher.webContents.send('library:changed');
  return true;
});

ipcMain.handle('editor:saveAs', async (e, { dataUrls, suggested }) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    defaultPath: path.join(app.getPath('desktop'), suggested + '.png'),
    filters: [
      { name: 'PNG Image', extensions: ['png'] },
      { name: 'JPEG Image', extensions: ['jpg', 'jpeg'] },
      { name: 'WebP Image', extensions: ['webp'] },
      { name: 'PDF Document', extensions: ['pdf'] },
    ],
  });
  if (canceled || !filePath) return null;
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.pdf') {
    await writePdf(dataUrls.png, filePath);
  } else {
    const key = ext === '.jpg' || ext === '.jpeg' ? 'jpeg' : ext === '.webp' ? 'webp' : 'png';
    fs.writeFileSync(filePath, dataUrlToBuffer(dataUrls[key] || dataUrls.png));
  }
  return filePath;
});

async function writePdf(pngDataUrl, filePath) {
  const img = nativeImage.createFromDataURL(pngDataUrl);
  const { width, height } = img.getSize();
  const w = new BrowserWindow({ show: false, webPreferences: { offscreen: true } });
  const html = `<html><body style="margin:0"><img src="${pngDataUrl}" style="width:100%;display:block"></body></html>`;
  await w.loadURL('data:text/html;base64,' + Buffer.from(html).toString('base64'));
  const pdf = await w.webContents.printToPDF({
    printBackground: true, margins: { marginType: 'none' },
    pageSize: { width: width / 96, height: height / 96 }, // inches at 96 dpi
  });
  w.destroy();
  fs.writeFileSync(filePath, pdf);
}

ipcMain.handle('clipboard:writeImage', (_e, dataUrl) => {
  clipboard.writeImage(nativeImage.createFromDataURL(dataUrl));
  return true;
});

// ---------- recording ----------
async function startRecording(display, rect) {
  const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 1, height: 1 } });
  const all = screen.getAllDisplays();
  pendingSource = sources.find((s) => String(s.display_id) === String(display.id)) || sources[all.findIndex((d) => d.id === display.id)] || sources[0];

  const b = display.bounds;
  const region = rect || { x: 0, y: 0, width: b.width, height: b.height };
  const barW = 340, barH = 52;
  let barX = b.x + region.x + Math.round((region.width - barW) / 2);
  let barY = b.y + region.y + region.height + 8;
  if (barY + barH > b.y + b.height) barY = b.y + region.y - barH - 8;     // above region
  if (barY < b.y) barY = b.y + b.height - barH - 48;                       // inside, near bottom
  barX = Math.max(b.x + 8, Math.min(barX, b.x + b.width - barW - 8));

  recorderWin = new BrowserWindow({
    x: barX, y: barY, width: barW, height: barH, frame: false, resizable: false,
    alwaysOnTop: true, skipTaskbar: false, title: 'SnapCap Recorder', icon: ICON,
    transparent: true, hasShadow: true, show: false,
    webPreferences: webPrefs({ backgroundThrottling: false }),
  });
  recorderWin.setAlwaysOnTop(true, 'screen-saver');
  recorderWin.setContentProtection(true); // keep the control bar out of the recording (Windows/macOS)
  recorderWin.loadFile(path.join(__dirname, 'recorder.html'));
  recorderWin.webContents.once('did-finish-load', () => {
    recorderWin.webContents.send('recorder:init', {
      region, displaySize: { width: b.width, height: b.height }, scaleFactor: display.scaleFactor,
      mic: settings.recordMic,
      systemAudio: settings.recordSystemAudio && process.platform === 'win32',
      countdown: settings.recordCountdown,
    });
    recorderWin.showInactive();
  });
  recorderWin.on('closed', () => { recorderWin = null; busy = false; });
}

ipcMain.handle('recorder:save', async (_e, { buffer, ext }) => {
  ensureDirs();
  const id = newId('rec');
  const file = path.join(LIB_DIR, `${id}.${ext}`);
  fs.writeFileSync(file, Buffer.from(buffer));
  if (recorderWin) recorderWin.destroy();
  showLauncher();
  return file;
});

ipcMain.on('recorder:close', () => { if (recorderWin) recorderWin.destroy(); });
ipcMain.on('recorder:error', (_e, msg) => {
  if (recorderWin) recorderWin.destroy();
  dialog.showErrorBox('Recording failed', msg);
});

// ---------- library ----------
ipcMain.handle('library:list', () => {
  ensureDirs();
  return fs.readdirSync(LIB_DIR)
    .filter((f) => /\.(png|jpe?g|webm|mp4)$/i.test(f))
    .map((f) => {
      const full = path.join(LIB_DIR, f);
      const st = fs.statSync(full);
      return {
        id: f.replace(/\.[^.]+$/, ''), file: f, path: full,
        url: pathToFileURL(full).href + '?v=' + st.mtimeMs,
        type: /\.(webm|mp4)$/i.test(f) ? 'video' : 'image',
        size: st.size, mtime: st.mtimeMs,
      };
    })
    .sort((a, b) => b.mtime - a.mtime);
});

ipcMain.handle('library:open', (_e, item) => {
  if (item.type === 'image') openEditor(item.id);
  else shell.openPath(item.path);
});
ipcMain.handle('library:reveal', (_e, item) => shell.showItemInFolder(item.path));
ipcMain.handle('library:openFolder', () => { ensureDirs(); shell.openPath(LIB_DIR); });
ipcMain.handle('library:delete', async (e, item) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  const { response } = await dialog.showMessageBox(win, {
    type: 'warning', buttons: ['Delete', 'Cancel'], defaultId: 1, cancelId: 1,
    message: `Delete ${item.file}?`, detail: 'The file is moved to the trash.',
  });
  if (response !== 0) return false;
  await shell.trashItem(item.path);
  for (const f of [`${item.id}.json`, `${item.id}.base.png`]) {
    const p = path.join(META_DIR, f);
    if (fs.existsSync(p)) fs.unlinkSync(p);
  }
  const ed = editors.get(item.id);
  if (ed && !ed.isDestroyed()) ed.destroy();
  return true;
});
ipcMain.handle('library:import', async (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  const { canceled, filePaths } = await dialog.showOpenDialog(win, {
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'] }],
  });
  if (canceled) return;
  for (const f of filePaths) {
    const img = nativeImage.createFromPath(f);
    if (img.isEmpty()) continue;
    ensureDirs();
    const id = newId('img');
    fs.writeFileSync(path.join(LIB_DIR, `${id}.png`), img.toPNG());
    fs.writeFileSync(path.join(META_DIR, `${id}.base.png`), img.toPNG());
    openEditor(id);
  }
  if (launcher) launcher.webContents.send('library:changed');
});

// ---------- misc IPC ----------
ipcMain.handle('capture:start', (_e, mode) => startCapture(mode));
ipcMain.handle('settings:get', () => ({ settings, hotkeys: HOTKEYS, platform: process.platform, libDir: LIB_DIR }));
ipcMain.handle('settings:set', (_e, patch) => { settings = { ...settings, ...patch }; saveSettings(); return settings; });

// ---------- app lifecycle ----------
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showLauncher);
  app.whenReady().then(() => {
    loadSettings();
    ensureDirs();
    session.defaultSession.setDisplayMediaRequestHandler((_req, cb) => {
      if (!pendingSource) return cb({});
      const res = { video: pendingSource };
      if (settings.recordSystemAudio && process.platform === 'win32') res.audio = 'loopback';
      cb(res);
    });
    createTray();
    createLauncher();
    const failed = registerHotkeys();
    if (failed.length) {
      launcher.webContents.once('did-finish-load', () => launcher.webContents.send('hotkeys:failed', failed));
    }
  });
  app.on('window-all-closed', (e) => e.preventDefault()); // keep running in the tray
  app.on('activate', showLauncher);
  app.on('before-quit', () => { app.isQuitting = true; });
  app.on('will-quit', () => globalShortcut.unregisterAll());
}
