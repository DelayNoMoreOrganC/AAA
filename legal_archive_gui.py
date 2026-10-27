#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案件档案一键归档 — 百度 OCR / MinerU 可切换"""

import os
import sys
import threading
import tkinter as tk
from typing import Dict, List, Optional
from tkinter import filedialog, messagebox, ttk

from app_paths import ensure_app_dirs, get_app_dir, get_config_path, get_outputs_dir, init_config_if_missing
from error_handler import get_friendly_error
from settings import (
    apply_ocr_engine,
    config_is_ready,
    config_status_message,
    get_ocr_engine,
    load_config,
)
from archive_pipeline import process_archive, process_archive_sources
from archive_pipeline import analyze_archive, assemble_archive  # V4
from archive_pipeline import recompute_found_and_missing  # V4 手动调整
from archive_pipeline import write_archive_report  # V4 结构化报告
from batch_processor import process_batch

# V4 新增
try:
    import archive_catalog as ac
except ImportError:
    ac = None
from document_segmenter import (
    DOC_TYPE_DEFAULT,
    DOC_TYPE_LABELS,
    DocumentSource,
)
from output_options import (
    ALL_TEMPLATES,
    OUTPUT_MODE_ALL,
    OUTPUT_MODE_SELECT,
)
from gui_settings_dialog import open_settings_dialog
from gui_theme import (
    ChipRadio,
    HeroHeader,
    ScrollPanel,
    SectionTitle,
    SegmentedControl,
    StatusBar,
    apply_ttk_combobox_style,
    fit_window,
    styled_entry,
)
from macos_ui_theme import MacOSLogPopup, MACOS_COLORS, MACOS_FONTS, apply_macos_style, MacOSCard, MacOSButton

# 颜色系统统一：将现有C系统映射到macOS风格
C = {
    "bg": MACOS_COLORS["window_bg"],           # 主背景色
    "bg2": MACOS_COLORS["panel_bg"],           # 次背景色
    "card": MACOS_COLORS["card_bg"],           # 卡片背景
    "card_bg": MACOS_COLORS["card_bg"],        # 卡片背景(MacOSCard需要)
    "text": MACOS_COLORS["text_primary"],      # 主文本
    "secondary": MACOS_COLORS["text_secondary"], # 次文本
    "tertiary": MACOS_COLORS["text_tertiary"],  # 三级文本
    "accent": MACOS_COLORS["accent"],           # 强调色
    "accent2": MACOS_COLORS["accent"],         # 次强调色
    "accent_soft": MACOS_COLORS["border_light"], # 柔和强调
    "accent_hover": MACOS_COLORS["accent_hover"], # 悬停强调
    "accent_text": MACOS_COLORS["button_text"],  # 按钮文本
    "success": MACOS_COLORS["success"],         # 成功色
    "success_soft": "#E3FBEF",                 # 成功背景(保持)
    "warn": MACOS_COLORS["warning"],           # 警告色
    "warn_soft": "#FFF4E5",                    # 警告背景(保持)
    "danger": MACOS_COLORS["error"],            # 危险色
    "danger_soft": "#FEECEB",                   # 危险背景(保持)
    "mineru": "#7A5AF8",                       # MinerU色(保持)
    "mineru_soft": "#F4F0FF",                  # MinerU背景(保持)
    "baidu": MACOS_COLORS["accent"],           # 百度色映射到系统蓝
    "baidu_soft": "#EFF8FF",                   # 百度背景(保持)
    "teal": MACOS_COLORS["accent"],            # 青色映射到系统蓝
    "teal_soft": "#E0F7FE",                    # 青色背景(保持)
    "border": MACOS_COLORS["border"],          # 边框色
    "input": MACOS_COLORS["input_bg"],         # 输入框背景
    "shadow": MACOS_COLORS["shadow"],         # 阴影色
    "hero_from": MACOS_COLORS["accent"],      # 渐变起始
    "hero_to": MACOS_COLORS["accent_hover"],  # 渐变结束
    "tip_bg": MACOS_COLORS["panel_bg"],       # 提示背景
    "tip_text": MACOS_COLORS["text_primary"], # 提示文本
}

# 字体系统统一：macOS风格字体映射
def ui_fonts_macos(root=None):
    """macOS风格字体，优先SF Pro系列，回退到系统字体"""
    # 基础字体族
    font_families = {
        "display": ("SF Pro Display", "Helvetica Neue", "Arial", "sans-serif"),
        "text": ("SF Pro Text", "Helvetica Neue", "Arial", "sans-serif"),
        "mono": ("SF Mono", "Menlo", "Consolas", "monospace")
    }

    # 选择最佳字体
    def choose_font(preferred_families):
        if root:
            for fam in preferred_families:
                try:
                    # 检查字体是否可用
                    if root.tk.call("font", "measure", fam, "test") >= 0:
                        return fam
                except:
                    continue
        return preferred_families[0]  # 回退到首选

    display_font = choose_font(font_families["display"])
    text_font = choose_font(font_families["text"])
    mono_font = choose_font(font_families["mono"])

    return {
        "hero": (display_font, 20, "bold"),
        "title": (text_font, 13, "bold"),      # tkinter不支持semibold，改用bold
        "body": (text_font, 11, "normal"),
        "body_b": (text_font, 11, "bold"),     # 加粗正文
        "cap": (text_font, 10, "normal"),
        "tiny": (text_font, 9, "normal"),
        "btn": (text_font, 10, "bold"),         # 按钮字体
        "btn_sm": (text_font, 9, "bold"),      # 小按钮字体
        "code": (mono_font, 10, "normal"),
        "button": (text_font, 11, "normal"),
        "log": (mono_font, 9, "normal"),       # 日志字体
    }

from app_version import V4_VERSION as APP_VERSION


class ArchiveApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"案件归档 {APP_VERSION}")
        self.configure(bg=C["bg"])

        ensure_app_dirs()
        init_config_if_missing()

        cfg = load_config()
        self.pdf_path = tk.StringVar()  # CLI 兼容
        self.max_pages = tk.IntVar(
            value=cfg.get("local_ocr", {}).get("max_pages", 0) or 0
        )
        self.ocr_engine = tk.StringVar(value=get_ocr_engine(cfg))
        self.mineru_cli_path = tk.StringVar(
            value=(cfg.get("mineru") or {}).get("cli_path", "")
        )
        self._running = False
        self._cancel_batch = False
        self._macos_log_popup = None  # 独立日志弹窗（开始弹出、完成收回）
        self.upload_mode = tk.StringVar(value="case")
        self.multi_files = []  # 个案归档：{path, doc_type}
        self.output_mode = tk.StringVar(value=OUTPUT_MODE_ALL)
        self.template_vars = {name: tk.BooleanVar(value=True) for name in ALL_TEMPLATES}
        self._supplement_files_map = {}  # Phase C: {seq: [file_paths]} 补充文件映射

        # 字体系统统一：使用macOS风格
        self._fonts = ui_fonts_macos(self)
        # 确保字体包含emoji字体（兼容原有逻辑）
        if "emoji" not in self._fonts:
            self._fonts["emoji"] = ("Segoe UI Emoji", 20)
        apply_macos_style(self)
        apply_ttk_combobox_style(self)

        # 初始化macOS风格日志弹窗
        self._macos_log_popup = MacOSLogPopup(self)

        self._main = tk.Frame(self, bg=C["bg"])
        self._main.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        self._build()
        self._on_engine_changed(initial=True)
        self._refresh_status()
        self._fit_window()

    def _fit_window(self):
        fit_window(self, content=self._main)

    def _shell_card(self, parent, pady=(0, 8)):  # macOS间距规范：8px基准
        card = MacOSCard(parent, colors=C, pady=pady, padx=0, autopack=True, fill=tk.X)
        return card.body

    def _build(self):
        root = self._main

        HeroHeader(
            root,
            "案件归档",
            "全选/自选 docx  ·  OCR 可切换",
            APP_VERSION,
            colors=C,
            fonts=self._fonts,
            compact=True,
        ).pack(fill=tk.X)

        # 主体：三列并列，紧凑布局（日志改用独立弹窗，不再占用主窗口空间）
        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.columnconfigure(2, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)

        col_upload = tk.Frame(body, bg=C["bg"])
        col_upload.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)

        col_ocr = tk.Frame(body, bg=C["bg"])
        col_ocr.grid(row=0, column=1, sticky="nsew", padx=6, pady=0)

        col_action = tk.Frame(body, bg=C["bg"])
        col_action.grid(row=0, column=2, sticky="nsew", padx=(6, 0), pady=0)

        self._low_conf_hint = tk.Label(
            col_action,
            text="",
            font=self._fonts["cap"],
            fg=C["warn"],
            bg=C["bg"],
            wraplength=260,
            justify="left",
        )

        # ── 列1：上传 ──
        upload = self._shell_card(col_upload, pady=(0, 3))
        SectionTitle(upload, "📤", "上传方式", colors=C, fonts=self._fonts).pack(anchor="w")
        mode_row = tk.Frame(upload, bg=C["card"])
        mode_row.pack(fill=tk.X, pady=(4, 0))
        ChipRadio(
            mode_row,
            (("case", "个案"), ("batch", "批量")),
            self.upload_mode,
            command=self._on_upload_mode_changed,
            colors=C,
            fonts=self._fonts,
        ).pack(fill=tk.X)

        self.upload_detail = tk.Frame(upload, bg=C["card"])
        self.upload_detail.pack(fill=tk.X, pady=(4, 0))
        self._build_case_upload(self.upload_detail)
        self._build_batch_upload(self.upload_detail)
        self._on_upload_mode_changed()

        # ── 列2：OCR ──
        ocr = self._shell_card(col_ocr, pady=(0, 3))
        SectionTitle(ocr, "🔍", "OCR 方案", colors=C, fonts=self._fonts).pack(anchor="w")
        self._ocr_seg = SegmentedControl(
            ocr,
            (
                ("mineru_api", "🌐  MinerU API"),
                ("baidu", "☁️  百度 OCR"),
                ("mineru", "🖥️  MinerU 本地"),
            ),
            self.ocr_engine,
            command=lambda: self._on_engine_changed(),
            colors=C,
            fonts=self._fonts,
            vertical=True,
        )
        self._ocr_seg.pack(fill=tk.X, pady=(8, 0))

        self.mineru_path_frame = tk.Frame(ocr, bg=C["card"])
        tk.Label(
            self.mineru_path_frame,
            text="MinerU 路径（可选）",
            font=self._fonts["cap"],
            fg=C["secondary"],
            bg=C["card"],
        ).pack(anchor="w", pady=(8, 4))
        path_wrap, _, path_inner = styled_entry(
            self.mineru_path_frame, self.mineru_cli_path, colors=C, fonts=self._fonts
        )
        path_wrap.pack(fill=tk.X)
        browse_btn = MacOSButton(
            path_inner,
            text="浏览",
            command=self._browse_mineru,
            style="soft",
            fonts=self._fonts,
        )
        browse_btn.pack(side=tk.RIGHT, padx=(6, 0))
        browse_btn.configure(width=64)

        orow = tk.Frame(ocr, bg=C["card"])
        orow.pack(fill=tk.X, pady=(8, 0))
        tk.Label(orow, text="解析页数", font=self._fonts["cap"], fg=C["secondary"], bg=C["card"]).pack(
            side=tk.LEFT
        )
        spin_fr = tk.Frame(orow, bg=C["input"], highlightbackground=C["border"], highlightthickness=1)
        spin_fr.pack(side=tk.RIGHT)
        tk.Spinbox(
            spin_fr,
            from_=0,
            to=999,
            textvariable=self.max_pages,
            width=4,
            font=self._fonts["body"],
            relief=tk.FLAT,
            bg=C["input"],
            bd=0,
        ).pack(padx=10, pady=4)
        self.ocr_hint = tk.Label(
            ocr,
            text="",
            font=self._fonts["cap"],
            fg=C["tertiary"],
            bg=C["card"],
            wraplength=260,
            justify="left",
        )
        self.ocr_hint.pack(anchor="w", pady=(6, 0))

        # ── 列3：完整归档 + 输出 + 操作 ──
        v4_card = self._shell_card(col_action, pady=(0, 6))
        SectionTitle(v4_card, "📋", "完整归档（V4）", colors=C, fonts=self._fonts).pack(anchor="w")

        # 完整归档开关
        self.full_archive_enabled = tk.BooleanVar(value=False)
        fa_toggle = tk.Frame(v4_card, bg=C["card"])
        fa_toggle.pack(fill=tk.X, pady=(8, 0))
        tk.Checkbutton(
            fa_toggle,
            text="启用完整归档（按标准目录拼装 PDF）",
            variable=self.full_archive_enabled,
            font=self._fonts["cap"],
            bg=C["card"],
            fg=C["text"],
            activebackground=C["card"],
            selectcolor=C["accent_soft"],
            command=self._on_full_archive_changed,
        ).pack(anchor="w")

        # 案件类型选择（仅完整归档启用时显示）
        self.case_type_frame = tk.Frame(v4_card, bg=C["card"])
        self.case_type = tk.StringVar(value="civil")
        ct_row = tk.Frame(self.case_type_frame, bg=C["card"])
        ct_row.pack(fill=tk.X, pady=(8, 0))
        tk.Label(
            ct_row,
            text="案件类型",
            font=self._fonts["cap"],
            fg=C["secondary"],
            bg=C["card"],
        ).pack(anchor="w", pady=(0, 4))

        # 五类案件类型选择
        ct_grid = tk.Frame(self.case_type_frame, bg=C["card"])
        ct_grid.pack(fill=tk.X, pady=(0, 8))

        ChipRadio(
            ct_grid,
            (
                ("civil", "民事"),
                ("criminal", "刑事"),
                ("admin", "行政"),
                ("nonlit", "非诉"),
                ("counsel", "顾问"),
            ),
            self.case_type,
            colors=C,
            fonts=self._fonts,
        ).pack(fill=tk.X)

        # 正文排序模式
        tk.Label(
            self.case_type_frame,
            text="正文排序",
            font=self._fonts["cap"],
            fg=C["secondary"],
            bg=C["card"],
        ).pack(anchor="w", pady=(8, 4))
        self.archive_order_mode = tk.StringVar(value="catalog")
        om_grid = tk.Frame(self.case_type_frame, bg=C["card"])
        om_grid.pack(fill=tk.X, pady=(0, 8))
        ChipRadio(
            om_grid,
            (("catalog", "按目录顺序"), ("original", "保持原始页序")),
            self.archive_order_mode,
            colors=C,
            fonts=self._fonts,
        ).pack(fill=tk.X)

        # 进度条（完整归档时显示）
        self.archive_progress = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self.case_type_frame,
            variable=self.archive_progress,
            maximum=100,
            mode="determinate",
        )
        self.progress_bar.pack(fill=tk.X, pady=(8, 0))

        out_card = self._shell_card(col_action, pady=(0, 6))
        self.output_card = out_card
        SectionTitle(out_card, "📄", "输出项目", colors=C, fonts=self._fonts).pack(anchor="w")
        self.output_mode_frame = tk.Frame(out_card, bg=C["card"])
        om = self.output_mode_frame
        om.pack(fill=tk.X, pady=(8, 0))
        for val, label in (
            (OUTPUT_MODE_ALL, "全选（5 份 docx）"),
            (OUTPUT_MODE_SELECT, "自选 docx"),
        ):
            tk.Radiobutton(
                om,
                text=label,
                variable=self.output_mode,
                value=val,
                font=self._fonts["cap"],
                bg=C["card"],
                fg=C["text"],
                activebackground=C["accent_soft"],
                activeforeground=C["accent"],
                selectcolor=C["accent_soft"],
                command=self._on_output_mode_changed,
            ).pack(anchor="w", pady=1)

        self.template_pick_frame = tk.Frame(
            out_card, bg=C["input"], highlightbackground=C["border"], highlightthickness=1
        )
        tpf = tk.Frame(self.template_pick_frame, bg=C["input"])
        tpf.pack(fill=tk.X, padx=10, pady=8)
        self._template_cb_widgets = []
        for i, name in enumerate(ALL_TEMPLATES):
            cb = tk.Checkbutton(
                tpf,
                text=name,
                variable=self.template_vars[name],
                font=self._fonts["cap"],
                bg=C["input"],
                fg=C["text"],
                activebackground=C["input"],
                selectcolor=C["accent_soft"],
            )
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=2)
            self._template_cb_widgets.append(cb)
        self.output_full_archive_hint = tk.Label(
            out_card,
            text="完整归档模式：自动生成全部 5 份系统 docx，并按标准目录合并为 PDF",
            font=self._fonts["cap"],
            fg=C["secondary"],
            bg=C["card"],
            wraplength=260,
            justify="left",
        )
        self._on_full_archive_changed()
        self._low_conf_hint.pack(anchor="w", pady=(6, 0))

        side = tk.Frame(col_action, bg=C["bg"])
        side.pack(fill=tk.X, pady=(0, 0))

        self.run_btn = MacOSButton(
            side, "✨  开始归档", self._start, style="primary", fonts=self._fonts
        )
        self.run_btn.pack(fill=tk.X, pady=(0, 8))

        self.status_var = tk.StringVar(value="🟢  就绪")
        StatusBar(side, self.status_var, colors=C, fonts=self._fonts).pack(fill=tk.X, pady=(0, 8))

        for label, cmd, style in (
            ("📂  打开输出文件夹", self._open_outputs, "soft"),
            ("⚙️  详细设置", self._open_settings, "secondary"),
            ("📘  MinerU 说明", self._open_mineru_doc, "secondary"),
        ):
            btn = MacOSButton(side, text=label, command=cmd, style=style, fonts=self._fonts)
            btn.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            root,
            text=f"📍 {get_app_dir()}",
            font=(self._fonts["cap"][0], 8),
            fg=C["tertiary"],
            bg=C["bg"],
            wraplength=920,
            justify="left",
        ).pack(fill=tk.X, pady=(8, 0))

        # macOS风格：移除嵌入式日志面板，使用独立弹窗避免主窗口变形

    # macOS风格：移除嵌入式日志面板，使用独立弹窗避免主窗口变形
    # 已移除 _build_embedded_log_panel() 方法

    def _on_output_mode_changed(self):
        mode = self.output_mode.get()
        if mode == OUTPUT_MODE_SELECT:
            self.template_pick_frame.pack(fill=tk.X, pady=(10, 0))
        else:
            self.template_pick_frame.pack_forget()
        self._fit_window()

    def _get_output_options(self):
        selected = [n for n in ALL_TEMPLATES if self.template_vars[n].get()]
        mode = self.output_mode.get()
        if mode == OUTPUT_MODE_SELECT and not selected:
            return None
        return {"mode": mode, "templates": selected}

    def _build_case_upload(self, parent):
        self.case_frame = tk.Frame(parent, bg=C["card"])
        tk.Label(
            self.case_frame,
            text="同一案件可添加 1 个或多个 PDF；默认按综合文档解析",
            font=self._fonts["cap"],
            fg=C["secondary"],
            bg=C["card"],
            wraplength=420,
            justify="left",
        ).pack(anchor="w")
        hdr = tk.Frame(self.case_frame, bg=C["card"])
        hdr.pack(fill=tk.X, pady=(10, 0))
        tk.Label(hdr, text="PDF 列表", font=self._fonts["cap"], fg=C["secondary"], bg=C["card"]).pack(
            side=tk.LEFT
        )
        add_btn = MacOSButton(
            hdr,
            text="＋  添加 PDF",
            command=self._add_case_pdf,
            style="soft",
            fonts=self._fonts,
        )
        add_btn.pack(side=tk.RIGHT)
        add_btn.configure(width=110)
        self.multi_list_panel = ScrollPanel(self.case_frame, height=72, colors=C)
        self.multi_list_panel.pack(fill=tk.X, pady=(6, 0))
        self.multi_list_frame = self.multi_list_panel.inner

        # 添加拖拽支持
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            # 根窗口为普通 tk.Tk，需先把 tkdnd Tcl 扩展加载进当前解释器，
            # 否则 drop_target_register 会抛 TclError: invalid command "tkdnd::drop_target"
            if not getattr(self, "_tkdnd_loaded", False):
                TkinterDnD._require(self)
                self._tkdnd_loaded = True
            # 使整个 case_frame 支持拖拽
            self.case_frame.drop_target_register(DND_FILES)
            self.case_frame.dnd_bind("<<Drop>>", self._on_drop_files)
            print("  [OK] 拖拽上传已启用")
        except ImportError:
            print("  [WARN] tkinterdnd2 未安装，拖拽上传不可用")
        except Exception as e:
            # tkdnd 原生库加载失败等：禁用拖拽但不影响主流程
            print(f"  [WARN] 拖拽上传初始化失败，已禁用（可用「选择文件」按钮）：{e}")

    def _build_batch_upload(self, parent):
        self.batch_frame = tk.Frame(parent, bg=C["card"])
        tk.Label(
            self.batch_frame,
            text="每个案件 1 个 PDF，分别生成至 batch_时间戳 子目录",
            font=self._fonts["cap"],
            fg=C["secondary"],
            bg=C["card"],
        ).pack(anchor="w")
        brow = tk.Frame(self.batch_frame, bg=C["card"])
        brow.pack(fill=tk.X, pady=(10, 0))
        for label, cmd in (("选多个 PDF", self._pick_batch_pdfs), ("选文件夹", self._pick_batch_folder)):
            btn = MacOSButton(brow, text=label, command=cmd, style="soft", fonts=self._fonts)
            btn.pack(side=tk.LEFT, padx=(0, 8))
            btn.configure(width=108)
        self.batch_files_var = tk.StringVar(value="未选择")
        tk.Label(
            self.batch_frame,
            textvariable=self.batch_files_var,
            font=self._fonts["cap"],
            fg=C["tertiary"],
            bg=C["card"],
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        self.batch_paths = []
        self.batch_list_panel = ScrollPanel(self.batch_frame, height=96, colors=C)
        self.batch_list_panel.pack(fill=tk.X, pady=(6, 0))
        self.batch_queue_frame = self.batch_list_panel.inner

    def _on_upload_mode_changed(self):
        mode = self.upload_mode.get()
        for fr in (self.case_frame, self.batch_frame):
            fr.pack_forget()
        if mode == "case":
            self.case_frame.pack(fill=tk.X)
        else:
            self.batch_frame.pack(fill=tk.X)
        self._fit_window()

    def _on_full_archive_changed(self):
        """V4 完整归档开关切换"""
        if self.full_archive_enabled.get():
            self.case_type_frame.pack(fill=tk.X, pady=(8, 0))
            if hasattr(self, "output_mode_frame"):
                self.output_mode_frame.pack_forget()
            if hasattr(self, "template_pick_frame"):
                self.template_pick_frame.pack_forget()
            if hasattr(self, "output_full_archive_hint"):
                self.output_full_archive_hint.pack(fill=tk.X, pady=(10, 0))
        else:
            self.case_type_frame.pack_forget()
            if hasattr(self, "output_full_archive_hint"):
                self.output_full_archive_hint.pack_forget()
            self._on_output_mode_changed()
        self._fit_window()

    def _refresh_multi_list(self):
        for w in self.multi_list_frame.winfo_children():
            w.destroy()
        # 单文件：按综合卷处理，无需选类型；多文件：每份可选材料种类
        multi = len(self.multi_files) > 1
        for i, item in enumerate(self.multi_files):
            row = tk.Frame(
                self.multi_list_frame,
                bg=C["input"],
                highlightbackground=C["border"],
                highlightthickness=1,
            )
            row.pack(fill=tk.X, pady=2, padx=2)
            inner = tk.Frame(row, bg=C["input"])
            inner.pack(fill=tk.X, padx=10, pady=8)

            # 【布局修复】移除按钮移到左侧，优化紧凑布局
            rm = MacOSButton(
                inner,
                text="移除",
                command=lambda idx=i: self._remove_multi_pdf(idx),
                style="danger_soft",
                fonts=self._fonts,
            )
            rm.configure(width=56)
            rm.pack(side=tk.RIGHT, padx=(6, 0))

            if multi:
                var = tk.StringVar(
                    value=DOC_TYPE_LABELS.get(item["doc_type"], item["doc_type"])
                )
                cb = ttk.Combobox(
                    inner,
                    textvariable=var,
                    values=list(DOC_TYPE_LABELS.values()),
                    width=12,
                    state="readonly",
                    font=self._fonts["cap"],
                    style="Archive.TCombobox",
                )
                cb.pack(side=tk.RIGHT, padx=(6, 0))
                label_to_key = {v: k for k, v in DOC_TYPE_LABELS.items()}
                cb.bind(
                    "<<ComboboxSelected>>",
                    lambda e, idx=i, v=var, m=label_to_key: self._set_multi_type(
                        idx, m.get(v.get(), DOC_TYPE_DEFAULT)
                    ),
                )

            name = os.path.basename(item["path"])
            tk.Label(
                inner,
                text=name[:28] + ("…" if len(name) > 28 else ""),
                font=self._fonts["cap"],
                fg=C["text"],
                bg=C["input"],
                anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 单文件场景提示其按综合件解析
        if self.multi_files and not multi:
            tk.Label(
                self.multi_list_frame,
                text="单份文件将按「综合卷」自动切分；如需按材料种类归位，请再添加文件",
                font=self._fonts["cap"],
                fg=C["tertiary"],
                bg=C["card"],
                wraplength=300,
                justify="left",
            ).pack(anchor="w", pady=(4, 0))
        self._fit_window()

    def _set_multi_type(self, idx, doc_type):
        if 0 <= idx < len(self.multi_files):
            self.multi_files[idx]["doc_type"] = doc_type

    def _remove_multi_pdf(self, idx):
        if 0 <= idx < len(self.multi_files):
            self.multi_files.pop(idx)
            self._refresh_multi_list()

    def _add_case_pdf(self):
        paths = filedialog.askopenfilenames(title="选择案件 PDF", filetypes=[("PDF", "*.pdf")])
        for p in paths:
            if not p:
                continue
            # 默认按综合卷解析；多文件时用户可在列表中改材料种类
            self.multi_files.append({
                "path": p,
                "doc_type": DOC_TYPE_DEFAULT,
            })
        self._refresh_multi_list()
        if self.multi_files:
            self.status_var.set(f"📄  个案已选 {len(self.multi_files)} 个 PDF")
            if len(self.multi_files) == 1:
                try:
                    from archive_ocr import get_pdf_page_count

                    n = get_pdf_page_count(self.multi_files[0]["path"])
                    if n > 0:
                        self.max_pages.set(n)
                except Exception:
                    pass

    def _on_drop_files(self, event):
        """处理拖拽上传的文件"""
        import re

        # 解析拖拽的文件路径
        data = event.data
        # Windows 可能使用大括号包裹多个文件
        files = re.findall(r'\{([^}]*)\}|([^{}]+)', data)
        dropped_files = []
        for match in files:
            path = match[0] if match[0] else match[1]
            if path.lower().endswith('.pdf'):
                dropped_files.append(path)

        for path in dropped_files:
            if path and os.path.exists(path):
                self.multi_files.append({
                    "path": path,
                    "doc_type": DOC_TYPE_DEFAULT,
                })
                self._log(f"拖拽添加: {os.path.basename(path)}")

        self._refresh_multi_list()
        if self.multi_files:
            self.status_var.set(f"📄  个案已选 {len(self.multi_files)} 个 PDF")
            if len(self.multi_files) == 1:
                try:
                    from archive_ocr import get_pdf_page_count
                    n = get_pdf_page_count(self.multi_files[0]["path"])
                    if n > 0:
                        self.max_pages.set(n)
                except Exception:
                    pass

    def _pick_batch_pdfs(self):
        paths = filedialog.askopenfilenames(title="批量选择 PDF", filetypes=[("PDF", "*.pdf")])
        if paths:
            for p in paths:
                if p and p not in self.batch_paths:
                    self.batch_paths.append(p)
            self._update_batch_count()
            self._refresh_batch_queue()

    def _pick_batch_folder(self):
        folder = filedialog.askdirectory(title="选择含 PDF 的文件夹")
        if folder:
            pdfs = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        pdfs.append(os.path.join(root, f))
            pdfs.sort()
            self.batch_paths = pdfs
            self._update_batch_count()
            self._refresh_batch_queue()

    def _update_batch_count(self):
        n = len(self.batch_paths)
        self.batch_files_var.set(f"已选 {n} 个 PDF" if n else "未选择")

    def _remove_batch_pdf(self, idx):
        if 0 <= idx < len(self.batch_paths):
            self.batch_paths.pop(idx)
            self._update_batch_count()
            self._refresh_batch_queue()

    def _refresh_batch_queue(self):
        for w in self.batch_queue_frame.winfo_children():
            w.destroy()
        if not self.batch_paths:
            self._fit_window()
            return
        for i, p in enumerate(self.batch_paths):
            row = tk.Frame(
                self.batch_queue_frame,
                bg=C["input"],
                highlightbackground=C["border"],
                highlightthickness=1,
            )
            row.pack(fill=tk.X, pady=2, padx=2)
            inner = tk.Frame(row, bg=C["input"])
            inner.pack(fill=tk.X, padx=10, pady=8)
            name = os.path.basename(p)
            tk.Label(
                inner,
                text=f"{i + 1}. {name[:40]}{'…' if len(name) > 40 else ''}",
                font=self._fonts["cap"],
                fg=C["text"],
                bg=C["input"],
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            rm = MacOSButton(
                inner,
                text="移除",
                command=lambda idx=i: self._remove_batch_pdf(idx),
                style="danger_soft",
                fonts=self._fonts,
            )
            rm.pack(side=tk.RIGHT)
            rm.configure(width=56)
        self._fit_window()

    def _select_engine(self, engine: str):
        self.ocr_engine.set(engine)
        self._on_engine_changed()

    def _on_engine_changed(self, initial=False):
        eng = self.ocr_engine.get()
        if eng == "mineru":
            self.mineru_path_frame.pack(fill=tk.X, pady=(0, 0))
            self.ocr_hint.configure(
                text="💡 本机 MinerU + GPU；首次较慢，可填 mineru.exe 全路径"
            )
        else:
            self.mineru_path_frame.pack_forget()
            if eng == "mineru_api":
                self.ocr_hint.configure(
                    text="💡 MinerU 云端精准解析（mineru.net）；Token 见 config 或桌面 token 文件"
                )
            else:
                self.ocr_hint.configure(
                    text="💡 百度云 OCR；0=全部页。注意每日 API 额度"
                )
        if not initial:
            apply_ocr_engine(
                eng,
                mineru_cli_path=self.mineru_cli_path.get(),
                max_pages=self._safe_max_pages(),
            )
            self._refresh_status()
        self._fit_window()

    def _browse_mineru(self):
        p = filedialog.askopenfilename(
            title="选择 mineru.exe",
            filetypes=[("mineru", "mineru.exe"), ("可执行文件", "*.exe")],
        )
        if p:
            self.mineru_cli_path.set(p)
            apply_ocr_engine(
                self.ocr_engine.get(),
                mineru_cli_path=p,
                max_pages=self._safe_max_pages(),
            )
            self._refresh_status()

    def _safe_max_pages(self) -> int:
        try:
            return int(self.max_pages.get())
        except (TypeError, ValueError, tk.TclError):
            return 0

    def _persist_prefs(self):
        apply_ocr_engine(
            self.ocr_engine.get(),
            mineru_cli_path=self.mineru_cli_path.get(),
            max_pages=self._safe_max_pages(),
        )

    def _refresh_status(self):
        msg = config_status_message(self.ocr_engine.get())
        if config_is_ready(self.ocr_engine.get()):
            self.status_var.set(f"🟢  {msg}")
        else:
            self.status_var.set(f"🟠  {msg}")

    def _show_log_popup(self):
        """开始处理时弹出日志窗口"""
        if self._macos_log_popup:
            try:
                self._macos_log_popup.show()
            except Exception:
                pass

    def _hide_log_popup(self):
        """完成后收回日志窗口"""
        if self._macos_log_popup:
            try:
                self._macos_log_popup.hide()
            except Exception:
                pass

    def _clear_log(self):
        if self._macos_log_popup:
            self._macos_log_popup.clear()

    def _log(self, msg):
        """线程安全：后台 worker 通过 after 回主线程写日志弹窗"""
        print(msg)  # 始终输出到控制台便于调试
        if threading.current_thread() is threading.main_thread():
            self._popup_log(msg)
        else:
            self.after(0, lambda m=msg: self._popup_log(m))

    def _popup_log(self, msg):
        if self._macos_log_popup:
            self._macos_log_popup.log(msg)

    def _open_outputs(self):
        out = os.path.join(get_app_dir(), "outputs")
        os.makedirs(out, exist_ok=True)
        os.startfile(out)

    def _open_settings(self):
        def _on_settings_saved(cfg):
            self.ocr_engine.set(get_ocr_engine(cfg))
            self._on_engine_changed(initial=True)
            self._refresh_status()

        open_settings_dialog(
            self,
            C,
            self._fonts,
            on_saved=_on_settings_saved,
        )

    def _open_mineru_doc(self):
        for doc in (
            os.path.join(get_app_dir(), "MINERU_V2_SETUP.md"),
            os.path.join(os.path.dirname(__file__), "MINERU_V2_SETUP.md"),
            os.path.join(get_app_dir(), "OCR_PACKAGING.md"),
        ):
            if os.path.isfile(doc):
                os.startfile(doc)
                return
        messagebox.showinfo("说明", "请查看 MINERU_V2_SETUP.md / OCR_PACKAGING.md")

    def _start(self):
        if self._running:
            return
        mode = self.upload_mode.get()

        # V4 完整归档检查
        if self.full_archive_enabled.get():
            if not self.multi_files:
                messagebox.showerror("提示", "请添加至少一个 PDF")
                return
            for item in self.multi_files:
                if not os.path.isfile(item["path"]):
                    messagebox.showerror("提示", f"PDF 文件无效: {item['path']}")
                    return

            case_type = self.case_type.get()
            self._run_full_archive(self.multi_files, case_type)
            return

        # V3 原流程
        try:
            self._persist_prefs()
        except Exception as e:
            title, message = get_friendly_error(str(e))
            messagebox.showerror(title, message)
            return
        eng = self.ocr_engine.get()
        if not config_is_ready(eng):
            title, message = get_friendly_error("OCR配置未完成")
            messagebox.showerror(title, message)
            return

        if mode == "case":
            if not self.multi_files:
                messagebox.showerror("提示", "请添加至少一个 PDF")
                return
            out_opts = self._get_output_options()
            if out_opts is None:
                messagebox.showerror("提示", "请至少勾选一份输出文书")
                return
            if len(self.multi_files) == 1:
                pdf = self.multi_files[0]["path"]
                if not os.path.isfile(pdf):
                    messagebox.showerror("提示", "PDF 文件无效")
                    return
                self._run_worker(
                    lambda: process_archive(
                        pdf,
                        max_pages=self._safe_max_pages(),
                        log=self._log,
                        output_options=out_opts,
                    )
                )
            else:
                types = {f["doc_type"] for f in self.multi_files}
                only_default = types <= {DOC_TYPE_DEFAULT}
                if not only_default and "judgment" not in types and "execution" not in types:
                    messagebox.showerror(
                        "提示",
                        "多文件个案至少需要一份判决书或执行裁定书，"
                        "或将全部文件设为「默认（综合文档）」",
                    )
                    return
                sources = [
                    DocumentSource(path=f["path"], doc_type=f["doc_type"])
                    for f in self.multi_files
                ]
                self._run_worker(
                    lambda: process_archive_sources(
                        sources,
                        max_pages=self._safe_max_pages(),
                        log=self._log,
                        output_options=out_opts,
                    )
                )
        else:
            if not self.batch_paths:
                messagebox.showerror("提示", "请选择批量 PDF 或文件夹")
                return
            out_opts = self._get_output_options()
            if out_opts is None:
                messagebox.showerror("提示", "请至少勾选一份输出文书")
                return
            self._cancel_batch = False
            self._run_worker(self._run_batch)

    def _run_worker(self, fn):
        self._running = True
        self.run_btn.set_state(False)
        self._clear_log()
        self._show_log_popup()  # 开始：弹出日志窗口

        labels = {
            "mineru": "MinerU 本地解析",
            "mineru_api": "MinerU API 解析",
            "baidu": "百度 OCR",
        }
        label = labels.get(self.ocr_engine.get(), "OCR")
        self.status_var.set(f"⏳  {label}…")

        def worker():
            try:
                r = fn()
                self.after(0, lambda res=r: self._on_done(res))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._on_done({"success": False, "error": msg}))

        threading.Thread(target=worker, daemon=True).start()

    def _set_archive_progress(self, value: float):
        """线程安全更新完整归档进度条（0~100）"""
        try:
            self.after(0, lambda v=value: self.archive_progress.set(v))
        except Exception:
            pass

    def _make_progress_log(self):
        """包装 _log：据 analyze 阶段标记 [1/4]..[4/4] 驱动进度条真实跳动，
        避免 OCR 耗时阶段进度条假死。analyze 阶段映射到 10~60%。"""
        orig_log = self._log
        stage_to_pct = {"[1/4]": 10, "[2/4]": 46, "[3/4]": 54, "[4/4]": 60}

        def _log(msg):
            orig_log(msg)
            for marker, pct in stage_to_pct.items():
                if marker in msg:
                    self._set_archive_progress(pct)
                    break

        return _log

    def _run_full_archive(self, files, case_type: str):
        """执行完整归档流程（V4 两阶段；路径 A 单卷 / 路径 B 多文件）

        两阶段流程设计（T-801）：
        - 阶段1（analyze）: analyze_archive → 生成 doc_spans + missing_items
        - 人工闸门: 缺失项确认对话框（用户补充或跳过）
        - 阶段2（assemble）: assemble_archive → 拼装完整归档 PDF

        架构优势：
        - analyze 与 assemble 可独立调用
        - 支持脚本验收和自动化测试
        - 人工干预在两阶段之间，不影响核心流程
        """
        try:
            self._persist_prefs()
        except Exception as e:
            title, message = get_friendly_error(str(e))
            messagebox.showerror(title, message)
            return

        eng = self.ocr_engine.get()
        if not config_is_ready(eng):
            title, message = get_friendly_error("OCR配置未完成")
            messagebox.showerror(title, message)
            return

        def worker():
            try:
                self._set_archive_progress(15)
                config = load_config()
                sources = [
                    DocumentSource(path=f["path"], doc_type=f["doc_type"])
                    for f in files
                ]
                progress_log = self._make_progress_log()
                analysis = analyze_archive(
                    case_type, sources=sources, config=config, log=progress_log
                )
                primary = analysis.original_pdf or files[0]["path"]
                self._set_archive_progress(50)

                self.after(0, lambda a=analysis, p=primary: self._on_analyze_done(a, p, case_type))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._on_done({"success": False, "error": msg}))

        # 设置 _running 状态并弹出日志窗口
        self._running = True
        self.run_btn.set_state(False)
        self._clear_log()
        self._show_log_popup()  # 开始：弹出日志窗口
        self.status_var.set("⏳  完整归档…")
        self._set_archive_progress(5)

        threading.Thread(target=worker, daemon=True).start()

    def _on_analyze_done(self, analysis, pdf: str, case_type: str):
        """analyze 完成后的回调"""
        low = getattr(analysis, "low_confidence_items", None) or []
        if low:
            hint = f"⚠ 有 {len(low)} 段材料识别置信度较低，生成前请知悉（详见运行日志）。"
            self._low_conf_hint.config(text=hint)
            for item in low[:5]:
                self._log(
                    f"  低置信 seq{item.get('catalog_seq')} "
                    f"页{item.get('pages')} conf={item.get('confidence', 0):.2f}"
                )
        else:
            self._low_conf_hint.config(text="")

        # 先让用户预览/调整文书归属与顺序，再进入缺失确认
        self._show_order_dialog(analysis, pdf, case_type)

    def _proceed_after_order(self, analysis, pdf: str, case_type: str):
        """文书顺序调整后：进入缺失确认或直接拼装"""
        if analysis.missing_items:
            self._show_missing_dialog(analysis, pdf, case_type)
        else:
            self._do_assemble(analysis, pdf, case_type, supplements={}, skipped=[])

    def _show_order_dialog(self, analysis, pdf: str, case_type: str):
        """文书预览与手动调整对话框：可改目录归属(seq)、同列表上下移。

        - 上移/下移：调整文书在列表中的相对顺序（同槽内据此决定插入次序）
        - 目录归属：下拉选择目标目录项（仅正文槽位），用于纠正识别错误
        确认后重排 doc_id 并重算缺失清单，再进入缺失确认。
        """
        import archive_catalog as ac
        from document_segmenter import DOC_TYPE_LABELS

        units = list(analysis.doc_spans or [])
        if not units:
            self._proceed_after_order(analysis, pdf, case_type)
            return

        # 按当前归属与页序排序后展示
        units.sort(key=lambda u: (getattr(u, "catalog_seq", 0) or 0,
                                  getattr(u, "doc_id", 0)))

        catalog = ac.get_catalog(case_type)
        # 可选目录归属：排除卷首/卷末系统模板项
        back = set(ac.get_back_system_seqs(case_type))
        seq_options = [
            (it.seq, f"seq{it.seq} {it.name}")
            for it in catalog
            if it.source != "system" and it.seq not in {0, 1} and it.seq not in back
        ]
        label_to_seq = {lbl: seq for seq, lbl in seq_options}
        seq_to_label = {seq: lbl for seq, lbl in seq_options}
        option_labels = [lbl for _, lbl in seq_options]

        dlg = tk.Toplevel(self)
        dlg.title("文书顺序与归属调整")
        dlg.geometry("720x520")
        dlg.minsize(600, 400)
        dlg.transient(self)
        dlg.grab_set()
        dlg.protocol(
            "WM_DELETE_WINDOW",
            lambda: (dlg.destroy(), self._cancel_archive_run("已取消完整归档")),
        )

        tk.Label(
            dlg,
            text="可调整每份文书的目录归属及顺序（上移/下移）。无需改动可直接「确认」。",
            font=("Microsoft YaHei UI", 10),
            wraplength=680,
            justify="left",
        ).pack(pady=10, padx=12, anchor="w")

        outer = tk.Frame(dlg)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas)
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 行状态：保存每行的 unit 引用与归属选择变量；row_order 决定最终次序
        rows = []  # [{"unit":u, "seq_var":StringVar}]
        for u in units:
            cur_seq = getattr(u, "catalog_seq", None)
            seq_var = tk.StringVar(value=seq_to_label.get(cur_seq, option_labels[0] if option_labels else ""))
            rows.append({"unit": u, "seq_var": seq_var})

        def render():
            for w in frame.winfo_children():
                w.destroy()
            headers = ["顺序", "页段", "识别类型", "目录归属", "操作"]
            for c, h in enumerate(headers):
                tk.Label(frame, text=h, font=("Microsoft YaHei UI", 9, "bold")).grid(
                    row=0, column=c, padx=5, pady=5, sticky="w")
            # 统计同一目录归属下的文书份数，>1 时编号区分（A 方案 + 仅重复时编号）
            def _cur_seq(rr):
                return label_to_seq.get(rr["seq_var"].get())
            seq_counts = {}
            for rr in rows:
                s = _cur_seq(rr)
                seq_counts[s] = seq_counts.get(s, 0) + 1
            seq_seen = {}

            for idx, r in enumerate(rows):
                u = r["unit"]
                tk.Label(frame, text=str(idx + 1)).grid(row=idx + 1, column=0, padx=5, pady=2)
                src = os.path.basename(getattr(u, "source_path", "") or pdf)
                pages = u.end_page - u.start_page + 1
                # 1-based 页码，显示为「第X–Y页（N页）」
                page_text = (
                    f"{src} 第{u.start_page + 1}–{u.end_page + 1}页（{pages}页）"
                )
                tk.Label(frame, text=page_text).grid(
                    row=idx + 1, column=1, padx=5, pady=2, sticky="w")
                tlabel = DOC_TYPE_LABELS.get(getattr(u, "doc_type", ""), getattr(u, "doc_type", ""))
                s = _cur_seq(r)
                seq_seen[s] = seq_seen.get(s, 0) + 1
                if seq_counts.get(s, 0) > 1:
                    tlabel = f"{tlabel}（第{seq_seen[s]}份）"
                tk.Label(frame, text=tlabel).grid(row=idx + 1, column=2, padx=5, pady=2, sticky="w")
                cb = ttk.Combobox(frame, textvariable=r["seq_var"], values=option_labels,
                                  state="readonly", width=22)
                cb.grid(row=idx + 1, column=3, padx=5, pady=2)
                # 改归属后重渲染，刷新「第N份」编号
                cb.bind("<<ComboboxSelected>>", lambda e: render())
                op = tk.Frame(frame)
                op.grid(row=idx + 1, column=4, padx=5, pady=2)
                tk.Button(op, text="↑", width=2, command=lambda i=idx: move(i, -1)).pack(side=tk.LEFT)
                tk.Button(op, text="↓", width=2, command=lambda i=idx: move(i, 1)).pack(side=tk.LEFT)
                tk.Button(
                    op, text="预览", width=4,
                    command=lambda uu=u: self._preview_doc_page(
                        getattr(uu, "source_path", "") or pdf, uu.start_page
                    ),
                ).pack(side=tk.LEFT, padx=(4, 0))

        def move(i, delta):
            j = i + delta
            if 0 <= j < len(rows):
                rows[i], rows[j] = rows[j], rows[i]
                render()

        render()

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=10)

        def on_confirm():
            # 应用归属变更 + 按列表顺序重排 doc_id
            for new_id, r in enumerate(rows):
                u = r["unit"]
                lbl = r["seq_var"].get()
                if lbl in label_to_seq:
                    u.catalog_seq = label_to_seq[lbl]
                u.doc_id = new_id
            analysis.doc_spans = [r["unit"] for r in rows]
            recompute_found_and_missing(analysis)
            self._log(f"文书归属调整完成：{len(analysis.doc_spans)} 份，"
                      f"缺失 {len(analysis.missing_items)} 项")
            dlg.destroy()
            self._proceed_after_order(analysis, pdf, case_type)

        def on_skip():
            dlg.destroy()
            self._proceed_after_order(analysis, pdf, case_type)

        tk.Button(btn_frame, text="确认调整并继续", command=on_confirm, width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="不调整，直接继续", command=on_skip, width=16).pack(side=tk.LEFT, padx=5)

    def _show_missing_dialog(self, analysis, pdf: str, case_type: str):
        """显示缺失项确认对话框"""
        # 创建对话框窗口
        dlg = tk.Toplevel(self)
        dlg.title("确认缺失项")
        dlg.geometry("640x480")
        dlg.minsize(520, 360)
        dlg.transient(self)
        dlg.grab_set()
        dlg.protocol(
            "WM_DELETE_WINDOW",
            lambda: (dlg.destroy(), self._cancel_archive_run("已取消完整归档")),
        )

        tk.Label(
            dlg,
            text="以下材料未找到，请选择「补充上传」或「跳过」：",
            font=("Microsoft YaHei UI", 10),
            wraplength=580,
            justify="left",
        ).pack(pady=10, padx=12, anchor="w")

        low = getattr(analysis, "low_confidence_items", None) or []
        if low:
            tk.Label(
                dlg,
                text=f"提示：另有 {len(low)} 段 OCR 切分置信度较低，将按当前结果生成 PDF。",
                font=("Microsoft YaHei UI", 9),
                fg="#F79009",
                wraplength=580,
                justify="left",
            ).pack(pady=(0, 8), padx=12, anchor="w")

        # 缺失项列表（可滚动）
        outer = tk.Frame(dlg)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas)
        frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 表头
        headers = ["序号", "名称", "补充文件（留空=跳过）"]
        for i, h in enumerate(headers):
            tk.Label(frame, text=h, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=i, padx=5, pady=5, sticky="w")

        # 缺失项行：每行内联「选择文件」按钮 + 已选文件名（替代连续弹窗）
        self._missing_files = {}  # {seq: [file_paths]}
        file_labels = {}  # {seq: Label}

        def pick_files(seq, item_name):
            picked = filedialog.askopenfilenames(
                title=f"补充 {item_name}（序号{seq}，可多选）",
                filetypes=[
                    ("PDF文件", "*.pdf"),
                    ("图片文件", "*.jpg;*.jpeg;*.png;*.bmp"),
                    ("所有文件", "*.*"),
                ],
            )
            paths = list(picked) if picked else []
            if paths:
                self._missing_files.setdefault(seq, [])
                self._missing_files[seq].extend(paths)
            names = self._missing_files.get(seq, [])
            file_labels[seq].config(
                text=("、".join(os.path.basename(p) for p in names) if names else "（未选，跳过）")
            )

        def clear_files(seq):
            self._missing_files[seq] = []
            file_labels[seq].config(text="（未选，跳过）")

        for i, item in enumerate(analysis.missing_items, 1):
            seq = item["seq"]
            self._missing_files[seq] = []
            tk.Label(frame, text=str(seq)).grid(row=i, column=0, padx=5, pady=2, sticky="w")
            tk.Label(frame, text=item["name"]).grid(row=i, column=1, padx=5, pady=2, sticky="w")

            act = tk.Frame(frame)
            act.grid(row=i, column=2, padx=5, pady=2, sticky="w")
            tk.Button(act, text="选择文件", width=8,
                      command=lambda s=seq, n=item["name"]: pick_files(s, n)).pack(side=tk.LEFT)
            tk.Button(act, text="清除", width=5,
                      command=lambda s=seq: clear_files(s)).pack(side=tk.LEFT, padx=(4, 6))
            lbl = tk.Label(act, text="（未选，跳过）", fg="#667085",
                           font=("Microsoft YaHei UI", 8), wraplength=240, justify="left")
            lbl.pack(side=tk.LEFT)
            file_labels[seq] = lbl

        # 底部按钮
        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=10)

        def on_confirm():
            supplements = {s: f for s, f in self._missing_files.items() if f}
            skipped = [item["seq"] for item in analysis.missing_items
                       if not self._missing_files.get(item["seq"])]
            for s, f in supplements.items():
                names = ", ".join(os.path.basename(p) for p in f)
                self._log(f"用户补充 seq{s}（{len(f)} 个）: {names}")
            if skipped:
                self._log(f"跳过缺失项: {skipped}")
            dlg.destroy()
            self._do_assemble(
                analysis, pdf, case_type,
                supplements=supplements,
                skipped=skipped,
            )

        def on_skip_all():
            skipped = [item["seq"] for item in analysis.missing_items]
            dlg.destroy()
            self._do_assemble(analysis, pdf, case_type, supplements={}, skipped=skipped)

        tk.Button(btn_frame, text="确认并生成归档 PDF", command=on_confirm, width=20).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="全部跳过", command=on_skip_all, width=15).pack(side=tk.LEFT, padx=5)

    def _collect_archive_outputs(self, case_dir: str, analysis):
        """把 5 份系统 docx 收拢进归档文件夹，并清理分析临时目录。

        目标：归档文件夹内最终只剩「完整归档 PDF + 5 份 docx 表格」。
        """
        import shutil

        analyze_dirs = set()
        for _name, src in (getattr(analysis, "generated_templates", None) or {}).items():
            if not src or not os.path.isfile(src):
                continue
            src_dir = os.path.dirname(os.path.abspath(src))
            if os.path.basename(src_dir).startswith("_analyze_"):
                analyze_dirs.add(src_dir)
            dst = os.path.join(case_dir, os.path.basename(src))
            try:
                if os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copy2(src, dst)
            except Exception as e:
                self._log(f"[WARN] 收拢模板失败 {os.path.basename(src)}: {e}")
        # 删除一次性分析临时目录（含残留 *_tmp.pdf）
        for d in analyze_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _do_assemble(
        self,
        analysis,
        pdf: str,
        case_type: str,
        *,
        supplements: Optional[Dict[int, List[str]]] = None,
        supplement_files: Optional[List[str]] = None,
        skipped: Optional[List[int]] = None,
    ):
        """执行 assemble 阶段"""
        self.status_var.set("⏳  拼装归档 PDF…")
        self._set_archive_progress(65)
        order_mode = self.archive_order_mode.get()

        self._last_analysis = analysis

        def worker():
            try:
                config = load_config()
                config.setdefault("archive", {})["order_mode"] = order_mode
                base_name = os.path.splitext(os.path.basename(pdf))[0]
                # 每个案件输出到独立文件夹，最终只保留：完整归档 PDF + 5 份 docx 表格
                case_dir = os.path.join(get_outputs_dir(), f"{base_name}_完整归档")
                os.makedirs(case_dir, exist_ok=True)
                output_pdf = os.path.join(case_dir, f"{base_name}_完整归档.pdf")

                result = assemble_archive(
                    analysis,
                    output_pdf,
                    supplements=supplements,
                    supplement_files=supplement_files,
                    skipped=skipped or [],
                    config=config,
                    log=self._log,
                )

                if result.success:
                    self._collect_archive_outputs(case_dir, analysis)

                self.after(0, lambda res=result: self._on_assemble_done(res))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._on_assemble_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _preview_doc_page(self, source_path: str, page_idx: int):
        """用 PyMuPDF 渲染指定 PDF 页为图片并弹窗预览，便于核对切分归属。"""
        if not source_path or not os.path.isfile(source_path):
            messagebox.showwarning("预览", f"找不到源文件：\n{source_path}")
            return
        try:
            import base64
            import fitz
        except ImportError:
            messagebox.showwarning("预览", "未安装 PyMuPDF，无法预览。")
            return
        try:
            doc = fitz.open(source_path)
            if page_idx < 0 or page_idx >= doc.page_count:
                doc.close()
                messagebox.showwarning("预览", f"页码超出范围：{page_idx}")
                return
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            png = pix.tobytes("png")
            doc.close()
        except Exception as e:
            messagebox.showwarning("预览", f"渲染失败：{e}")
            return

        win = tk.Toplevel(self)
        win.title(f"预览 {os.path.basename(source_path)} 第 {page_idx + 1} 页")
        win.transient(self)
        try:
            img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        except Exception as e:
            win.destroy()
            messagebox.showwarning("预览", f"图片加载失败：{e}")
            return
        # 保存引用，避免被垃圾回收
        win._preview_img = img
        cw, ch = min(img.width(), 760), min(img.height(), 920)
        canvas = tk.Canvas(win, width=cw, height=ch, highlightthickness=0)
        vbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set, scrollregion=(0, 0, img.width(), img.height()))
        canvas.create_image(0, 0, anchor="nw", image=img)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # 居中显示并设置合理初始尺寸
        win.update_idletasks()
        win.geometry(f"{cw + 20}x{ch + 10}")
        win.resizable(True, True)

    def _cancel_archive_run(self, reason: str = "已取消"):
        """用户中途关闭对话框：恢复 UI 状态，避免界面假死。"""
        self._log(f"[CANCEL] {reason}")
        self.status_var.set(f"⏹  {reason}")
        self._set_archive_progress(0)
        self._running = False
        self.run_btn.set_state(True)
        self._hide_log_popup()  # 完成/取消：收回日志窗口

    def _on_assemble_error(self, error_msg: str):
        """assemble 异常：恢复 UI 并提示"""
        self._log(f"[ERROR] 拼装失败: {error_msg}")
        self.status_var.set("❌  归档失败")
        self._set_archive_progress(0)
        self._running = False
        self.run_btn.set_state(True)
        self._hide_log_popup()  # 完成：收回日志窗口
        messagebox.showerror("失败", f"拼装归档 PDF 失败：\n{error_msg}")

    def _on_assemble_done(self, result):
        """assemble 完成后的回调"""
        self._set_archive_progress(100 if result.success else 0)
        analysis = getattr(self, "_last_analysis", None)

        # 写结构化报告（缺失/页守恒/排序问题）→ 单独的 _reports 目录，
        # 不污染「完整归档 PDF + 5 份 docx」的成品文件夹
        report_path = None
        try:
            reports_dir = os.path.join(get_outputs_dir(), "_reports")
            os.makedirs(reports_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(result.output_pdf))[0]
            report_target = os.path.join(reports_dir, base + ".pdf")
            report_path = write_archive_report(
                analysis, result, report_target, log=self._log
            )
        except Exception as e:
            self._log(f"[WARN] 写归档报告失败: {e}")

        orig = getattr(result, "original_pages_included", 0)
        order_issues = getattr(result, "order_issues", None) or []
        missing = result.missing or []

        self._hide_log_popup()  # 完成：收回日志窗口，再弹出结果提示

        if result.success:
            self._log(f"完整归档 PDF 已生成: {result.output_pdf} ({result.page_count} 页)")
            if orig:
                self._log(f"原 PDF 已纳入 {orig} 页")
            if missing:
                self._log(f"缺失/跳过项: {len(missing)} 项")
            for it in order_issues[:5]:
                self._log(f"  排序提示: {it.get('description', it)}")

            self.status_var.set("✅  归档完成")
            # 有缺失/排序问题时用警告弹窗并附明细
            if missing or order_issues:
                lines = [f"完整归档 PDF 已生成：\n{result.output_pdf}\n"]
                if missing:
                    names = "、".join(
                        str(m.get("name", m.get("seq", ""))) for m in missing[:8]
                    )
                    lines.append(f"缺失/跳过 {len(missing)} 项：{names}")
                if order_issues:
                    lines.append(f"排序待核对 {len(order_issues)} 项")
                if report_path:
                    lines.append(f"\n详见报告：{report_path}")
                messagebox.showwarning("完成（有提示）", "\n".join(lines))
            else:
                messagebox.showinfo("完成", f"完整归档 PDF 已生成：\n{result.output_pdf}")
        else:
            self.status_var.set("❌  归档失败")
            detail = []
            if orig:
                detail.append(f"源 PDF 仅纳入 {orig} 页（可能页守恒失败）")
            for it in order_issues[:5]:
                detail.append(f"排序问题: {it.get('description', it)}")
            for it in missing[:5]:
                detail.append(f"缺失: {it.get('name', it.get('seq', ''))}")
            if report_path:
                detail.append(f"详见报告: {report_path}")
            msg = "归档 PDF 生成失败" + ("\n\n" + "\n".join(detail) if detail else "")
            for line in detail:
                self._log(f"[FAIL] {line}")
            messagebox.showerror("失败", msg)
        self._running = False
        self.run_btn.set_state(True)

    def _run_batch(self):
        # 完整归档开关开启时，批量也走 V4 analyze+assemble 流水线（缺失自动跳过）
        if self.full_archive_enabled.get():
            return process_batch(
                self.batch_paths,
                max_pages=self._safe_max_pages(),
                log=self._make_progress_log(),
                cancel_check=lambda: self._cancel_batch,
                full_archive=True,
                case_type=self.case_type.get(),
            )
        out_opts = self._get_output_options()
        if out_opts is None:
            return {"success": False, "error": "请至少勾选一份输出文书"}
        return process_batch(
            self.batch_paths,
            max_pages=self._safe_max_pages(),
            log=self._log,
            cancel_check=lambda: self._cancel_batch,
            output_options=out_opts,
        )

    def _on_done(self, result):
        """处理完成回调"""
        self._hide_log_popup()  # 完成：收回日志窗口

        # 恢复按钮状态
        self._running = False
        self.run_btn.set_state(True)
        self._set_archive_progress(0)
        self._refresh_status()
        if result.get("batch_root"):
            ok = result.get("ok_count", 0)
            total = result.get("total", 0)
            if result.get("success"):
                self.status_var.set(f"✅  批量完成 {ok}/{total}")
                self._log(f"\n🎉 批量归档 {ok}/{total}")
                if messagebox.askyesno("完成", f"批量完成 {ok}/{total}，打开批次文件夹？"):
                    os.startfile(result["batch_root"])
            else:
                self.status_var.set("❌  批量失败")
                messagebox.showerror("失败", "所有案件均处理失败")
            return
        if result.get("success"):
            self.status_var.set("✅  归档完成")
            n = len(result.get("generated_files") or [])
            layout_n = len(result.get("layout_issues") or [])
            self._log(f"\n🎉 已生成 {n} 份 docx")
            if layout_n:
                self._log(f"⚠ 版式待核对 {layout_n} 项")
            if messagebox.askyesno("完成", f"已生成 {n} 份 docx，打开输出文件夹？"):
                os.startfile(result["output_dir"])
        else:
            self.status_var.set("❌  失败")
            self._log(f"\n❌ {result.get('error')}")
            title, message = get_friendly_error(result.get("error", "未知错误"))
            messagebox.showerror(title, message)


def run_cli(pdf_path, max_pages=0):
    ensure_app_dirs()
    init_config_if_missing()
    if not config_is_ready():
        print("[FAIL] 请在 config.json 或 GUI 中配置 OCR 与 DeepSeek")
        sys.exit(1)
    if not os.path.isfile(pdf_path):
        print(f"[FAIL] PDF 不存在: {pdf_path}")
        sys.exit(1)
    result = process_archive(pdf_path, max_pages=max_pages, log=print)
    if result.get("success"):
        print("\n[OK] 归档完成")
        print(f"  输出: {result['output_dir']}")
        return 0
    print(f"\n[FAIL] {result.get('error')}")
    return 1


def main():
    ArchiveApp().mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pages = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        sys.exit(run_cli(sys.argv[1], pages))
    main()
