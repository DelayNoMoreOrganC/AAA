"""Read-only original-form prerequisites, before any paid material analysis."""
import importlib.util
import os
from pathlib import Path
import re


def native_word_available():
    if os.name != "nt":
        return False
    try:
        if importlib.util.find_spec("win32com.client") is None:
            return False
        import winreg
        # Office may be 32-bit while this worker is 64-bit. This is a read-only
        # registration check; no Dispatch, repairs or registry writes occur.
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID", 0, winreg.KEY_READ | view) as key:
                    identifier = winreg.QueryValueEx(key, None)[0]
                for server_view in (view, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                    try:
                        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + identifier + r"\LocalServer32", 0,
                                            winreg.KEY_READ | server_view) as key:
                            command = winreg.QueryValueEx(key, None)[0]
                        match = re.match(r'\s*"([^"]+\.exe)"|\s*(.+?\.exe)(?:\s|$)', command, re.IGNORECASE)
                        executable = (match.group(1) or match.group(2)) if match else ""
                        if executable and Path(os.path.expandvars(executable)).is_file():
                            return True
                    except OSError:
                        continue
            except OSError:
                continue
        return False
    except (OSError, ImportError, TypeError, ValueError):
        return False


def original_form_readiness():
    issues = []
    if not native_word_available():
        issues.append("工作站的原表转换组件尚未就绪，需要可用的 Word COM 兼容程序；请管理员修复后再开始材料分析")
    try:
        from .original_template_service import template_metadata
        for name in ("立案审批表", "送达材料清单", "档案卷宗", "结案报告表", "质量监督卡"):
            template_metadata(name)
        template_metadata("档案卷宗", {"案件类别":"非诉"})
    except Exception:
        # The diagnostic must not echo a damaged path, XML or customer data.
        issues.append("律所原表底稿或版式校验资料缺失，请由管理员修复后再开始")
    return {"ready": not issues, "issues": issues, "check": "prerequisites_only_not_render_test"}
