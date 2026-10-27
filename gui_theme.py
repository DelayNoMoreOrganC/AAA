#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归档程序 UI 主题：圆角卡片、彩色按钮、窗口自适应"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# 丰富柔和的配色（偏现代应用风，非工业灰）
C = {
    "bg": "#F0F4FF",
    "bg2": "#E8EEFF",
    "card": "#FFFFFF",
    "text": "#1A1F36",
    "secondary": "#5B6478",
    "tertiary": "#9AA3B5",
    "accent": "#5B5FEF",
    "accent2": "#7C5CFC",
    "accent_soft": "#EEF0FF",
    "accent_hover": "#484CE0",
    "accent_text": "#FFFFFF",
    "success": "#12B76A",
    "success_soft": "#E3FBEF",
    "warn": "#F79009",
    "warn_soft": "#FFF4E5",
    "danger": "#F04438",
    "danger_soft": "#FEECEB",
    "mineru": "#7A5AF8",
    "mineru_soft": "#F4F0FF",
    "baidu": "#2E90FA",
    "baidu_soft": "#EFF8FF",
    "teal": "#0BA5EC",
    "teal_soft": "#E0F7FE",
    "border": "#D5DBEB",
    "input": "#F8F9FC",
    "shadow": "#C8D0E7",
    "hero_from": "#6E72F2",
    "hero_to": "#9B87F5",
    "tip_bg": "#EEF0FF",
    "tip_text": "#4338CA",
}


def ui_fonts(root=None):
    """优先微软雅黑，保证中文清晰。"""
    families = ("Microsoft YaHei UI", "Segoe UI", "PingFang SC", "sans-serif")
    chosen = families[0]
    if root is not None:
        for fam in families:
            try:
                tkfont.Font(root=root, family=fam, size=10)
                chosen = fam
                break
            except tk.TclError:
                continue
    return {
        "hero": (chosen, 24, "bold"),
        "title": (chosen, 12, "bold"),
        "body": (chosen, 10),
        "body_b": (chosen, 10, "bold"),
        "cap": (chosen, 9),
        "btn": (chosen, 10, "bold"),
        "btn_sm": (chosen, 9, "bold"),
        "emoji": ("Segoe UI Emoji", 20),
        "log": ("Cascadia Mono", 9),
    }


def round_rect(cv, x1, y1, x2, y2, r, **kwargs):
    r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kwargs)


def fit_window(
    window,
    content=None,
    design_w=960,
    min_w=None,
    min_h=640,
    pad_outer=28,
    max_h=900,
):
    """类正方形窗口：固定宽度，按内容测量高度并居中。"""
    if min_w is not None:
        design_w = min_w
    try:
        window.geometry(f"{design_w}x{min_h}")
        window.update_idletasks()
    except tk.TclError:
        pass
    # 允许尽量利用屏幕高度（为任务栏/标题栏留边距），避免日志区被压缩
    try:
        screen_h = window.winfo_screenheight()
        max_h = max(max_h, screen_h - 120)
    except tk.TclError:
        pass
    if content is not None:
        content.update_idletasks()
        h = content.winfo_reqheight() + pad_outer
    else:
        window.update_idletasks()
        h = window.winfo_reqheight()
    h = min(max(h, min_h), max_h)
    w = design_w
    try:
        sw = window.winfo_screenwidth()
        sh = window.winfo_screenheight()
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 2, 0)
        window.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        window.geometry(f"{w}x{h}")
    window.minsize(int(w * 0.82), min_h - 60)


class RoundedButton(tk.Canvas):
    """圆角按钮：primary / secondary / soft / danger"""

    STYLES = {
        "primary": {
            "fill": C["accent"],
            "fill_hover": C["accent_hover"],
            "fill_disabled": "#B8BCF8",
            "fg": "#FFFFFF",
            "outline": C["accent"],
            "h": 50,
            "r": 14,
            "font_key": "btn",
        },
        "secondary": {
            "fill": C["card"],
            "fill_hover": C["accent_soft"],
            "fill_disabled": C["input"],
            "fg": C["accent"],
            "outline": C["border"],
            "h": 40,
            "r": 12,
            "font_key": "btn_sm",
        },
        "soft": {
            "fill": C["accent_soft"],
            "fill_hover": C["bg2"],
            "fill_disabled": C["input"],
            "fg": C["accent"],
            "outline": C["accent_soft"],
            "h": 38,
            "r": 12,
            "font_key": "btn_sm",
        },
        "danger_soft": {
            "fill": C["danger_soft"],
            "fill_hover": "#FDD8D6",
            "fill_disabled": C["input"],
            "fg": C["danger"],
            "outline": C["danger_soft"],
            "h": 32,
            "r": 10,
            "font_key": "btn_sm",
        },
    }

    def __init__(self, parent, text, command=None, style="primary", fonts=None, **kwargs):
        self._style_name = style
        st = self.STYLES[style]
        self._fonts = fonts or {}
        super().__init__(
            parent,
            height=st["h"],
            highlightthickness=0,
            bg=parent.cget("bg"),
            cursor="hand2",
            **kwargs,
        )
        self._text = text
        self._command = command
        self._hover = False
        self._enabled = True
        self.bind("<Configure>", self._paint)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _: self._set_hover(True))
        self.bind("<Leave>", lambda _: self._set_hover(False))

    def set_state(self, enabled: bool):
        self._enabled = enabled
        self._paint()

    def configure_text(self, text: str):
        self._text = text
        self._paint()

    def _set_hover(self, v):
        self._hover = v
        self._paint()

    def _click(self, _):
        if self._enabled and self._command:
            self._command()

    def _paint(self, _=None):
        self.delete("all")
        st = self.STYLES[self._style_name]
        w = max(self.winfo_width(), 80)
        h = self.winfo_height() or st["h"]
        r = st["r"]
        if not self._enabled:
            fill = st["fill_disabled"]
            fg = C["tertiary"]
        elif self._hover:
            fill = st["fill_hover"]
            fg = st["fg"]
        else:
            fill = st["fill"]
            fg = st["fg"]
        outline = st["outline"]
        if self._style_name == "primary":
            round_rect(self, 1, 1, w - 1, h - 1, r, fill=fill, outline=fill)
        else:
            round_rect(self, 1, 1, w - 1, h - 1, r, fill=fill, outline=outline)
        fkey = st["font_key"]
        font = self._fonts.get(fkey, ("Segoe UI", 10, "bold"))
        self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=font)


class Card(tk.Frame):
    """圆角卡片容器。"""

    def __init__(
        self,
        parent,
        colors=None,
        radius=18,
        pady=(0, 12),
        padx=0,
        autopack=True,
        fill=tk.X,
        **kwargs,
    ):
        self._colors = colors or C
        super().__init__(parent, bg=self._colors["bg"], **kwargs)
        if autopack:
            self.pack(fill=fill, padx=padx, pady=pady)
        self._radius = radius
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=self._colors["bg"], height=40)
        self.canvas.pack(fill=tk.X)
        self.body = tk.Frame(self.canvas, bg=self._colors["card"])
        self._win_id = self.canvas.create_window(14, 14, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas)
        self.body.bind("<Configure>", self._on_body)

    def _on_body(self, event):
        h = event.height + 28
        self.canvas.configure(height=max(h, 48))
        self._draw_bg()

    def _on_canvas(self, event):
        w = event.width
        self.canvas.itemconfigure(self._win_id, width=max(w - 28, 100))
        self._draw_bg()

    def _draw_bg(self):
        self.canvas.delete("cardbg")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 4 or h < 4:
            return
        round_rect(
            self.canvas,
            2,
            2,
            w - 2,
            h - 2,
            self._radius,
            fill=self._colors["card"],
            outline=self._colors["border"],
            tags="cardbg",
        )
        self.canvas.tag_lower("cardbg")


class SectionTitle(tk.Frame):
    def __init__(self, parent, icon, title, colors=None, fonts=None, **kwargs):
        colors = colors or C
        fonts = fonts or {}
        super().__init__(parent, bg=colors["card"], **kwargs)
        badge = tk.Label(
            self,
            text=icon,
            font=fonts.get("emoji", ("Segoe UI Emoji", 18)),
            bg=colors["accent_soft"],
            fg=colors["accent"],
            padx=8,
            pady=4,
        )
        badge.pack(side=tk.LEFT)
        tk.Label(
            self,
            text=title,
            font=fonts.get("title", ("Segoe UI", 12, "bold")),
            fg=colors["text"],
            bg=colors["card"],
        ).pack(side=tk.LEFT, padx=(10, 0))


class SegmentedControl(tk.Frame):
    """分段选择器（OCR 方案等）。"""

    def __init__(
        self,
        parent,
        options,
        variable,
        command=None,
        colors=None,
        fonts=None,
        vertical=False,
        **kwargs,
    ):
        self._colors = colors or C
        self._fonts = fonts or {}
        self._variable = variable
        self._command = command
        self._buttons = {}
        self._vertical = vertical
        super().__init__(parent, bg=self._colors["card"], **kwargs)
        track_h = 38 * len(options) + 12 if vertical else 46
        track = tk.Canvas(self, height=track_h, highlightthickness=0, bg=self._colors["card"])
        track.pack(fill=tk.X)
        self._track = track
        inner = tk.Frame(track, bg=self._colors["input"])
        self._inner = inner
        self._inner_id = track.create_window(4, 4, window=inner, anchor="nw")
        if vertical:
            track.bind("<Configure>", self._layout_vertical)
        else:
            track.bind("<Configure>", self._layout)

        for key, label in options:
            btn = tk.Label(
                inner,
                text=label,
                font=self._fonts.get("cap", ("Segoe UI", 9)),
                bg=self._colors["input"],
                fg=self._colors["secondary"],
                cursor="hand2",
                padx=8,
                pady=6 if vertical else 8,
            )
            if vertical:
                btn.pack(fill=tk.X, padx=2, pady=2)
            else:
                btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, pady=2)
            btn.bind("<Button-1>", lambda e, k=key: self._select(k))
            self._buttons[key] = btn
        variable.trace_add("write", lambda *_: self._refresh())
        self._refresh()

    def _layout_vertical(self, event=None):
        w = self._track.winfo_width()
        inner_h = max(38 * len(self._buttons), 38)
        self._track.configure(height=inner_h + 8)
        self._track.itemconfigure(self._inner_id, width=max(w - 8, 80))
        self._track.delete("seg_bg")
        h = inner_h + 8
        round_rect(
            self._track,
            1,
            1,
            w - 1,
            h - 1,
            12,
            fill=self._colors["input"],
            outline=self._colors["border"],
            tags="seg_bg",
        )
        self._track.tag_lower("seg_bg")

    def _layout(self, event=None):
        w = self._track.winfo_width()
        self._track.itemconfigure(self._inner_id, width=max(w - 8, 100))
        self._track.delete("seg_bg")
        h = 46
        round_rect(
            self._track,
            1,
            1,
            w - 1,
            h - 1,
            14,
            fill=self._colors["input"],
            outline=self._colors["border"],
            tags="seg_bg",
        )
        self._track.tag_lower("seg_bg")

    def _select(self, key):
        self._variable.set(key)
        if self._command:
            self._command()

    def _refresh(self):
        cur = self._variable.get()
        for key, btn in self._buttons.items():
            if key == cur:
                btn.configure(
                    bg=self._colors["card"],
                    fg=self._colors["text"],
                    font=self._fonts.get("body_b", ("Segoe UI", 10, "bold")),
                )
            else:
                btn.configure(
                    bg=self._colors["input"],
                    fg=self._colors["secondary"],
                    font=self._fonts.get("cap", ("Segoe UI", 9)),
                )


class ChipRadio(tk.Frame):
    """圆角胶囊单选。"""

    def __init__(self, parent, options, variable, command=None, colors=None, fonts=None, **kwargs):
        colors = colors or C
        fonts = fonts or {}
        super().__init__(parent, bg=colors["card"], **kwargs)
        for val, label in options:
            rb = tk.Radiobutton(
                self,
                text=label,
                variable=variable,
                value=val,
                font=fonts.get("cap", ("Segoe UI", 9)),
                bg=colors["card"],
                fg=colors["text"],
                activebackground=colors["accent_soft"],
                activeforeground=colors["accent"],
                selectcolor=colors["accent_soft"],
                indicatoron=0,
                padx=14,
                pady=6,
                borderwidth=0,
                highlightthickness=0,
                command=command,
            )
            rb.pack(side=tk.LEFT, padx=(0, 8), pady=2)


class ActionTile(tk.Frame):
    """底部快捷操作块。"""

    TILES = {
        "output": ("📂", "打开输出", C["success_soft"], C["success"]),
        "settings": ("⚙️", "详细设置", C["baidu_soft"], C["baidu"]),
        "doc": ("📘", "MinerU 说明", C["mineru_soft"], C["mineru"]),
    }

    def __init__(self, parent, tile_id, command, colors=None, fonts=None, **kwargs):
        colors = colors or C
        fonts = fonts or {}
        icon, label, bg, fg = self.TILES[tile_id]
        super().__init__(parent, bg=colors["bg"], **kwargs)
        self.canvas = tk.Canvas(self, height=72, highlightthickness=0, bg=colors["bg"], cursor="hand2")
        self.canvas.pack(fill=tk.X)
        self._bg_color = bg
        self._command = command
        self.canvas.bind("<Configure>", self._draw)
        self.canvas.bind("<Button-1>", lambda _: self._command() if self._command else None)
        self.canvas.bind("<Enter>", lambda _: self._set_hover(True))
        self.canvas.bind("<Leave>", lambda _: self._set_hover(False))
        self._hover = False
        self._icon = icon
        self._label = label
        self._fg = fg
        self._fonts = fonts

    def _set_hover(self, v):
        self._hover = v
        self._draw()

    def _draw(self, _=None):
        self.canvas.delete("all")
        w = max(self.canvas.winfo_width(), 80)
        h = 72
        fill = self._bg_color if not self._hover else C["bg2"]
        round_rect(self.canvas, 2, 2, w - 2, h - 2, 14, fill=fill, outline=C["border"])
        self.canvas.create_text(
            w // 2,
            26,
            text=self._icon,
            font=self._fonts.get("emoji", ("Segoe UI Emoji", 18)),
        )
        self.canvas.create_text(
            w // 2,
            52,
            text=self._label,
            fill=self._fg,
            font=self._fonts.get("btn_sm", ("Segoe UI", 9, "bold")),
        )


class StatusBar(tk.Frame):
    def __init__(self, parent, textvariable, colors=None, fonts=None, **kwargs):
        colors = colors or C
        fonts = fonts or {}
        super().__init__(parent, bg=colors["bg"], **kwargs)
        self.canvas = tk.Canvas(self, height=44, highlightthickness=0, bg=colors["bg"])
        self.canvas.pack(fill=tk.X)
        self._var = textvariable
        self._colors = colors
        self._fonts = fonts
        textvariable.trace_add("write", lambda *_: self._draw())
        self.canvas.bind("<Configure>", self._draw)

    def _draw(self, _=None):
        self.canvas.delete("all")
        w = max(self.canvas.winfo_width(), 100)
        h = 44
        round_rect(
            self.canvas,
            2,
            2,
            w - 2,
            h - 2,
            12,
            fill=self._colors["card"],
            outline=self._colors["border"],
        )
        self.canvas.create_text(
            16,
            h // 2,
            text=self._var.get(),
            anchor="w",
            fill=self._colors["secondary"],
            font=self._fonts.get("body", ("Segoe UI", 10)),
        )


class ScrollPanel(tk.Frame):
    """固定高度可滚动区域（文件列表等）。"""

    def __init__(self, parent, height=108, colors=None, **kwargs):
        colors = colors or C
        super().__init__(parent, bg=colors["card"], **kwargs)
        self.canvas = tk.Canvas(
            self,
            height=height,
            highlightthickness=0,
            bg=colors["card"],
            borderwidth=0,
        )
        self.scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=colors["card"])
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_inner(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win_id, width=event.width)


class HeroHeader(tk.Frame):
    """顶部渐变标题区。"""

    def __init__(
        self,
        parent,
        title,
        subtitle,
        version,
        colors=None,
        fonts=None,
        compact=False,
        **kwargs,
    ):
        colors = colors or C
        fonts = fonts or {}
        super().__init__(parent, bg=colors["bg"], **kwargs)
        self._compact = compact
        h = 72 if compact else 96
        self.canvas = tk.Canvas(self, height=h, highlightthickness=0, bg=colors["bg"])
        self.canvas.pack(fill=tk.X, padx=0, pady=(0, 8))
        self._title = title
        self._subtitle = f"{subtitle}  ·  {version}"
        self._fonts = fonts
        self._colors = colors
        self._h = h
        self.canvas.bind("<Configure>", self._draw)

    def _draw(self, _=None):
        self.canvas.delete("all")
        w = max(self.canvas.winfo_width(), 200)
        h = self._h
        round_rect(self.canvas, 2, 2, w - 2, h - 2, 16, fill=self._colors["hero_from"], outline="")
        round_rect(self.canvas, w // 3, 2, w - 2, h - 2, 16, fill=self._colors["hero_to"], outline="")
        title_y = 26 if self._compact else 34
        sub_y = 50 if self._compact else 68
        title_font = self._fonts.get("title", ("Segoe UI", 12, "bold"))
        if self._compact:
            title_font = self._fonts.get("body_b", ("Segoe UI", 10, "bold"))
        self.canvas.create_text(
            16,
            title_y,
            text="📁  " + self._title,
            anchor="w",
            fill="#FFFFFF",
            font=title_font,
        )
        self.canvas.create_text(
            16,
            sub_y,
            text=self._subtitle,
            anchor="w",
            fill="#EDE9FE",
            font=self._fonts.get("cap", ("Segoe UI", 9)),
        )


class TipBanner(tk.Frame):
    def __init__(self, parent, text, colors=None, fonts=None, **kwargs):
        colors = colors or C
        fonts = fonts or {}
        super().__init__(parent, bg=colors["bg"], **kwargs)
        cv = tk.Canvas(self, height=44, highlightthickness=0, bg=colors["bg"])
        cv.pack(fill=tk.X, padx=22, pady=(0, 10))
        self._cv = cv
        self._text = text
        self._fonts = fonts
        cv.bind("<Configure>", self._draw)

    def _draw(self, _=None):
        self._cv.delete("all")
        w = max(self._cv.winfo_width(), 100)
        round_rect(self._cv, 2, 2, w - 2, 42, 12, fill=C["tip_bg"], outline=C["border"])
        self._cv.create_text(
            16,
            22,
            text=self._text,
            anchor="w",
            fill=C["tip_text"],
            font=self._fonts.get("body", ("Segoe UI", 10)),
        )


def styled_entry(parent, textvariable, colors=None, fonts=None, **kwargs):
    colors = colors or C
    fonts = fonts or {}
    wrap = tk.Frame(parent, bg=colors["input"], highlightbackground=colors["border"], highlightthickness=1)
    inner = tk.Frame(wrap, bg=colors["input"])
    inner.pack(fill=tk.X, padx=10, pady=8)
    e = tk.Entry(
        inner,
        textvariable=textvariable,
        font=fonts.get("cap", ("Segoe UI", 9)),
        relief=tk.FLAT,
        bg=colors["input"],
        fg=colors["text"],
        bd=0,
        **kwargs,
    )
    e.pack(side=tk.LEFT, fill=tk.X, expand=True)
    return wrap, e, inner


def apply_ttk_combobox_style(root):
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Archive.TCombobox",
            fieldbackground=C["input"],
            background=C["card"],
            foreground=C["text"],
            bordercolor=C["border"],
            lightcolor=C["border"],
            darkcolor=C["border"],
            arrowcolor=C["accent"],
            padding=4,
        )
        style.map(
            "Archive.TCombobox",
            fieldbackground=[("readonly", C["input"])],
            foreground=[("readonly", C["text"])],
        )
    except tk.TclError:
        pass


class LoadingIndicator(tk.Canvas):
    """加载动画指示器"""

    def __init__(self, parent, size=32, colors=None, **kwargs):
        colors = colors or C
        super().__init__(
            parent,
            width=size,
            height=size,
            highlightthickness=0,
            bg=kwargs.get("bg", colors["bg"]),
        )
        self._colors = colors
        self._size = size
        self._angle = 0
        self._running = False
        self._job = None

    def start(self):
        """开始动画"""
        if not self._running:
            self._running = True
            self._animate()

    def stop(self):
        """停止动画"""
        self._running = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.delete("all")

    def _animate(self):
        if not self._running:
            return

        self.delete("all")
        center = self._size // 2
        radius = self._size // 3

        # 绘制旋转圆弧
        for i in range(8):
            angle = self._angle + i * 45
            rad = angle * 3.14159 / 180
            x1 = center + (radius - 4) * rad
            y1 = center + (radius - 4) * rad
            x2 = center + radius * rad
            y2 = center + radius * rad

            alpha = 1.0 - (i / 8.0)
            color = self._colors["accent"] if i < 4 else self._colors["accent_soft"]

            self.create_arc(
                center - radius, center - radius,
                center + radius, center + radius,
                start=angle, extent=40,
                style=tk.ARC, outline=color, width=2
            )

        self._angle = (self._angle + 15) % 360
        self._job = self.after(50, self._animate)


class ProgressBar(tk.Frame):
    """现代化进度条"""

    def __init__(self, parent, colors=None, **kwargs):
        colors = colors or C
        super().__init__(parent, bg=kwargs.get("bg", colors["bg"]))
        self._colors = colors
        self._progress = 0

        self.canvas = tk.Canvas(
            self,
            height=8,
            highlightthickness=0,
            bg=self._colors["input"],
        )
        self.canvas.pack(fill=tk.X)
        self.canvas.bind("<Configure>", self._draw)

    def set_progress(self, value):
        """设置进度 (0-100)"""
        self._progress = max(0, min(100, value))
        self._draw()

    def _draw(self, event=None):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = 8

        if w < 10:
            return

        # 背景
        round_rect(self.canvas, 1, 1, w-1, h-1, 4, fill=self._colors["input"], outline="")

        # 进度
        if self._progress > 0:
            progress_w = (w - 4) * self._progress / 100
            round_rect(
                self.canvas, 2, 2, 2 + progress_w, h-2, 3,
                fill=self._colors["accent"], outline=""
            )
