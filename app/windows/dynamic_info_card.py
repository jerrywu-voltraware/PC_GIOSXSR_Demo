"""Mobile PRU metric tiles and VRECT threshold track, rendered with Qt."""
from __future__ import annotations
import math
import time
from datetime import datetime
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QFrame, QGroupBox, QVBoxLayout, QHBoxLayout,
                            QGridLayout, QLabel, QPushButton)
from ..constants import DYNAMIC_ALERT_BIT_LABELS

PRIMARY = '#116360'
ERROR = '#c62828'
WARNING = '#b36a00'


def thresholds(dynamic, static):
    values = []
    any_static = False
    for mask, dyn_attr, static_attr in ((0x10, 'vrect_min_mv', 'vrect_min_static_mv'),
                                       (0x08, 'vrect_set_mv', 'vrect_set_mv'),
                                       (0x04, 'vrect_high_mv', 'vrect_high_static_mv')):
        valid = bool(dynamic.optional_fields_validity & mask)
        value = getattr(dynamic, dyn_attr) if valid else (getattr(static, static_attr) if static else None)
        values.append(value)
        any_static |= value is not None and not valid
    return tuple(values), not any_static


def range_geometry(vrect, limits):
    points = [vrect] + [value for value in limits if value is not None]
    lo, hi = min(points), max(points)
    pad = max(200, min(1 << 30, math.floor((hi - lo) * .15 + .5)))
    lo, hi = lo - pad, hi + pad
    def fraction(value):
        return None if value is None else max(0., min(1., (value - lo) / (hi - lo)))
    return fraction(vrect), tuple(fraction(value) for value in limits)


class MetricTile(QFrame):
    def __init__(self, label, unit):
        super().__init__()
        self.unit = unit
        self.setObjectName('metricTile')
        self.setMinimumHeight(103)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 9)
        self.title = QLabel(label)
        root.addWidget(self.title)
        line = QHBoxLayout()
        self.value_label = QLabel('—')
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.unit_label = QLabel(unit)
        line.addWidget(self.value_label)
        line.addWidget(self.unit_label)
        line.addStretch()
        root.addLayout(line)
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        root.addWidget(self.note_label)
        self.set_value(None)

    def set_value(self, value, valid=True, alert=False, note='', note_color=None):
        valid = valid and value is not None
        color = ERROR if alert and valid else ('#183d40' if valid else '#899797')
        background = '#fff0ef' if alert and valid else '#f1f5f5'
        border = '#e7a09c' if alert and valid else '#d2e0e0'
        self.setStyleSheet(f'QFrame#metricTile {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}')
        self.value_label.setText(str(value) if valid else '—')
        self.value_label.setStyleSheet(f'font-size: 28px; font-weight: 700; color: {color};')
        self.unit_label.setText(self.unit + (' (無效)' if value is not None and not valid else ''))
        self.unit_label.setStyleSheet(f'color: {color};')
        self.note_label.setText(note if valid else '')
        self.note_label.setStyleSheet(f'color: {note_color or color}; font-weight: 600;')
        self.note_label.setVisible(bool(note and valid))


class VrectRangeBar(QWidget):
    def __init__(self):
        super().__init__()
        self.vrect = 0
        self.limits = (None, None, None)
        self.cursor_fraction = .5
        self.marker_fractions = (None, None, None)
        self.cursor_color = PRIMARY
        self.setMinimumHeight(30)

    def set_values(self, vrect, limits):
        self.vrect, self.limits = vrect, limits
        self.cursor_fraction, self.marker_fractions = range_geometry(vrect, limits)
        low, _, high = limits
        self.cursor_color = ERROR if high is not None and vrect > high else (
            WARNING if low is not None and vrect < low else PRIMARY)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(1, self.width() - 16)
        left, y = 8, 15
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#dfe6e6'))
        painter.drawRoundedRect(QRectF(left, y - 3, width, 6), 3, 3)
        low, _, high = self.marker_fractions
        if low is not None and high is not None:
            painter.setBrush(QColor('#a5d6b2'))
            painter.drawRoundedRect(QRectF(left + low * width, y - 3, max(0, high - low) * width, 6), 3, 3)
        painter.setPen(QPen(QColor('#657879'), 2))
        for fraction in self.marker_fractions:
            if fraction is not None:
                x = int(left + fraction * width)
                painter.drawLine(x, y - 10, x, y + 10)
        painter.setPen(QPen(QColor('white'), 2))
        painter.setBrush(QColor(self.cursor_color))
        painter.drawEllipse(QRectF(left + self.cursor_fraction * width - 7, y - 7, 14, 14))


class DynamicInfoCard(QGroupBox):
    def __init__(self):
        super().__init__('即時數據 · PRU Dynamic Info')
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.status = QLabel('等待資料')
        self.status.setWordWrap(True)
        self.refresh_btn = QPushButton('讀取一次')
        header.addWidget(self.status, 1)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)
        self.failure_label = QLabel()
        self.failure_label.setWordWrap(True)
        self.failure_label.setStyleSheet(f'color: {ERROR};')
        root.addWidget(self.failure_label)
        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        self.tiles = {}
        for index, (name, unit) in enumerate((('VRECT', 'mV'), ('IRECT', 'mA'), ('VOUT', 'mV'), ('IOUT', 'mA'))):
            tile = MetricTile(name, unit)
            self.tiles[name] = tile
            grid.addWidget(tile, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)
        self.range_section = QWidget()
        ranges = QVBoxLayout(self.range_section)
        ranges.setContentsMargins(0, 0, 0, 0)
        self.range_bar = VrectRangeBar()
        ranges.addWidget(self.range_bar)
        markers = QHBoxLayout()
        self.markers = []
        for index, name in enumerate(('MIN', 'SET', 'HIGH')):
            label = QLabel(name)
            label.setAlignment((Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignRight)[index])
            markers.addWidget(label, 1)
            self.markers.append(label)
        ranges.addLayout(markers)
        self.source_label = QLabel()
        ranges.addWidget(self.source_label)
        body.addWidget(self.range_section)
        self.temperature = QLabel()
        self.temperature.setStyleSheet('color: #8a9898;')
        body.addWidget(self.temperature)
        body.addWidget(QLabel('動態門檻'))
        rows = QGridLayout()
        self.threshold_labels = []
        for index, name in enumerate(('VRECT_MIN_DYN', 'VRECT_SET_DYN', 'VRECT_HIGH_DYN')):
            rows.addWidget(QLabel(name), index, 0)
            value = QLabel()
            rows.addWidget(value, index, 1)
            self.threshold_labels.append(value)
        rows.setColumnStretch(1, 1)
        body.addLayout(rows)
        self.inconsistent = QLabel('門檻順序矛盾 (MIN ≤ SET ≤ HIGH)')
        self.inconsistent.setStyleSheet(f'color: {ERROR};')
        body.addWidget(self.inconsistent)
        self.validity = QLabel()
        body.addWidget(self.validity)
        self.alert = QLabel()
        self.alert.setWordWrap(True)
        body.addWidget(self.alert)
        self.tester = QLabel()
        body.addWidget(self.tester)
        self.raw = QLabel()
        self.raw.setWordWrap(True)
        self.raw.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.raw.setStyleSheet('color: #657879; font-size: 11px;')
        body.addWidget(self.raw)
        root.addWidget(self.content)
        self.content.hide()
        self.failure_label.hide()

    def render_model(self, controller):
        c, d = controller, controller.dynamic
        stamp = datetime.fromtimestamp(time.time() - (time.monotonic() - c.dynamic_updated)).strftime('%H:%M:%S') if c.dynamic_updated is not None else '—'
        self.status.setText(('讀取中…' if c.dynamic_loading else (c.dynamic_error or '尚無資料')) if d is None else f'最後更新 {stamp}')
        self.failure_label.setText(f'最近讀取失敗 ×{c.failures}：{c.dynamic_error}')
        self.failure_label.setVisible(d is not None and c.failures > 0)
        self.content.setVisible(d is not None)
        if d is None:
            return
        limits, from_dynamic = thresholds(d, c.static)
        low, _, high = limits
        too_high = high is not None and d.vrect_mv > high
        too_low = low is not None and d.vrect_mv < low
        over_voltage = bool(d.pru_alert & 0x80)
        note = 'OV 警報' if over_voltage else (f'HIGH {high} 以上' if too_high else (f'MIN {low} 以下' if too_low else ''))
        self.tiles['VRECT'].set_value(d.vrect_mv, alert=over_voltage or too_high, note=note,
                                     note_color=ERROR if over_voltage or too_high else WARNING)
        self.tiles['IRECT'].set_value(d.irect_ma, alert=bool(d.pru_alert & 0x40),
                                     note='OC 警報' if d.pru_alert & 0x40 else '')
        self.tiles['VOUT'].set_value(d.vout_mv, valid=bool(d.optional_fields_validity & 0x80))
        self.tiles['IOUT'].set_value(d.iout_ma, valid=bool(d.optional_fields_validity & 0x40))
        self.range_section.setVisible(any(value is not None for value in limits))
        self.range_bar.set_values(d.vrect_mv, limits)
        for label, name, value in zip(self.markers, ('MIN', 'SET', 'HIGH'), limits):
            label.setText(f'{name}\n{value}' if value is not None else '')
        self.source_label.setText(f"門檻來源：{'DYN' if from_dynamic else 'Static'} · VRECT {d.vrect_mv} mV")
        self.temperature.setText(f'溫度    {d.temperature_c} °C (此版本未支援)')
        inconsistent = d.optional_fields_validity & 0x1c == 0x1c and not d.vrect_min_mv <= d.vrect_set_mv <= d.vrect_high_mv
        for label, mask, value in zip(self.threshold_labels, (0x10, 0x08, 0x04), (d.vrect_min_mv, d.vrect_set_mv, d.vrect_high_mv)):
            label.setText(f'{value} mV' if d.optional_fields_validity & mask else '— mV (無效)')
            label.setStyleSheet(f'color: {ERROR if inconsistent else "#183d40"};')
        self.inconsistent.setVisible(inconsistent)
        self.validity.setText(f'狀態    Validity 0x{d.optional_fields_validity:02X}')
        active = [label for i, label in enumerate(DYNAMIC_ALERT_BIT_LABELS) if d.pru_alert & (0x80 >> i)]
        self.alert.setText(f'PRU Alert 0x{d.pru_alert:02X}    ' + (' · '.join(active) if active else '無警報'))
        self.alert.setStyleSheet(f'color: {ERROR if d.pru_alert & 0xf0 else PRIMARY};')
        self.tester.setText(f'Tester Command    0x{d.tester_cmd:02X}')
        self.raw.setText('RAW    ' + bytes(d.raw).hex(' ').upper())
