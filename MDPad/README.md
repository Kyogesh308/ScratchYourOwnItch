# MDPad

A lightweight, Notepad-like desktop Markdown editor built for fast AI workflows.

MDPad is **not** an AI app — no chatbots, no cloud, no login, no telemetry.
It's a plain-text editor tuned for one thing: getting Markdown in and out of
AI chat tools as quickly as possible.

## Highlights

- Notepad-like UI: File / Edit / View / AI menus, single text area, status bar.
- Standard editing: undo/redo, cut/copy/paste, find, replace, go to line, word wrap.
- **Export as Markdown** — one click, choose a folder, `.md` file is written.
- **Copy as Markdown File** — puts an actual `.md` file on the clipboard
  (not just text), so `Ctrl+V` into an AI chat pastes it as a file attachment.
- Recent files, dark mode, autosave/crash recovery.

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

See `BUILD.md` for packaging into a standalone `.exe`.

## Keyboard shortcuts

| Shortcut         | Action                  |
|------------------|-------------------------|
| Ctrl+N           | New                     |
| Ctrl+O           | Open                    |
| Ctrl+S           | Save                    |
| Ctrl+Shift+S     | Save As                 |
| Ctrl+Shift+E     | Export as Markdown      |
| Ctrl+Shift+C     | Copy as Markdown File   |
| Ctrl+F           | Find                    |
| Ctrl+H           | Replace                 |
| Ctrl+G           | Go To Line              |
| Ctrl+W           | Close document (new)    |
