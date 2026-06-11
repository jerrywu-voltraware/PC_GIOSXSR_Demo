"""UUID 與封包常數 — 從 Flutter 版 device_pru_test_screen.dart 搬過來，勿修改值。"""

# 目標 service 的 UUID suffix（Flutter 版同時支援兩個）
TARGET_SERVICE_UUID_SUFFIXES = ("fffe", "bbbb")

# Characteristic UUIDs
UUID_PTU_STATIC_PARAM = "6455e670-a146-11e2-9e96-0800200c9a68"
UUID_PRU_CONTROL      = "6455e670-a146-11e2-9e96-0800200c9a67"
UUID_PRU_NOTIFY       = "6455e670-a146-11e2-9e96-0800200c9a69"
UUID_PRU_STATIC_READ  = "6455e670-a146-11e2-9e96-0800200c9a6a"
UUID_PRU_DYNAMIC_READ = "6455e670-a146-11e2-9e96-0800200c9a6b"

# 掃描名稱過濾（Flutter 版預設 "0501ST"）
FILTER_NAME = "0501ST"

# ===== PTU Static Parameter 封包 =====
PACKET_STATIC_PARAMETER: dict[str, list[int]] = {
    "1.0W,60ohm,10ohm,v1.3": [
        0x00,                   # Optional Fields Validity
        0x0A,                   # PTU Power
        0x01,                   # PTU Max Source Impedance
        0x01,                   # PTU Max Load Resistance
        0x00, 0x00,             # RFU
        0x00,                   # PTU class
        0xF1,                   # Hardware rev
        0xE1,                   # Firmware rev
        0x01,                   # Protocol Revision
        0x00,                   # PTU Number of Devices Supported
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # RFU
    ],
    "5.0W,100ohm,20ohm,v1.3": [
        0x00,
        0x50,
        0x05,
        0x03,
        0x00, 0x00,
        0x02,
        0xF3,
        0xE3,
        0x01,
        0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ],
}

# ===== PRU Control 封包 =====
PACKET_CONTROL: dict[str, list[int]] = {
    "DISABLE":            [0x00, 0x00, 0x00, 0x00, 0x00],
    "DIS_TIME_SET:0ms":   [0x00, 0x00, 0x00, 0x00, 0x00],
    "DIS_TIME_SET:10ms":  [0x00, 0x00, 0x01, 0x00, 0x00],
    "DIS_TIME_SET:30ms":  [0x00, 0x00, 0x03, 0x00, 0x00],
    "DIS_TIME_SET:40ms":  [0x00, 0x00, 0x04, 0x00, 0x00],
    "EN_TIME_SET:0ms":    [0xC0, 0x00, 0x00, 0x00, 0x00],
    "EN_TIME_SET:10ms":   [0xC0, 0x00, 0x01, 0x00, 0x00],
    "EN_TIME_SET:20ms":   [0xC0, 0x00, 0x02, 0x00, 0x00],
    "EN_TIME_SET:30ms":   [0xC0, 0x00, 0x03, 0x00, 0x00],
    "EN_TIME_SET:40ms":   [0xC0, 0x00, 0x04, 0x00, 0x00],
    "EN_TIME_SET:50ms":   [0xC0, 0x00, 0x05, 0x00, 0x00],
    "EN_TIME_SET:60ms":   [0xC0, 0x00, 0x06, 0x00, 0x00],
    "EN_TIME_SET:70ms":   [0xC0, 0x00, 0x07, 0x00, 0x00],
    "EN_TIME_SET:80ms":   [0xC0, 0x00, 0x08, 0x00, 0x00],
}

# ===== Alert Byte bit 對應（PRU Notify）=====
ALERT_BIT_LABELS = [
    (0x80, "PRU Over-Voltage"),
    (0x40, "PRU Over-Current"),
    (0x20, "PRU Over-Temperature"),
    (0x10, "Self Protection"),
    (0x08, "Charge Complete"),
    (0x04, "Wired Charger Detected"),
    (0x02, "Mode Transition Bit 1"),
    (0x01, "Mode Transition Bit 0"),
]

# Dynamic Info 表格 bit 標籤
VALIDITY_BIT_LABELS = [
    "VOUT", "IOUT", "Temperature",
    "VRECT_MIN_DYN", "VRECT_SET_DYN", "VRECT_HIGH_DYN",
    "RFU", "RFU",
]

DYNAMIC_ALERT_BIT_LABELS = [
    "Over-voltage", "Over-current", "Over-temp",
    "PRU Self Protection", "Charge Complete", "Wired Charger Detect",
    "PRU Charge Port", "Adjust Power Response",
]
