"""Copy only verified deliverables to an administrator-selected workstation folder."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from ..config import DATA_DIR

CONFIG = DATA_DIR / "output-settings.json"


def output_directory():
    if CONFIG.is_file():
        value = json.loads(CONFIG.read_text(encoding="utf-8")).get("output_directory")
        if value:
            return Path(value)
    return DATA_DIR / "归档成果"


def set_output_directory(value: str):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("请选择工作站上的绝对目录")
    path = path.resolve()
    # UNC shares may send case data outside the workstation's confidentiality boundary.
    if str(path).startswith("\\\\"):
        raise ValueError("保密模式仅保存到工作站本机目录，不支持网络共享路径")
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path) as probe:
        probe.write(b"gd-output-test")
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps({"output_directory": str(path)}, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, CONFIG)
    return path


def export_archive(work, org_id, case_id, task_id):
    source = Path(work)
    generation = source.name if source.name.startswith("render-") else None
    revision_dir = source.parent if generation else source
    revision = revision_dir.name if revision_dir.name.startswith("r") and revision_dir.name[1:].isdigit() else "r1"
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from workstation_security import protect_directory
    org_output = output_directory() / org_id
    protect_directory(org_output)
    destination = org_output / case_id / str(task_id) / revision
    if generation:
        destination = destination / generation
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=True)
    # Source snapshots, OCR text and log files are deliberately excluded.
    names = [p for p in source.iterdir() if p.is_file() and (p.suffix.lower() in (".pdf", ".zip") or p.name.startswith(("quality_report", "归档质检", "artifact_manifest")))]
    names.extend((source / "docx").glob("*.docx"))
    for path in names:
        subfolder = destination / "Word" if path.suffix.lower() == ".docx" else destination
        subfolder.mkdir(exist_ok=True)
        target = subfolder / path.name
        temp = target.with_suffix(target.suffix + ".tmp")
        shutil.copyfile(path, temp)
        os.replace(temp, target)
    return str(destination)
