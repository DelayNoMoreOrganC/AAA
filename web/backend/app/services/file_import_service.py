"""Validate local uploads, preserve their originals, and normalize them to PDF.

No network services are used. Each successful import owns an immutable directory;
the original filename is display metadata and is never used as a storage path.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import warnings
import zipfile
from xml.etree import ElementTree


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_TOTAL_PIXELS = 200_000_000
MAX_IMAGE_PAGES = 100
MAX_DOCX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_DOC_STREAM_BYTES = 64 * 1024 * 1024


class ImportFailure(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def display_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127).strip()
    if not name or name in (".", "..") or len(name) > 250:
        raise ImportFailure("文件名为空或过长，请重命名后上传。")
    return name


def _libreoffice_path() -> str:
    candidates = [shutil.which("soffice"), shutil.which("libreoffice")]
    if os.name == "nt":
        for key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(key)
            if base:
                # The Windows .com console wrapper waits for soffice.bin to exit.
                candidates.extend(str(Path(base) / "LibreOffice" / "program" / name) for name in ("soffice.com", "soffice.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            path = Path(candidate)
            if os.name == "nt" and path.suffix.lower() == ".exe" and path.with_suffix(".com").is_file():
                path = path.with_suffix(".com")
            return str(path)
    return ""


def _word_available() -> bool:
    if os.name != "nt" or importlib.util.find_spec("win32com") is None:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            return True
    except OSError:
        return False


def docx_converter() -> tuple[str | None, str]:
    executable = _libreoffice_path()
    if executable:
        return "libreoffice", executable
    if _word_available():
        return "word", sys.executable
    return None, ""


def legacy_doc_converter() -> str:
    """Fail closed if the parser or required LibreOffice guards are unavailable."""
    executable = _libreoffice_path()
    if not executable or importlib.util.find_spec("olefile") is None:
        return ""
    if os.name == "nt" and Path(executable).suffix.lower() != ".com":
        return ""
    try:
        registry = Path(executable).resolve().parent.parent / "share" / "registry" / "main.xcd"
        data = registry.read_text(encoding="utf-8")
        if all(name in data for name in ("DisableMacrosExecution", "DisableActiveContent", "BlockUntrustedRefererLinks")):
            return executable
    except OSError:
        pass
    return ""


def import_capabilities(max_upload_mb: int) -> dict:
    converter, _ = docx_converter()
    legacy_available = bool(legacy_doc_converter())
    return {
        "supported_extensions": [".pdf", *IMAGE_EXTENSIONS, *([".docx"] if converter else []), *([".doc"] if legacy_available else [])],
        "doc_available": legacy_available,
        "doc_note": "DOC 仅接收可核验的静态文本及表格；含宏、域、外链、对象或复杂图形时请另存为 PDF。" if legacy_available else "本机尚未具备旧版 DOC 的安全转换条件，请先另存为 PDF 或 DOCX。",
        "docx_available": bool(converter),
        "docx_converter": converter,
        "docx_note": (
            "DOCX 将由本机办公软件转为 PDF，并保留原件；请核对转换后的版式。"
            if converter else "本机未检测到可用的 Word／LibreOffice，请先将 DOCX 另存为 PDF 后上传。"
        ),
        "max_upload_mb": max_upload_mb,
    }


def check_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc", *IMAGE_EXTENSIONS):
        raise ImportFailure("暂不支持此格式。请上传 PDF、常见图片或受支持的 Word 文档。", 415)
    if ext == ".docx" and not docx_converter()[0]:
        raise ImportFailure(import_capabilities(0)["docx_note"], 503)
    if ext == ".doc" and not legacy_doc_converter():
        raise ImportFailure(import_capabilities(0)["doc_note"], 503)
    return ext


def validate_pdf(path: Path) -> int:
    import fitz

    try:
        with path.open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                raise ImportFailure("文件内容不是有效的 PDF，请检查格式后重新上传。")
        with fitz.open(str(path), filetype="pdf") as document:
            if document.needs_pass:
                raise ImportFailure("PDF 已加密，请解除打开密码后重新上传。")
            if not document.is_pdf or document.page_count < 1:
                raise ImportFailure("PDF 没有可读取的页面。")
            for page in document:
                if page.rect.is_empty or page.rect.is_infinite:
                    raise ImportFailure("PDF 中存在无法读取的页面，请修复后上传。")
            return document.page_count
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure("PDF 已损坏或无法读取，请重新导出后上传。") from exc


def _images_to_pdf(original: Path, target: Path) -> None:
    import fitz
    from PIL import Image, ImageOps, UnidentifiedImageError
    from io import BytesIO

    output = fitz.open()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(original) as image:
                if image.format not in ("JPEG", "PNG", "BMP", "TIFF", "WEBP"):
                    raise ImportFailure("图片内容与支持的格式不符，请另存为 JPEG、PNG 或 PDF。")
                frames = getattr(image, "n_frames", 1)
                if frames > MAX_IMAGE_PAGES:
                    raise ImportFailure(f"图片页数超过 {MAX_IMAGE_PAGES} 页，请拆分后上传。")
                if frames > 1 and image.format != "TIFF":
                    raise ImportFailure("不支持动态图像，请将需要的画面保存为静态图片或 PDF。")
                total_pixels = 0
                for index in range(frames):
                    image.seek(index)
                    pixels = image.width * image.height
                    total_pixels += pixels
                    if pixels > MAX_IMAGE_PIXELS or total_pixels > MAX_IMAGE_TOTAL_PIXELS:
                        raise ImportFailure("图片分辨率过大，请缩小或拆分后上传。")
                    frame = ImageOps.exif_transpose(image)
                    rgba = frame.convert("RGBA")
                    rgb = Image.new("RGB", rgba.size, "white")
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                    image_bytes = BytesIO()
                    rgb.save(image_bytes, format="PNG")
                    width, height = (842, 595) if rgb.width > rgb.height else (595, 842)
                    page = output.new_page(width=width, height=height)
                    page.insert_image(fitz.Rect(18, 18, width - 18, height - 18), stream=image_bytes.getvalue(), keep_proportion=True)
                    rgb.close()
                    rgba.close()
                    if frame is not image:
                        frame.close()
        output.save(str(target), deflate=True)
    except ImportFailure:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImportFailure("图片分辨率过大，请缩小或拆分后上传。") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImportFailure("图片内容损坏或格式无法识别，请重新导出后上传。") from exc
    finally:
        output.close()


def _validate_docx(original: Path) -> None:
    try:
        with zipfile.ZipFile(original) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if len(names) != len(entries):
                raise ImportFailure("DOCX 内部文件重复，请重新另存为 DOCX 或 PDF。")
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ImportFailure("文件不是有效的 DOCX，请使用 Word 另存为 DOCX 或 PDF。")
            if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_DOCX_EXPANDED_BYTES:
                raise ImportFailure("DOCX 解压后过大，请压缩图片或改为 PDF 后上传。")
            if any("vbaproject" in name.lower() or name.startswith("word/embeddings/") for name in names):
                raise ImportFailure("DOCX 含有宏或嵌入对象，请先在办公软件中另存为 PDF。")
            for entry in entries:
                if entry.flag_bits & 1:
                    raise ImportFailure("DOCX 已加密，请解除密码或另存为 PDF。")
                if entry.filename.endswith(".rels"):
                    if entry.file_size > 4 * 1024 * 1024:
                        raise ImportFailure("DOCX 引用信息异常，请另存为 PDF 后上传。")
                    root = ElementTree.fromstring(archive.read(entry))
                    for relation in root:
                        if relation.get("TargetMode") == "External" and not relation.get("Type", "").endswith("/hyperlink"):
                            raise ImportFailure("DOCX 含有外部链接的图片或模板，请先将其嵌入文档，或另存为 PDF。")
                elif entry.filename.startswith("word/") and entry.filename.endswith(".xml"):
                    if entry.file_size > 16 * 1024 * 1024:
                        raise ImportFailure("DOCX 文本内容过大，请拆分或另存为 PDF。")
                    root = ElementTree.fromstring(archive.read(entry))
                    instructions = []
                    for node in root.iter():
                        if node.tag.rsplit("}", 1)[-1] == "instrText":
                            instructions.append(node.text or "")
                        for name, value in node.attrib.items():
                            if name.rsplit("}", 1)[-1] == "instr":
                                instructions.append(value)
                    if re.search(r"\b(?:DDEAUTO|DDE|INCLUDETEXT|INCLUDEPICTURE|DATABASE|LINK)\b", "".join(instructions), re.IGNORECASE):
                        raise ImportFailure("DOCX 含有外部数据或动态链接域，请先在办公软件中转为静态内容或另存为 PDF。")
    except ImportFailure:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError, OSError) as exc:
        raise ImportFailure("DOCX 已损坏、被加密或格式不正确，请另存为 PDF 后上传。") from exc


def _validate_doc(original: Path) -> None:
    """Accept a deliberately small, static Word 97+ subset, never repair it.

    MS-DOC 2.5 (FIB), 2.9.38 (CLX), 2.9.276 (SttbfAssoc). Unknown
    streams/records are rejected; this is not a general malware scanner.
    All fields (even PAGE) and drawings are excluded rather than trying to
    identify only known dangerous field names inside a binary document.
    """
    try:
        import olefile
    except ImportError as exc:
        raise ImportFailure("旧版 DOC 检查组件未就绪，请先另存为 PDF 或 DOCX。", 503) from exc
    try:
        if original.stat().st_size > MAX_DOC_STREAM_BYTES or not olefile.isOleFile(original):
            raise ImportFailure("DOC 格式无效或体积过大，请另存为 PDF；不接收改名的 RTF、HTML 或其他格式。")
        with olefile.OleFileIO(original, raise_defects=olefile.DEFECT_INCORRECT) as ole:
            if ole.listdir(streams=False, storages=True):
                raise ImportFailure("DOC 含有宏、嵌入对象或复杂存储结构，请转为静态 PDF 后上传。")
            names = ole.listdir()
            allowed = {"WordDocument", "0Table", "1Table", "Data", "\x01CompObj", "\x01Ole", "\x05SummaryInformation", "\x05DocumentSummaryInformation"}
            if any(len(name) != 1 or name[0] not in allowed for name in names):
                raise ImportFailure("DOC 含有宏、对象或无法核验的附加数据，请另存为 PDF。")
            if any(ole.get_size(name) > MAX_DOC_STREAM_BYTES for name in names):
                raise ImportFailure("DOC 内部数据过大，请拆分或另存为 PDF。")
            if ole.exists("Data") and ole.get_size("Data"):
                raise ImportFailure("DOC 含有图形或嵌入数据，当前仅接收静态文本和表格，请另存为 PDF。")
            if ole.exists("\x01Ole") and ole.openstream("\x01Ole").read() != bytes.fromhex("0100000200000000000000000000000000000000"):
                raise ImportFailure("DOC 含有链接对象或无法核验的对象信息，请另存为 PDF。")
            word = ole.openstream("WordDocument").read()
            if len(word) < 154:
                raise ValueError("short FIB")
            ident, version = struct.unpack_from("<HH", word)
            flags = struct.unpack_from("<H", word, 10)[0]
            if ident != 0xA5EC or version not in (0xC1, 0xD9, 0x101, 0x10C, 0x112):
                raise ImportFailure("DOC 版本暂不支持安全导入，请另存为 PDF 或 DOCX。")
            if flags & 0x8100:
                raise ImportFailure("DOC 已加密或混淆，请解除保护并另存为 PDF。")
            if flags & 0x000F:
                raise ImportFailure("DOC 含有模板、增量保存内容或图形，当前无法完整核验，请另存为 PDF。")
            table_name = "1Table" if flags & 0x0200 else "0Table"
            if ole.exists("0Table") and ole.exists("1Table"):
                raise ValueError("ambiguous table streams")
            table = ole.openstream(table_name).read()
            if struct.unpack_from("<H", word, 32)[0] != 14 or struct.unpack_from("<H", word, 62)[0] != 22:
                raise ValueError("unsupported FIB dimensions")
            pair_count = struct.unpack_from("<H", word, 152)[0]
            if pair_count not in (93, 108, 136, 164, 183) or 154 + pair_count * 8 + 2 > len(word):
                raise ValueError("unsupported FIB array")
            if struct.unpack_from("<H", word, 154 + pair_count * 8)[0] != 0:
                raise ValueError("unsupported extended FIB")
            pairs = [struct.unpack_from("<II", word, 154 + index * 8) for index in range(pair_count)]
            # Fields, command customizations, drawings, mail merge, OCX and
            # external filename tables must all be absent. Newer extensions
            # other than the formatting cache at 93 are outside this subset.
            allowed_pairs = {0, 1, 2, 3, 4, 5, 6, 8, 11, 12, 13, 15, 21, 22, 23,
                             27, 28, 29, 30, 31, 32, 33, 36, 37, 42, 43, 46, 47,
                             51, 52, 53, 55, 56, 58, 63, 64, 65, 66, 67, 68,
                             71, 73, 74, 75, 76, 87, 89, 90, 91, 93}
            field_pairs = {16, 17, 18, 19, 20, 48, 57, 59}
            for index, (offset, length) in enumerate(pairs):
                if not length:
                    continue
                if index in field_pairs:
                    raise ImportFailure("DOC 含有字段域（可能包括 DDE 或动态外链），请先将域转为静态内容或另存为 PDF。")
                if index == 88:  # FILETIME, not an fc/lcb pair.
                    continue
                if index not in allowed_pairs:
                    raise ImportFailure("DOC 含有外部引用、宏相关信息或未支持的复杂结构，请另存为 PDF。")
                if offset + length > len(table):
                    raise ValueError("table record out of bounds")
            assoc_offset, assoc_size = pairs[32]
            if assoc_size:
                assoc = table[assoc_offset:assoc_offset + assoc_size]
                if len(assoc) < 6 or struct.unpack_from("<HHH", assoc) != (0xFFFF, 18, 0):
                    raise ValueError("unsupported associated strings")
                cursor, strings = 6, []
                for _ in range(18):
                    count = struct.unpack_from("<H", assoc, cursor)[0]
                    cursor += 2
                    if count == 0xFFFF:
                        strings.append("")
                        continue
                    if count > 255 or cursor + count * 2 > len(assoc):
                        raise ValueError("associated string out of bounds")
                    strings.append(assoc[cursor:cursor + count * 2].decode("utf-16le"))
                    cursor += count * 2
                if cursor != len(assoc):
                    raise ValueError("trailing associated data")
                if any(strings[index] for index in (1, 8, 9)):
                    raise ImportFailure("DOC 关联了外部模板或邮件合并数据，请解除关联或另存为 PDF。")
            clx_offset, clx_size = pairs[33]
            clx = table[clx_offset:clx_offset + clx_size]
            if len(clx) < 21 or clx[0] != 2:
                raise ValueError("unsupported CLX property records")
            piece_size = struct.unpack_from("<I", clx, 1)[0]
            if piece_size != len(clx) - 5 or (piece_size - 4) % 12:
                raise ValueError("bad piece table size")
            piece_count = (piece_size - 4) // 12
            if not 1 <= piece_count <= 100000:
                raise ValueError("bad piece count")
            cps = struct.unpack_from("<" + "I" * (piece_count + 1), clx, 5)
            if cps[0] != 0 or any(left >= right for left, right in zip(cps, cps[1:])):
                raise ValueError("invalid text positions")
            pcd_start = 5 + (piece_count + 1) * 4
            for index in range(piece_count):
                fc = struct.unpack_from("<I", clx, pcd_start + index * 8 + 2)[0]
                if fc & 0x80000000:
                    raise ValueError("reserved piece flag")
                compressed = bool(fc & 0x40000000)
                offset = (fc & 0x3FFFFFFF) // (2 if compressed else 1)
                size = (cps[index + 1] - cps[index]) * (1 if compressed else 2)
                if offset < 154 + pair_count * 8 or offset + size > len(word):
                    raise ValueError("text piece out of bounds")
                text = word[offset:offset + size].decode("latin1" if compressed else "utf-16le")
                if any(char in text for char in ("\x01", "\x08", "\x13", "\x14", "\x15")):
                    raise ImportFailure("DOC 含有对象或动态字段标记，请转为静态 PDF 后上传。")
            if ole.parsing_issues:
                raise ValueError("OLE structural defects")
    except ImportFailure:
        raise
    except (OSError, ValueError, struct.error, UnicodeError, IndexError) as exc:
        raise ImportFailure("DOC 已损坏或结构无法完整核验，请另存为 PDF 后上传。") from exc


def _secure_office_profile(profile: Path) -> None:
    """Per-conversion configuration; never changes the user's Office profile."""
    user = profile / "user"
    user.mkdir(parents=True)
    (user / "registrymodifications.xcu").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
<prop oor:name="SecureURL" oor:op="fuse"><value/></prop>
</item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update">
<prop oor:name="Link" oor:op="fuse"><value>2</value></prop>
<prop oor:name="Field" oor:op="fuse"><value>false</value></prop>
<prop oor:name="Chart" oor:op="fuse"><value>false</value></prop>
</item>
</oor:items>''', encoding="utf-8")


def _word_to_pdf(original: Path, target: Path) -> None:
    """Run only in a short-lived conversion subprocess, with macros disabled."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3
        word.Options.UpdateLinksAtOpen = False
        document = word.Documents.Open(
            str(original.resolve()), ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, PasswordDocument="", PasswordTemplate="",
            WritePasswordDocument="", WritePasswordTemplate="", Visible=False,
        )
        document.ExportAsFixedFormat(OutputFileName=str(target.resolve()), ExportFormat=17)
    finally:
        try:
            if document is not None:
                document.Close(False)
        finally:
            try:
                if word is not None:
                    word.Quit()
            finally:
                pythoncom.CoUninitialize()


def _docx_to_pdf(original: Path, target: Path) -> str:
    legacy = original.suffix.lower() == ".doc"
    if legacy:
        _validate_doc(original)
        kind, executable = "libreoffice", legacy_doc_converter()
        if not executable:
            raise ImportFailure(import_capabilities(0)["doc_note"], 503)
    else:
        _validate_docx(original)
        kind, executable = docx_converter()
    label = "DOC" if legacy else "DOCX"
    if not kind:
        raise ImportFailure(import_capabilities(0)["docx_note"], 503)
    # A profile below org/case/import UUIDs exceeds paths handled by Windows
    # LibreOffice (including its deeper internal config files). Keep its private
    # working copy and fresh profile near the workstation data root instead.
    from ..config import DATA_DIR
    office_root = DATA_DIR / "office-temp"
    office_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Office can briefly retain profile locks after successful conversion.
    # Cleanup is best effort and must not turn a valid PDF into an import 500.
    with tempfile.TemporaryDirectory(prefix="job-", dir=office_root, ignore_cleanup_errors=True) as temporary:
        office_work = Path(temporary)
        conversion_input = office_work / ("original" + original.suffix.lower())
        shutil.copyfile(original, conversion_input)
        if kind == "libreoffice":
            _secure_office_profile(office_work / "profile")
            command = [
                executable, "-env:UserInstallation=" + (office_work / "profile").as_uri(),
                "--headless", "--nologo", "--nodefault", "--norestore",
                "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(office_work), str(conversion_input),
            ]
            result_pdf = office_work / "original.pdf"
        else:
            result_pdf = office_work / "original.pdf"
            command = [executable, str(Path(__file__).resolve()), "--word", str(conversion_input), str(result_pdf)]
        try:
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=120, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise ImportFailure(f"{label} 转换超时。请在本机办公软件中另存为 PDF 后上传；原文件未改动。", 422) from exc
        except OSError as exc:
            raise ImportFailure(f"无法启动本机办公软件，请先将 {label} 另存为 PDF 后上传。", 503) from exc
        if completed.returncode != 0 or not result_pdf.is_file():
            raise ImportFailure(f"{label} 转换失败，请检查本机办公软件能否打开原文件，或另存为 PDF 后上传。", 422)
        if result_pdf != target:
            shutil.copyfile(result_pdf, target)
    return kind


def normalize_import(original: Path, filename: str) -> Path:
    """Validate and normalize a staged upload; caller owns cleanup on failure."""
    ext = original.suffix.lower()
    target = original.parent / "source.pdf"
    conversion = "none"
    if ext == ".pdf":
        pages = validate_pdf(original)
        # Keep PDF bytes unchanged (including signatures); analysis uses the original.
        target = original
    elif ext in IMAGE_EXTENSIONS:
        _images_to_pdf(original, target)
        pages = validate_pdf(target)
        conversion = "image"
    elif ext in (".docx", ".doc"):
        conversion = _docx_to_pdf(original, target)
        pages = validate_pdf(target)
    else:
        raise ImportFailure("不支持的文件格式。", 415)
    (original.parent / "import.json").write_text(
        json.dumps({"filename": filename, "original": original.name, "pdf": target.name, "pages": pages, "conversion": conversion}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def owned_import_directory(case_dir: Path, stored_path: Path) -> Path | None:
    """Return only a direct UUID import directory; legacy uploads return None."""
    root = (case_dir / "imports").resolve()
    parent = stored_path.resolve().parent
    if parent.parent == root and len(parent.name) == 32 and all(c in "0123456789abcdef" for c in parent.name):
        return parent
    return None


def original_file(case_dir: Path, stored_path: Path) -> Path:
    owned = owned_import_directory(case_dir, stored_path)
    if owned:
        metadata = json.loads((owned / "import.json").read_text(encoding="utf-8"))
        original = (owned / metadata["original"]).resolve()
        if original.parent != owned or not original.is_file():
            raise FileNotFoundError("original unavailable")
        return original
    resolved = stored_path.resolve()
    if not resolved.is_relative_to(case_dir.resolve()) or not resolved.is_file():
        raise FileNotFoundError("original unavailable")
    return resolved


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--word":
        _word_to_pdf(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit(2)
