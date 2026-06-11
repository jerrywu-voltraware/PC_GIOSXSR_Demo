# -*- coding: utf-8 -*-
"""GitHub release based updater for the packaged Windows executable."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from .version import (
    APP_NAME,
    APP_VERSION,
    GITHUB_RELEASES_API,
    RELEASE_ASSET_NAME,
)


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag_name: str
    release_name: str
    body: str
    html_url: str
    asset_name: str | None
    asset_url: str | None


def _version_tuple(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV").split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for part in cleaned.split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts or [0])


def _is_newer(candidate: str, current: str) -> bool:
    left = _version_tuple(candidate)
    right = _version_tuple(current)
    size = max(len(left), len(right), 3)
    return left + (0,) * (size - len(left)) > right + (0,) * (size - len(right))


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )


def _powershell_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def cleanup_update_artifacts() -> None:
    """Remove the .old backup left behind by a previous successful update."""
    if not getattr(sys, "frozen", False):
        return
    target = Path(sys.executable).resolve()
    backup = target.with_name(target.name + ".old")
    try:
        if backup.exists():
            backup.unlink()
    except OSError:
        pass


def _install_script_text(
    source: Path,
    target: Path,
    wait_pid: int,
    log_file: Path,
) -> str:
    # PyInstaller onefile runs as two processes (bootloader parent + child);
    # the script must wait for every process backed by the target exe, not
    # just the Python child's PID, before the image lock is released.
    return f"""$ErrorActionPreference = 'Stop'
$source = {_powershell_literal(source)}
$target = {_powershell_literal(target)}
$backup = "$target.old"
$pidToWait = {wait_pid}
$logFile = {_powershell_literal(log_file)}

function Write-UpdateLog([string]$message) {{
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $logFile -Value "[$timestamp] $message"
}}

function Get-TargetProcesses {{
    Get-Process | Where-Object {{
        try {{ $_.Path -and [string]::Equals($_.Path, $target, 'OrdinalIgnoreCase') }} catch {{ $false }}
    }}
}}

try {{
    Write-UpdateLog "Waiting for PID $pidToWait and every process running $target to exit."
    for ($i = 0; $i -lt 120; $i++) {{
        $running = @()
        $byPid = Get-Process -Id $pidToWait -ErrorAction SilentlyContinue
        if ($byPid) {{ $running += $byPid }}
        $running += @(Get-TargetProcesses)
        if ($running.Count -eq 0) {{ break }}
        Start-Sleep -Milliseconds 500
    }}

    $leftover = @(Get-TargetProcesses)
    if ($leftover.Count -gt 0) {{
        Write-UpdateLog "Force stopping leftover processes: $(($leftover | ForEach-Object Id) -join ', ')"
        $leftover | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }}

    $sourceSize = (Get-Item -LiteralPath $source).Length
    $installed = $false

    for ($attempt = 1; $attempt -le 60; $attempt++) {{
        try {{
            if (Test-Path -LiteralPath $backup) {{
                Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
            }}
            if (Test-Path -LiteralPath $target) {{
                Move-Item -LiteralPath $target -Destination $backup -Force -ErrorAction Stop
            }}
            Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
            $targetSize = (Get-Item -LiteralPath $target).Length
            if ($targetSize -ne $sourceSize) {{
                throw "Size mismatch after copy: $targetSize vs $sourceSize."
            }}
            Write-UpdateLog "Updated $target from $source on attempt $attempt."
            $installed = $true
            break
        }} catch {{
            Write-UpdateLog "Attempt $attempt failed: $($_.Exception.Message)"
            if (-not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $backup)) {{
                try {{ Move-Item -LiteralPath $backup -Destination $target -Force -ErrorAction Stop }} catch {{ }}
            }}
            Start-Sleep -Seconds 1
        }}
    }}

    if (-not $installed) {{
        Write-UpdateLog "Update failed after all retry attempts. Restarting existing app."
    }}
    Start-Sleep -Seconds 3
    Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target)
    if ($installed) {{
        Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }}
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}} catch {{
    try {{ Write-UpdateLog "Fatal updater error: $($_.Exception.Message)" }} catch {{ }}
    try {{
        if (-not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $backup)) {{
            Move-Item -LiteralPath $backup -Destination $target -Force
        }}
    }} catch {{ }}
    try {{
        Start-Sleep -Seconds 3
        Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target)
    }} catch {{ }}
}}
"""


def _fetch_latest_release() -> UpdateInfo | None:
    with urllib.request.urlopen(_request(GITHUB_RELEASES_API), timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    tag_name = str(payload.get("tag_name", "")).strip()
    latest_version = tag_name.lstrip("vV")
    if not latest_version or not _is_newer(latest_version, APP_VERSION):
        return None

    assets = payload.get("assets") or []
    selected = next(
        (asset for asset in assets if asset.get("name") == RELEASE_ASSET_NAME),
        None,
    )
    if selected is None:
        selected = next(
            (asset for asset in assets if str(asset.get("name", "")).lower().endswith(".exe")),
            None,
        )

    return UpdateInfo(
        version=latest_version,
        tag_name=tag_name,
        release_name=str(payload.get("name") or tag_name),
        body=str(payload.get("body") or ""),
        html_url=str(payload.get("html_url") or ""),
        asset_name=str(selected.get("name")) if selected else None,
        asset_url=str(selected.get("browser_download_url")) if selected else None,
    )


class UpdateCheckWorker(QObject):
    finished = pyqtSignal(object, str)

    def run(self) -> None:
        try:
            self.finished.emit(_fetch_latest_release(), "")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self.finished.emit(None, "找不到 GitHub release，請先建立第一個 release。")
            else:
                self.finished.emit(None, f"檢查更新失敗：HTTP {exc.code}")
        except Exception as exc:
            self.finished.emit(None, f"檢查更新失敗：{exc}")


class UpdateDownloadWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(object, str)

    def __init__(self, info: UpdateInfo):
        super().__init__()
        self.info = info

    def run(self) -> None:
        if not self.info.asset_url:
            self.finished.emit(None, "這個 release 沒有可下載的 exe 附件。")
            return

        suffix = Path(self.info.asset_name or RELEASE_ASSET_NAME).suffix or ".exe"
        destination = Path(tempfile.gettempdir()) / f"{APP_NAME}-{self.info.tag_name}{suffix}"

        try:
            with urllib.request.urlopen(_request(self.info.asset_url), timeout=30) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(min(100, int(downloaded * 100 / total)))
            self.progress.emit(100)
            self.finished.emit(destination, "")
        except Exception as exc:
            self.finished.emit(None, f"下載更新失敗：{exc}")


class UpdateController(QObject):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        self._threads: list[QThread] = []
        self._workers: list[QObject] = []
        self._checking = False
        self._downloading = False
        self._manual_check = False
        self._progress_dialog: QProgressDialog | None = None

    def check_for_updates(self, manual: bool = False) -> None:
        if self._checking:
            if manual:
                QMessageBox.information(self._parent, "檢查更新", "正在檢查更新，請稍候。")
            return

        self._checking = True
        self._manual_check = manual
        worker = UpdateCheckWorker()
        self._start_worker(worker, self._on_check_finished)

    def _on_check_finished(self, info: UpdateInfo | None, error: str) -> None:
        self._checking = False
        manual = self._manual_check
        self._manual_check = False

        if error:
            if manual:
                QMessageBox.warning(self._parent, "檢查更新", error)
            return

        if info is None:
            if manual:
                QMessageBox.information(
                    self._parent,
                    "檢查更新",
                    f"目前已是最新版本（v{APP_VERSION}）。",
                )
            return

        if not info.asset_url:
            QMessageBox.information(
                self._parent,
                "發現新版本",
                f"發現 v{info.version}，但 release 沒有 {RELEASE_ASSET_NAME} 附件。\n"
                "將開啟 GitHub release 頁面供手動下載。",
            )
            if info.html_url:
                webbrowser.open(info.html_url)
            return

        details = self._format_release_notes(info.body)
        message = (
            f"發現新版本 v{info.version}（目前版本 v{APP_VERSION}）。\n"
            "按 OK 後會自動下載更新檔。\n\n"
            f"{details}"
        ).strip()
        answer = QMessageBox.question(
            self._parent,
            "發現新版本",
            message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if answer == QMessageBox.StandardButton.Ok:
            self._download_update(info)

    def _download_update(self, info: UpdateInfo) -> None:
        if self._downloading:
            return

        self._downloading = True
        self._progress_dialog = QProgressDialog(
            f"正在下載 v{info.version}...",
            "",
            0,
            100,
            self._parent,
        )
        self._progress_dialog.setWindowTitle("下載更新")
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setCancelButton(None)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setValue(0)

        worker = UpdateDownloadWorker(info)
        worker.progress.connect(self._progress_dialog.setValue)
        self._start_worker(worker, self._on_download_finished)

    def _on_download_finished(self, path: Path | None, error: str) -> None:
        self._downloading = False
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None

        if error or path is None:
            QMessageBox.warning(self._parent, "下載更新", error or "下載更新失敗。")
            return

        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self._parent,
                "下載更新",
                f"更新檔已下載到：\n{path}\n\n"
                "目前是從原始碼啟動，請手動替換打包後的 exe。",
            )
            return

        answer = QMessageBox.question(
            self._parent,
            "安裝更新",
            "更新檔已下載完成。是否立即重新啟動並安裝？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._install_update(path)

    def _install_update(self, downloaded_exe: Path) -> None:
        target = Path(sys.executable).resolve()
        script = Path(tempfile.gettempdir()) / f"{APP_NAME}-apply-update.ps1"
        log_file = Path(tempfile.gettempdir()) / f"{APP_NAME}-apply-update.log"
        script.write_text(
            _install_script_text(downloaded_exe, target, os.getpid(), log_file),
            encoding="utf-8-sig",
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            creationflags=creation_flags,
        )
        QApplication.quit()

    def _start_worker(self, worker: QObject, finished_slot) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(finished_slot)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_worker(thread, worker))
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    def _cleanup_worker(self, thread: QThread, worker: QObject) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        if worker in self._workers:
            self._workers.remove(worker)

    @staticmethod
    def _format_release_notes(body: str) -> str:
        body = body.strip()
        if not body:
            return "Release notes 未填寫。"
        if len(body) > 500:
            return body[:500].rstrip() + "..."
        return body
