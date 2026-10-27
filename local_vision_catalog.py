"""Explicit deployment tiers, not measurements or automatic hardware selection.

Tags and download sizes checked against https://ollama.com/library/qwen3.5/tags
on 2026-10-26. Sizes are model downloads, not total inference memory.
"""
PRESETS = {
    "minimum": {"label": "最低配置", "hardware": "显存 16 GB + 内存 32 GB", "vram_gb": 16, "ram_gb": 32,
                "model": "qwen3.5:9b-q4_K_M", "name": "Qwen3.5 9B", "download_gb": 6.6},
    "recommended": {"label": "推荐配置", "hardware": "显存 32 GB + 内存 64 GB", "vram_gb": 32, "ram_gb": 64,
                    "model": "qwen3.5:27b-q4_K_M", "name": "Qwen3.5 27B", "download_gb": 17},
    "top": {"label": "顶级配置", "hardware": "显存 96 GB + 内存 128 GB", "vram_gb": 96, "ram_gb": 128,
            "model": "qwen3.5:122b-a10b-q4_K_M", "name": "Qwen3.5 122B-A10B", "download_gb": 81},
    "unified128": {"label": "统一内存", "hardware": "统一内存 128 GB", "vram_gb": None, "ram_gb": 128,
                   "model": "qwen3.5:35b-a3b-q4_K_M", "name": "Qwen3.5 35B-A3B", "download_gb": 22},
}
DEFAULT_TIER = "minimum"
DEFAULT_MODEL = PRESETS[DEFAULT_TIER]["model"]
ALLOWED_MODELS = frozenset([p["model"] for p in PRESETS.values()] + ["qwen3-vl:8b"])


def preset(tier):
    if tier not in PRESETS:
        raise ValueError("本地配置档位无效")
    return dict(PRESETS[tier])
