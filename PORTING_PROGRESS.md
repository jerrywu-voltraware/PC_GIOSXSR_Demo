# 手機版移植紀錄

## v0.1.7 發布工作

- 使用者授權更新版號、提交與發布；已讀 `VERSION_UPDATE_WORKFLOW.md` 與 `AUTO_UPDATE_ISSUE_SUMMARY.md`。
- 遠端 latest 為 v0.1.6，main 與本機基底 c127bf3 一致；本次版號更新為 0.1.7，release 附件保留 `PC_GIOSXSR_Demo.exe`。
- 將手機 protocol 原樣複製為 tests fixture，確保乾淨 checkout 可跑測試；完整 Flutter 參考資料與原本未追蹤的交接文件不加入本次提交。
- 30 tests、Qt smoke、必要 py_compile 已通過；v0.1.7 打包 exit 0。
- 隔離 updater 實跑通過：實際 PowerShell 替換目標、SHA256 與新版一致、新版以 UI smoke 重啟（diagnostics 顯示 version=0.1.7）、下載檔／備份／腳本清理完成。不涵蓋舊程序鎖檔情境；未覆蓋使用者正在執行的 EXE。
- 發布 EXE SHA256：`39747395f1d21214a5ea96f4f6cc88e4b5cfb042cfcd4f5d782d2b2c4b988bfd`。待提交與 GitHub 發布回讀。

## 動態數據介面補齊（使用者指定）

- 移除掃描頁「只顯示 0501ST」勾選框與名稱篩選邏輯。
- 對照手機 `pru_dynamic_info_card.dart` 與 `PruVrectRangeBar`，改為 2×2 VRECT/IRECT/VOUT/IOUT 大數字卡、即時門檻軌道與游標、MIN/SET/HIGH、門檻來源、動態門檻與警報顯示。
- 維持手機的判斷順序：OV 優先於 HIGH/MIN；各門檻 validity 獨立回補 Static；無效 VOUT/IOUT 顯示破折號；溫度淡化為未支援。僅資料更新移動游標，不自行產生數據。
- 30 項回歸測試已通過；新增游標移動、OV/HIGH/MIN 優先序、無效值、混合門檻回補、無門檻隱藏與保留最後資料測試。Qt smoke 通過，已檢視 `artifacts/dynamic_mobile_style.png`。
- 使用者新增圖示要求：使用本專案 `1024.png`（訊息中的跳脫路徑對應此檔）。主視窗與 QApplication 使用原 PNG，EXE 由 PyInstaller 轉換並嵌入圖示，PNG 一併打包；設定 Windows AppUserModelID。
- 本輪新版輸出 `dist/desktop_ui/PC_GIOSXSR_Demo.exe`：PyInstaller exit 0；EXE `--ui-smoke` exit 0（包含非空視窗圖示斷言）；以 PE resource read-back 確認 7 個尺寸的圖示 bytes 與由 1024.png 轉換出的 ICO 完全相同。
- fresh agent 獨立重跑 30 tests 及 main.py smoke 全過，確認掃描 checkbox 移除、VRECT 手機判斷／比例一致，獨立驗收通過。實體 BLE 持續更新仍需重連實測。
- 使用者驗證：關閉舊程式後執行上述 EXE（或 main.py），掃描頁不再有名稱勾選框；進 PRU 頁可看到四格量測與 VRECT 游標。確認左上角、工作列、EXE 檔案圖示是 1024.png 的藍灰標誌。改變實機量測值時，數字與游標應在選定輪詢週期更新。

## 使用者實測修正：Windows 找不到 PRU Service

- 截圖顯示 `serviceMissing`。確認原實作只對 UUID 做 `endswith(fffe/bbbb)`，未處理 Windows 將 16-bit UUID 展開成 Bluetooth base UUID 的表示法。
- 新增 `app/ble_uuid.py`：將標準 base UUID 還原成手機短 UUID 再匹配，保留 service 首次命中順序及原本自訂 UUID suffix 行為。不使用寬鬆 substring 以免選到其他服務。
- 新增 Windows 展開 UUID、大小寫、無關 UUID 排除，以及真實 BleManager + 模擬 client → controller ready / Static / Dynamic 讀取整合回歸。25 tests 與 Qt smoke 已通過。
- 服務缺失時停止讀取中狀態，並加入完整 discovery UUID 與 characteristic 診斷紀錄。
- 本輪修正版另放 `dist/uuid_fix/PC_GIOSXSR_Demo.exe`，避免與使用者正在執行的舊 exe 衝突。打包 exit 0、EXE `--ui-smoke` exit 0，打包清單包含 `app.ble_uuid`。fresh agent 獨立以 ResourceWarning 視為錯誤重跑 25 tests 全過，UUID first-match 驗收通過。尚未重新連接使用者的實體 PRU 驗證。
- 使用者重測：關閉舊程式，執行上述修正版（或重新執行 `main.py`），重新連線並進入 PRU 測試。預期狀態顯示「已連線」，Static/Dynamic 開始更新；若仍缺服務，設備資訊頁與 `%LOCALAPPDATA%/PC_GIOSXSR_Demo/diagnostics.log` 可提供實際 service/characteristic UUID。

來源：本專案 `gios040Xsr_demo/lib`（使用者訊息中的反斜線跳脫路徑未存在，專案內有完整手機來源）。
依使用者後續指示移除 DAC 工具及 pyserial 相依；保留 PC 自動更新功能。手機已註解、移除入口的工程頁不新增入口。

## 驗收範圍
- PRU 指令 bytes、UUID、服務查找順序、回應式寫入與解析倍率一致。
- 500 ms notify 延遲、循序輪詢 500/1000/2000 ms、5 次失敗暫停、背景暫停。
- 三次重連 0/2/4 s、狀態觀察 3 s、全部警報紀錄與提示 5 s 節流、20 筆紀錄。
- 靜態能力位元、有效性顯示、電壓門檻、溫度停用與原始封包。
- 設備資訊、OTA 啟動、OTAServiceMgr 分流、bin 傳輸與 ACK 重試。
- 模擬 GATT 測試、Qt offscreen 實跑、獨立驗收。實體 BLE/韌體燒錄另列未驗證。

## 進度
1. 已讀手機 controller / GATT / parsers / protocol / OTA 與現有 PC 架構，確認現有 PC 缺少狀態機與 OTA。
2. 已實作 PRU 控制器、桌面狀態視圖、OTA 封包與傳輸、主選單分流，移除 DAC UI。
3. 模擬測試、offscreen、獨立程式驗收已通過。Windows MTU 由系統協商，使用實際 negotiated MTU 計算與手機相同的封包長度。

## 已完成驗證（2026-09-18）

- 22 個 unittest 通過（exit 0）：手機 Dart 16 組指令逐 byte 對照、解析固定向量、短封包、能力 bit、GATT 單一在途、5 次失敗、背景暫停、重連三次與手動重試、警報全收／提示節流、回應觀察、OTA 交握／分包／ACK 15/240，以及多裝置與連線中關閉。
- `tests/ui_smoke.py` Qt offscreen 實跑通過（exit 0）：5 個頁面、無 DAC、按鈕實際操作、PRU 刷新、保留連線返回掃描、重進頁、OTA 檔案重置與取消完成後清理。截圖 `artifacts/pru_desktop.png` 已檢視，中文與英文可正常顯示。
- `main.py --ble-scan-smoke` 實際 Windows BLE 掃描通過（exit 0），本次收到 17 個廣播裝置。這僅證明掃描，不代表 PRU 控制驗證。
- 獨立驗收找出的返回斷線、OTA 導航、資訊頁延遲通知、OTA 頁重進與 shutdown 競態均已修正並加入驗證；fresh agent 獨立重跑 22 tests 與 Qt smoke，程式終驗通過（限模擬與桌面執行範圍）。
- PyInstaller 6.19.0 打包完成（exit 0），`dist/mobile_parity/PC_GIOSXSR_Demo.exe` 39,846,872 bytes；新執行檔 `--ui-smoke` exit 0、`--ble-scan-smoke` exit 0（17 個廣播裝置）。打包分析清單無 `dac_tool_page` 或 `serial`。
- `git diff --check` 通過；未改動手機原始碼、使用者既有未追蹤文件、舊 dist 根目錄執行檔。

## 實機驗收步驟（尚未執行）

1. 以相同 PRU 分別連手機與 PC（避免同時連線造成干擾）。確認 2 個 PTU 與 14 個 Control 選項一致，使用韌體 BLE log 比對 UUID、bytes、response=True；確認電壓 ×10、PRECT ×1000、溫度停用顯示。
2. 進 PRU 頁確認自動讀取；切換 500/1000/2000 ms，暫停與手動刷新，再最小化／還原視窗，確認背景沒有新輪詢、還原恢復。
3. 中斷 PRU 電源再恢复，確認 0/2/4 s 最多三次重連、成功後刷新 Static、失敗可手動重試；使用者已暫停時不自行恢復 live。
4. 觸發警報確認計數每筆增加、最近20筆紀錄可見、5秒內提示不洗版。送出 Control 後觀察 Tester／Alert／Validity 變化，3秒無變化只顯示觀察結果，不宣稱寫入失敗。
5. 返回掃描確認原設備仍連線，可連第二設備再切回第一設備；使用獨立斷線按鈕中止選取設備。
6. 使用正確且已知可用的 .bin：按設備更新並確認，設備應進 OTA；重新掃描並連線 `OTAServiceMgr`，選檔開始更新。完成後重連確認韌體版本與基本功能。此步會實際寫入設備韌體，未在本次自動測試執行。

## 明確平台差異

- Windows 的 WinRT 自動協商 MTU，替代手機 Android `requestMtu`；封包尺寸公式不變。
- 手機頁面以桌面控制項呈現；最小化／隱藏對應手機 background，單純失去焦點（例如確認對話框）不暂停。
- OTA 斷線仍返回掃描，但不把斷線本身宣稱為燒錄驗證成功；空 bin／短 ACK 顯示錯誤。
- 保留既有 PC 軟體更新功能；未執行發佈或上傳。
