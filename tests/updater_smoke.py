"""Exercise the real installer script in an isolated directory (no user EXE).

Only the restart command is adapted to run the new EXE's hidden UI smoke.
This checks replacement and restart, not the old process/file-lock scenario.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.updater import _install_script_text


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


source_exe = Path(sys.argv[1]).resolve()
workspace = Path(tempfile.mkdtemp(prefix='updater-smoke-', dir=ROOT / 'build')).resolve()
assert workspace.is_relative_to((ROOT / 'build').resolve())
download = workspace / 'download.exe'
target = workspace / 'PC_GIOSXSR_Demo.exe'
script = workspace / 'apply.ps1'
log = workspace / 'apply.log'
shutil.copyfile(source_exe, download)
target.write_bytes(b'Previous application placeholder')
text = _install_script_text(download, target, 2147483647, log)
restart = 'Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target)'
assert restart in text
text = text.replace(restart, "$smokeProcess = " + restart + " -WindowStyle Hidden -ArgumentList '--ui-smoke' -Wait -PassThru\n    if ($smokeProcess.ExitCode -ne 0) { throw 'Smoke restart failed' }")
script.write_text(text, encoding='utf-8-sig')
result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                        capture_output=True, timeout=45)
assert result.returncode == 0, result.stderr
assert digest(source_exe) == digest(target), 'Installed binary hash differs'
assert not download.exists(), 'Download cleanup did not complete'
assert not target.with_name(target.name + '.old').exists(), 'Backup cleanup did not complete'
assert not script.exists(), 'Installer did not finish'
assert 'Updated ' in log.read_text(), log.read_text()
print('PASS: isolated installer replaced target; SHA256 matches; new EXE restarted in UI smoke; cleanup complete')
print(f'Installer log: {log}')
