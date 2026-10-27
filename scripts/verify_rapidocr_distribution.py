"""Compare installed OCR models with the official wheel, without installation.

Only public release metadata and wheel bytes are fetched. No credentials,
runtime settings, customer data, model inference or service IO is used.
"""
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import io
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/dependency-provenance-20261024"
WHEEL_SHA = "971d7d5f223a7a808662229df1ef69893809d8457d834e6373d3854bc1782cbf"
NAMES = ("ch_PP-OCRv4_det_infer.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx", "ch_PP-OCRv4_rec_infer.onnx")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fetch(url, limit):
    assert urlparse(url).scheme == "https"
    assert urlparse(url).hostname in {"pypi.org", "files.pythonhosted.org", "raw.githubusercontent.com"}
    request = urllib.request.Request(url, headers={"User-Agent": "GD-dependency-evidence/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        assert urlparse(response.url).hostname == urlparse(url).hostname
        value = response.read(limit + 1)
        assert len(value) <= limit, "Public artifact exceeded allowed size"
        return value


def main():
    assert not OUT.exists(), "Evidence directory already exists; do not overwrite"
    distribution = metadata.distribution("rapidocr-onnxruntime")
    assert distribution.version == "1.4.4"
    url = "https://pypi.org/pypi/rapidocr-onnxruntime/1.4.4/json"
    release = json.loads(fetch(url, 1_000_000))
    wheels = [item for item in release["urls"] if item["filename"] == "rapidocr_onnxruntime-1.4.4-py3-none-any.whl"]
    assert len(wheels) == 1 and wheels[0]["digests"]["sha256"] == WHEEL_SHA
    wheel = fetch(wheels[0]["url"], 20_000_000)
    assert sha(wheel) == WHEEL_SHA and len(wheel) == wheels[0]["size"]
    models = []
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        for name in NAMES:
            member = "rapidocr_onnxruntime/models/" + name
            installed = Path(distribution.locate_file(member))
            upstream = archive.read(member)
            local = installed.read_bytes()
            models.append({"name":name, "wheel_member":member, "installed_size":len(local),
                           "installed_sha256":sha(local), "wheel_sha256":sha(upstream), "identical":local == upstream})
    assert all(item["identical"] for item in models), "Installed OCR model differs from official wheel"
    license_url = "https://raw.githubusercontent.com/RapidAI/RapidOCR/v1.4.4/LICENSE"
    license_bytes = fetch(license_url, 100_000)
    assert b"Apache License" in license_bytes
    ort = metadata.distribution("onnxruntime")
    privacy_path = Path(ort.locate_file("onnxruntime/Privacy.md"))
    privacy = privacy_path.read_bytes()
    assert b"ORT_DISABLE_TELEMETRY" in privacy
    result = {"collected_at":datetime.now(timezone.utc).isoformat(), "source":url,
              "package":"rapidocr-onnxruntime", "version":distribution.version,
              "wheel":{"url":wheels[0]["url"],"sha256":WHEEL_SHA,"size":len(wheel),"uploaded":wheels[0]["upload_time_iso_8601"]},
              "models":models,
              "project_license":{"url":license_url,"file":"RapidOCR-v1.4.4-LICENSE.txt","sha256":sha(license_bytes)},
              "ort_privacy":{"installed_version":ort.version,"file":"onnxruntime-installed-Privacy.md","sha256":sha(privacy),
                             "official_reference":"https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md"},
              "limits":["Wheel identity is not proof of training-data provenance or complete model redistribution obligations.",
                        "No model-specific notice was inferred from the current PP-OCRv6 documentation.",
                        "Wheel and model binaries were compared in memory, not installed or retained.",
                        "No whole-machine network traffic measurement was performed."]}
    OUT.mkdir(parents=True)
    (OUT / "RapidOCR-v1.4.4-LICENSE.txt").write_bytes(license_bytes)
    (OUT / "onnxruntime-installed-Privacy.md").write_bytes(privacy)
    (OUT / "report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"official_wheel_verified":True, "models_identical":len(models), "wheel_bytes_retained":False,
                      "report":str((OUT / "report.json").relative_to(ROOT))}))


if __name__ == "__main__":
    main()
