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
from .protocol import parse_pru_dynamic, parse_pru_static, parse_alert_byte, format_mac_from_notify


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

    def __init__(self, ble, changed=lambda: None, alert_snack=lambda text: None):
        self.ble = ble
        self.changed = changed
        self.alert_snack = alert_snack
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
        self.log = deque(maxlen=20)
        self.alert_count = 0
        self.last_alert = ""
        self._last_snack = None
        self._lock = asyncio.Lock()
        self._tasks = set()
        self._loop_task = self._reconnect_task = None
        self._watches = {}
        self.disposed = False

    @property
    def live_state(self):
        if not self.user_wants_live:
            return "pausedByUser"
        if self.link_state != "ready":
            return "pausedLink"
        if not self.foreground:
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

    def _log(self, title, detail=""):
        self.log.appendleft((time.strftime("%H:%M:%S"), title, detail))

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
                self._log("警報通知啟用失敗", str(exc))
            if self.disposed or self.link_state != "discovering":
                return
            if self.ble.find_target_service() is None:
                self._service_missing()
                return
            self.link_state = "ready"
            self._emit()
            await self.refresh_static()
            self.set_live(True)
        except Exception as exc:
            if self.link_state == "discovering":
                self._service_missing(str(exc))

    def _service_missing(self, message="找不到目標 Service (fffe/bbbb)"):
        self.link_state = "serviceMissing"
        self.link_error = message
        self.static_loading = self.dynamic_loading = False
        self.static_error = self.dynamic_error = message
        self._log("找不到 PRU 服務", message)
        self._emit()

    def on_disconnected(self):
        if self.disposed or self.link_state == "reconnectFailed":
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self.link_state = "reconnecting"
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
                self._log("已重新連線", f"第 {attempt}/3 次")
                self._maybe_loop()
                await self.refresh_static()
                return
            except Exception as exc:
                self.link_error = str(exc)
                self._log(f"重新連線失敗（第 {attempt}/3 次）", str(exc))
                self._emit()
        self.link_state = "reconnectFailed"
        self._emit()

    async def refresh_static(self):
        self.static_loading = True
        self._emit()
        try:
            raw = await self._op(lambda: self.ble.read_pru(UUID_PRU_STATIC_READ))
            self.static = parse_pru_static(raw)
            self.static_updated = time.monotonic()
            self.static_error = ""
        except Exception as exc:
            self.static_error = str(exc)
        finally:
            self.static_loading = False
            self._emit()

    async def refresh_dynamic(self):
        self.dynamic_loading = True
        self._emit()
        try:
            raw = await self._op(lambda: self.ble.read_pru(UUID_PRU_DYNAMIC_READ))
            self.dynamic = parse_pru_dynamic(raw)
            self.dynamic_updated = time.monotonic()
            self.dynamic_error = ""
            self.failures = 0
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
            self.dynamic_error = str(exc)
            self.failures += 1
        finally:
            self.dynamic_loading = False
            self._emit()
        self._maybe_loop()

    def set_live(self, on):
        if self.disposed:
            return
        self.user_wants_live = on
        if on:
            self.failures = 0
        self._emit()
        self._maybe_loop()

    def set_foreground(self, foreground):
        self.foreground = foreground
        self._emit()
        self._maybe_loop()

    def set_poll_interval(self, interval):
        if interval in (.5, 1, 2):
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
            return result
        packets = PACKET_STATIC_PARAMETER if group == "ptu" else PACKET_CONTROL
        payload = packets[label]
        self.sending = True
        self._cancel_watch(group)
        result.phase = "sending"
        self.results[group] = result
        self._emit()
        try:
            async def write():
                start = time.monotonic()
                await self.ble.write_pru(uuid, payload)
                return time.monotonic() - start
            result.latency = await self._op(write)
            result.phase = "sent"
            self._log(f"已發送 {label}", f"…{uuid[-4:]} · {bytes(payload).hex(' ')} · {result.latency * 1000:.0f} ms")
        except TimeoutError:
            result.phase, result.error = "timeout", "逾時 8 s"
            self._log(f"寫入逾時 {label}", result.error)
        except Exception as exc:
            result.phase, result.error = "failed", str(exc)
            self._log(f"寫入失敗 {label}", result.error)
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
        self._emit()

    def _expire_watch(self, group):
        if group in self._watches and not self.disposed:
            self._finish_watch(group, "3 s 內狀態位元組無變化（不代表失敗）"
                               if self.live_state == "running" else "輪詢暫停，無法觀察回應")

    def on_notification(self, uuid, raw):
        if self.disposed or uuid.lower() != UUID_PRU_NOTIFY or not raw:
            return
        self.alert_count += 1
        self.last_alert = (f"PRU Alert 0x{raw[0]:02X} · Addr {format_mac_from_notify(raw)} · "
                           + " · ".join(parse_alert_byte(raw[0]) or ["⚪ 無警報"]))
        self._log(self.last_alert)
        now = time.monotonic()
        if self._last_snack is None or now - self._last_snack >= 5:
            self._last_snack = now
            self.alert_snack(self.last_alert)
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
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        async with self._lock:
            await self.ble.disable_all_notify()
