"""PRU desktop view driven exclusively by the mobile-equivalent controller."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QGroupBox, QScrollArea, QTreeWidget, QTreeWidgetItem, QPlainTextEdit, QMessageBox,
)
from qasync import asyncSlot
from ..constants import PACKET_CONTROL, PACKET_STATIC_PARAMETER
from .dynamic_info_card import DynamicInfoCard
from ..pru_controller import PruController


class InfoCard(QGroupBox):
    def __init__(self, title):
        super().__init__(title)
        layout = QVBoxLayout(self)
        self.refresh_btn = QPushButton("刷新")
        layout.addWidget(self.refresh_btn)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["欄位", "值"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setMinimumHeight(250)
        layout.addWidget(self.tree)
        self._rows = None

    def render(self, rows, error, loading, updated):
        stamp = datetime.fromtimestamp(time.time() - (time.monotonic() - updated)).strftime("%H:%M:%S") if updated else "—"
        self.status.setText(error or ("讀取中…" if loading else f"最後更新 {stamp}"))
        if rows != self._rows:
            self._rows = rows
            self.tree.clear()
            for key, value in rows:
                self.tree.addTopLevelItem(QTreeWidgetItem([key, value]))


class PruTestPage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, ble, parent=None):
        super().__init__(parent)
        self.ble = ble
        self.controller = None
        self._closing = None
        self._init_task = None
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.back_btn = QPushButton("← 返回")
        self.back_btn.clicked.connect(self._request_back)
        top.addWidget(self.back_btn)
        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        top.addWidget(self.status_banner, 1)
        self.retry_btn = QPushButton("重新連線 / 探索服務")
        self.retry_btn.clicked.connect(self._retry)
        top.addWidget(self.retry_btn)
        root.addLayout(top)
        self.snack = QLabel()
        self.snack.setWordWrap(True)
        root.addWidget(self.snack)
        self._snack_timer = QTimer(self)
        self._snack_timer.setSingleShot(True)
        self._snack_timer.timeout.connect(self.snack.clear)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        root.addWidget(scroll)
        body = QVBoxLayout(content)
        self.ptu_combo, self.ptu_send_btn, self.ptu_result = self._command_row(body, "PTU Static Parameter", PACKET_STATIC_PARAMETER, "ptu")
        self.ctrl_combo, self.ctrl_send_btn, self.ctrl_result = self._command_row(body, "PRU Control", PACKET_CONTROL, "control")
        quick = QHBoxLayout()
        self.disable_btn = QPushButton("快速停用 DISABLE")
        self.enable_btn = QPushButton("快速啟用 EN_TIME_SET:0ms")
        self.disable_btn.clicked.connect(lambda: self._send_label("control", "DISABLE"))
        self.enable_btn.clicked.connect(lambda: self._send_label("control", "EN_TIME_SET:0ms"))
        quick.addWidget(self.disable_btn)
        quick.addWidget(self.enable_btn)
        body.addLayout(quick)
        live = QHBoxLayout()
        self.live_btn = QPushButton("即時更新")
        self.live_btn.setCheckable(True)
        self.live_btn.toggled.connect(lambda on: self.controller and self.controller.set_live(on))
        self.interval_combo = QComboBox()
        for text, interval in (("500 ms", .5), ("1 s", 1.), ("2 s", 2.)):
            self.interval_combo.addItem(text, interval)
        self.interval_combo.setCurrentIndex(1)
        self.interval_combo.currentIndexChanged.connect(lambda: self.controller and self.controller.set_poll_interval(self.interval_combo.currentData()))
        live.addWidget(self.live_btn)
        live.addWidget(self.interval_combo)
        self.live_status = QLabel()
        live.addWidget(self.live_status, 1)
        body.addLayout(live)
        self.static_card = InfoCard("PRU Static Info")
        self.dynamic_card = DynamicInfoCard()
        self.static_card.refresh_btn.clicked.connect(self._refresh_static)
        self.dynamic_card.refresh_btn.clicked.connect(self._refresh_dynamic)
        body.addWidget(self.dynamic_card)
        body.addWidget(self.static_card)
        self.alert_label = QLabel()
        self.alert_label.setWordWrap(True)
        body.addWidget(self.alert_label)
        body.addWidget(QLabel("事件紀錄（最近 20 筆）"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(170)
        body.addWidget(self.log_view)
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(500)
        self._age_timer.timeout.connect(self._render)

    def _request_back(self):
        if self.controller and self.controller.sending:
            answer = QMessageBox.question(self, "指令寫入中", "現在離開將看不到寫入結果，確定離開？")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.back_requested.emit()

    def _command_row(self, layout, title, packets, group):
        box = QGroupBox(title)
        inner = QVBoxLayout(box)
        row = QHBoxLayout()
        combo = QComboBox()
        combo.addItems(packets)
        button = QPushButton("發送")
        button.clicked.connect(lambda: self._send_label(group, combo.currentText()))
        row.addWidget(combo, 1)
        row.addWidget(button)
        inner.addLayout(row)
        result = QLabel()
        result.setWordWrap(True)
        result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner.addWidget(result)
        layout.addWidget(box)
        return combo, button, result

    @asyncSlot()
    async def enter_page(self):
        if self._closing:
            await self._closing
        if self.controller and not self.controller.disposed:
            return
        self.ptu_combo.setCurrentIndex(0)
        self.ctrl_combo.setCurrentIndex(0)
        self.interval_combo.setCurrentIndex(1)
        self.controller = PruController(self.ble, self._render, self._show_snack)
        self._age_timer.start()
        self._init_task = asyncio.create_task(self.controller.init())
        try:
            await self._init_task
        except asyncio.CancelledError:
            pass

    def leave_page(self):
        self._age_timer.stop()
        if self._init_task and not self._init_task.done():
            self._init_task.cancel()
        if self.controller and not self.controller.disposed:
            self.controller.shutdown()
            self._closing = asyncio.create_task(self.controller.close())
        return self._closing

    @asyncSlot()
    async def _retry(self):
        if not self.controller:
            return
        if self.controller.link_state == "reconnectFailed":
            self.controller.reconnect()
        else:
            await self.controller.init()

    @asyncSlot(str, str)
    async def _send_label(self, group, label):
        if self.controller:
            result = await self.controller.send(group, label)
            self._show_snack(f"{label}：{result.error or '已發送'}")

    @asyncSlot()
    async def _refresh_static(self):
        if self.controller:
            await self.controller.refresh_static()

    @asyncSlot()
    async def _refresh_dynamic(self):
        if self.controller:
            await self.controller.refresh_dynamic()

    def _show_snack(self, text):
        self.snack.setText(text)
        self._snack_timer.start(5000)

    def set_reconnect_status(self, text):
        self.status_banner.setText(text)

    def _render(self):
        c = self.controller
        if not c or c.disposed:
            return
        states = {"discovering": "探索服務中", "ready": "已連線", "reconnecting": f"重新連線 {c.reconnect_attempt}/3",
                  "reconnectFailed": "自動重連失敗", "serviceMissing": "找不到 PRU 服務"}
        self.status_banner.setText(states[c.link_state] + (" · " + c.link_error if c.link_error else ""))
        self.retry_btn.setVisible(c.link_state in ("reconnectFailed", "serviceMissing"))
        for button in (self.ptu_send_btn, self.ctrl_send_btn, self.disable_btn, self.enable_btn):
            button.setEnabled(c.link_state == "ready" and not c.sending)
        for card in (self.static_card, self.dynamic_card):
            card.refresh_btn.setEnabled(c.link_state == "ready")
        self.live_btn.blockSignals(True)
        self.live_btn.setChecked(c.user_wants_live)
        self.live_btn.setText("暫停即時更新" if c.user_wants_live else "啟動即時更新")
        self.live_btn.blockSignals(False)
        live_states = {"running": "更新中", "pausedByUser": "使用者暫停", "pausedBackground": "背景暫停",
                       "pausedLink": "連線暫停", "pausedFailures": "連續 5 次失敗，請重新啟動即時更新"}
        self.live_status.setText(live_states[c.live_state] + (" · 資料過期" if c.is_stale else ""))
        for group, label in (("ptu", self.ptu_result), ("control", self.ctrl_result)):
            r = c.results.get(group)
            label.setText("" if r is None else f"{r.label} · {r.phase} · {r.latency * 1000:.0f} ms\n{r.error or r.response}")
        static_rows = [] if c.static is None else c.static.as_display_lines()
        if c.static:
            if c.static.vrect_min_static_mv > c.static.vrect_set_mv or c.static.vrect_set_mv > c.static.vrect_high_static_mv:
                static_rows.append(("警告", "靜態電壓門檻順序不一致"))
            static_rows.append(("RAW", bytes(c.static.raw).hex(" ").upper()))
        self.static_card.render(static_rows, c.static_error, c.static_loading, c.static_updated)
        self.dynamic_card.render_model(c)
        self.alert_label.setText(f"警報通知 {c.alert_count} 筆 · {c.last_alert}")
        text = "\n".join(f"{at} {title} {detail}" for at, title, detail in c.log)
        if self.log_view.toPlainText() != text:
            self.log_view.setPlainText(text)
