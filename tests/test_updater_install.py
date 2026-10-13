"""Run the PowerShell installer against isolated fixtures/owned processes only."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from app.updater import _install_script_text, _powershell_literal


@unittest.skipUnless(os.name == 'nt', 'PowerShell installer is Windows-specific')
class UpdaterInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gios-installer-test-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'download new.exe'
        self.target = self.root / 'installed app.exe'
        self.log = self.root / 'install.log'
        self.script = self.root / 'apply.ps1'
        self.restarted = self.root / 'restart.txt'
        self.backup = self.target.with_name(self.target.name + '.old')
        self.old = b'original valid executable fixture'
        self.new = b'new complete executable fixture'
        self.source.write_bytes(self.new)
        self.target.write_bytes(self.old)

    def tearDown(self):
        self.temp.cleanup()

    def run_installer(self, *, inject='', wait_pid=2147483647, start_error=False):
        # Reduce deadlines only; keep real file replacement, hashing and process checks.
        text = _install_script_text(self.source, self.target, wait_pid, self.log)
        text = text.replace('$i -lt 120', '$i -lt 2').replace('$attempt -le 60', '$attempt -le 2')
        text = text.replace('Start-Sleep -Milliseconds 500', 'Start-Sleep -Milliseconds 20')
        text = text.replace('Start-Sleep -Seconds 1', 'Start-Sleep -Milliseconds 10')
        text = text.replace('Start-Sleep -Seconds 3', 'Start-Sleep -Milliseconds 10')
        restart = f'''function Start-Process {{
    param($FilePath, $WorkingDirectory, $WindowStyle)
    if ($WindowStyle -ne 'Hidden') {{ throw 'Restart must be hidden' }}
    Add-Content -LiteralPath {_powershell_literal(self.restarted)} -Value $FilePath -Encoding utf8
    {"throw 'Injected restart error'" if start_error else ''}
}}
'''
        self.script.write_text(inject + restart + text, encoding='utf-8-sig')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.script)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
        self.output = result.stdout.decode('utf-8', errors='replace')
        self.log_text = self.log.read_text(encoding='utf-8-sig') if self.log.exists() else ''
        self.assertFalse(list(self.root.glob('*.update-*.tmp')), 'Staging fixture leaked')
        return result.returncode

    def test_success_replaces_verified_bytes_and_retains_backup_until_app_startup(self):
        self.assertEqual(self.run_installer(), 0, self.output)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertFalse(self.source.exists())
        self.assertFalse(self.script.exists())
        self.assertTrue(self.restarted.exists())
        self.assertIn('SHA256', self.log_text)

    def test_partial_stage_copy_cannot_damage_old_target_or_backup(self):
        inject = '''function Copy-Item {
    param($LiteralPath, $Destination, [switch]$Force, $ErrorAction)
    [System.IO.File]::WriteAllText($Destination, 'partial')
    throw 'Injected partial-copy error'
}
'''
        self.assertEqual(self.run_installer(inject=inject), 1, self.output)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.backup.exists())
        self.assertIn('Injected partial-copy error', self.log_text)
        self.assertIn('Restarted verified previous application', self.log_text)

    def test_same_size_corruption_is_rejected_by_sha256(self):
        inject = '''function Copy-Item {
    param($LiteralPath, $Destination, [switch]$Force, $ErrorAction)
    $length = (Get-Item -LiteralPath $LiteralPath).Length
    [System.IO.File]::WriteAllBytes($Destination, [byte[]]::new($length))
}
'''
        self.assertEqual(self.run_installer(inject=inject), 1, self.output)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertIn('SHA256 mismatch in staging file', self.log_text)

    def test_existing_backup_is_preserved_without_overwriting(self):
        self.backup.write_bytes(b'previous recoverable backup')
        self.assertEqual(self.run_installer(), 1, self.output)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.backup.read_bytes(), b'previous recoverable backup')
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertIn('Previous backup exists', self.log_text)
        self.assertFalse(self.restarted.exists(), 'Restart would trigger startup cleanup of the existing backup')

    def test_restart_failure_keeps_download_and_original_backup(self):
        self.assertEqual(self.run_installer(start_error=True), 1, self.output)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertIn('Injected restart error', self.log_text)
        self.assertNotIn('Started updated application.', self.log_text)

    def test_post_replace_hash_failure_restores_original_before_retry(self):
        inject = '''Import-Module Microsoft.PowerShell.Utility
function Get-FileHash {
    param($LiteralPath, $Algorithm)
    $result = Microsoft.PowerShell.Utility\\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
    if ($LiteralPath -eq $target -and (Test-Path -LiteralPath $backup)) {
        $result.Hash = 'injected-post-replace-mismatch'
    }
    return $result
}
'''
        self.assertEqual(self.run_installer(inject=inject), 1, self.output)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.backup.exists(), 'Backup should be restored as target')
        self.assertEqual(self.log_text.count('Restored previous target after failed replacement.'), 2)
        self.assertNotIn('Rollback failed', self.log_text)
        self.assertIn('Restarted verified previous application', self.log_text)

    def test_rollback_lock_failure_preserves_recovery_files_without_restart(self):
        inject = '''Import-Module Microsoft.PowerShell.Utility
function Get-FileHash {
    param($LiteralPath, $Algorithm)
    $result = Microsoft.PowerShell.Utility\\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
    if ($LiteralPath -eq $target -and (Test-Path -LiteralPath $backup)) {
        $script:rollbackLock = [System.IO.File]::Open($target, 'Open', 'Read', 'Read')
        $result.Hash = 'injected-post-replace-mismatch'
    }
    return $result
}
'''
        self.assertEqual(self.run_installer(inject=inject), 1, self.output)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertFalse(self.restarted.exists(), 'Failed rollback must not restart an unverified target')
        self.assertIn('Rollback failed', self.log_text)
        self.assertNotIn('Updated ', self.log_text)
        self.assertNotIn('Started updated application.', self.log_text)

    def test_locked_target_remains_usable_after_atomic_replace_retries(self):
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        create_file.restype = ctypes.c_void_p
        close_handle = ctypes.windll.kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        # Read sharing permits hashes but denies rename/delete/write replacement.
        handle = create_file(str(self.target), 0x80000000, 0x1, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.assertEqual(self.run_installer(), 1, self.output)
        finally:
            close_handle(handle)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertNotIn('Updated ', self.log_text)

    def test_wait_timeout_never_kills_or_restarts_owned_target_process(self):
        process_dir = self.root / 'owned process'
        process_dir.mkdir()
        self.target = process_dir / 'powershell.exe'
        shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe', self.target)
        original = self.target.read_bytes()
        sleeper = subprocess.Popen([str(self.target), '-NoProfile', '-Command', 'Start-Sleep -Seconds 25'],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertEqual(self.run_installer(wait_pid=sleeper.pid), 2, self.output)
            self.assertIsNone(sleeper.poll(), 'Installer terminated a still-running application')
            self.assertEqual(self.target.read_bytes(), original)
            self.assertEqual(self.source.read_bytes(), self.new)
            self.assertFalse(self.restarted.exists(), 'Timeout launched a duplicate application')
            self.assertIn('Update deferred', self.log_text)
        finally:
            if sleeper.poll() is None:
                sleeper.terminate()  # Only this test-created child; no user process enumeration.
            sleeper.communicate(timeout=3)


if __name__ == '__main__':
    unittest.main()
