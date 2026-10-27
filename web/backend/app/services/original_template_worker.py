"""Isolated native Word PDF export. No source text or exception is printed."""
import sys
from pathlib import Path


def export(docx, pdf):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = document = None
    try:
        word = win32com.client.DispatchEx('Word.Application')
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3
        word.Options.UpdateLinksAtOpen = False
        document = word.Documents.Open(str(Path(docx).resolve()), ConfirmConversions=False,
            ReadOnly=True, AddToRecentFiles=False)
        document.ExportAsFixedFormat(str(Path(pdf).resolve()), 17)
        return Path(pdf).is_file()
    except Exception:
        # Some Word installations terminate their COM server immediately after
        # exporting. The parent independently validates the completed PDF.
        return Path(pdf).is_file()
    finally:
        if document is not None:
            try: document.Close(0)
            except Exception: pass
        if word is not None:
            try: word.Quit(0)
            except Exception: pass
        pythoncom.CoUninitialize()


if __name__ == '__main__':
    try:
        ok = len(sys.argv) == 3 and export(sys.argv[1], sys.argv[2])
    except Exception:
        ok = False
    raise SystemExit(0 if ok else 1)
