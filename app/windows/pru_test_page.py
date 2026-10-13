"""PRU desktop view matching the mobile page's controls and feedback."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QGroupBox, QScrollArea, QMessageBox, QSplitter, QFileDialog, QInputDialog,
)
from qasync import asyncSlot
from ..constants import PACKET_CONTROL, PACKET_STATIC_PARAMETER
from ..pru_controller import PruController
from ..version import APP_VERSION
from .dynamic_info_card import DynamicInfoCard
from .pru_widgets import StaticInfoCard, EventLogCard, clock_text, set_badge


def plain_label():
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class PruTestPage(QWidget):
    back_requested = pyqtSignal()
    session_changed = pyqtSignal()

    def __init__(self, ble, parent=None):
        super().__init__(parent)
        self.ble = ble
        self.controller = None
        self.device_name = ''
        self.device_address = ''
        self.recording_busy = False
        self._record_task = None
        self._export_task = None
        self._export_busy = False
        self._record_error = ''
        self._session_snapshot = None
        self._record_duration = 0
        self._record_started_at = None
        self._page_active = False
        self._enter_generation = 0
        self._shutdown_requested = False
        self._closing = None
        self._init_task = None
        self._snack_action = None
        self._alert_dialog = None
        self._previews = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        top = QHBoxLayout()
        self.back_btn = QPushButton('← 返回')
        self.back_btn.clicked.connect(self._request_back)
        top.addWidget(self.back_btn)
        self.status_banner = plain_label()
        top.addWidget(self.status_banner, 1)
        self.retry_btn = QPushButton('重新連線 / 探索服務')
        self.retry_btn.clicked.connect(self._retry)
        top.addWidget(self.retry_btn)
        root.addLayout(top)
        controls = QHBoxLayout()
        self.record_btn = QPushButton('● 開始紀錄')
        self.record_btn.clicked.connect(self._toggle_recording)
        self.export_btn = QPushButton('匯出 CSV')
        self.export_btn.clicked.connect(self._export_csv)
        self.freeze_btn = QPushButton('凍結畫面')
        self.freeze_btn.setCheckable(True)
        self.freeze_btn.setToolTip('只停止數值與 RAW 畫面更新，背景收集與紀錄照常進行')
        self.freeze_btn.toggled.connect(self._set_frozen)
        self.marker_btn = QPushButton('加入標記')
        self.marker_btn.clicked.connect(self._add_marker)
        self.live_btn = QPushButton('開始收集')
        self.live_btn.setCheckable(True)
        self.live_btn.toggled.connect(lambda on: self.controller and self.controller.set_live(on))
        self.interval_combo = QComboBox()
        for text, interval in (('500 ms', .5), ('1 s', 1.), ('2 s', 2.)):
            self.interval_combo.addItem(text, interval)
        self.interval_combo.setCurrentIndex(1)
        self.interval_combo.currentIndexChanged.connect(lambda: self.controller and self.controller.set_poll_interval(self.interval_combo.currentData()))
        for control in (self.record_btn, self.export_btn, self.freeze_btn, self.marker_btn):
            controls.addWidget(control)
        controls.addStretch()
        controls.addWidget(QLabel('收集間隔'))
        controls.addWidget(self.interval_combo)
        controls.addWidget(self.live_btn)
        root.addLayout(controls)
        states = QHBoxLayout()
        self.live_status = plain_label()
        self.record_status = plain_label()
        states.addWidget(self.live_status, 1)
        states.addWidget(self.record_status, 1)
        root.addLayout(states)
        self.record_path = plain_label()
        self.record_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.record_path)
        self.record_error = plain_label()
        root.addWidget(self.record_error)
        self.record_error.hide()
        self.snack_box = QWidget()
        snack_row = QHBoxLayout(self.snack_box)
        snack_row.setContentsMargins(0, 0, 0, 0)
        self.snack = plain_label()
        self.snack_action_btn = QPushButton()
        self.snack_action_btn.clicked.connect(self._run_snack_action)
        snack_row.addWidget(self.snack, 1)
        snack_row.addWidget(self.snack_action_btn)
        root.addWidget(self.snack_box)
        self.snack_box.hide()
        self._snack_timer = QTimer(self)
        self._snack_timer.setSingleShot(True)
        self._snack_timer.timeout.connect(self._clear_snack)

        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self.vertical_splitter.setChildrenCollapsible(False)
        self.vertical_splitter.setHandleWidth(8)
        root.addWidget(self.vertical_splitter, 1)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(8)
        self.vertical_splitter.addWidget(self.workspace_splitter)
        left = QWidget()
        left.setMinimumWidth(440)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.page_state = plain_label()
        self.page_state.setMinimumHeight(120)
        self.page_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.page_state)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        self.scroll.setWidget(content)
        left_layout.addWidget(self.scroll, 1)
        self.workspace_splitter.addWidget(left)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self.static_card = StaticInfoCard()
        self.dynamic_card = DynamicInfoCard()
        self.static_card.refresh_btn.clicked.connect(self._refresh_static)
        self.dynamic_card.refresh_btn.clicked.connect(self._refresh_dynamic)
        body.addWidget(self.dynamic_card)
        body.addWidget(self.static_card)
        self.diagnostic_btn = QPushButton('診斷資料（RAW / 通知計數）')
        self.diagnostic_btn.setCheckable(True)
        body.addWidget(self.diagnostic_btn)
        self.diagnostics = QWidget()
        diagnostic_layout = QVBoxLayout(self.diagnostics)
        self.alert_label = plain_label()
        self.raw_label = plain_label()
        for label in (self.alert_label, self.raw_label):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            diagnostic_layout.addWidget(label)
        body.addWidget(self.diagnostics)
        self.diagnostics.hide()
        self.diagnostic_btn.toggled.connect(self.diagnostics.setVisible)
        body.addStretch()
        self.command_scroll = QScrollArea()
        self.command_scroll.setWidgetResizable(True)
        self.command_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.command_scroll.setMinimumWidth(286)
        commands = QWidget()
        command_layout = QVBoxLayout(commands)
        command_layout.setContentsMargins(0, 0, 0, 0)
        self.ptu_combo, self.ptu_send_btn, self.ptu_result = self._command_row(command_layout, 'PTU Static Parameter', PACKET_STATIC_PARAMETER, 'ptu')
        self.ctrl_combo, self.ctrl_send_btn, self.ctrl_result = self._command_row(command_layout, 'PRU Control', PACKET_CONTROL, 'control')
        quick = QGroupBox('快速操作')
        quick_layout = QVBoxLayout(quick)
        self.disable_btn = QPushButton('快速停用 DISABLE')
        self.enable_btn = QPushButton('快速啟用 EN_TIME_SET:0ms')
        self.disable_btn.clicked.connect(lambda: self._send_label('control', 'DISABLE'))
        self.enable_btn.clicked.connect(lambda: self._send_label('control', 'EN_TIME_SET:0ms'))
        quick_layout.addWidget(self.disable_btn)
        quick_layout.addWidget(self.enable_btn)
        command_layout.addWidget(quick)
        command_hint = plain_label()
        command_hint.setText('寫入完成後觀察狀態變化；狀態無變化不代表指令失敗。')
        command_layout.addWidget(command_hint)
        command_layout.addStretch()
        self.command_scroll.setWidget(commands)
        self.workspace_splitter.addWidget(self.command_scroll)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([650, 290])
        self.log_view = EventLogCard()
        self.vertical_splitter.addWidget(self.log_view)
        self.vertical_splitter.setStretchFactor(0, 3)
        self.vertical_splitter.setStretchFactor(1, 2)
        self.vertical_splitter.setSizes([390, 260])
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(500)
        self._age_timer.timeout.connect(self._render)
        self.record_path.setText('尚未存檔 · 即時緩衝僅保留最近 1000 筆事件')
        self.export_btn.setEnabled(False)
        self.record_btn.setEnabled(False)

    def _request_back(self):
        if self.recording_busy:
            return
        if self.controller and self.controller.sending:
            answer = QMessageBox.question(self, '指令寫入中', '現在離開將看不到寫入結果，確定離開？')
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.back_requested.emit()

    def _command_row(self, layout, title, packets, group):
        box = QGroupBox(title)
        inner = QVBoxLayout(box)
        row = QHBoxLayout()
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.addItems(packets)
        button = QPushButton('發送')
        button.clicked.connect(lambda: self._send_label(group, combo.currentText()))
        row.addWidget(combo, 1)
        row.addWidget(button)
        inner.addLayout(row)
        preview = plain_label()
        preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner.addWidget(preview)
        self._previews[group] = preview

        def update_preview(label):
            payload = packets[label]
            preview.setText(f'{len(payload)} B: {bytes(payload).hex(" ").upper()}')
        combo.currentTextChanged.connect(update_preview)
        update_preview(combo.currentText())
        result = plain_label()
        result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner.addWidget(result)
        layout.addWidget(box)
        return combo, button, result

    @asyncSlot()
    async def enter_page(self):
        generation = self._enter_generation
        if self._shutdown_requested:
            return
        if self._closing:
            await self._closing
        if self._shutdown_requested or generation != self._enter_generation:
            return
        self._page_active = True
        if self.controller and not self.controller.disposed:
            self._age_timer.start()
            self._render()
            return
        self._clear_snack()
        self.ptu_combo.setCurrentIndex(0)
        self.ctrl_combo.setCurrentIndex(0)
        self.interval_combo.setCurrentIndex(1)
        self.static_card.reset()
        self.freeze_btn.setChecked(False)
        self.dynamic_card.details_btn.setChecked(False)
        self._record_error = ''
        self.diagnostic_btn.setChecked(False)
        self.controller = PruController(self.ble, self._render, self._show_alert_snack, self._show_link_event)
        self._age_timer.start()
        self._init_task = asyncio.create_task(self.controller.init())
        try:
            await self._init_task
        except asyncio.CancelledError:
            pass

    def leave_page(self, force=False):
        self._enter_generation += 1
        if force:
            self._shutdown_requested = True
        self._page_active = False
        self._age_timer.stop()
        self._clear_snack()
        if self._alert_dialog:
            self._alert_dialog.close()
            self._alert_dialog = None
        if not force and self.controller and getattr(self.controller, 'recording', False):
            return None
        if self._init_task and not self._init_task.done():
            self._init_task.cancel()
        if self.controller and not self.controller.disposed:
            self.controller.shutdown()
            self._closing = asyncio.create_task(self.controller.close())
        return self._closing

    async def wait_recording_operation(self):
        for task in (self._record_task, self._export_task):
            if task and task is not asyncio.current_task() and not task.done():
                await asyncio.shield(task)

    def _set_frozen(self, frozen):
        self.freeze_btn.setText('恢復畫面' if frozen else '凍結畫面')
        self._render()

    @asyncSlot()
    async def _toggle_recording(self):
        c = self.controller
        if not c or c.disposed or self.recording_busy:
            return
        recording = getattr(c, 'recording', False)
        path = None
        if not recording:
            proposed = Path.cwd() / f'pru-{datetime.now():%Y%m%d-%H%M%S}.sqlite'
            path, _ = QFileDialog.getSaveFileName(self, '建立新的紀錄檔', str(proposed), 'PRU 紀錄 (*.sqlite)',
                                                options=QFileDialog.Option.DontConfirmOverwrite)
            if not path:
                return
            if Path(path).exists():
                self._record_error = '檔案已存在，請使用新的檔名；既有紀錄不會被覆寫。'
                self._render()
                return
        self.recording_busy = True
        self._record_task = asyncio.current_task()
        self._record_error = ''
        self.session_changed.emit()
        self._render()
        try:
            if recording:
                await c.stop_recording()
                self._show_snack('紀錄已停止，資料已完成寫入', 'success')
            else:
                await c.start_recording(path, metadata={'device_name': self.device_name,
                    'device_address': self.device_address, 'app_version': APP_VERSION,
                    'poll_interval': c.poll_interval})
                self.log_view.source_combo.setCurrentIndex(1)
                self._show_snack('開始紀錄 · 離開此頁或最小化後持續收集' if c.user_wants_live else
                                 '開始紀錄 · 收集目前暫停，可按「開始收集」', 'success')
        except Exception as exc:
            self._record_error = f'紀錄失敗：{exc}'
        finally:
            self.recording_busy = False
            self._record_task = None
            self.session_changed.emit()
            self._render()

    @asyncSlot()
    async def _export_csv(self):
        c = self.controller
        recorder = getattr(c, 'recorder', None) if c else None
        if not recorder or self._export_busy or self.recording_busy:
            return
        destination = Path(recorder.path).with_name(Path(recorder.path).stem + f'-export-{datetime.now():%H%M%S}.csv')
        path, _ = QFileDialog.getSaveFileName(self, '匯出量測與事件 CSV', str(destination), 'CSV (*.csv)',
                                            options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if Path(path).exists():
            self._record_error = '匯出檔已存在，請使用新的檔名；既有檔案不會被覆寫。'
            self._render()
            return
        self._export_busy = True
        self._export_task = asyncio.current_task()
        self._record_error = ''
        self._render()
        try:
            exported = await recorder.export_csv(path)
            if c is self.controller and not c.disposed:
                self._show_snack(f'CSV 已匯出：{exported}', 'success', duration_ms=6000)
        except Exception as exc:
            if c is self.controller:
                self._record_error = f'匯出失敗：{exc}'
        finally:
            self._export_busy = False
            self._export_task = None
            self._render()

    def _add_marker(self):
        c = self.controller
        if not c or c.disposed:
            return
        text, accepted = QInputDialog.getText(self, '加入人工標記', '簡述此刻的操作或觀察：')
        if accepted and text.strip():
            c.add_marker(text.strip())
            self._render()

    @asyncSlot()
    async def _retry(self):
        if not self.controller:
            return
        if self.controller.link_state == 'reconnectFailed':
            self.controller.reconnect()
        elif self.controller.link_state == 'serviceMissing':
            await self.controller.init()

    @asyncSlot(str, str)
    async def _send_label(self, group, label):
        c = self.controller
        if not c or c.disposed:
            return
        result = await c.send(group, label)
        if c.disposed or c is not self.controller:
            return
        if result.phase == 'sent':
            self._show_snack(f'寫入完成 {label} · {result.latency * 1000:.0f} ms', 'success')
        elif result.phase == 'timeout':
            self._show_snack(f'寫入逾時 (8 s)：{label}', 'warning')
        else:
            self._show_snack(f'寫入失敗：{result.error}', 'error', '重試',
                             lambda: self._send_label(group, result.label))

    @asyncSlot()
    async def _refresh_static(self):
        if self.controller and not self.controller.static_loading:
            await self.controller.refresh_static()

    @asyncSlot()
    async def _refresh_dynamic(self):
        if self.controller:
            await self.controller.refresh_dynamic()

    def _clear_snack(self):
        self._snack_timer.stop()
        self._snack_action = None
        self.snack.clear()
        self.snack_action_btn.hide()
        self.snack_box.hide()

    def _show_snack(self, text, level='info', action_label='', action=None, duration_ms=None):
        set_badge(self.snack, text, level)
        self._snack_action = (self.controller, action) if action else None
        self.snack_action_btn.setText(action_label)
        self.snack_action_btn.setVisible(action is not None)
        self.snack_box.show()
        self._snack_timer.start(duration_ms if duration_ms is not None else 4000 if level == 'error' else 3000)

    def _run_snack_action(self):
        saved = self._snack_action
        self._clear_snack()
        if saved:
            controller, action = saved
            if controller is self.controller and controller and not controller.disposed:
                action()

    def _show_alert_snack(self, alert):
        flags = ', '.join(alert.flags) or '無警報'
        self._show_snack(f'PRU Alert 0x{alert.alert_byte:02X}：{flags}', 'warning', '詳細',
                         lambda: self._show_alert_dialog(alert), duration_ms=5000)

    def _show_alert_dialog(self, alert):
        if self._alert_dialog:
            self._alert_dialog.close()
        dialog = QMessageBox(self)
        dialog.setWindowTitle('PRU Alert Notification')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f'Alert Byte: 0x{alert.alert_byte:02X}\nAddress: {alert.address}\n\n{alert.decoded}')
        dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        dialog.button(QMessageBox.StandardButton.Close).setText('關閉')
        self._alert_dialog = dialog
        dialog.finished.connect(lambda: self._release_alert_dialog(dialog))
        dialog.open()

    def _release_alert_dialog(self, dialog):
        if self._alert_dialog is dialog:
            self._alert_dialog = None
        dialog.deleteLater()

    def _show_link_event(self, entry):
        self._show_snack(entry.title, entry.level)

    def set_reconnect_status(self, text):
        self.status_banner.setText(text)

    def _render(self):
        c = self.controller
        if not c or c.disposed:
            return
        states = {'discovering': '探索服務中', 'ready': '已連線', 'reconnecting': f'重新連線 {c.reconnect_attempt}/3',
                  'reconnectFailed': '自動重連失敗', 'serviceMissing': '找不到 PRU 服務'}
        level = 'success' if c.link_state == 'ready' else 'error' if c.link_state in ('reconnectFailed', 'serviceMissing') else 'info'
        name = self.device_name or getattr(getattr(self.ble, 'device', None), 'name', '') or ''
        set_badge(self.status_banner, states[c.link_state] + (f' · {name}' if name else '') +
                  (' · ' + c.link_error if c.link_error else ''), level)
        recording = getattr(c, 'recording', False)
        recorder = getattr(c, 'recorder', None)
        recorder_error = getattr(recorder, 'error', '') if recorder else ''
        session_snapshot = (recording, self.recording_busy, recorder_error)
        if session_snapshot != self._session_snapshot:
            self._session_snapshot = session_snapshot
            self.session_changed.emit()
        self.back_btn.setEnabled(not self.recording_busy)
        self.record_btn.setEnabled(not self.recording_busy and not self._export_busy and (recording or c.link_state == 'ready'))
        self.record_btn.setText('寫入中…' if self.recording_busy else '■ 停止紀錄' if recording else '● 開始紀錄')
        self.export_btn.setEnabled(recorder is not None and not self.recording_busy and not self._export_busy)
        self.export_btn.setText('匯出中…' if self._export_busy else '匯出 CSV')
        self.marker_btn.setEnabled(not self.recording_busy)
        self.live_btn.setEnabled(not self.recording_busy)
        self.interval_combo.setEnabled(not self.recording_busy)
        if recorder:
            started = getattr(recorder, 'started_at', None)
            if started != self._record_started_at:
                self._record_started_at, self._record_duration = started, 0
            if recording and started:
                try:
                    self._record_duration = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()))
                except (TypeError, ValueError):
                    pass
            hours, rest = divmod(self._record_duration, 3600)
            minutes, seconds = divmod(rest, 60)
            title = '保存異常' if recorder_error else '紀錄中' if recording else '已停止'
            saved = f"量測 {recorder.sample_count} / 事件 {recorder.event_count}"
            pending = getattr(recorder, 'pending_count', 0)
            set_badge(self.record_status, f'{title} · {hours:02d}:{minutes:02d}:{seconds:02d} · 已寫入 {saved}' +
                      (f' · 待寫 {pending}' if pending else ''), 'error' if recorder_error else 'success' if recording else 'muted')
            full_path = str(recorder.path)
            display_path = self.record_path.fontMetrics().elidedText(full_path, Qt.TextElideMode.ElideMiddle, max(200, self.width() - 90))
            self.record_path.setText('紀錄檔：' + display_path)
            self.record_path.setToolTip(full_path)
        else:
            set_badge(self.record_status, '未開始紀錄 · 尚未存檔', 'warning')
            self.record_path.setText('即時緩衝僅保留最近 1000 筆事件；開始紀錄後保留完整量測、指令、警報與 RAW。')
            self.record_path.setToolTip('')
        storage_error = self._record_error or (f'保存錯誤：{recorder_error}' if recorder_error else '')
        self.record_error.setVisible(bool(storage_error))
        if storage_error:
            set_badge(self.record_error, storage_error, 'error')
        self.retry_btn.setVisible(c.link_state in ('reconnectFailed', 'serviceMissing'))
        content_visible = c.link_state not in ('discovering', 'serviceMissing')
        self.scroll.setVisible(content_visible)
        self.page_state.setVisible(not content_visible)
        self.page_state.setText('搜尋 PRU 服務…' if c.link_state == 'discovering' else c.link_error)
        interactive = c.link_state == 'ready' and not c.sending
        for control in (self.ptu_combo, self.ctrl_combo, self.ptu_send_btn, self.ctrl_send_btn, self.disable_btn, self.enable_btn):
            control.setEnabled(interactive)
        self.dynamic_card.refresh_btn.setEnabled(c.link_state == 'ready')
        self.live_btn.blockSignals(True)
        self.live_btn.setChecked(c.user_wants_live)
        self.live_btn.setText('暫停收集' if c.user_wants_live else '開始收集')
        self.live_btn.blockSignals(False)
        live_states = {'running': f'收集中 · 每 {c.poll_interval:g} s', 'pausedByUser': '收集已暫停', 'pausedBackground': '背景暫停',
                       'pausedLink': '未連線', 'pausedFailures': '連續失敗已暫停 · 可按讀取一次重試'}
        live_text = live_states[c.live_state]
        live_level = 'info' if c.live_state == 'running' else 'error' if c.live_state in ('pausedLink', 'pausedFailures') else 'warning'
        if c.live_state == 'running' and c.failures:
            live_text += f' · 讀取失敗 ×{c.failures}'
            live_level = 'error'
        elif c.is_stale:
            live_text += ' · 資料過期'
            live_level = 'warning'
        if self.freeze_btn.isChecked():
            live_text += ' · 畫面凍結'
        set_badge(self.live_status, live_text, live_level)
        for group, label, button in (('ptu', self.ptu_result, self.ptu_send_btn), ('control', self.ctrl_result, self.ctrl_send_btn)):
            r = c.results.get(group)
            button.setText('寫入中…' if r and r.phase == 'sending' else '發送')
            if r is None:
                label.hide()
                label.clear()
                continue
            phase_text = {'sending': '寫入中…', 'sent': f'寫入完成 {clock_text(r.at)} · {r.latency * 1000:.0f} ms',
                          'failed': '失敗', 'timeout': '逾時 8 s'}[r.phase]
            detail = (r.response or '觀察回應中…') if r.phase == 'sent' else r.error
            set_badge(label, f'{r.label} · {phase_text}' + (f'\n{detail}' if detail else ''),
                      {'sending': 'info', 'sent': 'success', 'failed': 'error', 'timeout': 'warning'}[r.phase])
            label.show()
        frozen = self.freeze_btn.isChecked()
        self.static_card.render_model(c, frozen=frozen)
        self.dynamic_card.render_model(c, frozen=frozen)
        self.alert_label.setText(f'警報通知 {c.alert_count} 筆 · {c.last_alert}')
        if not frozen:
            self.raw_label.setText('\n'.join(f'{name} RAW    {bytes(data.raw).hex(" ").upper()}'
                                            for name, data in (('Static', c.static), ('Dynamic', c.dynamic)) if data))
        self.log_view.render(c.log, recorder=recorder, total_seen=getattr(c, 'event_count', len(c.log)))
