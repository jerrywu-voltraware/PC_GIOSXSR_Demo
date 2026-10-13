# PC_GIOSXSR_Demo

Windows 桌面版 GIOS BLE SR 工具。以本專案 `gios040Xsr_demo/lib` 手機原始碼為控制行為基準；DAC 工具已移除。

## 功能

- BLE 掃描、保留多個設備連線、個別斷線；返回掃描不切斷連線。
- 即時數據採手機版四格數字卡與 VRECT MIN/SET/HIGH 動態游標；無效值、OV/OC 警報及門檻來源與手機一致。
- 視窗、工作列與 EXE 圖示使用專案 `1024.png`。
- 設備資訊：Service / Characteristic / Properties，與手機相同的延遲通知訂閱。
- PRU：2 組 PTU / 14 組 Control 指令、快速 Enable/Disable、Static / Dynamic 解析、有效性位元、電壓門檻、原始封包與事件紀錄。
- 500 ms / 1 s / 2 s 循序輪詢、5 次失敗暫停、0/2/4 s 三次自動重連；紀錄期間切頁／最小化持續收集，未紀錄時維持原最小化暫停行為。
- 指令寫入狀態與 3 s 回應觀察；畫面提示每 5 s 最多一次，即時緩衝保留最近 1000 筆事件，開始紀錄後完整事件持續寫入 SQLite。
- PRU Alert 八個旗標個別分色、通知詳細視窗、事件等級；寫入失敗可重送原指令，讀取逾時明確顯示原因。
- 桌面分區配置：四個即時數值、指令側欄及可調高度的事件區；靜態資訊、工程詳情及 RAW 可收合。
- 事件支援搜尋、類型篩選、分頁與複製；紀錄支援已提交筆數、保存錯誤提示、人工標記及 CSV 匯出。
- 設備更新：送出 OTA 啟動指令後斷線；掃描連線 `OTAServiceMgr` 進入 .bin 傳輸頁。
- 手機目前隱藏的參數修改、工程模式、舊藍牙測試頁，桌面也不增加入口。

## 執行

### Debug 工作台第一階段（2026-10-13）

發布建置位於 `dist/v0.1.8/PC_GIOSXSR_Demo.exe`；GitHub 下載入口為 [Releases](https://github.com/jerrywu-voltraware/PC_GIOSXSR_Demo/releases)。請先關閉舊程式，再開啟新版。

1. 連線裝置後開啟「除錯工作台」，按「開始紀錄」選擇新的 `.sqlite` 檔；既有檔案不會被覆寫。
2. 狀態列分別顯示收集與保存狀態。只有實際提交到 SQLite 的量測才計入「已存」；讀取失敗或存檔失敗會明確提示。
3. 「凍結畫面」只保留當下數值／RAW 顯示，收集與存檔繼續；「暫停收集」才停止自動讀值。
4. 紀錄期間可返回選單／掃描頁或最小化。切換裝置、斷線、設備資訊與 OTA 入口暫時停用，避免正在記錄的連線與通知被取代；請先停止紀錄再操作。
5. 事件來源選「紀錄檔」可搜尋所有已寫入的事件；「即時緩衝」僅保留最近 1000 筆。可加入標記，或複製選取事件的完整詳細資料。
6. 「停止紀錄」會等待資料寫完；「匯出 CSV」輸出本次紀錄的量測、靜態資料、事件及 RAW，第一筆資料列為 metadata。無效選用欄位留空；時間以 UTC 保存，介面依本機時區顯示。

CSV 可在紀錄中匯出已提交快照。紀錄與 CSV 一律建立新檔；匯出耗時取決於檔案大小，關閉程式會等候進行中的寫入／匯出。紀錄檔保留在使用者選定位置。

目前只支援單一裝置的紀錄工作階段；趨勢圖、重新開啟舊紀錄與歷史回放屬後續階段。Windows 睡眠期間無法維持 BLE 採樣；需要長時間收集時，請將電腦保持喚醒。

需要 Windows BLE、Python 3.10 以上。

```powershell
py -3 -m pip install -r requirements.txt
py -3 -X utf8 main.py
```

v0.1.8 執行檔位於 `dist/v0.1.8/PC_GIOSXSR_Demo.exe`；2026-10-02 的 `dist/pru_parity_20261002/PC_GIOSXSR_Demo.exe` 及原 `dist/v0.1.7/PC_GIOSXSR_Demo.exe` 均保留。

從舊版升級時仍由舊版內建的更新器安裝；若重啟後版本沒變，請關閉所有舊程式，再從 Releases 手動下載新版 EXE。更新相關紀錄位於 `%TEMP%\PC_GIOSXSR_Demo-apply-update.log`。

## 驗證

```powershell
py -3 -X utf8 -m unittest discover -s tests -v
py -3 -X utf8 tests/ui_smoke.py
py -3 -X utf8 main.py --ble-scan-smoke
```

`tests/ui_smoke.py` 使用模擬 GATT 與 Qt offscreen，截圖輸出 `artifacts/pru_desktop.png`、`artifacts/pru_feedback_full.png`、`artifacts/pru_alert_detail.png`。完整驗證紀錄與實機步驟見 `PORTING_PROGRESS.md`。

## 平台差異與尚待實機驗證

Windows 由 WinRT 協商 MTU，無 Android `requestMtu` 呼叫；OTA 仍按實際 MTU 使用手機版分包公式、9-byte 交握、8 包 ACK、XOR checksum 與錯誤碼 15/240 重送。

實體 PRU 的讀寫、斷電重連、OTA 燒錄和重啟後版本尚未驗證。OTA 途中斷線沿用手機返回掃描流程，但 PC 不將單純斷線顯示為韌體驗證成功，請重連後確認版本。空韌體與短 ACK 會顯示明確錯誤。

## 打包

```powershell
py -3 -X utf8 -m PyInstaller --noconfirm --distpath dist\v0.1.8 --workpath build\v0.1.8 PC_GIOSXSR_Demo.spec
```
