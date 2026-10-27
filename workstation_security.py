"""Restrict installation-owned data to the service user and OS administrators."""
import os
from pathlib import Path
import subprocess


def protect_directory(path):
    path = Path(path).resolve()
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise ValueError('Refusing to change permissions on a drive or home directory')
    path.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        path.chmod(0o700)
        return
    account = os.environ['USERDOMAIN'] + '\\' + os.environ['USERNAME']
    result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
        account+':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
        capture_output=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('无法限制工作站数据目录权限，启动已停止；请由部署管理员检查目录权限。')
