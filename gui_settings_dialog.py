#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归档程序 — API / OCR 设置对话框"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from gui_theme import (
    C,
    Card,
    RoundedButton,
    SectionTitle,
    apply_ttk_combobox_style,
    fit_window,
    styled_entry,
    ui_fonts,
)
from settings import load_config, save_config


def open_settings_dialog(parent, colors, fonts, on_saved=None):
    """
    打开设置窗口：DeepSeek、百度 OCR、MinerU 路径与 API 地址。
    colors/fonts 与主界面一致。
    """
    C_local = colors or C
    fonts = fonts or ui_fonts(parent)
    cfg = load_config()

    win = tk.Toplevel(parent)
    win.title("API 与 OCR 设置")
    win.configure(bg=C_local["bg"])
    win.transient(parent)
    win.grab_set()
    apply_ttk_combobox_style(win)

    body = tk.Frame(win, bg=C_local["bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=4, pady=8)

    def row_entry(card_body, label, var, show=None):
        fr = tk.Frame(card_body, bg=C_local["card"])
        fr.pack(fill=tk.X, pady=4)
        tk.Label(
            fr,
            text=label,
            font=fonts["cap"],
            fg=C_local["secondary"],
            bg=C_local["card"],
            width=12,
            anchor="w",
        ).pack(side=tk.LEFT)
        wrap, e, _ = styled_entry(fr, var, colors=C_local, fonts=fonts, show=show)
        wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return e

    # DeepSeek
    ds_card = Card(body, colors=C_local, pady=(0, 10))
    SectionTitle(ds_card.body, "🤖", "DeepSeek", colors=C_local, fonts=fonts).pack(
        anchor="w", pady=(0, 8)
    )
    ds_key = tk.StringVar(value=cfg.get("deepseek", {}).get("api_key", ""))
    row_entry(ds_card.body, "API Key", ds_key, show="*")

    # 百度 OCR
    bd_card = Card(body, colors=C_local, pady=(0, 10))
    SectionTitle(bd_card.body, "☁️", "百度 OCR", colors=C_local, fonts=fonts).pack(
        anchor="w", pady=(0, 8)
    )
    bd = cfg.get("baidu_ocr", {})
    bd_app = tk.StringVar(value=bd.get("app_id", ""))
    bd_key = tk.StringVar(value=bd.get("api_key", ""))
    bd_sec = tk.StringVar(value=bd.get("secret_key", ""))
    bd_mode = tk.StringVar(value=bd.get("mode", "basic"))
    row_entry(bd_card.body, "App ID", bd_app)
    row_entry(bd_card.body, "API Key", bd_key)
    row_entry(bd_card.body, "Secret Key", bd_sec, show="*")
    mfr = tk.Frame(bd_card.body, bg=C_local["card"])
    mfr.pack(fill=tk.X, pady=4)
    tk.Label(
        mfr,
        text="识别模式",
        font=fonts["cap"],
        fg=C_local["secondary"],
        bg=C_local["card"],
        width=12,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        mfr,
        textvariable=bd_mode,
        values=("basic", "basicAccurate"),
        state="readonly",
        width=18,
        style="Archive.TCombobox",
    ).pack(side=tk.LEFT)

    # MinerU 本地
    mu_card = Card(body, colors=C_local, pady=(0, 10))
    SectionTitle(mu_card.body, "🖥️", "MinerU 本地", colors=C_local, fonts=fonts).pack(
        anchor="w", pady=(0, 8)
    )
    mu = cfg.get("mineru", {})
    mu_cli = tk.StringVar(value=mu.get("cli_path", ""))
    mu_qual = tk.StringVar(value=mu.get("quality", "ultra"))
    cli_fr = tk.Frame(mu_card.body, bg=C_local["card"])
    cli_fr.pack(fill=tk.X, pady=4)
    tk.Label(
        cli_fr,
        text="程序路径",
        font=fonts["cap"],
        fg=C_local["secondary"],
        bg=C_local["card"],
        width=12,
        anchor="w",
    ).pack(side=tk.LEFT)
    path_wrap, _, path_inner = styled_entry(cli_fr, mu_cli, colors=C_local, fonts=fonts)
    path_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def browse_mineru():
        p = filedialog.askopenfilename(
            title="选择 mineru.exe",
            filetypes=[("mineru", "mineru.exe"), ("可执行文件", "*.exe"), ("全部", "*.*")],
        )
        if p:
            mu_cli.set(p)

    browse = RoundedButton(
        path_inner, text="浏览…", command=browse_mineru, style="soft", fonts=fonts
    )
    browse.pack(side=tk.RIGHT, padx=(8, 0))
    browse.configure(width=72)

    qfr = tk.Frame(mu_card.body, bg=C_local["card"])
    qfr.pack(fill=tk.X, pady=4)
    tk.Label(
        qfr,
        text="精细度",
        font=fonts["cap"],
        fg=C_local["secondary"],
        bg=C_local["card"],
        width=12,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        qfr,
        textvariable=mu_qual,
        values=("ultra", "high", "fast"),
        state="readonly",
        width=12,
        style="Archive.TCombobox",
    ).pack(side=tk.LEFT)

    # MinerU API
    api_card = Card(body, colors=C_local, pady=(0, 10))
    SectionTitle(api_card.body, "🌐", "MinerU API", colors=C_local, fonts=fonts).pack(
        anchor="w", pady=(0, 8)
    )
    mu_token = tk.StringVar(value=mu.get("api_token", ""))
    mu_model = tk.StringVar(value=mu.get("api_model_version", "vlm"))
    row_entry(api_card.body, "API Token", mu_token, show="*")
    tk.Label(
        api_card.body,
        text="留空则自动读取桌面 minerU API TOKEN.txt",
        font=fonts["cap"],
        fg=C_local["tertiary"],
        bg=C_local["card"],
        wraplength=400,
        justify="left",
    ).pack(anchor="w", pady=(0, 6))
    mfr2 = tk.Frame(api_card.body, bg=C_local["card"])
    mfr2.pack(fill=tk.X, pady=4)
    tk.Label(
        mfr2,
        text="模型",
        font=fonts["cap"],
        fg=C_local["secondary"],
        bg=C_local["card"],
        width=12,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        mfr2,
        textvariable=mu_model,
        values=("vlm", "pipeline", "MinerU-HTML"),
        state="readonly",
        width=14,
        style="Archive.TCombobox",
    ).pack(side=tk.LEFT)

    def do_save():
        from mineru_api import normalize_mineru_api_token

        c = load_config()
        c.setdefault("deepseek", {})["api_key"] = ds_key.get().strip()
        c.setdefault("baidu_ocr", {}).update(
            {
                "app_id": bd_app.get().strip(),
                "api_key": bd_key.get().strip(),
                "secret_key": bd_sec.get().strip(),
                "mode": bd_mode.get().strip() or "basic",
            }
        )
        token = normalize_mineru_api_token(mu_token.get())
        c.setdefault("mineru", {}).update(
            {
                "cli_path": mu_cli.get().strip(),
                "quality": mu_qual.get().strip() or "ultra",
                "api_token": token,
                "api_model_version": mu_model.get().strip() or "vlm",
            }
        )
        if token:
            c.setdefault("ocr", {})["engine"] = "mineru_api"
        save_config(c)
        if on_saved:
            on_saved(c)
        messagebox.showinfo("已保存", "设置已写入 config.json", parent=win)
        win.destroy()

    def test_mineru_api():
        from mineru_api import check_mineru_api_available, normalize_mineru_api_token

        c = load_config()
        c.setdefault("mineru", {})["api_token"] = normalize_mineru_api_token(
            mu_token.get()
        )
        ok, msg = check_mineru_api_available(c)
        if ok:
            messagebox.showinfo("MinerU API", msg, parent=win)
        else:
            messagebox.showerror("MinerU API", msg, parent=win)

    def test_mineru():
        from mineru_ocr import check_mineru_available

        c = load_config()
        c.setdefault("mineru", {})["cli_path"] = mu_cli.get().strip()
        ok, msg = check_mineru_available(c)
        if ok:
            messagebox.showinfo("MinerU", msg, parent=win)
        else:
            messagebox.showerror("MinerU", msg, parent=win)

    btn_fr = tk.Frame(win, bg=C_local["bg"])
    btn_fr.pack(fill=tk.X, padx=22, pady=(4, 16))
    RoundedButton(
        btn_fr,
        text="测试 MinerU API",
        command=test_mineru_api,
        style="secondary",
        fonts=fonts,
    ).pack(side=tk.LEFT)
    RoundedButton(
        btn_fr,
        text="测试 MinerU 本地",
        command=test_mineru,
        style="secondary",
        fonts=fonts,
    ).pack(side=tk.LEFT, padx=(8, 0))
    RoundedButton(btn_fr, text="保存", command=do_save, style="primary", fonts=fonts).pack(
        side=tk.RIGHT
    )
    RoundedButton(btn_fr, text="取消", command=win.destroy, style="soft", fonts=fonts).pack(
        side=tk.RIGHT, padx=(0, 8)
    )

    fit_window(win, content=body, min_w=460, min_h=400)
