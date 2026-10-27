"""Remove generated archive outputs from disk."""
from __future__ import annotations

import os
import shutil

from ..models import ArchiveTask


def remove_task_outputs(task: ArchiveTask) -> None:
    if task.output_pdf and os.path.exists(task.output_pdf):
        try:
            os.remove(task.output_pdf)
        except OSError:
            pass
    if task.output_docx_dir:
        zip_path = task.output_docx_dir + ".zip"
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        if os.path.isdir(task.output_docx_dir):
            try:
                shutil.rmtree(task.output_docx_dir)
            except OSError:
                pass
