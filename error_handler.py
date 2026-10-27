#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""友好错误提示系统 - 提供具体解决方案"""

from typing import Dict, Optional, Tuple


class ErrorHandler:
    """统一错误处理，提供友好的错误提示和解决方案"""

    # 错误类型到解决方案的映射
    ERROR_SOLUTIONS = {
        # 配置错误
        "config_save": {
            "title": "配置保存失败",
            "solutions": [
                "1. 检查是否有写入权限",
                "2. 确认config.json文件未被其他程序占用",
                "3. 尝试以管理员身份运行程序",
                "4. 检查磁盘空间是否充足"
            ]
        },

        # PDF文件错误
        "pdf_not_found": {
            "title": "PDF文件未找到",
            "solutions": [
                "1. 确认PDF文件路径正确",
                "2. 检查文件是否被移动或删除",
                "3. 尝试重新选择文件",
                "4. 确认文件名包含正确的扩展名.pdf"
            ]
        },

        "pdf_invalid": {
            "title": "PDF文件无效",
            "solutions": [
                "1. 确认文件是有效的PDF格式",
                "2. 尝试用PDF阅读器打开文件",
                "3. 检查文件是否损坏",
                "4. 重新获取PDF文件"
            ]
        },

        # OCR配置错误
        "ocr_not_ready": {
            "title": "OCR配置未完成",
            "solutions": [
                "1. 打开「详细设置」填写OCR配置",
                "2. 百度OCR需要APP ID、API Key、Secret Key",
                "3. MinerU需要本地路径或API Token",
                "4. 点击「保存」后重试"
            ]
        },

        # 网络错误
        "network_error": {
            "title": "网络连接失败",
            "solutions": [
                "1. 检查网络连接是否正常",
                "2. 确认代理设置正确",
                "3. 尝试切换OCR引擎（本地/云端）",
                "4. 检查防火墙设置"
            ]
        },

        # 模板错误
        "template_not_found": {
            "title": "模板文件未找到",
            "solutions": [
                "1. 确认templates目录存在",
                "2. 检查模板文件是否完整",
                "3. 重新安装程序恢复模板",
                "4. 联系技术支持获取模板文件"
            ]
        },

        # 权限错误
        "permission_denied": {
            "title": "权限不足",
            "solutions": [
                "1. 以管理员身份运行程序",
                "2. 检查文件夹的读写权限",
                "3. 确认没有被杀毒软件阻止",
                "4. 尝试更改输出目录"
            ]
        },

        # 默认错误
        "default": {
            "title": "操作失败",
            "solutions": [
                "1. 查看运行日志了解详细错误",
                "2. 尝试重启程序",
                "3. 检查输入参数是否正确",
                "4. 联系技术支持"
            ]
        }
    }

    @classmethod
    def get_error_info(cls, error_type: str) -> Dict:
        """获取错误信息"""
        return cls.ERROR_SOLUTIONS.get(error_type, cls.ERROR_SOLUTIONS["default"])

    @classmethod
    def format_friendly_message(cls, error_type: str, detail: str = "") -> Tuple[str, str]:
        """格式化友好的错误消息"""
        error_info = cls.get_error_info(error_type)

        title = error_info["title"]
        message = f"{error_info['title']}\n\n"

        if detail:
            message += f"错误详情：{detail}\n\n"

        message += "解决方案：\n"
        message += "\n".join(error_info["solutions"])

        return title, message

    @classmethod
    def identify_error_type(cls, error_msg: str) -> str:
        """根据错误消息识别错误类型"""
        error_msg = error_msg.lower()

        if "config" in error_msg or "配置" in error_msg:
            return "config_save"
        elif "pdf" in error_msg and ("not found" in error_msg or "不存在" in error_msg):
            return "pdf_not_found"
        elif "pdf" in error_msg and ("invalid" in error_msg or "无效" in error_msg):
            return "pdf_invalid"
        elif "ocr" in error_msg:
            return "ocr_not_ready"
        elif "network" in error_msg or "网络" in error_msg or "connection" in error_msg:
            return "network_error"
        elif "template" in error_msg or "模板" in error_msg:
            return "template_not_found"
        elif "permission" in error_msg or "权限" in error_msg:
            return "permission_denied"
        else:
            return "default"


def get_friendly_error(error_msg: str) -> Tuple[str, str]:
    """获取友好的错误消息（便捷函数）"""
    error_type = ErrorHandler.identify_error_type(error_msg)
    return ErrorHandler.format_friendly_message(error_type, error_msg)


# 测试代码
if __name__ == "__main__":
    # 测试各种错误类型
    test_errors = [
        "无法写入 config.json",
        "PDF文件不存在",
        "PDF文件无效",
        "OCR配置未完成",
        "网络连接失败",
        "模板文件未找到",
        "权限不足",
        "未知错误"
    ]

    for error in test_errors:
        title, message = get_friendly_error(error)
        print(f"=== {title} ===")
        print(message)
        print()
