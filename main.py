"""
MDPad - A lightweight Notepad-like Markdown editor for AI workflows.

Run with:  python main.py
Package with PyInstaller (see build.md).
"""

import os
import sys
import tempfile
import time

from PySide6.QtCore import Qt, QSettings, QTimer, QFileInfo
from PySide6.QtGui import QAction, QKeySequence, QTextOption, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPlainTextEdit, QFileDialog, QMessageBox,
    QStatusBar, QLabel, QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QCheckBox, QSpinBox, QWidget, QMenu
)

APP_NAME = "MDPad"
ORG_NAME = "MDPad"
RECOVERY_FILENAME = "mdpad_recovery.md"
MAX_RECENT_FILES = 8
AUTOSAVE_INTERVAL_MS = 30_000  # 30 seconds


# --------------------------------------------------------------------------- #
# Clipboard-as-file support
# --------------------------------------------------------------------------- #
def copy_file_to_clipboard(file_path: str) -> bool:
    """
    Places a real file reference onto the system clipboard (CF_HDROP on
    Windows) so that pasting into another application (e.g. an AI chat
    web app) attaches the file rather than pasting text.

    Falls back to copying the file's text content if native file-clipboard
    support isn't available (e.g. non-Windows platforms without the
    optional pywin32 dependency).
    """
    if sys.platform == "win32":
        try:
            import win32clipboard
            import win32con
            import struct

            # Build a DROPFILES structure followed by a double-null
            # terminated list of file paths (Windows CF_HDROP format).
            path = os.path.abspath(file_path)
            path_bytes = path.encode("utf-16-le") + b"\x00\x00"

            # DROPFILES struct: pFiles, pt(x,y), fNC, fWide
            offset = 20  # sizeof(DROPFILES)
            dropfiles = struct.pack("<L2l2L", offset, 0, 0, 0, 1)  # fWide=1 (unicode)
            data = dropfiles + path_bytes

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_HDROP, data)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            pass  # fall through to text fallback

    # Fallback: copy plain text content to clipboard.
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        QApplication.clipboard().setText(content)
    except Exception:
        return False
    return False  # indicates fallback was used (text, not file)


# --------------------------------------------------------------------------- #
# Find / Replace dialog
# --------------------------------------------------------------------------- #
class FindReplaceDialog(QDialog):
    def __init__(self, editor: QPlainTextEdit, parent=None, replace_mode=False):
        super().__init__(parent)
        self.editor = editor
        self.setWindowTitle("Replace" if replace_mode else "Find")
        self.setModal(False)

        layout = QVBoxLayout(self)

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find:"))
        self.find_edit = QLineEdit()
        find_row.addWidget(self.find_edit)
        layout.addLayout(find_row)

        self.replace_edit = None
        if replace_mode:
            replace_row = QHBoxLayout()
            replace_row.addWidget(QLabel("Replace:"))
            self.replace_edit = QLineEdit()
            replace_row.addWidget(self.replace_edit)
            layout.addLayout(replace_row)

        opts_row = QHBoxLayout()
        self.case_checkbox = QCheckBox("Match case")
        opts_row.addWidget(self.case_checkbox)
        layout.addLayout(opts_row)

        btn_row = QHBoxLayout()
        find_next_btn = QPushButton("Find Next")
        find_next_btn.clicked.connect(self.find_next)
        btn_row.addWidget(find_next_btn)

        if replace_mode:
            replace_btn = QPushButton("Replace")
            replace_btn.clicked.connect(self.replace_one)
            btn_row.addWidget(replace_btn)

            replace_all_btn = QPushButton("Replace All")
            replace_all_btn.clicked.connect(self.replace_all)
            btn_row.addWidget(replace_all_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _flags(self):
        flags = QTextOption.WrapMode.WordWrap  # unused placeholder
        from PySide6.QtGui import QTextDocument
        f = QTextDocument.FindFlag(0)
        if self.case_checkbox.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        return f

    def find_next(self):
        text = self.find_edit.text()
        if not text:
            return
        found = self.editor.find(text, self._flags())
        if not found:
            # wrap around
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            self.editor.find(text, self._flags())

    def replace_one(self):
        cursor = self.editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == self.find_edit.text():
            cursor.insertText(self.replace_edit.text())
        self.find_next()

    def replace_all(self):
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        if not find_text:
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
        count = 0
        while self.editor.find(find_text, self._flags()):
            c = self.editor.textCursor()
            c.insertText(replace_text)
            count += 1
        QMessageBox.information(self, "Replace All", f"Replaced {count} occurrence(s).")


class GoToLineDialog(QDialog):
    def __init__(self, max_line: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go To Line")
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"Line number (1-{max_line}):"))
        self.spin = QSpinBox()
        self.spin.setRange(1, max(1, max_line))
        row.addWidget(self.spin)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Go")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def line_number(self):
        return self.spin.value()


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MDPadWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.current_file = None
        self.dark_mode = self.settings.value("dark_mode", False, type=bool)

        self._build_ui()
        self._build_menus()
        self._build_status_bar()
        self._connect_signals()
        self._apply_theme()
        self._load_recovery_if_present()
        self._update_title()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(AUTOSAVE_INTERVAL_MS)

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self):
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setCentralWidget(self.editor)
        self.resize(900, 700)
        self.setWindowTitle(APP_NAME)

    def _build_menus(self):
        menubar = self.menuBar()

        # ---------------- File menu ----------------
        file_menu = menubar.addMenu("&File")

        self.act_new = QAction("&New", self, shortcut=QKeySequence.StandardKey.New,
                                triggered=self.new_file)
        self.act_open = QAction("&Open...", self, shortcut=QKeySequence.StandardKey.Open,
                                 triggered=self.open_file)
        self.act_save = QAction("&Save", self, shortcut=QKeySequence.StandardKey.Save,
                                 triggered=self.save_file)
        self.act_save_as = QAction("Save &As...", self, shortcut="Ctrl+Shift+S",
                                    triggered=self.save_file_as)
        self.act_exit = QAction("E&xit", self, shortcut="Ctrl+Q", triggered=self.close)

        file_menu.addAction(self.act_new)
        file_menu.addAction(self.act_open)

        self.recent_menu = QMenu("Recent Files", self)
        file_menu.addMenu(self.recent_menu)
        self._refresh_recent_menu()

        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        # ---------------- Edit menu ----------------
        edit_menu = menubar.addMenu("&Edit")

        self.act_undo = QAction("&Undo", self, shortcut=QKeySequence.StandardKey.Undo,
                                 triggered=self.editor.undo)
        self.act_redo = QAction("&Redo", self, shortcut=QKeySequence.StandardKey.Redo,
                                 triggered=self.editor.redo)
        self.act_cut = QAction("Cu&t", self, shortcut=QKeySequence.StandardKey.Cut,
                                triggered=self.editor.cut)
        self.act_copy = QAction("&Copy", self, shortcut=QKeySequence.StandardKey.Copy,
                                 triggered=self.editor.copy)
        self.act_paste = QAction("&Paste", self, shortcut=QKeySequence.StandardKey.Paste,
                                  triggered=self.editor.paste)
        self.act_delete = QAction("De&lete", self, shortcut=QKeySequence.StandardKey.Delete,
                                   triggered=lambda: self.editor.textCursor().removeSelectedText())
        self.act_select_all = QAction("Select &All", self, shortcut=QKeySequence.StandardKey.SelectAll,
                                       triggered=self.editor.selectAll)
        self.act_find = QAction("&Find...", self, shortcut="Ctrl+F", triggered=self.show_find)
        self.act_replace = QAction("&Replace...", self, shortcut="Ctrl+H", triggered=self.show_replace)
        self.act_goto = QAction("&Go To Line...", self, shortcut="Ctrl+G", triggered=self.show_goto_line)

        for a in (self.act_undo, self.act_redo, None, self.act_cut, self.act_copy,
                  self.act_paste, self.act_delete, None, self.act_select_all, None,
                  self.act_find, self.act_replace, self.act_goto):
            if a is None:
                edit_menu.addSeparator()
            else:
                edit_menu.addAction(a)

        # ---------------- View menu ----------------
        view_menu = menubar.addMenu("&View")

        self.act_word_wrap = QAction("&Word Wrap", self, checkable=True, checked=True,
                                      triggered=self.toggle_word_wrap)
        self.act_dark_mode = QAction("&Dark Mode", self, checkable=True, checked=self.dark_mode,
                                      triggered=self.toggle_dark_mode)
        view_menu.addAction(self.act_word_wrap)
        view_menu.addAction(self.act_dark_mode)

        # ---------------- AI menu ----------------
        ai_menu = menubar.addMenu("&AI")

        self.act_export_md = QAction("&Export as Markdown...", self, shortcut="Ctrl+Shift+E",
                                      triggered=self.export_as_markdown)
        self.act_copy_md_file = QAction("Copy as &Markdown File", self, shortcut="Ctrl+Shift+C",
                                         triggered=self.copy_as_markdown_file)
        ai_menu.addAction(self.act_export_md)
        ai_menu.addAction(self.act_copy_md_file)

        # Close document shortcut (optional, maps to New for single-doc MVP)
        self.act_close_doc = QAction(self, shortcut="Ctrl+W", triggered=self.new_file)
        self.addAction(self.act_close_doc)

    def _build_status_bar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.lbl_position = QLabel("Ln 1, Col 1")
        self.lbl_encoding = QLabel("UTF-8")
        self.lbl_markdown = QLabel("Markdown")

        self.status.addPermanentWidget(self.lbl_position)
        self.status.addPermanentWidget(self.lbl_encoding)
        self.status.addPermanentWidget(self.lbl_markdown)

    def _connect_signals(self):
        self.editor.cursorPositionChanged.connect(self._update_position_label)
        self.editor.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------- state ---
    def _on_text_changed(self):
        self._update_title()

    def _update_position_label(self):
        cursor = self.editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.lbl_position.setText(f"Ln {line}, Col {col}")

    def _update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else "Untitled"
        modified = "*" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{modified}{name} - {APP_NAME}")

    # ------------------------------------------------------------- files ---
    def _maybe_save_changes(self) -> bool:
        """Returns True if it's OK to proceed (discard/save), False to cancel."""
        if not self.editor.document().isModified():
            return True
        reply = QMessageBox.question(
            self, APP_NAME,
            "You have unsaved changes. Do you want to save them?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self.save_file()
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        return False

    def new_file(self):
        if not self._maybe_save_changes():
            return
        self.editor.clear()
        self.current_file = None
        self.editor.document().setModified(False)
        self._update_title()

    def open_file(self, path=None):
        if not self._maybe_save_changes():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open Markdown File", "", "Markdown Files (*.md);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not open file:\n{e}")
            return
        self.editor.setPlainText(content)
        self.current_file = path
        self.editor.document().setModified(False)
        self._add_recent_file(path)
        self._update_title()

    def save_file(self) -> bool:
        if self.current_file:
            return self._write_to_path(self.current_file)
        return self.save_file_as()

    def save_file_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Markdown File", self.current_file or "untitled.md",
            "Markdown Files (*.md);;All Files (*)")
        if not path:
            return False
        if self._write_to_path(path):
            self.current_file = path
            self._add_recent_file(path)
            self._update_title()
            return True
        return False

    def _write_to_path(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.editor.document().setModified(False)
            self._update_title()
            return True
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not save file:\n{e}")
            return False

    # --------------------------------------------------------- recent files
    def _recent_files(self):
        return self.settings.value("recent_files", [], type=list) or []

    def _add_recent_file(self, path: str):
        recents = self._recent_files()
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        recents = recents[:MAX_RECENT_FILES]
        self.settings.setValue("recent_files", recents)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        recents = self._recent_files()
        if not recents:
            empty_action = QAction("(No recent files)", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for path in recents:
            action = QAction(path, self)
            action.triggered.connect(lambda checked=False, p=path: self.open_file(p))
            self.recent_menu.addAction(action)

    # --------------------------------------------------------- autosave/recovery
    def _recovery_path(self):
        return os.path.join(tempfile.gettempdir(), RECOVERY_FILENAME)

    def _autosave(self):
        if self.editor.document().isModified():
            try:
                with open(self._recovery_path(), "w", encoding="utf-8") as f:
                    f.write(self.editor.toPlainText())
            except Exception:
                pass

    def _load_recovery_if_present(self):
        rec_path = self._recovery_path()
        if os.path.exists(rec_path) and os.path.getsize(rec_path) > 0:
            reply = QMessageBox.question(
                self, APP_NAME,
                "MDPad found unsaved recovery data from a previous session. "
                "Would you like to restore it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    with open(rec_path, "r", encoding="utf-8") as f:
                        self.editor.setPlainText(f.read())
                    self.editor.document().setModified(True)
                except Exception:
                    pass
            try:
                os.remove(rec_path)
            except Exception:
                pass

    def _clear_recovery(self):
        try:
            os.remove(self._recovery_path())
        except Exception:
            pass

    # ------------------------------------------------------------ editing
    def show_find(self):
        dlg = FindReplaceDialog(self.editor, self, replace_mode=False)
        dlg.show()

    def show_replace(self):
        dlg = FindReplaceDialog(self.editor, self, replace_mode=True)
        dlg.show()

    def show_goto_line(self):
        max_line = self.editor.document().blockCount()
        dlg = GoToLineDialog(max_line, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            target = dlg.line_number()
            block = self.editor.document().findBlockByLineNumber(target - 1)
            cursor = self.editor.textCursor()
            cursor.setPosition(block.position())
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()

    def toggle_word_wrap(self, checked: bool):
        mode = (QPlainTextEdit.LineWrapMode.WidgetWidth if checked
                else QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setLineWrapMode(mode)

    # ------------------------------------------------------------ theming
    def toggle_dark_mode(self, checked: bool):
        self.dark_mode = checked
        self.settings.setValue("dark_mode", checked)
        self._apply_theme()

    def _apply_theme(self):
        if self.dark_mode:
            self.editor.setStyleSheet(
                "QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
                "border: none; }"
            )
        else:
            self.editor.setStyleSheet(
                "QPlainTextEdit { background-color: #ffffff; color: #000000; "
                "border: none; }"
            )
        self.act_dark_mode.setChecked(self.dark_mode)

    # ------------------------------------------------------------ AI features
    def export_as_markdown(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not folder:
            return
        base_name = os.path.splitext(os.path.basename(self.current_file))[0] \
            if self.current_file else "untitled"
        dest = os.path.join(folder, f"{base_name}.md")

        # avoid clobbering silently
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(folder, f"{base_name}_{counter}.md")
            counter += 1

        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.status.showMessage(f"Exported to {dest}", 5000)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Export failed:\n{e}")

    def copy_as_markdown_file(self):
        try:
            tmp_dir = tempfile.gettempdir()
            timestamp = int(time.time())
            base_name = os.path.splitext(os.path.basename(self.current_file))[0] \
                if self.current_file else "mdpad_clip"
            tmp_path = os.path.join(tmp_dir, f"{base_name}_{timestamp}.md")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())

            is_file_copy = copy_file_to_clipboard(tmp_path)
            if is_file_copy:
                self.status.showMessage(
                    "Markdown file copied to clipboard — paste it as an attachment.", 5000)
            else:
                self.status.showMessage(
                    "File-clipboard not available on this platform — "
                    "copied text content instead.", 5000)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Copy as Markdown File failed:\n{e}")

    # ------------------------------------------------------------ lifecycle
    def closeEvent(self, event):
        if self._maybe_save_changes():
            self._clear_recovery()
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    window = MDPadWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()