"""Money's window: the page in ui/ shown by WebView2 (through pywebview). Nothing leaves this PC.
  .venv\\Scripts\\python desktop.py      from the repo: works on data/, like the Streamlit app
  Money.exe                            data in %LOCALAPPDATA%\\Money, or next to the exe if Money.ini is there (portable)
"""
import base64, ctypes, os, re, shutil, sys
from pathlib import Path

VERSION = "0.1.0"
FROZEN = getattr(sys, "frozen", False)
UI = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ui"
EXE_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent


def data_dir():
    if not FROZEN:
        return Path(__file__).parent / "data"
    if (EXE_DIR / "Money.ini").exists():
        return EXE_DIR / "data"
    return Path(os.environ["LOCALAPPDATA"]) / "Money"


os.environ.setdefault("MONEY_DATA", str(data_dir()))
import money  # noqa: E402  (reads MONEY_DATA at import)
import webview  # noqa: E402


def lang():
    return "it" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x10 else "en"


def kind_of(account, name):
    if account == "Bolletta":
        return "bill"
    if account == "Busta paga":
        return "payslip"
    return "card" if name.endswith("_nexi.pdf") else "account"


class Api:
    """Called by the page as window.pywebview.api.<name>(). Each call runs on its own thread: one db connection each."""

    def __init__(self):
        self._window = None  # underscore: pywebview doesn't hand private attributes to the page

    def init(self):
        return {"lang": lang(), "version": VERSION, "stats": self.stats()}

    def stats(self):
        db = money.connect()
        try:
            n, first, last, todo = db.execute(
                "SELECT COUNT(*), MIN(date), MAX(date), SUM(category IS NULL) FROM tx").fetchone()
            return {
                "tx": n, "first": first, "last": last, "todo": todo or 0,
                "bills": db.execute("SELECT COUNT(*) FROM bills").fetchone()[0],
                "payslips": db.execute("SELECT COUNT(*) FROM payslips").fetchone()[0],
                "accounts": [a for (a,) in db.execute("SELECT DISTINCT account FROM tx ORDER BY account")],
                "folder": str(money.DATA),
            }
        finally:
            db.close()

    def import_files(self, files):
        """files: [{name, data: base64}] from a drop. Copies land in data/nuovi/, then go where they belong."""
        out = []
        for f in files:
            name = re.sub(r"[^\w .()-]", "_", Path(f.get("name") or "file").name)[:120] or "file"
            path = money.INBOX / name
            money.INBOX.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(f.get("data") or ""))
            out.append(self._import(path, name))
        return {"results": out, "stats": self.stats()}

    def pick_files(self):
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                file_types=("PDF, CSV (*.pdf;*.csv)", "Tutti i file (*.*)"))
        out = []
        for p in paths or []:
            money.INBOX.mkdir(parents=True, exist_ok=True)
            copy = money.INBOX / Path(p).name  # a copy: the user's own file stays where it was
            shutil.copyfile(p, copy)
            out.append(self._import(copy, Path(p).name))
        return {"results": out, "stats": self.stats()}

    def open_folder(self):
        money.DATA.mkdir(parents=True, exist_ok=True)
        os.startfile(money.DATA)

    @staticmethod
    def _import(path, name):
        db = money.connect()
        try:
            before = db.execute("SELECT COALESCE(MAX(rowid), 0) FROM files").fetchone()[0]
            try:
                res = money.import_file(db, path)
            except Exception as e:  # a broken or locked file must not stop the others
                res = f"{type(e).__name__}: {e}"
            added = db.execute("SELECT name, account, rows FROM files WHERE rowid > ?", (before,)).fetchone()
        finally:
            db.close()
        if isinstance(res, str):
            return {"name": name, "status": "error", "msg": res}
        if res is None:
            return {"name": name, "status": "unknown"}
        if not added:
            if path.exists() and path.parent == money.INBOX:
                path.unlink()  # our copy of a file that is already in: nothing to keep
            return {"name": name, "status": "dup"}
        stored, account, rows = added
        return {"name": name, "status": "ok", "kind": kind_of(account, stored), "account": account,
                "stored": stored, "rows": rows, "new": res}


def dark_title(window):
    """Dark title bar on Windows 10 2004+, and on Windows 11 the same black as the page."""
    try:
        hwnd = window.native.Handle.ToInt64()
        on, black = ctypes.c_int(1), ctypes.c_int(0x00060705)  # COLORREF is 0x00BBGGRR
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(black), 4)
    except Exception:
        pass


def main():
    api = Api()
    window = webview.create_window("Money", str(UI / "index.html"), js_api=api, width=1180, height=820,
                                   min_size=(760, 560), background_color="#050706")
    api._window = window
    window.events.before_show += lambda: dark_title(window)
    webview.start(private_mode=True)  # no cookies or cache kept: the page has nothing to remember


if __name__ == "__main__":
    main()
