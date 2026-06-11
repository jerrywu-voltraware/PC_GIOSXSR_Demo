# PC_GIOSXSR_Demo

電腦版 (Windows) GIOS BLE SR Demo，以 Python + PyQt6 實作，功能對應 `Flutter_Gios040Xsr_Demo` 但僅保留：

- 藍牙掃描 / 連線
- 設備資訊
- PRU 測試（PTU 靜態參數、PRU Control、PRU Static/Dynamic Info、Alert Notify）

參數修改 / OTA 更新不移植。

## 環境需求
- Windows 10 1703 以上（`bleak` WinRT backend）
- Python 3.10+
- 藍牙硬體支援 BLE

## 安裝
```powershell
cd PC_GIOSXSR_Demo
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 執行
```powershell
python main.py
```

## CLI BLE smoke test（不開 UI）
驗證 `bleak` 能掃到 / 連到裝置：
```powershell
python -m app.ble_manager --scan
python -m app.ble_manager --connect <MAC or UUID>
```

## 專案結構
```
PC_GIOSXSR_Demo/
├── main.py
├── requirements.txt
└── app/
    ├── constants.py        # UUID、封包字典
    ├── protocol.py         # PRU static/dynamic 位元解析
    ├── ble_manager.py      # bleak 封裝 + CLI smoke test
    └── windows/
        ├── main_window.py  # QStackedWidget 頁面管理
        ├── scan_page.py
        ├── menu_page.py
        ├── info_page.py
        └── pru_test_page.py
```
