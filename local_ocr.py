"""明确的离线 OCR 路径：固定包内 ONNX 模型，绝不调用云 OCR 或下载模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata, util
from pathlib import Path
import math
import os
import re


SUPPORTED_RAPIDOCR_VERSION = "1.4.4"
MODEL_FILES = {
    "det_model_path": "ch_PP-OCRv4_det_infer.onnx",
    "cls_model_path": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "rec_model_path": "ch_PP-OCRv4_rec_infer.onnx",
}


class LocalOcrError(RuntimeError):
    """离线 OCR 无法继续；调用方必须展示失败，不能切换云服务。"""


@dataclass
class LocalOcrResult:
    page_texts: list[str] = field(default_factory=list)
    ocr_pages: int = 0
    layout_blocks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def bundled_model_paths() -> dict[str, str]:
    """在初始化推理前检查固定版本及全部模型，不提供下载地址或下载逻辑。"""
    try:
        version = metadata.version("rapidocr-onnxruntime")
        spec = util.find_spec("rapidocr_onnxruntime")
    except (metadata.PackageNotFoundError, ImportError, ValueError) as exc:
        raise LocalOcrError("本地 OCR 未安装，请安装 rapidocr-onnxruntime==1.4.4（Python 3.12）。") from exc
    if version != SUPPORTED_RAPIDOCR_VERSION or spec is None or not spec.origin:
        raise LocalOcrError("本地 OCR 需要已验证的 rapidocr-onnxruntime==1.4.4，未自动更换引擎。")
    root = Path(spec.origin).resolve().parent / "models"
    paths = {name: str(root / filename) for name, filename in MODEL_FILES.items()}
    missing = [Path(path).name for path in paths.values() if not Path(path).is_file() or Path(path).stat().st_size == 0]
    if missing:
        raise LocalOcrError("本地 OCR 模型缺失：" + "、".join(missing) + "；请修复安装，不会联网下载。")
    return paths


def create_local_engine():
    paths = bundled_model_paths()
    try:
        # ORT 1.31 can emit a native initialization event before its API guard.
        # Set the documented process opt-out before importing the native library.
        os.environ["ORT_DISABLE_TELEMETRY"] = "1"
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR(
            **paths,
            det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False,
            det_use_dml=False, cls_use_dml=False, rec_use_dml=False,
            intra_op_num_threads=2, inter_op_num_threads=1,
        )
    except Exception as exc:
        raise LocalOcrError("本地 OCR 模型加载失败，未切换其他 OCR 服务。") from exc


def _usable_text_layer(page, text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact or compact.count("\ufffd") > len(compact) * 0.05:
        return False
    # 只有页码/页脚文字但正文是扫描图时仍需 OCR。纯文字短页可直接采用。
    return len(compact) >= 80 or (len(compact) >= 5 and not page.get_images())


def ordered_text_layer(page) -> str:
    """Order same-baseline font runs spatially (Office may emit fallback glyphs last)."""
    rows = []
    for block in page.get_text('dict').get('blocks', []):
        for line in block.get('lines', []):
            if tuple(line.get('dir', (1,0))) != (1,0):
                return page.get_text(sort=True)
            for span in line.get('spans', []):
                text = span.get('text', '')
                if not text:
                    continue
                baseline = span.get('origin', (0,span['bbox'][3]))[1]
                row = next((row for row in rows if abs(row[0]-baseline)<.75), None)
                if row is None:
                    row=[baseline,[]]; rows.append(row)
                row[1].append(span)
    lines=[]
    for _, spans in sorted(rows,key=lambda row:row[0]):
        spans.sort(key=lambda span:span['bbox'][0])
        parts=[]; previous=None
        for span in spans:
            if previous and span['bbox'][0]-previous['bbox'][2]>max(2,span.get('size',12)*.35):
                parts.append(' ')
            parts.append(span['text']); previous=span
        lines.append(''.join(parts))
    return '\n'.join(lines)


def read_local_pdf(pdf_path: str, config: dict | None = None, log=print) -> LocalOcrResult:
    """逐页优先文字层，其余页仅用包内模型；保留空页及页码，不跨页均分。"""
    try:
        import fitz
    except ImportError as exc:
        raise LocalOcrError("缺少 PyMuPDF，无法读取本地 PDF。") from exc
    options = (config or {}).get("local_onnx") or {}
    dpi = int(options.get("dpi", 180))
    if not 72 <= dpi <= 300:
        raise LocalOcrError("本地 OCR 分辨率必须在 72 至 300 DPI 之间。")
    result = LocalOcrResult()
    engine = None
    try:
        with fitz.open(pdf_path) as document:
            if document.needs_pass or document.page_count <= 0:
                raise LocalOcrError("PDF 为空或已加密，请先提供可读取的 PDF。")
            for index, page in enumerate(document):
                text = ordered_text_layer(page).strip()
                if _usable_text_layer(page, text):
                    result.page_texts.append(text)
                    continue
                if engine is None:
                    engine = create_local_engine()
                try:
                    scale = min(dpi / 72, math.sqrt(16_000_000 / max(page.rect.width * page.rect.height, 1)))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                    rows, _elapsed = engine(pix.tobytes("png"))
                    result.ocr_pages += 1
                    lines = []
                    for row in rows or []:
                        if len(row) < 3 or not isinstance(row[1], str):
                            raise ValueError("本地 OCR 返回结构无效")
                        line = row[1].strip()
                        if not line:
                            continue
                        lines.append(line)
                        result.layout_blocks.append({
                            "page_idx": index, "type": "text", "text": line,
                            "confidence": float(row[2]), "bbox": row[0],
                        })
                    recognized = "\n".join(lines)
                    result.page_texts.append(recognized or text)
                    if not recognized:
                        result.warnings.append(f"第 {index + 1} 页未识别到正文文字，请核对是否为空白页或图像材料。")
                    log(f"  [本地 OCR] 第 {index + 1}/{document.page_count} 页完成")
                except LocalOcrError:
                    raise
                except Exception as exc:
                    raise LocalOcrError(f"第 {index + 1} 页本地 OCR 失败，已停止；未切换云端服务。") from exc
    except LocalOcrError:
        raise
    except Exception as exc:
        raise LocalOcrError("本地 PDF 读取失败，未调用其他 OCR 服务。") from exc
    return result
