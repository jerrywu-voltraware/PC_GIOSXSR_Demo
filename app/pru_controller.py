"""Desktop port of lib/screen/pru/pru_controller.dart.

One controller owns each page session; every GATT operation shares its lock.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from .constants import (
    PACKET_CONTROL, PACKET_STATIC_PARAMETER, UUID_PRU_CONTROL,
    UUID_PTU_STATIC_PARAM, UUID_PRU_DYNAMIC_READ, UUID_PRU_STATIC_READ,
    UUID_PRU_NOTIFY,
)
from .protocol import parse_pru_dynamic, parse_pru_static, parse_alert_notification
from .session_store import SessionRecorder, timestamp
from .version import APP_NAME, APP_VERSION


def friendly_error(exc, timeout_seconds=None):
    if isinstance(exc, TimeoutError):
        return f"逾時 {timeout_seconds} s" if timeout_seconds is not None else "逾時"
    return str(exc) or type(exc).__name__


@dataclass(frozen=True)
class LogEntry:
    at: str
    title: str
    detail: str
    kind: str
    level: str


@dataclass
class CommandResult:
    label: str
    uuid: str
    phase: str
    at: float
    latency: float = 0
    error: str = ""
    response: str = ""


class PruController:
    notify_delay = .5
    reconnect_backoff = (0, 2, 4)
    watch_window = 3

    def __init__(self, ble, changed=lambda: None, alert_snack=lambda alert: None,
                 link_event=lambda entry: None):
        self.ble = ble
        self.changed = changed
        self.alert_snack = alert_snack
        self.link_event = link_event
        self.link_state = "discovering"
        self.link_error = ""
        self.reconnect_attempt = 0
        self.user_wants_live = False
        self.foreground = True
        self.poll_interval = 1.
        self.failures = 0
        self.static = self.dynamic = None
        self.static_error = self.dynamic_error = ""
        self.static_updated = self.dynamic_updated = None
        self.static_loading = self.dynamic_loading = True
        self.sending = False
        self.results = {}
        self.log = deque(maxlen=1000)
        self.event_count = 0
        self.recorder = None
        self._recording = False
        self._recording_lock = asyncio.Lock()
        self.alert_count = 0
        self.last_alert = ""
        self.last_alert_data = None
        self._last_snack = None
        self._lock = asyncio.Lock()
        self._tasks = set()
        self._loop_task = self._reconnect_task = None
        self._watches = {}
        self.disposed = False

    @property
    def recording(self):
        return self._recording

    @property
    def live_state(self):
        if not self.user_wants_live:
            return "pausedByUser"
        if self.link_state != "ready":
            return "pausedLink"
        if not self.foreground and not self.recording:
            return "pausedBackground"
        if self.failures >= 5:
            return "pausedFailures"
        return "running"

    @property
    def is_stale(self):
        return (self.live_state == "running" and self.dynamic_updated is not None
                and time.monotonic() - self.dynamic_updated > 3 * self.poll_interval)

    def _emit(self):
        if not self.disposed:
            self.changed()

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _log(self, title, detail="", *, kind="link", level="info", raw=None, data=None):
        entry = LogEntry(timestamp(), title, detail, kind, level)
        self.log.appendleft(entry)
        self.event_count += 1
        if self.recording:
            self.recorder.record_event(title, detail, kind=kind, level=level, raw=raw, data=data, at=entry.at)
        return entry

    def add_marker(self, text):
        if self.disposed or not str(text).strip():
            return
        self._log("人工標記", str(text).strip(), kind="marker")
        self._emit()

    async def start_recording(self, path, metadata=None):
        async with self._recording_lock:
            if self.disposed:
                raise RuntimeError("Controller is closed")
            if self.recording:
                raise RuntimeError("A recording session is already open")
            address = getattr(self.ble, "address", None)
            device = getattr(self.ble, "device", None)
            details = {"app_name": APP_NAME, "app_version": APP_VERSION,
                       "device_address": address or getattr(device, "address", None),
                       "device_name": getattr(self.ble, "device_names", {}).get(address)
                                      or getattr(device, "name", None),
                       "poll_interval_seconds": self.poll_interval,
                       "link_state_at_start": self.link_state,
                       "collecting_at_start": self.user_wants_live}
            details.update(metadata or {})
            recorder = await SessionRecorder.create(path, details)
            if self.disposed:
                await recorder.close()
                raise RuntimeError("Controller closed while starting recording")
            self.recorder = recorder
            self._recording = True
            self._log("開始儲存", str(recorder.path), kind="recording")
            if self.static is not None:
                recorder.record_static(self.static)
                self._log("Static 快照", "開始儲存時保留最近一次 Static 資料", kind="read")
            self._emit()
            self._maybe_loop()
            return recorder

    async def stop_recording(self):
        async with self._recording_lock:
            if not self.recording:
                return
            self._log("停止儲存", "等待已接收資料寫入磁碟", kind="recording")
            self._recording = False
            self._emit()
            try:
                await self.recorder.close()
            finally:
                self._emit()

    def _emit_link(self, title, detail, level):
        entry = self._log(title, detail, level=level)
        if not self.disposed:
            self.link_event(entry)

    async def _op(self, operation):
        async with self._lock:
            if self.disposed:
                raise asyncio.CancelledError
            return await operation()

    async def init(self):
        if self.disposed:
            return
        self.ble.set_notification_callback(self.on_notification)
        self.link_state = "discovering"
        self.link_error = ""
        self._emit()
        if not self.ble.is_connected:
            self.on_disconnected()
            return
        try:
            await self._op(self.ble.discover)
            await asyncio.sleep(self.notify_delay)
            if self.disposed or self.link_state != "discovering":
                return
            try:
                await self._op(lambda: self.ble.enable_notify(UUID_PRU_NOTIFY))
            except Exception as exc:
                self._log("警報通知啟用失敗", friendly_error(exc), level="warning")
            if self.disposed or self.link_state != "discovering":
                return
            if self.ble.find_target_service() is None:
                self._service_missing()
                return
            self.link_state = "ready"
            self._log("PRU 已就緒", "服務探索及通知設定完成")
            self._emit()
            await self.refresh_static()
            self.set_live(True)
        except Exception as exc:
            if self.link_state == "discovering":
                self._service_missing(friendly_error(exc))

    def _service_missing(self, message="找不到目標 Service (fffe/bbbb)"):
        self.link_state = "serviceMissing"
        self.link_error = message
        self.static_loading = self.dynamic_loading = False
        self.static_error = self.dynamic_error = message
        self._log("找不到 PRU 服務", message, level="error")
        self._emit()

    def on_disconnected(self):
        if self.disposed or self.link_state == "reconnectFailed":
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self.link_state = "reconnecting"
        self._log("連線中斷", "暫停讀取並嘗試重新連線", level="warning")
        self._reconnect_task = self._spawn(self._reconnect())
        self._emit()

    def reconnect(self):
        if self.link_state == "reconnectFailed":
            self.link_state = "reconnecting"
            self.on_disconnected()

    async def _reconnect(self):
        for attempt, delay in enumerate(self.reconnect_backoff, 1):
            self.reconnect_attempt = attempt
            self._emit()
            await asyncio.sleep(delay)
            try:
                await self._op(self.ble.disable_all_notify)
                await self._op(self.ble.reconnect)
                await self._op(self.ble.discover)
                if self.ble.find_target_service() is None:
                    self._service_missing()
                    return
                await asyncio.sleep(self.notify_delay)
                await self._op(lambda: self.ble.enable_notify(UUID_PRU_NOTIFY))
                self.link_state = "ready"
                self.link_error = ""
                self._emit_link("已重新連線", f"第 {attempt}/3 次", "success")
                self._maybe_loop()
                await self.refresh_static()
                return
            except Exception as exc:
                self.link_error = friendly_error(exc)
                self._log(f"重新連線失敗（第 {attempt}/3 次）", self.link_error, level="warning")
                self._emit()
        self.link_state = "reconnectFailed"
        self._emit_link("自動重新連線失敗", self.link_error, "error")
        self._emit()

    async def refresh_static(self):
        self.static_loading = True
        self._emit()
        raw = None
        try:
            raw = await self._op(lambda: self.ble.read_pru(UUID_PRU_STATIC_READ))
            observed_at, observed_monotonic = timestamp(), time.monotonic()
            self.static = parse_pru_static(raw)
            self.static_updated = observed_monotonic
            self.static_error = ""
            if self.recording:
                self.recorder.record_static(self.static, at=observed_at, monotonic=observed_monotonic)
        except Exception as exc:
            self.static_error = friendly_error(exc, 5)
            if self.recording:
                self.recorder.record_static(raw=raw, error=self.static_error)
            self._log("Static 讀取失敗", self.static_error, kind="read", level="error", raw=raw)
        finally:
            self.static_loading = False
            self._emit()

    async def refresh_dynamic(self):
        self.dynamic_loading = True
        self._emit()
        raw = None
        try:
            raw = await self._op(lambda: self.ble.read_pru(UUID_PRU_DYNAMIC_READ))
            observed_at, observed_monotonic = timestamp(), time.monotonic()
            self.dynamic = parse_pru_dynamic(raw)
            self.dynamic_updated = observed_monotonic
            self.dynamic_error = ""
            self.failures = 0
            if self.recording:
                self.recorder.record_sample(self.dynamic, at=observed_at, monotonic=observed_monotonic)
            for group, (baseline, timer) in list(self._watches.items()):
                if baseline is None:
                    response = (f"無基準資料：Validity 0x{self.dynamic.optional_fields_validity:02X} · "
                                f"Alert 0x{self.dynamic.pru_alert:02X} · Tester 0x{self.dynamic.tester_cmd:02X}")
                else:
                    changes = [f"{label} 0x{getattr(baseline, attr):02X}→0x{getattr(self.dynamic, attr):02X}"
                               for attr, label in (("tester_cmd", "Tester Cmd"), ("pru_alert", "Alert"),
                                                   ("optional_fields_validity", "Validity"))
                               if getattr(baseline, attr) != getattr(self.dynamic, attr)]
                    response = "狀態變化：" + ", ".join(changes) if changes else ""
                if response:
                    self._finish_watch(group, response)
        except Exception as exc:
            self.dynamic_error = friendly_error(exc, 5)
            self.failures += 1
            if self.recording:
                self.recorder.record_sample(raw=raw, error=self.dynamic_error)
            self._log("Dynamic 讀取失敗", self.dynamic_error, kind="read", level="error", raw=raw)
            if self.failures == 5:
                self._log("收集已自動暫停", "連續 5 次讀取失敗；請確認連線後手動恢復收集",
                          kind="collection", level="warning")
        finally:
            self.dynamic_loading = False
            self._emit()
        self._maybe_loop()

    def set_live(self, on):
        if self.disposed:
            return
        changed = self.user_wants_live != on or (on and self.failures)
        self.user_wants_live = on
        if on:
            self.failures = 0
        if changed:
            self._log("恢復收集" if on else "暫停收集", f"輪詢間隔 {self.poll_interval:g} s", kind="collection")
        self._emit()
        self._maybe_loop()

    def set_foreground(self, foreground):
        if self.foreground != foreground:
            self._log("視窗回到前景" if foreground else "視窗進入背景",
                      "儲存中，背景持續收集" if self.recording and not foreground else
                      ("背景暫停收集" if not foreground else "依收集設定恢復輪詢"), kind="collection")
        self.foreground = foreground
        self._emit()
        self._maybe_loop()

    def set_poll_interval(self, interval):
        if interval in (.5, 1, 2):
            if self.poll_interval != interval:
                self._log("更新輪詢間隔", f"{self.poll_interval:g} → {interval:g} s", kind="collection")
            self.poll_interval = interval
            self._emit()

    def _maybe_loop(self):
        if self.disposed or self.live_state != "running":
            return
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = self._spawn(self._run_loop())

    async def _run_loop(self):
        while not self.disposed and self.live_state == "running":
            start = time.monotonic()
            await self.refresh_dynamic()
            await asyncio.sleep(max(0, self.poll_interval - (time.monotonic() - start)))

    async def send(self, group, label):
        uuid = UUID_PTU_STATIC_PARAM if group == "ptu" else UUID_PRU_CONTROL
        result = CommandResult(label, uuid, "failed", time.monotonic())
        if self.sending or self.disposed or self.link_state != "ready":
            result.error = "另一指令進行中" if self.sending else "未連線"
            self._log(f"指令未發送 {label}", result.error, kind="command", level="warning")
            return result
        packets = PACKET_STATIC_PARAMETER if group == "ptu" else PACKET_CONTROL
        payload = packets[label]
        packet_detail = f"…{uuid[-4:]} · {len(payload)} B: {bytes(payload).hex(' ').upper()}"
        self.sending = True
        self._cancel_watch(group)
        result.phase = "sending"
        self.results[group] = result
        self._log(f"發送中 {label}", packet_detail, kind="command", raw=payload,
                  data={"uuid": uuid, "phase": "sending", "group": group})
        self._emit()
        try:
            async def write():
                start = time.monotonic()
                await self.ble.write_pru(uuid, payload)
                return time.monotonic() - start
            result.latency = await self._op(write)
            result.phase = "sent"
            self._log(f"已發送 {label}", f"{packet_detail} · {result.latency * 1000:.0f} ms",
                      kind="command", level="success", raw=payload,
                      data={"uuid": uuid, "phase": result.phase, "latency_seconds": result.latency})
        except asyncio.CancelledError:
            self._log(f"指令等待已取消 {label}", f"{packet_detail} · 無法確認設備是否收到",
                      kind="command", level="warning", raw=payload)
            raise
        except TimeoutError:
            result.phase, result.error = "timeout", "逾時 8 s"
            self._log(f"寫入逾時 {label}", f"{packet_detail} · {result.error}", kind="command", level="warning", raw=payload)
        except Exception as exc:
            result.phase, result.error = "failed", friendly_error(exc)
            self._log(f"寫入失敗 {label}", f"{packet_detail} · {result.error}", kind="command", level="error", raw=payload)
        finally:
            self.sending = False
            self._emit()
        if result.phase == "sent" and not self.disposed:
            handle = asyncio.get_running_loop().call_later(self.watch_window, self._expire_watch, group)
            self._watches[group] = (self.dynamic, handle)
            self._spawn(self.refresh_dynamic())
        return result

    def _cancel_watch(self, group):
        watch = self._watches.pop(group, None)
        if watch:
            watch[1].cancel()

    def _finish_watch(self, group, response):
        self._cancel_watch(group)
        self.results[group].response = response
        self._log(f"指令觀測 {self.results[group].label}", response, kind="command")
        self._emit()

    def _expire_watch(self, group):
        if group in self._watches and not self.disposed:
            self._finish_watch(group, "3 s 內狀態位元組無變化（不代表失敗）"
                               if self.live_state == "running" else "輪詢暫停，無法觀察回應")

    def on_notification(self, uuid, raw):
        if self.disposed or uuid.lower() != UUID_PRU_NOTIFY:
            return
        if not raw:
            self._log("警報資料無效", "警報資料為空", kind="alert", level="error", raw=raw)
            self._emit()
            return
        self.alert_count += 1
        alert = parse_alert_notification(raw)
        self.last_alert_data = alert
        title = f"PRU Alert 0x{alert.alert_byte:02X}"
        detail = alert.decoded.replace("\n", " · ") + f" · Addr {alert.address}"
        self.last_alert = f"{title} · {detail}"
        self._log(title, detail, kind="alert", level=("error" if alert.is_fault else
                                                     "info" if alert.alert_byte == 0 else "warning"), raw=raw)
        now = time.monotonic()
        if self._last_snack is None or now - self._last_snack >= 5:
            self._last_snack = now
            self.alert_snack(alert)
        self._emit()

    def shutdown(self):
        if self.disposed:
            return
        self.disposed = True
        for group in list(self._watches):
            self._cancel_watch(group)
        for task in list(self._tasks):
            task.cancel()

    async def close(self):
        self.shutdown()
        try:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            async with self._lock:
                await self.ble.disable_all_notify()
        finally:
            await self.stop_recording()
