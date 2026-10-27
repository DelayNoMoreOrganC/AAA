#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""macOS风格UI主题 - 圆角、毛玻璃、原生控件感"""

import tkinter as tk
from tkinter import ttk

# macOS风格颜色方案
MACOS_COLORS = {
    "window_bg": "#FFFFFF",
    "panel_bg": "#F5F5F7",
    "card_bg": "#FFFFFF",
    "text_primary": "#000000",
    "text_secondary": "#6E6E73",
    "text_tertiary": "#8E8E93",
    "accent": "#007AFF",
    "accent_hover": "#0051D5",
    "accent_active": "#004BB8",
    "border": "#D1D1D6",
    "border_light": "#E5E5EA",
    "shadow": "rgba(0,0,0,0.1)",
    "success": "#34C759",
    "warning": "#FF9500",
    "error": "#FF3B30",
    "input_bg": "#FFFFFF",
    "button_bg": "#007AFF",
    "button_text": "#FFFFFF",
}

# macOS字体（必须是合法的 tkinter 字体元组：(family, size[, style])，
# 不能写成两个 family；否则 tkinter 渲染时报错，曾导致日志弹窗静默创建失败）
MACOS_FONTS = {
    "large": ("SF Pro Display", 20, "bold"),
    "title": ("SF Pro Text", 13, "bold"),  # tkinter不支持semibold，改用bold
    "body": ("SF Pro Text", 11, "normal"),
    "caption": ("SF Pro Text", 10, "normal"),
    "monospace": ("SF Mono", 10, "normal"),
}


def apply_macos_style(root):
    """应用macOS风格到root窗口"""
    try:
        root.configure(bg=MACOS_COLORS["window_bg"])
    except Exception:
        pass  # 如果配置失败，使用默认背景

    try:
        # 配置ttk样式
        style = ttk.Style(root)
        style.theme_use("aqua")  # macOS原生主题
    except Exception:
        pass  # 如果aqua主题不可用，使用默认主题

    return MACOS_COLORS


class MacOSTooltip:
    """macOS风格工具提示"""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None

        widget.bind("<Enter>", self.show_tooltip)
        widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return

        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.configure(bg="#000000")

        label = tk.Label(
            self.tooltip_window,
            text=self.text,
            bg="#000000",
            fg="#FFFFFF",
            font=("SF Pro Text", 10),
            padx=6,
            pady=4
        )
        label.pack()

        self.tooltip_window.geometry(f"+{x}+{y}")

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class MacOSButton(tk.Button):
    """macOS风格按钮 - 兼容RoundedButton API"""

    def __init__(self, parent, text="", command=None, style="primary", fonts=None, **kwargs):
        colors = MACOS_COLORS

        # 兼容RoundedButton的style映射
        style_mapping = {
            "primary": "primary",
            "secondary": "secondary",
            "tertiary": "tertiary",
            "soft": "tertiary",  # soft映射到tertiary
            "text": "tertiary",  # text映射到tertiary
            "danger_soft": "secondary",  # 危险柔和→次要样式
        }
        macos_style = style_mapping.get(style, "primary")

        if macos_style == "primary":
            bg = colors["accent"]
            fg = colors["button_text"]
            active_bg = colors["accent_hover"]
            border_color = colors["accent"]
        elif macos_style == "secondary":
            bg = colors["panel_bg"]
            fg = colors["text_primary"]
            active_bg = colors["border"]
            border_color = colors["border"]
        else:  # tertiary
            bg = colors["card_bg"]
            fg = colors["text_secondary"]
            active_bg = colors["border_light"]
            border_color = colors["border_light"]

        # 字体选择：优先使用提供的fonts，否则使用macOS字体
        button_font = kwargs.pop('font', None)
        if not button_font and fonts:
            button_font = fonts.get("btn", MACOS_FONTS["title"])
        if not button_font:
            button_font = MACOS_FONTS["title"]

        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            highlightbackground=border_color,
            highlightthickness=1,
            relief=tk.FLAT,
            padx=20,
            pady=8,
            font=button_font,
            cursor="hand2",
            **kwargs
        )

        self._style = style
        self._original_bg = bg
        self._active_bg = active_bg

        # macOS风格悬停效果
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        """鼠标悬停效果"""
        try:
            self.configure(bg=self._active_bg)
        except Exception:
            pass

    def _on_leave(self, event=None):
        """鼠标离开效果"""
        try:
            self.configure(bg=self._original_bg)
        except Exception:
            pass

    def set_state(self, enabled):
        """设置按钮状态"""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.configure(state=state)
        if not enabled:
            self.configure(bg=MACOS_COLORS["border"], fg=MACOS_COLORS["text_tertiary"])
        else:
            self.configure(bg=self._original_bg, fg=MACOS_COLORS.get("button_text", MACOS_COLORS["text_primary"]))


class MacOSCard(tk.Frame):
    """macOS风格卡片 - 兼容Card API，增加圆角和阴影效果"""

    def __init__(self, parent, title="", colors=None, radius=12, pady=(0, 12), padx=0,
                 autopack=True, fill=tk.X, **kwargs):
        # 使用提供的颜色或macOS默认颜色
        self._colors = colors or MACOS_COLORS
        self._radius = radius
        self._title = title

        # 外层容器（用于阴影效果）
        # 兼容不同的颜色键名：优先window_bg，其次bg，最后使用默认值
        bg_color = self._colors.get("window_bg") or self._colors.get("bg") or MACOS_COLORS["window_bg"]

        shadow_frame = tk.Frame(
            parent,
            bg=bg_color,
            bd=0,
            **kwargs
        )

        super().__init__(
            shadow_frame,
            bg=self._colors["card_bg"],
            highlightbackground=self._colors["border"],
            highlightthickness=1,
            bd=0,
        )

        # 兼容Card的API
        if autopack:
            shadow_frame.pack(fill=fill, padx=padx, pady=pady)
            self.pack(fill=tk.BOTH, expand=True)

        # 创建内容区域（兼容Card.body）
        self.body = tk.Frame(self, bg=self._colors["card_bg"], padx=20, pady=16)
        self.body.pack(fill=tk.BOTH, expand=True)

        # 内边距调整，增加呼吸感
        inner_body = tk.Frame(self.body, bg=self._colors["card_bg"])
        inner_body.pack(fill=tk.BOTH, expand=True)

        # 重新赋值body为内层容器
        self.body = inner_body

        if title:
            self._build_header()

    def _build_header(self):
        """构建macOS风格标题栏"""
        header = tk.Frame(self.body, bg=self._colors["card_bg"], padx=0, pady=(0, 12))
        header.pack(fill=tk.X)

        title_label = tk.Label(
            header,
            text=self._title,
            font=MACOS_FONTS["title"],
            bg=self._colors["card_bg"],
            fg=self._colors["text_primary"]
        )
        title_label.pack(anchor=tk.W)


class MacOSLogPopup:
    """macOS风格日志弹窗 - 解决窗口变形问题"""

    def __init__(self, parent):
        self.parent = parent
        self.window = None
        self.text_widget = None
        self.is_visible = False

    def show(self):
        """显示日志弹窗"""
        if self.is_visible:
            return

        self._create_window()
        self.is_visible = True

    def hide(self):
        """隐藏日志弹窗"""
        if self.window:
            self.window.destroy()
            self.window = None
            self.text_widget = None
            self.is_visible = False

    def log(self, message):
        """添加日志消息"""
        if self.text_widget and self.is_visible:
            self.text_widget.insert(tk.END, f"{message}\n")
            self.text_widget.see(tk.END)

    def clear(self):
        """清空日志"""
        if self.text_widget:
            self.text_widget.delete(1.0, tk.END)

    def _create_window(self):
        """创建日志窗口"""
        self.window = tk.Toplevel(self.parent)
        self.window.title("运行日志")
        self.window.configure(bg=MACOS_COLORS["window_bg"])

        # 设置窗口大小和位置（相对父窗口居中）
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        window_width = 700
        window_height = 500
        x = parent_x + (parent_width - window_width) // 2 + 50  # 稍微偏右，避免完全遮挡
        y = parent_y + (parent_height - window_height) // 2 + 50  # 稍微偏下

        self.window.geometry(f"{window_width}x{window_height}+{x}+{y}")

        # macOS风格毛玻璃效果边框
        self.window.configure(highlightbackground=MACOS_COLORS["border"], highlightthickness=1)

        # macOS风格标题栏
        title_bar = tk.Frame(self.window, bg=MACOS_COLORS["panel_bg"], height=44)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)  # 固定高度

        # 左侧：标题和图标
        title_left = tk.Frame(title_bar, bg=MACOS_COLORS["panel_bg"])
        title_left.pack(side=tk.LEFT, padx=16, pady=0)

        title_label = tk.Label(
            title_left,
            text="📋 运行日志",
            font=MACOS_FONTS["title"],
            bg=MACOS_COLORS["panel_bg"],
            fg=MACOS_COLORS["text_primary"]
        )
        title_label.pack(side=tk.LEFT, pady=12)

        # 右侧：控制按钮组
        title_right = tk.Frame(title_bar, bg=MACOS_COLORS["panel_bg"])
        title_right.pack(side=tk.RIGHT, padx=16, pady=0)

        # 清空按钮
        clear_btn = MacOSButton(
            title_right,
            text="清空",
            command=self.clear,
            style="tertiary"
        )
        clear_btn.pack(side=tk.LEFT, padx=(0, 8))

        # 关闭按钮
        close_btn = MacOSButton(
            title_right,
            text="关闭",
            command=self.hide,
            style="secondary"
        )
        close_btn.pack(side=tk.LEFT, padx=8)

        # 日志文本区域
        log_frame = tk.Frame(self.window, bg=MACOS_COLORS["window_bg"])
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # 创建带圆角的文本框容器
        text_container = tk.Frame(
            log_frame,
            bg=MACOS_COLORS["input_bg"],
            highlightbackground=MACOS_COLORS["border"],
            highlightthickness=1,
            relief=tk.FLAT
        )
        text_container.pack(fill=tk.BOTH, expand=True)

        # 创建文本框和滚动条
        scroll = tk.Scrollbar(text_container)
        self.text_widget = tk.Text(
            text_container,
            font=MACOS_FONTS["monospace"],
            bg=MACOS_COLORS["input_bg"],
            fg=MACOS_COLORS["text_primary"],
            yscrollcommand=scroll.set,
            wrap=tk.WORD,
            bd=0,
            padx=12,
            pady=12,
            selectbackground=MACOS_COLORS["accent"],
            selectforeground=MACOS_COLORS["button_text"]
        )

        scroll.config(command=self.text_widget.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 底部状态栏（macOS风格）
        status_bar = tk.Frame(self.window, bg=MACOS_COLORS["panel_bg"], height=32)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        status_label = tk.Label(
            status_bar,
            text="● 系统运行中",
            font=MACOS_FONTS["caption"],
            bg=MACOS_COLORS["panel_bg"],
            fg=MACOS_COLORS["success"]
        )
        status_label.pack(side=tk.LEFT, padx=16, pady=8)

        # 初始消息
        self.log("系统就绪，等待操作...")


class MacOSDialog:
    """macOS风格对话框 - 替代原生messagebox"""

    @staticmethod
    def show_info(parent, title, message):
        """显示信息对话框"""
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=MACOS_COLORS["window_bg"])
        dialog.geometry("400x200")
        dialog.resizable(False, False)

        # 居中显示
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        dialog_width = 400
        dialog_height = 200
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")

        # 内容区域
        content = tk.Frame(dialog, bg=MACOS_COLORS["window_bg"], padx=20, pady=20)
        content.pack(fill=tk.BOTH, expand=True)

        # 图标和消息
        message_frame = tk.Frame(content, bg=MACOS_COLORS["window_bg"])
        message_frame.pack(fill=tk.BOTH, expand=True)

        icon_label = tk.Label(
            message_frame,
            text="ℹ️",
            font=("SF Pro Display", 24),
            bg=MACOS_COLORS["window_bg"],
            fg=MACOS_COLORS["accent"]
        )
        icon_label.pack(side=tk.LEFT, padx=(0, 12))

        text_label = tk.Label(
            message_frame,
            text=message,
            font=MACOS_FONTS["body"],
            bg=MACOS_COLORS["window_bg"],
            fg=MACOS_COLORS["text_primary"],
            wraplength=300,
            justify=tk.LEFT
        )
        text_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 按钮区域
        button_frame = tk.Frame(content, bg=MACOS_COLORS["window_bg"])
        button_frame.pack(fill=tk.X, pady=(12, 0))

        ok_btn = MacOSButton(
            button_frame,
            text="确定",
            command=dialog.destroy,
            style="primary"
        )
        ok_btn.pack(side=tk.RIGHT)

        # 模态对话框
        dialog.transient(parent)
        dialog.grab_set()
        parent.wait_window(dialog)

    @staticmethod
    def show_error(parent, title, message):
        """显示错误对话框"""
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=MACOS_COLORS["window_bg"])
        dialog.geometry("400x200")
        dialog.resizable(False, False)

        # 居中显示
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        dialog_width = 400
        dialog_height = 200
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")

        # 内容区域
        content = tk.Frame(dialog, bg=MACOS_COLORS["window_bg"], padx=20, pady=20)
        content.pack(fill=tk.BOTH, expand=True)

        # 图标和消息
        message_frame = tk.Frame(content, bg=MACOS_COLORS["window_bg"])
        message_frame.pack(fill=tk.BOTH, expand=True)

        icon_label = tk.Label(
            message_frame,
            text="⚠️",
            font=("SF Pro Display", 24),
            bg=MACOS_COLORS["window_bg"],
            fg=MACOS_COLORS["error"]
        )
        icon_label.pack(side=tk.LEFT, padx=(0, 12))

        text_label = tk.Label(
            message_frame,
            text=message,
            font=MACOS_FONTS["body"],
            bg=MACOS_COLORS["window_bg"],
            fg=MACOS_COLORS["text_primary"],
            wraplength=300,
            justify=tk.LEFT
        )
        text_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 按钮区域
        button_frame = tk.Frame(content, bg=MACOS_COLORS["window_bg"])
        button_frame.pack(fill=tk.X, pady=(12, 0))

        ok_btn = MacOSButton(
            button_frame,
            text="确定",
            command=dialog.destroy,
            style="primary"
        )
        ok_btn.pack(side=tk.RIGHT)

        # 模态对话框
        dialog.transient(parent)
        dialog.grab_set()
        parent.wait_window(dialog)

    @staticmethod
    def ask_yes_no(parent, title, message):
        """询问确认对话框"""
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=MACOS_COLORS["window_bg"])
        dialog.geometry("400x200")
        dialog.resizable(False, False)

        # 居中显示
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        dialog_width = 400
        dialog_height = 200
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")

        # 结果变量
        result = [False]

        # 内容区域
        content = tk.Frame(dialog, bg=MACOS_COLORS["window_bg"], padx=20, pady=20)
        content.pack(fill=tk.BOTH, expand=True)

        # 图标和消息
        message_frame = tk.Frame(content, bg=MACOS_COLORS["window_bg"])
        message_frame.pack(fill=tk.BOTH, expand=True)

        icon_label = tk.Label(
            message_frame,
            text="❓",
            font=("SF Pro Display", 24),
            bg=MACOS_COLORS["window_bg"],
            fg=MACOS_COLORS["warning"]
        )
        icon_label.pack(side=tk.LEFT, padx=(0, 12))

        text_label = tk.Label(
            message_frame,
            text=message,
            font=MACOS_FONTS["body"],
            bg=MACOS_COLORS["window_bg"],
            fg=MACOS_COLORS["text_primary"],
            wraplength=300,
            justify=tk.LEFT
        )
        text_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 按钮区域
        button_frame = tk.Frame(content, bg=MACOS_COLORS["window_bg"])
        button_frame.pack(fill=tk.X, pady=(12, 0))

        def on_yes():
            result[0] = True
            dialog.destroy()

        def on_no():
            result[0] = False
            dialog.destroy()

        no_btn = MacOSButton(
            button_frame,
            text="取消",
            command=on_no,
            style="secondary"
        )
        no_btn.pack(side=tk.RIGHT, padx=(8, 0))

        yes_btn = MacOSButton(
            button_frame,
            text="确定",
            command=on_yes,
            style="primary"
        )
        yes_btn.pack(side=tk.RIGHT)

        # 模态对话框
        dialog.transient(parent)
        dialog.grab_set()
        parent.wait_window(dialog)

        return result[0]

    def append(self, text):
        """追加日志文本"""
        self.log(text)