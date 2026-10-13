"""Status, static information and event widgets shared by the PRU page."""
from datetime import datetime
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QLabel, QGroupBox, QPushButton, QVBoxLayout,
                            QHBoxLayout, QGridLayout, QTreeWidget, QTreeWidgetItem,
                            QLineEdit, QComboBox, QApplication, QAbstractItemView)

PRIMARY = '#116360'
ERROR = '#c62828'
WARNING = '#b36a00'
SUCCESS = '#187347'
INFO = '#246ea6'
MUTED = '#718181'
COLORS = {'error': ERROR, 'warning': WARNING, 'success': SUCCESS, 'info': INFO,
          'muted': MUTED}
BACKGROUNDS = {'error': '#fff0ef', 'warning': '#fff3df', 'success': '#e5f4eb',
               'info': '#e8f2fb', 'muted': '#eef1f1'}
STATIC_CAPABILITY_LABELS = ('NFC receiver', 'Separate BTLE radio', 'Power Ctrl Algo',
                            'Adjust power', 'Charge complete connected',
                            'PTU test mode', 'RFU', 'RFU')


def clock_text(monotonic_time):
    if monotonic_time is None:
        return '—'
    return datetime.fromtimestamp(time.time() - (time.monotonic() - monotonic_time)).strftime('%H:%M:%S')


def set_badge(label, text, level):
    label.setText(text)
    label.setProperty('level', level)
    label.setStyleSheet(f'color: {COLORS[level]}; background: {BACKGROUNDS[level]}; '
                       'border-radius: 5px; padding: 5px 8px;')


class BitChips(QWidget):
    def __init__(self, labels, *, alert=False):
        super().__init__()
        self.alert = alert
        self.labels = labels
        self.chips = []
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, title in enumerate(labels):
            chip = QLabel(title)
            chip.setWordWrap(True)
            grid.addWidget(chip, i // 2, i % 2)
            self.chips.append(chip)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.set_byte(0)

    def set_byte(self, value):
        for i, (chip, title) in enumerate(zip(self.chips, self.labels)):
            on = bool(value & (0x80 >> i))
            level = 'muted' if not on else (
                ('error' if i <= 3 else 'success' if i == 4 else 'info') if self.alert else 'info')
            set_badge(chip, title, level)
            chip.setProperty('active', on)
            chip.setToolTip(f'bit{7-i} = {int(on)}')


class StaticInfoCard(QGroupBox):
    def __init__(self):
        super().__init__('靜態資訊 · PRU Static Info')
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        self.expand_btn = QPushButton('展開靜態資訊')
        self.expand_btn.setCheckable(True)
        self.expand_btn.toggled.connect(self._toggle)
        self.refresh_btn = QPushButton('重新讀取')
        row.addWidget(self.expand_btn, 1)
        row.addWidget(self.refresh_btn)
        root.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.details = QWidget()
        body = QVBoxLayout(self.details)
        body.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['欄位', '值'])
        self.tree.setColumnWidth(0, 280)
        self.tree.setMinimumHeight(300)
        body.addWidget(self.tree)
        self.inconsistent = QLabel('門檻順序矛盾 (MIN ≤ SET ≤ HIGH)')
        set_badge(self.inconsistent, self.inconsistent.text(), 'error')
        body.addWidget(self.inconsistent)
        self.info_label = QLabel()
        body.addWidget(self.info_label)
        self.bits = BitChips(STATIC_CAPABILITY_LABELS)
        body.addWidget(self.bits)
        self.received = QLabel()
        body.addWidget(self.received)
        root.addWidget(self.details)
        self.details.hide()
        self._snapshot = None
        self._summary = '靜態資訊'

    def _toggle(self, expanded):
        self.details.setVisible(expanded)
        self.expand_btn.setText(('收合 · ' if expanded else '展開 · ') + self._summary)

    def reset(self):
        self.expand_btn.setChecked(False)
        self._snapshot = None

    def render_model(self, c, frozen=False):
        s = c.static
        self.refresh_btn.setEnabled(c.link_state == 'ready' and not c.static_loading)
        self.expand_btn.setEnabled(s is not None)
        self.status.setText(('更新失敗：' + c.static_error) if c.static_error else
                            '讀取中…' if c.static_loading else
                            f'最後更新 {clock_text(c.static_updated)}' if s else '尚無資料')
        self.status.setStyleSheet(f'color: {ERROR if c.static_error else MUTED};')
        if frozen:
            if not c.static_error:
                self.status.setText('畫面已凍結')
            return
        self._summary = ('靜態資訊' if s is None else
                         f'Cat {s.pru_category} · HW 0x{s.hardware_rev:02X} · '
                         f'FW 0x{s.firmware_rev:02X} · Proto {s.protocol_revision}')
        self._toggle(self.expand_btn.isChecked() and s is not None)
        if s is None:
            self.tree.clear()
            self._snapshot = None
            return
        snapshot = (tuple(s.raw), c.static_updated)
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        bad = not s.vrect_min_static_mv <= s.vrect_set_mv <= s.vrect_high_static_mv
        rows = [
            ('Protocol Revision', f'0x{s.protocol_revision:02X} ({s.protocol_revision})'),
            ('PRU Category', f'0x{s.pru_category:02X} ({s.pru_category})'),
            ('Hardware rev', f'0x{s.hardware_rev:02X} ({s.hardware_rev})'),
            ('Firmware rev', f'0x{s.firmware_rev:02X} ({s.firmware_rev})'),
            ('PRECT_MAX', f'{s.prect_max_mw} mW'),
            ('VRECT_MIN_STATIC', f'{s.vrect_min_static_mv} mV'),
            ('VRECT_SET', f'{s.vrect_set_mv} mV'),
            ('VRECT_HIGH_STATIC', f'{s.vrect_high_static_mv} mV'),
            ('ΔR1', f'{s.delta_r1_ohm:.2f} Ω'),
            ('PRU Information', f'0x{s.pru_information:02X}'),
            ('Optional fields validity', f'0x{s.optional_fields_validity:02X}'),
        ]
        self.tree.clear()
        for key, value in rows:
            item = QTreeWidgetItem([key, value])
            if bad and key.startswith('VRECT_'):
                for column in (0, 1):
                    item.setForeground(column, QColor(ERROR))
            self.tree.addTopLevelItem(item)
        self.inconsistent.setVisible(bad)
        self.info_label.setText(f'PRU Information 0x{s.pru_information:02X}')
        self.bits.set_byte(s.pru_information)
        self.received.setText(f'讀取時間 {clock_text(c.static_updated)} · {len(s.raw)} bytes')


class EventLogCard(QGroupBox):
    PAGE_SIZE = 100
    KIND_LABELS = {'command': '指令', 'alert': '警報', 'link': '連線',
                   'marker': '標記', 'recording': '紀錄', 'read': '讀取', 'collection': '收集'}

    def __init__(self):
        super().__init__('事件紀錄')
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 8)
        filters = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem('即時緩衝', 'live')
        self.source_combo.addItem('紀錄檔', 'recording')
        self.source_combo.setToolTip('紀錄檔可搜尋此次檔案中已寫入的全部事件')
        self.kind_combo = QComboBox()
        self.kind_combo.addItem('全部類型', '')
        for kind, label in self.KIND_LABELS.items():
            self.kind_combo.addItem(label, kind)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('搜尋事件 / 詳細 / RAW')
        self.copy_btn = QPushButton('複製詳細')
        self.copy_btn.clicked.connect(self._copy_selected)
        self.copy_btn.setEnabled(False)
        filters.addWidget(self.source_combo)
        filters.addWidget(self.kind_combo)
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.copy_btn)
        root.addLayout(filters)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['時間（本機）', '類型', '事件', '詳細'])
        for column, width in enumerate((175, 55, 210)):
            self.tree.setColumnWidth(column, width)
        self.tree.setMinimumHeight(70)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.tree, 1)
        footer = QHBoxLayout()
        self.older = QLabel()
        footer.addWidget(self.older, 1)
        self.prev_btn = QPushButton('上一頁')
        self.next_btn = QPushButton('下一頁')
        self.prev_btn.clicked.connect(lambda: self._change_page(-1))
        self.next_btn.clicked.connect(lambda: self._change_page(1))
        footer.addWidget(self.prev_btn)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)
        self.details_label = QLabel('選取事件可複製完整詳細資料')
        self.details_label.setTextFormat(Qt.TextFormat.PlainText)
        self.details_label.setWordWrap(False)
        self.details_label.setMaximumHeight(20)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.details_label)
        self._entries = None
        self._recorder = None
        self._total_seen = 0
        self._page = 0
        self._cache_key = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._filters_changed)
        self.search_edit.textChanged.connect(lambda: self._search_timer.start())
        self.source_combo.currentIndexChanged.connect(self._filters_changed)
        self.kind_combo.currentIndexChanged.connect(self._filters_changed)

    def _filters_changed(self):
        self._page = 0
        self._cache_key = None
        self._refresh_rows()

    def _change_page(self, direction):
        self._page = max(0, self._page + direction)
        self._cache_key = None
        self._refresh_rows()

    @staticmethod
    def _entry_row(entry):
        if isinstance(entry, dict):
            return entry
        row = {name: getattr(entry, name) for name in ('at', 'title', 'detail', 'kind', 'level')}
        row['id'] = id(entry)
        return row

    @staticmethod
    def _row_key(row):
        return tuple(str(row.get(name, '')) for name in ('id', 'at', 'title', 'detail', 'kind', 'level'))

    def render(self, entries, recorder=None, total_seen=None):
        self._entries = tuple(entries)
        self._recorder = recorder
        self._total_seen = len(self._entries) if total_seen is None else total_seen
        self.source_combo.model().item(1).setEnabled(recorder is not None)
        if recorder is None and self.source_combo.currentData() == 'recording':
            self.source_combo.setCurrentIndex(0)
        self._refresh_rows()

    def _refresh_rows(self):
        if self._entries is None:
            return
        query = self.search_edit.text().strip()
        kind = self.kind_combo.currentData() or ''
        from_file = self.source_combo.currentData() == 'recording' and self._recorder is not None
        version = (id(self._recorder), getattr(self._recorder, 'event_count', 0)) if from_file else self._entries
        key = (from_file, version, query, kind, self._page, self._total_seen)
        if key == self._cache_key:
            return
        self._cache_key = key
        try:
            if from_file:
                rows, total = self._recorder.query_events(query=query, kind=kind,
                    limit=self.PAGE_SIZE, offset=self._page * self.PAGE_SIZE)
            else:
                rows = [self._entry_row(entry) for entry in self._entries]
                rows = [row for row in rows if (not kind or row['kind'] == kind) and
                        (not query or query.casefold() in (row['title'] + ' ' + row['detail']).casefold())]
                total = len(rows)
                rows = rows[self._page * self.PAGE_SIZE:(self._page + 1) * self.PAGE_SIZE]
        except Exception as exc:
            self.older.setText(f'讀取紀錄檔失敗：{exc}')
            self.older.setStyleSheet(f'color: {ERROR};')
            self._cache_key = None
            return
        if self._page and not rows:
            self._page = max(0, (total - 1) // self.PAGE_SIZE)
            self._cache_key = None
            self._refresh_rows()
            return
        selected = self.tree.currentItem()
        selected_key = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        scroll_value = self.tree.verticalScrollBar().value()
        self.tree.blockSignals(True)
        self.tree.clear()
        for row in rows:
            at = str(row['at'])
            try:
                display_time = datetime.fromisoformat(at).astimezone().strftime('%m-%d %H:%M:%S.%f')[:-3]
            except ValueError:
                display_time = at
            detail = row['detail']
            if row.get('raw_hex'):
                detail += f"\nRAW: {row['raw_hex']}"
            if row.get('data_json'):
                detail += f"\n{row['data_json']}"
            item = QTreeWidgetItem([display_time, self.KIND_LABELS.get(row['kind'], row['kind']),
                                   row['title'], detail.replace('\n', ' · ')])
            item.setForeground(2, QColor(COLORS.get(row['level'], INFO)))
            row_key = self._row_key(row)
            item.setData(0, Qt.ItemDataRole.UserRole, row_key)
            item.setData(2, Qt.ItemDataRole.UserRole, row['level'])
            item.setData(3, Qt.ItemDataRole.UserRole, f"{at} · {row['title']}\n{detail}")
            item.setToolTip(0, at)
            item.setToolTip(2, row['title'])
            item.setToolTip(3, detail)
            self.tree.addTopLevelItem(item)
            if row_key == selected_key:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self.tree.verticalScrollBar().setValue(scroll_value)
        self._selection_changed()
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled((self._page + 1) * self.PAGE_SIZE < total)
        page_text = f'第 {self._page + 1}/{max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)} 頁 · {total} 筆'
        prefix = '紀錄檔已寫入事件' if from_file else '即時緩衝僅保留最近 1000 筆'
        self.older.setText(f'{prefix} · {page_text}' + (f' · 本次共 {self._total_seen} 筆' if not from_file else ''))
        self.older.setStyleSheet(f'color: {MUTED};')

    def _selection_changed(self):
        item = self.tree.currentItem()
        self.copy_btn.setEnabled(item is not None)
        text = item.data(3, Qt.ItemDataRole.UserRole) if item else '選取事件可複製完整詳細資料'
        self.details_label.setText(text.split('\n')[0])
        self.details_label.setToolTip(text)

    def _copy_selected(self):
        item = self.tree.currentItem()
        if item:
            QApplication.clipboard().setText(item.data(3, Qt.ItemDataRole.UserRole))
