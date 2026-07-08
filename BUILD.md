# Building / Packaging MDPad

## 1. Run from source

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python main.py
```

## 2. Package as a standalone Windows .exe (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name MDPad main.py
```

The executable will be created at `dist/MDPad.exe`.

Flags explained:
- `--onefile` — bundle everything into a single .exe for easy distribution.
- `--windowed` — no console window on launch (GUI app).
- `--name MDPad` — output filename.

For a faster-starting build (folder instead of single file), drop `--onefile`.

## 3. Package with Nuitka (alternative, often faster startup)

```bash
pip install nuitka
python -m nuitka --standalone --windows-console-mode=disable --enable-plugin=pyside6 main.py
```

## Notes on "Copy as Markdown File"

- On Windows, this feature uses `pywin32` to place a real file (CF_HDROP)
  onto the clipboard, so pasting into a browser-based AI chat attaches the
  `.md` file directly.
- If `pywin32` isn't installed, or the app is run on macOS/Linux, the
  feature automatically falls back to copying the document's plain text
  instead (the app tells you which happened via the status bar).
- Temporary files created for this feature are written to the OS temp
  directory and are not deleted automatically (since the target
  application needs to read them after paste) — the OS will typically
  clean these up over time.