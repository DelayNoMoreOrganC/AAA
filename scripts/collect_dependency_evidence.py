"""Collect installed-package evidence without importing dependencies or accessing services.

Reads only the pinned manifests, installed package metadata/legal files and the
three RapidOCR ONNX files (hash only). Every collection creates a new directory.
This is neither a final-distribution SBOM nor a licensing/compliance approval.
Recommended invocation: python -I -S scripts/collect_dependency_evidence.py
(-I -S also prevents startup site-package hooks from being imported.)
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / ".venv" / "Lib" / "site-packages"
FRONT = ROOT / "web" / "frontend"
NODE = FRONT / "node_modules"
EVIDENCE = ROOT / "artifacts" / "dependency-evidence-20261024"
LOCK = ROOT / "web" / "backend" / "requirements-workstation.lock.txt"
MAX_LEGAL_BYTES = 16 * 1024 * 1024
MODEL_NAMES = {
    "Det": "ch_PP-OCRv4_det_infer.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "Rec": "ch_PP-OCRv4_rec_infer.onnx",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canon(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def within(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("PATH_OUTSIDE_ALLOWED_ROOT")
    return resolved


def root_relative(path):
    return within(path, ROOT).relative_to(ROOT).as_posix()


def read_allowed(path, root, *, max_bytes=None):
    target = within(path, root)
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise ValueError("LEGAL_FILE_EXCEEDS_LIMIT")
    return target.read_bytes()


def legal_candidate(relative):
    p = PurePosixPath(str(relative).replace("\\", "/"))
    name = p.name.lower()
    if p.suffix.lower() in {".dll", ".so", ".exe", ".pyd", ".py", ".pyi", ".pyc", ".onnx", ".wasm", ".map"}:
        return False
    stem = re.sub(r"[^a-z0-9]", "", name)
    return bool(re.match(r"^(licen[cs]e|copying|notice|copyright|authors)(?:$|[._-])", name)
                or name.endswith((".license.txt", ".license.md"))
                or stem.startswith(("thirdpartynotice", "thirdpartylicense", "license3rdparty", "3rdpartylicense"))
                or name == "privacy.md"
                or any(part.lower() in {"license", "licenses", "licences"} for part in p.parts[:-1]))


def files_below(base, allowed_root, *, skip_node_modules=False):
    """Enumerate only contained directories; do not follow external junctions."""
    stack = [base]
    while stack:
        current = stack.pop()
        within(current, allowed_root)
        for child in sorted(current.iterdir(), key=lambda item: item.name.lower()):
            if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                continue
            within(child, allowed_root)
            if child.is_dir():
                if child.name not in {".git", "__pycache__"} and not (skip_node_modules and child.name == "node_modules"):
                    stack.append(child)
            elif child.is_file():
                yield child


class Collection:
    def __init__(self, output):
        self.output = output
        self.copies = []
        self.issues = []

    def issue(self, component, code, path=None):
        item = {"component":component, "code":code}
        if path is not None:
            # Only explicit installed-package/manifest paths, never exception text.
            item["source"] = root_relative(path)
        self.issues.append(item)

    def write(self, relative, data):
        path = within(self.output / relative, self.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        return path

    def json(self, relative, value):
        return self.write(relative, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def copy(self, source, relative, allowed_root, component, *, legal=False):
        try:
            data = read_allowed(source, allowed_root, max_bytes=MAX_LEGAL_BYTES if legal else None)
            if legal and b"\0" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                self.issue(component, "LEGAL_CANDIDATE_NOT_PLAIN_TEXT", source)
                return None
            target = self.write(relative, data)
            item = {"component":component, "source":root_relative(source),
                    "evidence":target.relative_to(self.output).as_posix(), "sha256":sha(data), "bytes":len(data)}
            self.copies.append(item)
            return item
        except (OSError, ValueError):
            self.issue(component, "FILE_UNAVAILABLE_OR_OUTSIDE_ALLOWED_ROOT", source if source.resolve().is_relative_to(ROOT) else None)
            return None


def collect_python(col):
    locked = []
    for line in read_allowed(LOCK, ROOT).decode("utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", stripped)
        if not match:
            raise ValueError("PYTHON_LOCK_NOT_EXACTLY_PINNED")
        locked.append((match[1], match[2]))
    installed = {}
    for dist in sorted(SITE.glob("*.dist-info")):
        raw = read_allowed(dist / "METADATA", SITE)
        meta = BytesParser(policy=compat32).parsebytes(raw, headersonly=True)
        name = meta.get("Name", "")
        if name:
            installed.setdefault(canon(name), []).append((dist, raw, meta))
    rows = []
    for name, version in locked:
        component = "python:" + canon(name)
        row = {"name":name, "locked_version":version, "installed":[], "issues":[]}
        candidates = installed.get(canon(name), [])
        if not candidates:
            col.issue(component, "INSTALLED_DISTRIBUTION_MISSING")
            row["version_status"] = "missing"
        else:
            row["version_status"] = "match" if len(candidates) == 1 and candidates[0][2].get("Version") == version else "conflict"
            if row["version_status"] != "match":
                col.issue(component, "INSTALLED_VERSION_OR_DUPLICATE_CONFLICT")
        for dist, raw, meta in candidates:
            current = {"name":meta.get("Name"), "version":meta.get("Version"), "metadata_source":root_relative(dist / "METADATA"),
                "metadata_sha256":sha(raw), "license_expression_raw":meta.get_all("License-Expression", []),
                "license_raw":meta.get_all("License", []),
                "license_classifiers_raw":[value for value in meta.get_all("Classifier", []) if value.startswith("License ::")],
                "declared_license_files_raw":meta.get_all("License-File", []), "legal_files":[]}
            sources = set()
            record = dist / "RECORD"
            if record.is_file():
                record_raw = read_allowed(record, SITE)
                current["record_sha256"] = sha(record_raw)
                for entry in csv.reader(io.StringIO(record_raw.decode("utf-8-sig"))):
                    if entry and legal_candidate(entry[0]):
                        candidate = SITE / PurePosixPath(entry[0])
                        if candidate.resolve().is_relative_to(SITE.resolve()):
                            sources.add(candidate.resolve())
                        else:
                            col.issue(component, "RECORDED_LEGAL_FILE_OUTSIDE_SITE_PACKAGES")
            else:
                col.issue(component, "DISTRIBUTION_RECORD_MISSING", record)
            sources.update(path for path in files_below(dist, SITE) if legal_candidate(path.relative_to(dist)))
            for declared in current["declared_license_files_raw"]:
                candidates_for_name = [dist / declared, dist / "licenses" / declared]
                for candidate in candidates_for_name:
                    if candidate.resolve().is_relative_to(dist.resolve()) and candidate.is_file():
                        sources.add(candidate.resolve())
                if not any(path.name == Path(declared).name for path in sources):
                    col.issue(component, "DECLARED_LICENSE_FILE_NOT_LOCATED")
            for source in sorted(sources):
                result = col.copy(source, Path("licenses/python") / canon(name) / source.relative_to(SITE), SITE, component, legal=True)
                if result:
                    current["legal_files"].append(result)
            if not current["legal_files"]:
                col.issue(component, "NO_BUNDLED_LEGAL_TEXT_FOUND")
            row["installed"].append(current)
        rows.append(row)
    return rows


def collect_frontend(col):
    lock = json.loads(read_allowed(FRONT / "package-lock.json", FRONT))
    if not isinstance(lock.get("packages"), dict):
        raise ValueError("NPM_LOCK_PACKAGES_MISSING")
    rows = []
    for package_path, locked in sorted(lock["packages"].items()):
        if not package_path or locked.get("dev") is True:
            continue
        posix = PurePosixPath(package_path)
        if posix.is_absolute() or ".." in posix.parts or not package_path.startswith("node_modules/"):
            raise ValueError("NPM_LOCK_PATH_OUTSIDE_NODE_MODULES")
        base = within(FRONT / posix, NODE)
        component = "npm:" + package_path
        row = {"lock_path":package_path, "locked_version":locked.get("version"), "lock_license_raw":locked.get("license"),
               "optional":bool(locked.get("optional")), "installed_version":None, "installed_license_raw":None, "legal_files":[]}
        manifest = base / "package.json"
        if not manifest.is_file():
            row["version_status"] = "missing"
            col.issue(component, "INSTALLED_PACKAGE_MISSING", manifest)
            rows.append(row)
            continue
        raw = read_allowed(manifest, NODE)
        metadata = json.loads(raw)
        row.update(name=metadata.get("name"), installed_version=metadata.get("version"),
                   installed_license_raw=metadata.get("license"), installed_licenses_raw=metadata.get("licenses"),
                   package_json_source=root_relative(manifest), package_json_sha256=sha(raw))
        row["version_status"] = "match" if row["locked_version"] == row["installed_version"] else "conflict"
        if row["version_status"] != "match":
            col.issue(component, "INSTALLED_VERSION_CONFLICT")
        if row["lock_license_raw"] != row["installed_license_raw"]:
            col.issue(component, "LOCK_AND_INSTALLED_LICENSE_METADATA_DIFFER")
        if row["lock_license_raw"] is None or row["installed_license_raw"] is None:
            col.issue(component, "LICENSE_METADATA_MISSING")
        for source in files_below(base, NODE, skip_node_modules=True):
            if legal_candidate(source.relative_to(base)):
                result = col.copy(source, Path("licenses/npm") / posix / source.relative_to(base), NODE, component, legal=True)
                if result:
                    result["discovery"] = "named_legal_file"
                    row["legal_files"].append(result)
        if not row["legal_files"]:
            # Some npm packages ship their actual MIT grant in README rather
            # than a separate LICENSE. Preserve the whole original document,
            # identified explicitly as embedded evidence, not a reconstructed
            # or assistant-selected license.
            for source in sorted(base.iterdir()):
                if source.is_file() and source.name.lower().startswith("readme"):
                    raw_readme = read_allowed(source, NODE, max_bytes=MAX_LEGAL_BYTES)
                    text = raw_readme.decode("utf-8", errors="replace")
                    if re.search(r"(?im)^(?:#{1,6}\s*)?licen[sc]e\s*$", text):
                        result = col.copy(source, Path("licenses/npm") / posix / source.name, NODE, component, legal=True)
                        if result:
                            result["discovery"] = "readme_with_license_section"
                            row["legal_files"].append(result)
        if not row["legal_files"]:
            col.issue(component, "NO_BUNDLED_LEGAL_TEXT_FOUND")
        rows.append(row)
    return {"lockfile_version":lock.get("lockfileVersion"), "selection":"non-root packages entries where dev is not true",
            "packages":rows}


def collect_models(col):
    base = SITE / "rapidocr_onnxruntime"
    config = base / "config.yaml"
    config_raw = read_allowed(config, SITE)
    col.copy(config, "inputs/rapidocr-config.yaml", SITE, "rapidocr-models")
    configured = {}; section = ""
    for line in config_raw.decode("utf-8").splitlines():
        match = re.fullmatch(r"(Det|Cls|Rec):\s*", line)
        if match:
            section = match[1]
        path_match = re.fullmatch(r"\s+model_path:\s*([^#\s]+)\s*", line)
        if path_match:
            if section in configured:
                raise ValueError("DUPLICATE_MODEL_CONFIG")
            configured[section] = path_match[1]
    rows = []
    for role, expected_name in MODEL_NAMES.items():
        relative = configured.get(role, "")
        if relative != "models/" + expected_name:
            col.issue("rapidocr-models", "CONFIGURED_MODEL_DIFFERS_FROM_FROZEN_SCOPE")
            rows.append({"role":role, "expected_name":expected_name, "status":"config_mismatch"})
            continue
        target = within(base / relative, base)
        try:
            with target.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            rows.append({"role":role, "name":expected_name, "source":root_relative(target), "bytes":target.stat().st_size,
                         "sha256":digest, "status":"hashed_only", "copied":False,
                         "license_provenance_status":"specific_weight_origin_and_license_not_verified"})
        except OSError:
            col.issue("rapidocr-models", "CONFIGURED_MODEL_MISSING")
            rows.append({"role":role, "expected_name":expected_name, "status":"missing"})
    return rows


def verify(output):
    output = within(output, EVIDENCE)
    manifest = json.loads((output / "file-manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    if not files or len({item["path"] for item in files}) != len(files):
        raise ValueError("EVIDENCE_MANIFEST_INVALID")
    for item in files:
        path = within(output / item["path"], output)
        raw = path.read_bytes()
        if sha(raw) != item["sha256"] or len(raw) != item["bytes"]:
            raise ValueError("EVIDENCE_COPY_HASH_MISMATCH")
    inventory = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
    fixed_python = [line.strip() for line in (output / "inputs/requirements-workstation.lock.txt").read_text(encoding="utf-8-sig").splitlines()
                    if line.strip() and not line.strip().startswith("#")]
    if fixed_python != [row["name"] + "==" + row["locked_version"] for row in inventory["python"]]:
        raise ValueError("PYTHON_INVENTORY_LOCK_COVERAGE_MISMATCH")
    fixed_npm = json.loads((output / "inputs/package-lock.json").read_text(encoding="utf-8"))["packages"]
    selected_npm = {path:row for path,row in fixed_npm.items() if path and row.get("dev") is not True}
    if set(selected_npm) != {row["lock_path"] for row in inventory["frontend"]["packages"]}:
        raise ValueError("FRONTEND_INVENTORY_LOCK_COVERAGE_MISMATCH")
    for row in inventory["frontend"]["packages"]:
        locked = selected_npm[row["lock_path"]]
        if row["locked_version"] != locked.get("version") or row["lock_license_raw"] != locked.get("license"):
            raise ValueError("FRONTEND_INVENTORY_LOCK_VALUE_MISMATCH")
    referenced = [entry for row in inventory["python"] for installed in row["installed"] for entry in installed["legal_files"]]
    referenced += [entry for row in inventory["frontend"]["packages"] for entry in row["legal_files"]]
    indexed = {item["path"]:item for item in files}
    for item in referenced:
        if item["evidence"] not in indexed or indexed[item["evidence"]]["sha256"] != item["sha256"]:
            raise ValueError("INVENTORY_COPY_REFERENCE_MISMATCH")
    onnx = inventory["rapidocr_models"]
    if len(onnx) != 3 or any(path.suffix.lower() == ".onnx" for path in output.rglob("*")):
        raise ValueError("MODEL_HASH_ONLY_BOUNDARY_FAILED")
    current = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if current - set(indexed) - {"file-manifest.json", "self-check.json"}:
        raise ValueError("UNINDEXED_EVIDENCE_FILE")
    if (output / "self-check.json").is_file():
        prior = json.loads((output / "self-check.json").read_text(encoding="utf-8"))
        if prior["file_manifest_sha256"] != sha((output / "file-manifest.json").read_bytes()):
            raise ValueError("FILE_MANIFEST_HASH_MISMATCH")
    return {"valid":True, "files_checked":len(files), "license_copies_checked":len(referenced),
            "python_entries":len(inventory["python"]), "frontend_entries":len(inventory["frontend"]["packages"]),
            "model_entries":len(onnx), "model_files_copied":0,
            "meaning":"structure and copied-byte hashes only; not license approval or network audit"}


def run(output):
    within(output, EVIDENCE)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    col = Collection(output)
    for path, destination in [(Path(__file__), "inputs/collector.py"), (LOCK,"inputs/requirements-workstation.lock.txt"),
                              (FRONT / "package.json","inputs/package.json"), (FRONT / "package-lock.json","inputs/package-lock.json")]:
        col.copy(path, destination, ROOT, "collection-input")
    python = collect_python(col)
    frontend = collect_frontend(col)
    models = collect_models(col)
    inventory = {"schema_version":1, "collected_at_utc":datetime.now(timezone.utc).isoformat(),
        "purpose":"installed local dependency evidence; not final distribution SBOM or compliance approval",
        "scope":{"python_lock_entries":len(python), "frontend_non_dev_lock_entries":len(frontend["packages"]),
                 "no_package_imports":True,"no_downloads":True,"no_model_execution":True,"no_credentials_read":True,
                 "source_paths":"relative to workspace root; explicit installed packages and manifests only"},
        "python":python, "frontend":frontend, "rapidocr_models":models, "issues":col.issues,
        "copied_inputs":[item for item in col.copies if item["evidence"].startswith("inputs/")],
        "limitations":["No license route selected; raw OR/AND expressions and full bundled texts preserved.",
            "File presence is not proof of complete upstream, embedded binary or weight attribution.",
            "Installed packages are not identical to final distributable or browser bundle contents.",
            "No WPS/Office/LibreOffice purchase, distribution or cloud-service contract examined.",
            "No environment variables, process command lines, model runtime, account configuration or case materials read.",
            "Privacy declarations are preserved as documents; this is not a telemetry or whole-machine network test.",
            "Python discovery uses wheel RECORD, declared License-File and dist-info legal files; unrecorded package files may be missed."]}
    col.json("inventory.json", inventory)
    counts = {"python_entries":len(python), "python_versions_matching":sum(row["version_status"] == "match" for row in python),
        "frontend_entries":len(frontend["packages"]), "frontend_versions_matching":sum(row["version_status"] == "match" for row in frontend["packages"]),
        "legal_files_copied":len([item for item in col.copies if item["evidence"].startswith("licenses/")]),
        "issues":len(col.issues), "models_hashed":sum(row["status"] == "hashed_only" for row in models)}
    col.json("summary.json", counts)
    col.write("README.txt", ("LOCAL INSTALLED DEPENDENCY EVIDENCE — NOT A FINAL SBOM OR COMPLIANCE APPROVAL\n"
        "Raw package license declarations and bundled legal texts are preserved without choosing an OR license route.\n"
        "Read inventory.json issues and limitations before use. No model weights or binaries are copied.\n"
        "Recollect into a new directory: python -I -S scripts/collect_dependency_evidence.py\n"
        "Verify existing copies: python -I -S scripts/collect_dependency_evidence.py --verify <this-run-directory>\n"
        "Verification checks saved bytes/structure, not legal completeness, source authenticity or network behavior.\n").encode("utf-8"))
    manifest = {"files":[{"path":path.relative_to(output).as_posix(), "bytes":path.stat().st_size,
                         "sha256":sha(path.read_bytes())} for path in sorted(output.rglob("*")) if path.is_file()]}
    col.json("file-manifest.json", manifest)
    checked = verify(output)
    checked["file_manifest_sha256"] = sha((output / "file-manifest.json").read_bytes())
    col.json("self-check.json", checked)
    return {"output":root_relative(output), **counts, "self_check":checked["valid"]}


def main():
    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            raise ValueError("NETWORK_AND_PROCESS_EXECUTION_FORBIDDEN")
    sys.addaudithook(audit)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New directory strictly under artifacts/dependency-evidence-20261024")
    parser.add_argument("--verify", type=Path, help="Read-only verification of a previously collected directory")
    args = parser.parse_args()
    if args.output and args.verify:
        parser.error("--output and --verify are mutually exclusive")
    try:
        if args.verify:
            result = verify(args.verify.resolve())
        else:
            output = args.output or EVIDENCE / ("local-packages-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            result = run(output.resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        # Do not print exception text, environment, traceback or local values.
        print(json.dumps({"ok":False, "code":"EVIDENCE_COLLECTION_OR_VERIFICATION_FAILED", "existing_evidence_not_overwritten":True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
