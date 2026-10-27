"""Operator-only deployment of pinned public runtime and model. Never run on uploads."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "llama"
MODEL = ROOT / "runtime" / "models" / "Qwen3-4B-Q4_K_M.gguf"
ASSETS = [
    ("https://github.com/ggml-org/llama.cpp/releases/download/b11822/llama-b11822-bin-win-cpu-x64.zip", RUNTIME.parent / "llama-b11822.zip", "b9484b510a37320ada6d6bac9b0864af3d855320347ccd90fa5ece7b3d9aed88"),
    ("https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf?download=true", MODEL, "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"),
]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and digest(target) == expected:
        print("Verified", target.name, flush=True)
        return
    temporary = target.with_suffix(target.suffix + ".part")
    offset = temporary.stat().st_size if temporary.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
    with urllib.request.urlopen(request, timeout=90) as response:
        resumed = offset and response.status == 206
        total = offset if resumed else 0
        last = total // (256 * 1024**2)
        with temporary.open("ab" if resumed else "wb") as output:
            while block := response.read(4 * 1024**2):
                output.write(block)
                total += len(block)
                if total // (256 * 1024**2) > last:
                    last = total // (256 * 1024**2)
                    print(target.name, round(total / 1024**2), "MiB", flush=True)
    if digest(temporary) != expected:
        raise RuntimeError("Public asset SHA256 mismatch: " + target.name)
    temporary.replace(target)
    print("Verified", target.name, flush=True)


if __name__ == "__main__":
    for asset in ASSETS:
        download(*asset)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ASSETS[0][1]) as archive:
        for member in archive.infolist():
            if not (RUNTIME / member.filename).resolve().is_relative_to(RUNTIME.resolve()):
                raise RuntimeError("Unsafe archive member")
        archive.extractall(RUNTIME)
    (ROOT / "runtime" / "manifest.json").write_text(json.dumps({
        "runtime": "llama.cpp b11822 Windows CPU x64", "model": "Qwen3-4B-Q4_K_M",
        "model_license": "Apache-2.0", "runtime_license": "MIT",
        "assets": [{"url": u, "file": str(p.relative_to(ROOT)), "sha256": s} for u, p, s in ASSETS],
    }, indent=2), encoding="utf-8")
    print("Local assets ready", flush=True)
