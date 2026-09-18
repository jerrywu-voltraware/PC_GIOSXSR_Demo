/// PRU 測試頁通訊常數（UUID、指令集、bit 標籤、時序）。
///
/// 所有數值逐字搬移自舊版 `device_pru_test_screen.dart` /
/// `pru_static_info_card.dart` / `pru_dynamic_info_card.dart`，不得更動。
library;

abstract final class PruUuids {
  static const List<String> targetServiceSuffixes = ['fffe', 'bbbb'];
  static const String ptuStaticParameter =
      '6455e670-a146-11e2-9e96-0800200c9a68'; // write
  static const String pruControl =
      '6455e670-a146-11e2-9e96-0800200c9a67'; // write
  static const String pruAlertNotify =
      '6455e670-a146-11e2-9e96-0800200c9a69'; // notify
  static const String pruStaticRead =
      '6455e670-a146-11e2-9e96-0800200c9a6a'; // read
  static const String pruDynamicRead =
      '6455e670-a146-11e2-9e96-0800200c9a6b'; // read
}

/// 一筆可發送的指令；不覆寫 `==`，dropdown 的 value 必須是
/// [PruCommandSets] 內的同一實例。
class PruCommand {
  const PruCommand(this.label, this.bytes);
  final String label;
  final List<int> bytes;
}

abstract final class PruCommandSets {
  /// PTU Static Parameter（17 bytes）。
  static const List<PruCommand> ptuStaticParameter = [
    PruCommand('1.0W,60ohm,10ohm,v1.3', [
      0x00, 0x0A, 0x01, 0x01, 0x00, 0x00, 0x00, 0xF1, 0xE1, //
      0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]),
    PruCommand('5.0W,100ohm,20ohm,v1.3', [
      0x00, 0x50, 0x05, 0x03, 0x00, 0x00, 0x02, 0xF3, 0xE3, //
      0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]),
  ];

  /// PRU Control（5 bytes，14 筆，順序不變）。
  static const List<PruCommand> pruControl = [
    PruCommand('DISABLE', [0x00, 0x00, 0x00, 0x00, 0x00]),
    PruCommand('DIS_TIME_SET:0ms', [0x00, 0x00, 0x00, 0x00, 0x00]),
    PruCommand('DIS_TIME_SET:10ms', [0x00, 0x00, 0x01, 0x00, 0x00]),
    PruCommand('DIS_TIME_SET:30ms', [0x00, 0x00, 0x03, 0x00, 0x00]),
    PruCommand('DIS_TIME_SET:40ms', [0x00, 0x00, 0x04, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:0ms', [0xC0, 0x00, 0x00, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:10ms', [0xC0, 0x00, 0x01, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:20ms', [0xC0, 0x00, 0x02, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:30ms', [0xC0, 0x00, 0x03, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:40ms', [0xC0, 0x00, 0x04, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:50ms', [0xC0, 0x00, 0x05, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:60ms', [0xC0, 0x00, 0x06, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:70ms', [0xC0, 0x00, 0x07, 0x00, 0x00]),
    PruCommand('EN_TIME_SET:80ms', [0xC0, 0x00, 0x08, 0x00, 0x00]),
  ];

  static PruCommand get defaultPtuStatic => ptuStaticParameter[0];
  static PruCommand get defaultPruControl => pruControl[0];
  static PruCommand get quickDisable => pruControl[0];
  static PruCommand get quickEnable0ms => pruControl[5];
}

/// 皆 MSB-first：index 0 = bit7。
abstract final class PruBitLabels {
  static const List<String> dynamicValidity = [
    'VOUT',
    'IOUT',
    'Temperature',
    'VRECT_MIN_DYN',
    'VRECT_SET_DYN',
    'VRECT_HIGH_DYN',
    'RFU',
    'RFU',
  ];
  static const List<String> dynamicAlert = [
    'Over-voltage',
    'Over-current',
    'Over-temp',
    'PRU Self Protection',
    'Charge Complete',
    'Wired Charger Detect',
    'PRU Charge Port',
    'Adjust Power Response',
  ];
  static const List<String> notifyAlert = [
    'PRU Over-Voltage',
    'PRU Over-Current',
    'PRU Over-Temperature',
    'Self Protection',
    'Charge Complete',
    'Wired Charger Detected',
    'Mode Transition Bit 1',
    'Mode Transition Bit 0',
  ];
  static const List<String> staticInfoPosition = [
    'b7',
    'b6',
    'b5',
    'b4',
    'b3',
    'b2',
    'b1',
    'b0',
  ];

  /// PRU Information (raw[4]) 各位元的能力名稱，依 AirFuel BSS（MSB→LSB）。
  /// bit5 的 0/1 語意未取得第一手佐證，因此標籤只寫能力名稱。
  static const List<String> staticInfoCapability = [
    'NFC receiver',
    'Separate BTLE radio',
    'Power Ctrl Algo',
    'Adjust power',
    'Charge complete connected',
    'PTU test mode',
    'RFU',
    'RFU',
  ];
}

abstract final class PruTiming {
  static const Duration notifyEnableDelay = Duration(milliseconds: 500);
  static const Duration alertSnackThrottle = Duration(seconds: 5);
  static const int readTimeoutSec = 5;
  static const int writeTimeoutSec = 8;
  static const Duration responseWatchWindow = Duration(seconds: 3);
  static const Duration defaultPollInterval = Duration(seconds: 1);
  static const List<Duration> pollIntervals = [
    Duration(milliseconds: 500),
    Duration(seconds: 1),
    Duration(seconds: 2),
  ];
  static const List<Duration> reconnectBackoff = [
    Duration.zero,
    Duration(seconds: 2),
    Duration(seconds: 4),
  ];
  static const int staleFactor = 3;
  static const int maxConsecutiveFailures = 5;
  static const int maxReconnectAttempts = 3;
  static const int logCapacity = 20;
}

abstract final class PruThresholds {
  static const int minPayloadLength = 20;

  /// App 參考值（非裝置回報）。
  static const int tempWarnC = 60;
}

/// 韌體支援度開關。目前韌體沒有實作的欄位在畫面上淡化為停用樣式，
/// 日後韌體支援時把對應的值改成 true 即可恢復（不需要動版面）。
abstract final class PruFeatures {
  /// 溫度：2026-09-09 使用者確認這版韌體沒有作用。
  static const bool temperature = false;
}
