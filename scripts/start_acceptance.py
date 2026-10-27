"""Start the local test workspace, preserving its existing accounts and data."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".runtime-tmp/full-experience"


def request(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:8766"+path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type":"application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as response:
        return json.load(response)


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0,str(ROOT))
    from workstation_security import protect_directory
    protect_directory(DATA)
    env = dict(os.environ, V5_DATA_DIR=str(DATA),V5_DATABASE_URL="",V5_HOST="127.0.0.1",V5_PORT="8766",V5_PREVIEW_ONLY="true",
        V5_ALLOW_EXTERNAL_AI="false",V5_REGISTRATION_ENABLED="false",V5_NAME_LOGIN_ENABLED="true",V5_LOCAL_LLM_BASE_URL="http://127.0.0.1:11434/v1",
        V5_LOCAL_LLM_MODEL="gd-qwen3-4b",TEMP=str(DATA),TMP=str(DATA),PYTHONUTF8="1")
    release_path = DATA / "frontend-release.json"
    if release_path.exists():
        release = json.loads(release_path.read_text(encoding="utf-8"))
        frontend = Path(release["frontend_dist"]).resolve()
        if (not frontend.is_relative_to((ROOT / ".runtime-tmp/deployed-frontend").resolve())
                or not (frontend / "index.html").is_file() or not (frontend / "assets").is_dir()):
            raise RuntimeError("Test frontend release is unavailable; existing data is unchanged")
        env["V5_FRONTEND_DIST"] = str(frontend)
    with (DATA / "service.log").open("ab") as log:
        command = ([sys.executable, str(ROOT/'scripts/local_boundary_guard.py'), '--port','8766','--data-dir',str(DATA)]
                   if '--guard' in sys.argv else [sys.executable,str(ROOT/'web/backend/run.py')])
        proc = subprocess.Popen(command,cwd=ROOT/'web/backend',env=env,
            stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    (DATA/'service.pid').write_text(str(proc.pid))
    for _ in range(60):
        try:
            status=request('/api/setup/status')
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError('Acceptance server exited; inspect isolated log')
            time.sleep(.5)
    # Windows venv python.exe is a small launcher with a separate Python child.
    # Record the listening worker, so restart tests and RAM sampling target it.
    if os.name == 'nt':
        actual = subprocess.check_output(['powershell', '-NoProfile', '-Command',
            '(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8766 -State Listen | Select-Object -First 1).OwningProcess'],
            text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
        (DATA/'service.pid').write_text(actual)
    if status['required']:
        credentials={'username':'gd_acceptance','password':secrets.token_urlsafe(18)+'A1'}
        request('/api/setup',dict(credentials,org_name='虚构功能验收律所',display_name='体验验收',
            setup_token=(DATA/'setup.token').read_text().strip()))
        (DATA/'credentials.json').write_text(json.dumps(credentials))
    print('Isolated acceptance server ready: http://127.0.0.1:8766')
