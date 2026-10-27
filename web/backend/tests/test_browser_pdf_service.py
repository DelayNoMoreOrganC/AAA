from __future__ import annotations

import os
import io
import traceback
from types import SimpleNamespace

import fitz
import pytest

from app.config import get_settings
from app.services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES
# Legacy HTML/Chrome remains a separately tested utility; production forms now
# delegate exclusively to original_template_service (covered by its tests).
from app.services.browser_pdf_service import FORM_LAYOUTS, render_form_html, _legacy_render_form_pdf as render_form_pdf
from app.services import browser_pdf_service


SAMPLE_FIELDS = {
    "案件类别": "民事",
    "委托人": "甲方 <测试>",
    "当事人": "甲方",
    "对方当事人": "乙方",
    "法院收案号": "（2026）粤0604民初1号",
    "结案小结": "判决后进入执行程序，法院采取网络查控和限制消费措施。",
    "法院文件清单": "民事判决书\n执行裁定书",
    "_preview_styles": {"档案卷宗": {"field:结案小结": {"fontSize": "9pt", "textAlign": "justify"}}},
    "_preview_custom_values": {"立案审批表": {"p0-b0-r6-c0": "同意承办。"}},
}


def test_backend_layouts_cover_all_browser_forms():
    assert set(FORM_LAYOUTS) == set(SYSTEM_TEMPLATE_NAMES)


def test_render_form_html_uses_saved_values_styles_and_escapes_input():
    rendered = render_form_html("立案审批表", SAMPLE_FIELDS, "广东至高律师事务所")
    assert "广东至高律师事务所制" in rendered
    assert "甲方 &lt;测试&gt;" in rendered
    assert "同意承办。" in rendered
    assert "<测试>" not in rendered

    archive = render_form_html("档案卷宗", SAMPLE_FIELDS, "广东至高律师事务所")
    assert "font-size:9pt" in archive
    assert "text-align:justify" in archive


def test_close_report_never_defaults_to_customer_satisfaction():
    empty = render_form_html("结案报告表", {}, "虚构示例律师事务所")
    assert "委托人对承办律师服务质量表示满意" not in empty
    feedback = "委托人提出需要改进沟通频率"
    filled = render_form_html("结案报告表", {"委托人对服务质量意见": feedback}, "虚构示例律师事务所")
    assert feedback in filled


def test_browser_render_refuses_root_instead_of_disabling_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_pdf_service, "get_settings", lambda: SimpleNamespace(chromium_executable="chromium"))
    monkeypatch.setattr(browser_pdf_service.os, "geteuid", lambda: 0, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Root rendering must stop before starting a browser")
    monkeypatch.setattr(browser_pdf_service.subprocess, "Popen", forbidden)
    output = tmp_path / "root-output.pdf"
    with pytest.raises(RuntimeError, match="非 root"):
        render_form_pdf("立案审批表", SAMPLE_FIELDS, "虚构示例律师事务所", str(output))
    assert not output.exists()
    assert not output.with_suffix(".html").exists()


@pytest.fixture
def private_browser_setup(monkeypatch):
    monkeypatch.setattr(browser_pdf_service, "get_settings", lambda: SimpleNamespace(chromium_executable="fictional-browser"))
    monkeypatch.setattr(browser_pdf_service.os, "geteuid", lambda: 1000, raising=False)


@pytest.mark.parametrize("exit_code,category", [(17, "BROWSER_EXITED"), (0, "BROWSER_INVALID_PDF")])
def test_browser_output_never_enters_failure_or_log(tmp_path, monkeypatch, private_browser_setup, exit_code, category):
    marker = "FICTIONAL_BROWSER_PRIVATE_CONTENT_f8e2"
    stream = io.StringIO(marker)
    observed = {}
    def launch(command, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(poll=lambda: exit_code, stderr=stream, stdout=stream)
    monkeypatch.setattr(browser_pdf_service.subprocess, "Popen", launch)
    output = tmp_path / f"{marker}.pdf"
    logs = []
    with pytest.raises(RuntimeError, match=category) as error:
        render_form_pdf("立案审批表", {"委托人": marker}, "虚构律所", str(output), log=logs.append)
    assert observed["stderr"] == browser_pdf_service.subprocess.DEVNULL
    assert observed["stdout"] == browser_pdf_service.subprocess.DEVNULL
    assert stream.tell() == 0
    assert f"exit_code={exit_code}" in str(error.value)
    assert marker not in str(error.value) + "\n".join(logs)
    assert not output.exists()
    # Authorized output source is not erased to achieve diagnostic redaction.
    assert marker in output.with_suffix(".html").read_text(encoding="utf-8")


def test_browser_launch_exception_suppresses_private_message_and_chain(tmp_path, monkeypatch, private_browser_setup):
    marker = "FICTIONAL_PRIVATE_LAUNCH_PATH_774c"
    def launch(*args, **kwargs):
        raise OSError(marker)
    monkeypatch.setattr(browser_pdf_service.subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="BROWSER_START_FAILED") as error:
        render_form_pdf("立案审批表", {}, "虚构律所", str(tmp_path / "output.pdf"))
    assert marker not in "".join(traceback.format_exception(error.value))


def test_browser_timeout_is_a_failure_and_cleans_process(tmp_path, monkeypatch, private_browser_setup):
    state = {"terminated": False}
    def terminate():
        state["terminated"] = True
    process = SimpleNamespace(poll=lambda: None, terminate=terminate, wait=lambda timeout: 0)
    monkeypatch.setattr(browser_pdf_service.subprocess, "Popen", lambda *args, **kwargs: process)
    ticks = iter([0, 100])
    monkeypatch.setattr(browser_pdf_service.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="BROWSER_RENDER_TIMEOUT"):
        render_form_pdf("立案审批表", {}, "虚构律所", str(tmp_path / "output.pdf"))
    assert state["terminated"]


def test_browser_cleanup_exception_has_fixed_category(tmp_path, monkeypatch, private_browser_setup):
    marker = "FICTIONAL_PRIVATE_COMMAND_ARGUMENT_aa94"
    def fail_wait(timeout):
        raise browser_pdf_service.subprocess.TimeoutExpired([marker], timeout, output=marker, stderr=marker)
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: None, kill=lambda: None, wait=fail_wait)
    monkeypatch.setattr(browser_pdf_service.subprocess, "Popen", lambda *args, **kwargs: process)
    ticks = iter([0, 100])
    monkeypatch.setattr(browser_pdf_service.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="BROWSER_CLEANUP_FAILED") as error:
        render_form_pdf("立案审批表", {}, "虚构律所", str(tmp_path / "output.pdf"))
    assert marker not in "".join(traceback.format_exception(error.value))


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_PDF_TESTS") != "1" or not get_settings().chromium_executable,
    reason="set RUN_BROWSER_PDF_TESTS=1 to exercise local Chrome",
)
def test_chromium_generates_a4_pdf(tmp_path):
    output = tmp_path / "质量监督卡.pdf"
    render_form_pdf("质量监督卡", SAMPLE_FIELDS, "广东至高律师事务所", str(output), log=lambda _msg: None)
    with fitz.open(output) as document:
        assert document.page_count == 2
        assert all(abs(page.rect.width - 595.28) <= 3 for page in document)
        assert all(abs(page.rect.height - 841.89) <= 3 for page in document)
    assert output.stat().st_size > 10_000
