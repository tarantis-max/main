# SnapCap

Desktop screen capture, screen recording, and image annotation tool (Snagit-style). Runs on Windows, macOS, and Linux (X11). Built with Electron.

## Run

```bash
cd snapcap
npm install
npm start
```

SnapCap runs in the system tray. Closing the main window keeps it running; quit from the tray menu.

## Build an installer

| Platform | Command | Output |
|---|---|---|
| Windows | `npm run dist:win` | `dist/*.exe` (NSIS installer) |
| macOS | `npm run dist:mac` | `dist/*.dmg` |
| Linux | `npm run dist:linux` | `dist/*.AppImage` |

Build each installer on its own OS.

## Hotkeys (global)

| Action | Hotkey |
|---|---|
| Capture region | `PrintScreen` or `Alt+Shift+1` |
| Capture window | `Alt+Shift+2` |
| Capture full screen (monitor under cursor) | `Alt+Shift+3` |
| Start / stop video recording | `Alt+Shift+4` |

If another app owns a hotkey, SnapCap shows a warning and that hotkey is skipped. On Windows 11, `PrintScreen` is owned by Snipping Tool unless you turn off *Settings → Accessibility → Keyboard → Use the Print screen key to open screen capture*.

## Features

**Capture**
- Region: frozen-screen overlay with crosshair, 8× pixel magnifier, pixel coordinates, color readout, and live size. Click without dragging = whole monitor. Multi-monitor and HiDPI aware.
- Window: pick from thumbnails of open windows.
- Full screen: monitor under the cursor.
- Delay timer: 3 / 5 / 10 s.
- Auto-copy to clipboard and auto-save to library (both on by default).

**Video recording**
- Full screen or any region.
- Pause / resume / stop / discard. Control bar is hidden from the recording (Windows/macOS).
- Optional microphone. Optional system audio (Windows only).
- Saves MP4 when the platform encoder supports it; otherwise WebM.

**Editor**
| Tool | Key | Notes |
|---|---|---|
| Select | V | Move, resize via handles, arrow keys nudge (Shift = 10 px) |
| Arrow | A | Tapered arrow. Shift snaps to 45° |
| Line | L | Shift snaps to 45° |
| Shape | R | Rectangle, optional fill. Shift = square |
| Ellipse | E | Optional fill. Shift = circle |
| Text | T | Callout box with fill, or plain text. Double-click to edit |
| Step | N | Auto-numbered circles (1, 2, 3…) |
| Highlight | H | Highlighter-pen effect (multiply blend) |
| Pen | P | Freehand |
| Blur | B | Pixelates the area (strength adjustable) |
| Spotlight | S | Dims everything outside an ellipse |
| Magnify | M | Zoomed-in lens (1.5×–6×) |
| Crop | C | Drag, then Enter |

- Image operations: rotate, flip, resize, border, drop shadow. Annotations stay editable through all of them.
- Per-object color, fill, thickness, font size, drop shadow. Duplicate, bring to front / send to back, delete.
- Unlimited undo/redo (`Ctrl+Z` / `Ctrl+Y`). Zoom (`Ctrl+=`, `Ctrl+-`, `Ctrl+0` fit, `Ctrl+wheel`).
- `Ctrl+C` copy, `Ctrl+S` save to library, `Ctrl+Shift+S` export as PNG / JPG / WebP / PDF.
- Autosaves 1.5 s after each change.

**Library**
- Every capture and recording is saved to `Pictures/SnapCap`.
- Reopening an image restores its annotations as editable objects (stored in `Pictures/SnapCap/.snapcap`).
- Open, show in folder, delete (moves to trash), import existing images.

## Permissions

- **macOS:** grant *Screen Recording* (and *Microphone* if recording audio) in System Settings → Privacy & Security, then restart SnapCap.
- **Linux:** X11 sessions work. Wayland sessions are not supported for region/fullscreen capture.

## Not included (vs. Snagit)

Scrolling/panoramic capture, OCR text grab, GIF export, video trimming, webcam overlay, cloud sharing, templates.

## Project layout

```
src/main.js        Main process: tray, hotkeys, capture, library, file I/O
src/preload.js     Safe IPC bridge (contextIsolation on, nodeIntegration off)
src/overlay.*      Region selector
src/picker.*       Window picker
src/recorder.*     Screen recorder + control bar
src/editor.*       Annotation editor
src/launcher.*     Main window + library
```

The editor also runs in a plain browser for development: open `src/editor.html` and paste or drop an image.
