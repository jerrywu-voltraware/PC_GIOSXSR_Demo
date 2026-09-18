# PC_GIOSXSR_Demo

Windows 桌面版 GIOS BLE SR 工具。以本專案 `gios040Xsr_demo/lib` 手機原始碼為控制行為基準；DAC 工具已移除。

## 功能

- BLE 掃描、保留多個設備連線、個別斷線；返回掃描不切斷連線。
- 即時數據採手機版四格數字卡與 VRECT MIN/SET/HIGH 動態游標；無效值、OV/OC 警報及門檻來源與手機一致。
- 視窗、工作列與 EXE 圖示使用專案 `1024.png`。
- 設備資訊：Service / Characteristic / Properties，與手機相同的延遲通知訂閱。
- PRU：2 組 PTU / 14 組 Control 指令、快速 Enable/Disable、Static / Dynamic 解析、有效性位元、電壓門檻、原始封包與事件紀錄。
- 500 ms / 1 s / 2 s 循序輪詢、5 次失敗暫停、視窗最小化暫停、0/2/4 s 三次自動重連。
- 指令寫入狀態與 3 s 回應觀察；警報全部記錄，畫面提示每 5 s 最多一次，保留最近 20 筆事件。
- 設備更新：送出 OTA 啟動指令後斷線；掃描連線 `OTAServiceMgr` 進入 .bin 傳輸頁。
- 手機目前隱藏的參數修改、工程模式、舊藍牙測試頁，桌面也不增加入口。

## 執行

需要 Windows BLE、Python 3.10 以上。

```powershell
py -3 -m pip install -r requirements.txt
py -3 -X utf8 main.py
```

本次產出的獨立執行檔位於 `dist/v0.1.7/PC_GIOSXSR_Demo.exe`。舊版 `dist` 根目錄執行檔並未覆蓋。

## 驗證

```powershell
py -3 -X utf8 -m unittest discover -s tests -v
py -3 -X utf8 tests/ui_smoke.py
py -3 -X utf8 main.py --ble-scan-smoke
```

`tests/ui_smoke.py` 使用模擬 GATT 與 Qt offscreen，截圖輸出 `artifacts/pru_desktop.png`。完整驗證紀錄與實機步驟見 `PORTING_PROGRESS.md`。

## 平台差異與尚待實機驗證

Windows 由 WinRT 協商 MTU，無 Android `requestMtu` 呼叫；OTA 仍按實際 MTU 使用手機版分包公式、9-byte 交握、8 包 ACK、XOR checksum 與錯誤碼 15/240 重送。

實體 PRU 的讀寫、斷電重連、OTA 燒錄和重啟後版本尚未驗證。OTA 途中斷線沿用手機返回掃描流程，但 PC 不將單純斷線顯示為韌體驗證成功，請重連後確認版本。空韌體與短 ACK 會顯示明確錯誤。

## 打包

```powershell
py -3 -X utf8 -m PyInstaller --noconfirm --distpath dist\v0.1.7 --workpath build\v0.1.7 PC_GIOSXSR_Demo.spec
```
