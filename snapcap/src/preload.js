'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const on = (channel) => (cb) => {
  const fn = (_e, ...args) => cb(...args);
  ipcRenderer.on(channel, fn);
  return () => ipcRenderer.removeListener(channel, fn);
};

contextBridge.exposeInMainWorld('snapcap', {
  // capture
  capture: (mode) => ipcRenderer.invoke('capture:start', mode),
  // overlay
  onOverlayInit: on('overlay:init'),
  overlaySelect: (payload) => ipcRenderer.send('overlay:select', payload),
  overlayCancel: () => ipcRenderer.send('overlay:cancel'),
  // window picker
  onPickerInit: on('picker:init'),
  pickWindow: (id) => ipcRenderer.send('picker:choose', id),
  // editor
  loadCapture: (id) => ipcRenderer.invoke('editor:load', id),
  saveCapture: (payload) => ipcRenderer.invoke('editor:save', payload),
  saveAs: (payload) => ipcRenderer.invoke('editor:saveAs', payload),
  copyImage: (dataUrl) => ipcRenderer.invoke('clipboard:writeImage', dataUrl),
  // recorder
  onRecorderInit: on('recorder:init'),
  onRecorderStop: on('recorder:stop'),
  saveRecording: (payload) => ipcRenderer.invoke('recorder:save', payload),
  closeRecorder: () => ipcRenderer.send('recorder:close'),
  recorderError: (msg) => ipcRenderer.send('recorder:error', msg),
  // library
  listLibrary: () => ipcRenderer.invoke('library:list'),
  openItem: (item) => ipcRenderer.invoke('library:open', item),
  revealItem: (item) => ipcRenderer.invoke('library:reveal', item),
  deleteItem: (item) => ipcRenderer.invoke('library:delete', item),
  openFolder: () => ipcRenderer.invoke('library:openFolder'),
  importImages: () => ipcRenderer.invoke('library:import'),
  onLibraryChanged: on('library:changed'),
  onHotkeysFailed: on('hotkeys:failed'),
  // settings
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (patch) => ipcRenderer.invoke('settings:set', patch),
});
