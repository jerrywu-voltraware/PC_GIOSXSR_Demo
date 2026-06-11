"""DAC 工具頁 — 透過 ESP32 DAC 直接灌訊號到電路板腳位，用於韌體行為測試。

原始獨立程式 (PySide6) 轉為 PyQt6 頁面，嵌入 QStackedWidget 導航。
"""
from __future__ import annotations

import time
import threading
import json
from pathlib import Path

import serial
import serial.tools.list_ports

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QPushButton, QSlider,
    QTextEdit, QFrame, QMessageBox, QLineEdit, QDialog, QSpinBox,
    QTabWidget, QCheckBox, QScrollArea, QInputDialog, QSplitter,
)

# ── Constants ──────────────────────────────────────────────────────────
BAUD_RATE    = 115200
DAC_MAX      = 255
DEFAULT_VREF = 3.3
MAX_BOARDS   = 8
CONFIG_FILE  = Path(__file__).resolve().parent.parent.parent / "dac_config.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if "boards" not in cfg:
                vref = cfg.get("vref", DEFAULT_VREF)
                cfg = {
                    "board_count": 1,
                    "boards": [{"label": "ESP32 #1", "port": "", "vref": vref}],
                    "remember_setup": True,
                }
            return cfg
        except Exception:
            pass
    return {
        "board_count": 1,
        "boards": [{"label": "ESP32 #1", "port": "", "vref": DEFAULT_VREF}],
        "remember_setup": True,
    }


def save_config(cfg: dict):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Stylesheet (scoped to DAC tool) ───────────────────────────────────
DAC_QSS = """
QWidget#dac_central {
    background: #f4f6f9;
}

QWidget#dac_titlebar {
    background: #1a73e8;
}
QLabel#dac_title {
    color: white;
    font: bold 13px "Consolas";
    padding: 9px 14px;
}

QGroupBox {
    font: bold 12px "Consolas";
    color: #1a73e8;
    border: 1px solid #c8d6e8;
    border-radius: 5px;
    margin-top: 10px;
    background: #ffffff;
    padding: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    left: 10px;
}

QLabel {
    background: transparent;
    color: #333333;
    font: 10px "Consolas";
}
QLabel#readout {
    font: bold 22px "Consolas";
    color: #1a1a1a;
    min-width: 95px;
}
QLabel#readout_raw  { color: #6a1fd0; }
QLabel#readout_volt { color: #1e8c45; }
QLabel#readout_pct  { color: #b05a00; }
QLabel#caption {
    color: #777777;
    font: 12px "Consolas";
}

QFrame#chip {
    background: #e8eef8;
    border: 1px solid #c0cfe8;
    border-radius: 4px;
    padding: 3px 8px;
}
QLabel#chip_val {
    font: bold 14px "Consolas";
    color: #1a4080;
}
QLabel#chip_key {
    font: 10px "Consolas";
    color: #6677aa;
}

QComboBox {
    font: 10px "Consolas";
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 4px 8px;
    background: white;
    min-width: 105px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { font: 10px "Consolas"; }

QPushButton {
    font: 10px "Consolas";
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 4px 10px;
    background: #e8e8e8;
    color: #1a1a1a;
}
QPushButton:hover   { background: #d8d8d8; }
QPushButton:pressed { background: #c8c8c8; }
QPushButton:disabled { color: #aaaaaa; background: #f0f0f0; border-color: #d8d8d8; }

QPushButton#btn_connect {
    font: bold 10px "Consolas";
    background: #1e8c45;
    color: white;
    border: none;
    padding: 5px 16px;
    border-radius: 4px;
}
QPushButton#btn_connect:hover   { background: #166c36; }
QPushButton#btn_connect[connected="true"] {
    background: #c0392b;
}
QPushButton#btn_connect[connected="true"]:hover { background: #96281b; }

QPushButton#btn_refresh {
    font: bold 13px "Consolas";
    color: #1a73e8;
    padding: 3px 8px;
}

QPushButton#btn_send {
    font: bold 12px "Consolas";
    background: #1a73e8;
    color: white;
    border: none;
    padding: 6px 16px;
    border-radius: 4px;
    min-width: 120px;
}
QPushButton#btn_send:hover    { background: #1557b0; }
QPushButton#btn_send:disabled { background: #a8c4f0; color: #ddeeff; border: none; }

QPushButton#btn_preset {
    font: 11px "Consolas";
    padding: 4px 10px;
    min-width: 46px;
}

QPushButton#btn_clear {
    font: 9px "Consolas";
    padding: 3px 8px;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #dde3ee;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #1a73e8;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover   { background: #1557b0; }
QSlider::handle:horizontal:disabled { background: #aac4e8; }
QSlider::sub-page:horizontal {
    background: #1a73e8;
    border-radius: 3px;
}
QSlider::sub-page:horizontal:disabled { background: #aac4e8; }

QLabel#status_ok  { color: #1e8c45; font: bold 10px "Consolas"; }
QLabel#status_err { color: #c0392b; font: bold 10px "Consolas"; }

QLineEdit#vref_edit {
    font: bold 11px "Consolas";
    color: #1a4080;
    background: #e8eef8;
    border: 1px solid #1a73e8;
    border-radius: 3px;
    padding: 1px 3px;
}
QLineEdit#vref_edit:focus {
    background: #ffffff;
    border-color: #c0392b;
}

QTextEdit#log {
    font: 10px "Consolas";
    background: #fafafa;
    color: #222222;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
}

QTabWidget::pane {
    border: 1px solid #c8d6e8;
    border-top: none;
    background: #f4f6f9;
}
QTabBar::tab {
    font: bold 11px "Consolas";
    padding: 7px 18px;
    border: 1px solid #c8d6e8;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: #e0e6ef;
    color: #555555;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1a73e8;
    border-bottom: 2px solid #1a73e8;
}
QTabBar::tab:hover:!selected {
    background: #d0d8e8;
}

QPushButton#btn_global {
    font: bold 10px "Consolas";
    padding: 5px 14px;
    border-radius: 4px;
    border: 1px solid #c0c0c0;
    background: #e8e8e8;
}
QPushButton#btn_global:hover { background: #d8d8d8; }
QPushButton#btn_global_danger {
    font: bold 10px "Consolas";
    padding: 5px 14px;
    border-radius: 4px;
    border: none;
    background: #c0392b;
    color: white;
}
QPushButton#btn_global_danger:hover { background: #96281b; }

QDialog#setup_dialog {
    background: #f4f6f9;
}
QSpinBox {
    font: bold 12px "Consolas";
    padding: 4px 8px;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    background: white;
}
QPushButton#btn_start {
    font: bold 13px "Consolas";
    background: #1a73e8;
    color: white;
    border: none;
    padding: 8px 32px;
    border-radius: 5px;
    min-width: 160px;
}
QPushButton#btn_start:hover { background: #1557b0; }
QLabel#setup_title {
    font: bold 14px "Consolas";
    color: #1a73e8;
    padding: 4px 0;
}

QPushButton#btn_setup {
    font: bold 10px "Consolas";
    color: white;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.4);
    border-radius: 4px;
    padding: 4px 12px;
    margin: 4px 8px;
}
QPushButton#btn_setup:hover {
    background: rgba(255,255,255,0.15);
    border-color: rgba(255,255,255,0.7);
}

QPushButton#btn_blink {
    font: bold 10px "Consolas";
    padding: 4px 10px;
    background: #f0ad4e;
    color: white;
    border: none;
    border-radius: 4px;
}
QPushButton#btn_blink:hover { background: #d4952e; }

QPushButton#btn_scan {
    font: bold 11px "Consolas";
    background: #1a73e8;
    color: white;
    border: none;
    padding: 6px 18px;
    border-radius: 4px;
}
QPushButton#btn_scan:hover { background: #1557b0; }

QPushButton#btn_setid {
    font: bold 10px "Consolas";
    padding: 4px 10px;
    background: #6a1fd0;
    color: white;
    border: none;
    border-radius: 4px;
}
QPushButton#btn_setid:hover { background: #5218a5; }

QLabel#scan_result {
    font: 10px "Consolas";
    color: #1e8c45;
    padding: 2px 4px;
}

QPushButton#btn_back_dac {
    font-size: 13px;
    font-weight: bold;
    padding: 6px 14px;
    background-color: #555;
    color: white;
    border-radius: 6px;
}
QPushButton#btn_back_dac:hover { background-color: #777; }
"""


# ── Serial helpers ─────────────────────────────────────────────────────
def _probe_port(port: str, timeout: float = 2.0) -> int | None:
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
    except Exception:
        return None
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ser.in_waiting:
                line = ser.readline().decode(errors="replace").strip()
                bid = _parse_board_id(line)
                if bid is not None:
                    return bid
            else:
                break
        ser.write(b"PING\r\n")
        while time.time() < deadline:
            if ser.in_waiting:
                line = ser.readline().decode(errors="replace").strip()
                bid = _parse_board_id(line)
                if bid is not None:
                    return bid
            else:
                time.sleep(0.05)
    except Exception:
        pass
    finally:
        try:
            ser.close()
        except Exception:
            pass
    return None


def _parse_board_id(line: str) -> int | None:
    if line.startswith("PONG"):
        parts = line.split()
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                pass
    if line.startswith("READY"):
        parts = line.split()
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                pass
    return None


def _send_cmd_quick(port: str, cmd: str, timeout: float = 2.0) -> str | None:
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
    except Exception:
        return None
    try:
        ser.reset_input_buffer()
        ser.write(f"{cmd}\r\n".encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ser.in_waiting:
                line = ser.readline().decode(errors="replace").strip()
                if line:
                    return line
            else:
                time.sleep(0.05)
    except Exception:
        pass
    finally:
        try:
            ser.close()
        except Exception:
            pass
    return None


# ── Serial worker ──────────────────────────────────────────────────────
class SerialWorker(QObject):
    line_received = pyqtSignal(str)
    error         = pyqtSignal(str)

    def __init__(self, ser: serial.Serial):
        super().__init__()
        self._ser     = ser
        self._running = True

    def run(self):
        while self._running:
            try:
                if self._ser and self._ser.in_waiting:
                    line = self._ser.readline().decode(errors="replace").strip()
                    if line:
                        self.line_received.emit(line)
                else:
                    time.sleep(0.01)
            except Exception as e:
                if self._running:
                    self.error.emit(str(e))
                break

    def stop(self):
        self._running = False


# ── Setup dialog ───────────────────────────────────────────────────────
class SetupDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ESP32 DAC Controller — Setup")
        self.setObjectName("setup_dialog")
        self.setMinimumWidth(480)
        self._cfg = cfg
        self._port_combos: list[QComboBox] = []
        self._id_labels: list[QLabel] = []
        self._board_rows: list[QWidget] = []
        self._build_ui()
        self.setStyleSheet(DAC_QSS)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("ESP32 DAC CONTROLLER — SETUP")
        title.setObjectName("setup_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("ESP32 數量："))
        self._spin_count = QSpinBox()
        self._spin_count.setRange(1, MAX_BOARDS)
        self._spin_count.setValue(self._cfg.get("board_count", 1))
        self._spin_count.valueChanged.connect(self._rebuild_board_rows)
        count_row.addWidget(self._spin_count)
        count_row.addStretch()

        btn_scan = QPushButton("🔍  自動掃描")
        btn_scan.setObjectName("btn_scan")
        btn_scan.clicked.connect(self._auto_scan)
        count_row.addWidget(btn_scan)
        layout.addLayout(count_row)

        self._lbl_scan = QLabel("")
        self._lbl_scan.setObjectName("scan_result")
        layout.addWidget(self._lbl_scan)

        self._rows_container = QVBoxLayout()
        self._rows_container.setSpacing(6)
        layout.addLayout(self._rows_container)

        self._chk_remember = QCheckBox("記住這組設定")
        self._chk_remember.setChecked(self._cfg.get("remember_setup", True))
        layout.addWidget(self._chk_remember)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_start = QPushButton("▶  START")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self._btn_start)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._rebuild_board_rows(self._spin_count.value())

    def _get_ports(self) -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def _rebuild_board_rows(self, count: int):
        for w in self._board_rows:
            w.setParent(None)
            w.deleteLater()
        self._board_rows.clear()
        self._port_combos.clear()
        self._id_labels.clear()

        ports = self._get_ports()
        saved_boards = self._cfg.get("boards", [])

        for i in range(count):
            box = QGroupBox(f"  ESP32 #{i + 1}  ")
            col = QVBoxLayout(box)
            col.setSpacing(4)

            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(QLabel("COM Port:"))

            combo = QComboBox()
            combo.addItem("")
            combo.addItems(ports)
            if i < len(saved_boards):
                saved_port = saved_boards[i].get("port", "")
                if saved_port in ports:
                    combo.setCurrentText(saved_port)
            row.addWidget(combo)

            btn_refresh = QPushButton("↻")
            btn_refresh.setObjectName("btn_refresh")
            btn_refresh.setFixedWidth(32)
            btn_refresh.clicked.connect(lambda _, c=combo: self._refresh_one(c))
            row.addWidget(btn_refresh)

            btn_blink = QPushButton("🔍 辨識")
            btn_blink.setObjectName("btn_blink")
            btn_blink.clicked.connect(lambda _, c=combo, idx=i: self._blink_board(c, idx))
            row.addWidget(btn_blink)

            row.addStretch()
            col.addLayout(row)

            lbl_id = QLabel("")
            lbl_id.setObjectName("scan_result")
            col.addWidget(lbl_id)

            self._port_combos.append(combo)
            self._id_labels.append(lbl_id)
            self._board_rows.append(box)
            self._rows_container.addWidget(box)

    def _refresh_one(self, combo: QComboBox):
        current = combo.currentText()
        ports = self._get_ports()
        combo.clear()
        combo.addItem("")
        combo.addItems(ports)
        if current in ports:
            combo.setCurrentText(current)

    def _blink_board(self, combo: QComboBox, idx: int):
        port = combo.currentText()
        if not port:
            QMessageBox.warning(self, "提示", "請先選擇 COM Port。")
            return
        self._id_labels[idx].setText(f"正在辨識 {port} ...")
        QApplication.processEvents()
        resp = _send_cmd_quick(port, "BLINK 3", timeout=3.0)
        if resp and resp.startswith("OK BLINK"):
            bid = _probe_port(port, timeout=2.0)
            id_str = f"  (Board ID: {bid})" if bid is not None else ""
            self._id_labels[idx].setText(f"✔ {port} 已閃燈{id_str}")
        else:
            self._id_labels[idx].setText(f"✘ {port} 無回應（非 ESP32 或未燒錄韌體）")

    def _auto_scan(self):
        self._lbl_scan.setText("掃描中 ...")
        QApplication.processEvents()
        ports = self._get_ports()
        found: list[tuple[str, int]] = []
        for port in ports:
            bid = _probe_port(port, timeout=2.0)
            if bid is not None:
                found.append((port, bid))
            QApplication.processEvents()

        if not found:
            self._lbl_scan.setText("未偵測到任何 ESP32。請確認 USB 已連接且韌體已燒錄。")
            return

        found.sort(key=lambda x: x[1])
        self._lbl_scan.setText(
            f"找到 {len(found)} 顆 ESP32: "
            + ", ".join(f"{p} (ID:{bid})" for p, bid in found)
        )

        self._spin_count.setValue(len(found))
        QApplication.processEvents()
        for i, (port, bid) in enumerate(found):
            if i < len(self._port_combos):
                combo = self._port_combos[i]
                idx = combo.findText(port)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                self._id_labels[i].setText(f"Board ID: {bid}")

    def _on_start(self):
        assigned = [c.currentText() for c in self._port_combos if c.currentText()]
        if len(assigned) != len(set(assigned)):
            QMessageBox.warning(self, "Port 衝突",
                                "不同的 ESP32 不能使用相同的 COM Port。")
            return
        self.accept()

    def get_result(self) -> dict:
        count = self._spin_count.value()
        saved_boards = self._cfg.get("boards", [])
        boards = []
        for i in range(count):
            port = self._port_combos[i].currentText() if i < len(self._port_combos) else ""
            vref = DEFAULT_VREF
            if i < len(saved_boards):
                vref = saved_boards[i].get("vref", DEFAULT_VREF)
            boards.append({
                "label": f"ESP32 #{i + 1}",
                "port": port,
                "vref": vref,
            })
        return {
            "board_count": count,
            "boards": boards,
            "remember_setup": self._chk_remember.isChecked(),
        }


# ── Pin chip widget ────────────────────────────────────────────────────
def _make_chip(parent, key: str, val: str) -> QFrame:
    frame = QFrame(parent)
    frame.setObjectName("chip")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 2, 6, 2)
    layout.setSpacing(0)

    lbl_key = QLabel(key, frame)
    lbl_key.setObjectName("chip_key")
    lbl_key.setAlignment(Qt.AlignmentFlag.AlignCenter)

    lbl_val = QLabel(val, frame)
    lbl_val.setObjectName("chip_val")
    lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(lbl_key)
    layout.addWidget(lbl_val)
    return frame


# ── DAC channel widget ─────────────────────────────────────────────────
class DACChannelWidget(QGroupBox):
    send_requested = pyqtSignal(str, int)
    vref_changed   = pyqtSignal(float)

    def __init__(self, ch: int, gpio: int, pin: int, cmd_prefix: str,
                 vref: float = DEFAULT_VREF, parent=None):
        super().__init__(f"  {cmd_prefix}  ·  GPIO{gpio}  ", parent)
        self.cmd_prefix = cmd_prefix
        self._vref = vref
        self._build(ch, gpio, pin)
        self.set_enabled(False)

    def _build(self, ch: int, gpio: int, pin: int):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for key, val in [("DAC CH", str(ch)), ("GPIO", str(gpio)),
                         ("PIN #", str(pin)), ("RES", "8-bit")]:
            chip_row.addWidget(_make_chip(self, key, val))

        vref_frame = QFrame(self)
        vref_frame.setObjectName("chip")
        vref_layout = QVBoxLayout(vref_frame)
        vref_layout.setContentsMargins(6, 2, 6, 2)
        vref_layout.setSpacing(0)
        vref_key = QLabel("VREF", vref_frame)
        vref_key.setObjectName("chip_key")
        vref_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vref_edit = QLineEdit(f"{self._vref:.2f}", vref_frame)
        self._vref_edit.setObjectName("vref_edit")
        self._vref_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vref_edit.setFixedWidth(58)
        self._vref_edit.editingFinished.connect(self._on_vref_edited)
        vref_layout.addWidget(vref_key)
        vref_layout.addWidget(self._vref_edit)
        chip_row.addWidget(vref_frame)

        chip_row.addStretch()
        root.addLayout(chip_row)

        readout_row = QHBoxLayout()
        readout_row.setSpacing(4)

        for caption, attr, obj_name in [
            ("RAW",  "_lbl_raw",  "readout_raw"),
            ("VOLT", "_lbl_volt", "readout_volt"),
            ("PCT",  "_lbl_pct",  "readout_pct"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(0)
            cap = QLabel(caption)
            cap.setObjectName("caption")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)

            lbl = QLabel("---")
            lbl.setObjectName(obj_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            col.addWidget(cap)
            col.addWidget(lbl)
            setattr(self, attr, lbl)
            readout_row.addLayout(col)

        readout_row.addStretch()
        root.addLayout(readout_row)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, DAC_MAX)
        self._slider.setValue(0)
        self._slider.valueChanged.connect(self._update_readout)
        root.addWidget(self._slider)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        for label, val in [("0%", 0), ("25%", 64), ("50%", 128), ("75%", 191), ("100%", 255)]:
            b = QPushButton(label)
            b.setObjectName("btn_preset")
            b.clicked.connect(lambda _, v=val: self._set_preset(v))
            btn_row.addWidget(b)

        btn_row.addStretch()

        self._btn_send = QPushButton(f"▶  SEND  {self.cmd_prefix}")
        self._btn_send.setObjectName("btn_send")
        self._btn_send.clicked.connect(self._on_send)
        btn_row.addWidget(self._btn_send)

        root.addLayout(btn_row)

        self._update_readout(0)

    def _update_readout(self, val: int):
        voltage = val / DAC_MAX * self._vref
        pct     = int(val / DAC_MAX * 100)
        self._lbl_raw.setText(f"{val:03d}")
        self._lbl_volt.setText(f"{voltage:.3f} V")
        self._lbl_pct.setText(f"{pct:>3d}%")

    def _on_vref_edited(self):
        try:
            v = float(self._vref_edit.text())
            if v <= 0:
                raise ValueError
            self._vref = v
            self._vref_edit.setText(f"{v:.2f}")
            self._update_readout(self._slider.value())
            self.vref_changed.emit(v)
        except ValueError:
            self._vref_edit.setText(f"{self._vref:.2f}")

    def set_vref(self, vref: float):
        self._vref = vref
        self._vref_edit.setText(f"{vref:.2f}")
        self._update_readout(self._slider.value())

    def get_vref(self) -> float:
        return self._vref

    def _set_preset(self, val: int):
        self._slider.setValue(val)

    def _on_send(self):
        self.send_requested.emit(self.cmd_prefix, self._slider.value())

    def set_enabled(self, enabled: bool):
        self._slider.setEnabled(enabled)
        self._btn_send.setEnabled(enabled)
        for btn in self.findChildren(QPushButton, "btn_preset"):
            btn.setEnabled(enabled)

    def set_all_zero(self):
        self._slider.setValue(0)

    def set_all_max(self):
        self._slider.setValue(DAC_MAX)


# ── Board panel ────────────────────────────────────────────────────────
class BoardPanel(QWidget):
    log_message    = pyqtSignal(int, str)
    status_changed = pyqtSignal(int, bool)
    board_id_changed = pyqtSignal(int, str)

    def __init__(self, board_index: int, port: str, vref: float, parent=None):
        super().__init__(parent)
        self.board_index = board_index
        self._initial_port = port
        self._board_id: int | None = None
        self._ser    = None
        self._worker = None
        self._thread = None
        self._build_ui(vref)

    def _build_ui(self, vref: float):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        conn_box = QGroupBox("  CONNECTION  ")
        conn_grid = QGridLayout(conn_box)
        conn_grid.setSpacing(6)

        conn_grid.addWidget(QLabel("PORT:"), 0, 0)
        self._port_combo = QComboBox()
        conn_grid.addWidget(self._port_combo, 0, 1)

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setObjectName("btn_refresh")
        self._btn_refresh.setFixedWidth(32)
        self._btn_refresh.clicked.connect(self._refresh_ports)
        conn_grid.addWidget(self._btn_refresh, 0, 2)

        self._btn_connect = QPushButton("CONNECT")
        self._btn_connect.setObjectName("btn_connect")
        self._btn_connect.setProperty("connected", "false")
        self._btn_connect.clicked.connect(self._toggle_connection)
        conn_grid.addWidget(self._btn_connect, 0, 3)

        conn_grid.addWidget(QLabel("STATUS:"), 1, 0)
        self._lbl_status = QLabel("DISCONNECTED")
        self._lbl_status.setObjectName("status_err")
        conn_grid.addWidget(self._lbl_status, 1, 1, 1, 3)

        conn_grid.addWidget(QLabel("BOARD ID:"), 2, 0)
        self._lbl_board_id = QLabel("---")
        self._lbl_board_id.setObjectName("scan_result")
        conn_grid.addWidget(self._lbl_board_id, 2, 1)

        btn_blink = QPushButton("🔍 辨識")
        btn_blink.setObjectName("btn_blink")
        btn_blink.clicked.connect(self._blink)
        conn_grid.addWidget(btn_blink, 2, 2)

        btn_setid = QPushButton("設定 ID")
        btn_setid.setObjectName("btn_setid")
        btn_setid.clicked.connect(self._set_board_id)
        conn_grid.addWidget(btn_setid, 2, 3)

        layout.addWidget(conn_box)

        self._dac0 = DACChannelWidget(ch=0, gpio=25, pin=9,  cmd_prefix="V0", vref=vref)
        self._dac1 = DACChannelWidget(ch=1, gpio=26, pin=10, cmd_prefix="V1", vref=vref)
        self._dac0.send_requested.connect(self._send_dac)
        self._dac1.send_requested.connect(self._send_dac)
        self._dac0.vref_changed.connect(self._on_vref_changed)
        self._dac1.vref_changed.connect(self._on_vref_changed)
        layout.addWidget(self._dac0)
        layout.addWidget(self._dac1)

        self._refresh_ports()
        if self._initial_port:
            idx = self._port_combo.findText(self._initial_port)
            if idx >= 0:
                self._port_combo.setCurrentIndex(idx)

    def _refresh_ports(self):
        current = self._port_combo.currentText()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)

    def _toggle_connection(self):
        if self._ser and self._ser.is_open:
            self.disconnect_board()
        else:
            self._connect()

    def _connect(self):
        port = self._port_combo.currentText()
        if not port:
            QMessageBox.critical(self, "Error", "No COM port selected.")
            return
        try:
            self._ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
            self._worker = SerialWorker(self._ser)
            self._worker.line_received.connect(self._handle_rx_line)
            self._worker.error.connect(
                lambda msg: (self.log_message.emit(self.board_index, f"[ERR] RX: {msg}"),
                             self.disconnect_board())
            )
            self._thread = threading.Thread(target=self._worker.run, daemon=True)
            self._thread.start()

            self._dac0.set_enabled(True)
            self._dac1.set_enabled(True)
            self._btn_connect.setText("DISCONNECT")
            self._btn_connect.setProperty("connected", "true")
            self._btn_connect.setStyle(self._btn_connect.style())
            self._port_combo.setEnabled(False)
            self._btn_refresh.setEnabled(False)
            self._set_status(f"CONNECTED   {port}   @ {BAUD_RATE} baud", ok=True)
            self.log_message.emit(self.board_index,
                                  f"[INFO] Connected to {port} @ {BAUD_RATE} baud")
            self.status_changed.emit(self.board_index, True)
            self._send_raw("PING")
        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", str(e))

    def disconnect_board(self):
        if self._worker:
            self._worker.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser    = None
        self._worker = None
        self._thread = None

        self._dac0.set_enabled(False)
        self._dac1.set_enabled(False)
        self._btn_connect.setText("CONNECT")
        self._btn_connect.setProperty("connected", "false")
        self._btn_connect.setStyle(self._btn_connect.style())
        self._port_combo.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._set_status("DISCONNECTED", ok=False)
        self.log_message.emit(self.board_index, "[INFO] Disconnected")
        self.status_changed.emit(self.board_index, False)

    def _handle_rx_line(self, line: str):
        self.log_message.emit(self.board_index, f"[RX]  {line}")
        bid = _parse_board_id(line)
        if bid is not None:
            self._board_id = bid
            self._lbl_board_id.setText(f"ID: {bid}")
            self.board_id_changed.emit(self.board_index, str(bid))
            self.log_message.emit(self.board_index, f"[INFO] Board ID = {bid}")
            return
        if line.startswith("ERR"):
            self.log_message.emit(self.board_index, f"[WARN] Firmware error: {line}")

    def _send_raw(self, cmd: str):
        if not (self._ser and self._ser.is_open):
            return
        try:
            self._ser.write(f"{cmd}\r\n".encode())
            self.log_message.emit(self.board_index, f"[TX]  {cmd}")
        except Exception as e:
            self.log_message.emit(self.board_index, f"[ERR] TX failed: {e}")
            self.disconnect_board()

    def _blink(self):
        if not self.is_connected():
            QMessageBox.warning(self, "提示", "請先連線。")
            return
        self._send_raw("BLINK 3")

    def _set_board_id(self):
        new_id, ok = QInputDialog.getInt(
            self, "設定 Board ID",
            f"ESP32 #{self.board_index + 1} 的新 Board ID (0-255):",
            value=self._board_id if self._board_id is not None else self.board_index,
            min=0, max=255)
        if not ok:
            return
        if self.is_connected():
            self._send_raw(f"ID {new_id}")
        else:
            QMessageBox.warning(self, "提示", "請先連線後再設定 ID。")

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def _on_vref_changed(self, vref: float):
        self._dac0.set_vref(vref)
        self._dac1.set_vref(vref)
        self.log_message.emit(self.board_index, f"[CFG] VREF set to {vref:.2f} V")

    def _send_dac(self, prefix: str, val: int):
        if not (self._ser and self._ser.is_open):
            return
        cmd = f"{prefix} {val}\r\n"
        vref = self._dac0.get_vref()
        try:
            self._ser.write(cmd.encode())
            voltage = val / DAC_MAX * vref
            self.log_message.emit(self.board_index,
                                  f"[TX]  {prefix} {val:>3d}   ({voltage:.3f} V)")
        except Exception as e:
            self.log_message.emit(self.board_index, f"[ERR] TX failed: {e}")
            self.disconnect_board()

    def send_all_zero(self):
        self._dac0.set_all_zero()
        self._dac1.set_all_zero()
        if self.is_connected():
            self._send_dac("V0", 0)
            self._send_dac("V1", 0)

    def send_all_max(self):
        self._dac0.set_all_max()
        self._dac1.set_all_max()
        if self.is_connected():
            self._send_dac("V0", DAC_MAX)
            self._send_dac("V1", DAC_MAX)

    def get_vref(self) -> float:
        return self._dac0.get_vref()

    def get_port(self) -> str:
        return self._port_combo.currentText()

    def _set_status(self, text: str, ok: bool):
        self._lbl_status.setText(text)
        self._lbl_status.setObjectName("status_ok" if ok else "status_err")
        self._lbl_status.setStyle(self._lbl_status.style())


# ── DacToolPage — 嵌入 QStackedWidget 的主頁面 ────────────────────────
class DacToolPage(QWidget):
    _log_signal    = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg    = load_config()
        self._boards: list[BoardPanel] = []
        self._first_enter = True
        self._build_ui()
        self.setStyleSheet(DAC_QSS)
        self._log_signal.connect(self._append_log)

    def _build_ui(self):
        self.setObjectName("dac_central")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        titlebar = QWidget()
        titlebar.setObjectName("dac_titlebar")
        tbl = QHBoxLayout(titlebar)
        tbl.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel("ESP32 DAC CONTROLLER")
        self._title_lbl.setObjectName("dac_title")
        tbl.addWidget(self._title_lbl)
        tbl.addStretch()

        btn_setup = QPushButton("⚙  SETUP")
        btn_setup.setObjectName("btn_setup")
        btn_setup.clicked.connect(self._show_setup)
        tbl.addWidget(btn_setup)
        main_layout.addWidget(titlebar)

        # Body
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 8, 12, 12)
        body_layout.setSpacing(8)
        main_layout.addWidget(body, 1)

        # Global ops
        global_row = QHBoxLayout()
        global_row.setSpacing(6)

        btn_all_zero = QPushButton("ALL ZERO")
        btn_all_zero.setObjectName("btn_global")
        btn_all_zero.clicked.connect(self._all_zero)
        global_row.addWidget(btn_all_zero)

        btn_all_max = QPushButton("ALL MAX")
        btn_all_max.setObjectName("btn_global")
        btn_all_max.clicked.connect(self._all_max)
        global_row.addWidget(btn_all_max)

        global_row.addStretch()

        btn_disconnect_all = QPushButton("DISCONNECT ALL")
        btn_disconnect_all.setObjectName("btn_global_danger")
        btn_disconnect_all.clicked.connect(self._disconnect_all)
        global_row.addWidget(btn_disconnect_all)

        body_layout.addLayout(global_row)

        # Splitter: tabs + log
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        self._tabs = QTabWidget()
        splitter.addWidget(self._tabs)

        log_box = QGroupBox("  SERIAL LOG  ")
        log_layout = QVBoxLayout(log_box)
        log_layout.setSpacing(4)

        self._log_edit = QTextEdit()
        self._log_edit.setObjectName("log")
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(60)
        log_layout.addWidget(self._log_edit)

        clear_row = QHBoxLayout()
        clear_row.addStretch()
        btn_clear = QPushButton("CLEAR LOG")
        btn_clear.setObjectName("btn_clear")
        btn_clear.clicked.connect(self._log_edit.clear)
        clear_row.addWidget(btn_clear)
        log_layout.addLayout(clear_row)

        splitter.addWidget(log_box)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        body_layout.addWidget(splitter, 1)

    # ── Board management ──────────────────────────────────────────────

    def _rebuild_boards(self):
        # Disconnect and remove existing boards
        for panel in self._boards:
            panel.disconnect_board()
        self._boards.clear()

        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if w:
                w.deleteLater()

        board_count = self._cfg.get("board_count", 1)
        boards_cfg  = self._cfg.get("boards", [])

        suffix = f"  ·  {board_count} Board{'s' if board_count > 1 else ''}"
        self._title_lbl.setText(f"ESP32 DAC CONTROLLER{suffix}")

        for i in range(board_count):
            bcfg = boards_cfg[i] if i < len(boards_cfg) else {}
            port = bcfg.get("port", "")
            vref = bcfg.get("vref", DEFAULT_VREF)
            panel = BoardPanel(board_index=i, port=port, vref=vref)
            panel.log_message.connect(self._on_board_log)
            panel.status_changed.connect(self._on_board_status)
            panel.board_id_changed.connect(self._on_board_id)
            self._boards.append(panel)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(panel)

            tab_label = self._make_tab_label(i, port, False)
            self._tabs.addTab(scroll, tab_label)

    # ── Page lifecycle ────────────────────────────────────────────────

    def auto_load(self):
        """啟動時靜默載入已儲存的設定（如果有的話），不彈對話框。"""
        if self._cfg.get("boards") and self._cfg["boards"][0].get("port"):
            self._rebuild_boards()

    def enter_page(self):
        if self._first_enter:
            self._first_enter = False
            self._show_setup()

    def _show_setup(self):
        # Disconnect existing boards before reconfiguring
        for panel in self._boards:
            panel.disconnect_board()

        dlg = SetupDialog(self._cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._cfg = dlg.get_result()
            if self._cfg.get("remember_setup", True):
                save_config(self._cfg)
            self._rebuild_boards()

    def cleanup(self):
        """Called when the main window is closing."""
        self._save_config()
        for panel in self._boards:
            panel.disconnect_board()

    # ── Tab labels ────────────────────────────────────────────────────

    def _make_tab_label(self, index: int, port: str, connected: bool,
                        board_id: str = "") -> str:
        port_str = port if port else "---"
        status   = "●" if connected else "○"
        id_str   = f"  [ID:{board_id}]" if board_id else ""
        return f" #{index + 1}  {port_str}{id_str}  {status} "

    def _on_board_status(self, board_index: int, connected: bool):
        panel = self._boards[board_index]
        port  = panel.get_port()
        bid   = str(panel._board_id) if panel._board_id is not None else ""
        label = self._make_tab_label(board_index, port, connected, bid)
        self._tabs.setTabText(board_index, label)
        self._save_config()

    def _on_board_id(self, board_index: int, board_id_str: str):
        panel = self._boards[board_index]
        port  = panel.get_port()
        connected = panel.is_connected()
        label = self._make_tab_label(board_index, port, connected, board_id_str)
        self._tabs.setTabText(board_index, label)

    # ── Global operations ─────────────────────────────────────────────

    def _all_zero(self):
        for panel in self._boards:
            panel.send_all_zero()
        self._append_log("[GLOBAL] ALL ZERO")

    def _all_max(self):
        for panel in self._boards:
            panel.send_all_max()
        self._append_log("[GLOBAL] ALL MAX")

    def _disconnect_all(self):
        for panel in self._boards:
            if panel.is_connected():
                panel.disconnect_board()
        self._append_log("[GLOBAL] DISCONNECT ALL")

    # ── Log ───────────────────────────────────────────────────────────

    def _on_board_log(self, board_index: int, msg: str):
        self._log_signal.emit(f"[#{board_index + 1}] {msg}")

    def _append_log(self, msg: str):
        ts   = time.strftime("%H:%M:%S")
        line = f"{ts}  {msg}"
        self._log_edit.append(line)

    # ── Config persistence ────────────────────────────────────────────

    def _save_config(self):
        boards = []
        for panel in self._boards:
            boards.append({
                "label": f"ESP32 #{panel.board_index + 1}",
                "port": panel.get_port(),
                "vref": panel.get_vref(),
            })
        self._cfg["board_count"] = len(self._boards)
        self._cfg["boards"] = boards
        save_config(self._cfg)
