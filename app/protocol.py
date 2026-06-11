"""PRU static / dynamic 20-byte 封包解析 — 邏輯對照 Flutter pru_static_info_card.dart / pru_dynamic_info_card.dart。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from .constants import ALERT_BIT_LABELS


def get_bits_msb(byte_value: int) -> list[int]:
    """回傳 bit7..bit0 共 8 位，對應 Flutter getBits()。"""
    return [(byte_value >> i) & 0x01 for i in range(7, -1, -1)]


@dataclass
class PruStaticInfo:
    raw: list[int] = field(default_factory=list)
    optional_fields_validity: Optional[int] = None
    protocol_revision: Optional[int] = None
    pru_category: Optional[int] = None
    pru_information: Optional[int] = None
    hardware_rev: Optional[int] = None
    firmware_rev: Optional[int] = None
    prect_max_mw: Optional[int] = None       # mW
    vrect_min_static_mv: Optional[int] = None  # mV
    vrect_high_static_mv: Optional[int] = None
    vrect_set_mv: Optional[int] = None
    delta_r1_ohm: Optional[float] = None
    valid: bool = False

    def as_display_lines(self) -> list[tuple[str, str]]:
        if not self.valid:
            return [("狀態", "❌ 資料不足")]
        info = self.pru_information or 0
        bits = get_bits_msb(info)
        # NOTE: Flutter 原始碼所有子項都讀 bits[2]（看起來是 bug），此處照搬以維持相同行為
        b2 = bits[2]
        return [
            ("Optional fields validity", str(self.optional_fields_validity)),
            (". Delta R1", str(get_bits_msb(self.optional_fields_validity or 0)[7])),
            ("Protocol Revision", str(self.protocol_revision)),
            ("PRU Category", str(self.pru_category)),
            ("PRU Information", str(self.pru_information)),
            ("PTU Test Mode", "Yes" if b2 == 1 else "No"),
            ("Charge Complete Connected Mode", "Supported" if b2 == 1 else "Not supported"),
            ("Adjust power capability", "Supported" if b2 == 1 else "Not supported"),
            ("Power Control Algorithm Preference",
             "VRECT_MIN_ERROR" if b2 == 1 else "Max System Efficiency"),
            ("Separate BTLE radio in PRU", "Supported" if b2 == 1 else "Not supported"),
            ("NFC receiver", "Supported" if b2 == 1 else "Not supported"),
            ("Hardware rev", str(self.hardware_rev)),
            ("Firmware rev", str(self.firmware_rev)),
            ("PRECT_MAX", f"{self.prect_max_mw} mW"),
            ("VRECT_MIN_STATIC", f"{self.vrect_min_static_mv} mV"),
            ("VRECT_HIGH_STATIC", f"{self.vrect_high_static_mv} mV"),
            ("VRECT_SET", f"{self.vrect_set_mv} mV"),
            ("ΔR1", f"{self.delta_r1_ohm:.2f} Ω" if self.delta_r1_ohm is not None else "N/A"),
        ]


def parse_pru_static(value: list[int] | bytes) -> PruStaticInfo:
    v = list(value)
    info = PruStaticInfo(raw=v)
    if len(v) < 20:
        return info
    info.optional_fields_validity = v[0]
    info.protocol_revision = v[1]
    info.pru_category = v[3]
    info.pru_information = v[4]
    info.hardware_rev = v[5]
    info.firmware_rev = v[6]
    info.prect_max_mw = v[7] * 100 * 10
    info.vrect_min_static_mv = ((v[9] << 8) | v[8]) * 10
    info.vrect_high_static_mv = ((v[11] << 8) | v[10]) * 10
    info.vrect_set_mv = ((v[13] << 8) | v[12]) * 10
    info.delta_r1_ohm = ((v[15] << 8) | v[14]) * 0.01
    info.valid = True
    return info


@dataclass
class PruDynamicInfo:
    raw: list[int] = field(default_factory=list)
    optional_fields_validity: Optional[int] = None
    vrect_mv: Optional[int] = None
    irect_ma: Optional[int] = None
    vout_mv: Optional[int] = None
    iout_ma: Optional[int] = None
    temperature_c: Optional[int] = None
    vrect_min_mv: Optional[int] = None
    vrect_set_mv: Optional[int] = None
    vrect_high_mv: Optional[int] = None
    pru_alert: Optional[int] = None
    tester_cmd: Optional[int] = None
    valid: bool = False

    def as_display_lines(self) -> list[tuple[str, str]]:
        if not self.valid:
            return [("狀態", "❌ 資料不足")]
        return [
            ("VRECT", f"{self.vrect_mv} mV"),
            ("IRECT", f"{self.irect_ma} mA"),
            ("VOUT", f"{self.vout_mv} mV"),
            ("IOUT", f"{self.iout_ma} mA"),
            ("Temperature", f"{self.temperature_c} °C"),
            ("VRECT_MIN_DYN", f"{self.vrect_min_mv} mV"),
            ("VRECT_SET_DYN", f"{self.vrect_set_mv} mV"),
            ("VRECT_HIGH_DYN", f"{self.vrect_high_mv} mV"),
        ]


def parse_pru_dynamic(value: list[int] | bytes) -> PruDynamicInfo:
    v = list(value)
    info = PruDynamicInfo(raw=v)
    if len(v) < 20:
        return info
    info.optional_fields_validity = v[0]
    info.vrect_mv = ((v[2] << 8) | v[1]) * 10
    info.irect_ma = ((v[4] << 8) | v[3])
    info.vout_mv = ((v[6] << 8) | v[5]) * 10
    info.iout_ma = ((v[8] << 8) | v[7])
    info.temperature_c = v[9] - 40
    info.vrect_min_mv = ((v[11] << 8) | v[10]) * 10
    info.vrect_set_mv = ((v[13] << 8) | v[12]) * 10
    info.vrect_high_mv = ((v[15] << 8) | v[14]) * 10
    info.pru_alert = v[16]
    info.tester_cmd = v[17]
    info.valid = True
    return info


def parse_alert_byte(alert: int) -> list[str]:
    """Notify 收到第 0 byte，拆成狀態字串列表。對應 Flutter _onNotificationReceived。"""
    hits = [label for mask, label in ALERT_BIT_LABELS if alert & mask]
    return hits


def format_mac_from_notify(value: list[int] | bytes) -> str:
    """Notify 的 bytes[1..6] = device address，轉 AA:BB:... 大寫。"""
    v = list(value)
    if len(v) < 7:
        return "無"
    return ":".join(f"{b:02x}" for b in v[1:7]).upper()
