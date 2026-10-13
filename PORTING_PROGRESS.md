# 手機版移植紀錄

## Debug 工作台第一階段（2026-10-13）

本文件提及的 `artifacts/` 報告與截圖為本機驗證證據，不一定隨原始碼發布；可重跑的測試位於 `tests/`。

- 桌面分區：四項量測並排、右側指令、底部可調事件區。凍結顯示不停止採樣，警報及保存錯誤持續更新。
- SQLite 背景保存 RAW、Validity、UTC 毫秒時間與事件；有限佇列，提交後才計數，無效選用欄位為 NULL。紀錄及 CSV 均建立新檔，不覆寫已有資料。
- 紀錄期間切頁／最小化持續收集；單一裝置工作階段，全域狀態列可返回工作台。停止／關窗等待寫入及匯出；設備切換、資訊、OTA 與更新安裝受紀錄狀態保護。
- 事件搜尋、類型篩選、分頁、複製及人工標記；即時緩衝上限 1000 筆，本次紀錄檔可查所有已寫入事件。本節取代歷史版本的 20／10 筆限制及紀錄期間最小化暫停行為。
- 從明確 stage 的原始碼匯出乾淨目錄（不含完整 Flutter），完整 unittest 83 項通過，exit 0。另有獨立 7 項競態驗證與生命週期重跑；修復關窗時延後進頁重新建立 controller 的競態。
- 已知量測對回 SQLite；壓力測試完整讀回 10,000 筆量測與 10,000 筆標記，SQLite integrity_check=ok，事件緩衝 1000，峰值待寫 206。這是快速模擬壓力測試，不代表數小時實機測試。
- Qt/qasync smoke 通過；留存 960×850、1280×900 截圖，獨立 UI 審查通過。手動更新選單實際查詢 GitHub API 通過，紀錄期間不發送查詢。
- v0.1.8 發布建置：`dist/v0.1.8/PC_GIOSXSR_Demo.exe`，41,029,661 bytes，SHA256 `bd769e8d62239438464dd09779cc1e9fb76bdf79d0bd5d72471d892e9a3d26b3`。PyInstaller 與 EXE --ui-smoke exit 0，診斷讀回版本 0.1.8。
- 更新安裝改為同目錄暫存、SHA256 驗證及原子替換；逾時不強制關閉仍執行中的程式，失敗保留下載與可用舊版。9 個 PowerShell 實跑案例涵蓋部分複製、同大小損壞、檔案鎖、既有備份、啟動失敗、替換後驗證失敗還原及還原受鎖保護。舊版升級仍由舊版 updater 執行，新修正於安裝本版後生效。
- 隔離副本以 v0.1.7 舊 helper 與本版新 helper 各自實際替換／啟動最終 EXE，全部 exit 0；診斷確認 0.1.7→0.1.8，目標 SHA256 與正式成品一致，下載／備份清理成功。未操作使用者既有程序，v0.1.0／0.1.1 升級鏈未追溯驗證。
- 實體 BLE、數小時連續紀錄、真實斷電重連及硬體指令回應未驗證。趨勢圖、重新開啟舊紀錄、歷史回放尚未實作。實機步驟如下：
  1. 啟動 `dist/v0.1.8/PC_GIOSXSR_Demo.exe`，連線 PRU，進入除錯工作台；確認四項量測更新、無效值顯示破折號。
  2. 新建 .sqlite，確認已存筆數增加並加入標記。凍結畫面約 10 秒，數值／RAW 保持，但已存筆數增加；解除凍結後恢復即時顯示。
  3. 返回選單／掃描頁、最小化約 1 分鐘再返回；確認同一紀錄持續。Windows 睡眠不能採樣，長時間驗證須保持喚醒。
  4. 事件選「紀錄檔」搜尋標記，測試篩選／分頁；停止後匯出 CSV，比對已知量測、RAW、Validity 與時間。CSV 使用 UTC，畫面依本機時區；無效選用欄位留空。
  5. 再做短紀錄並直接關窗，確認程式結束後 SQLite 可讀且有結束事件。紀錄中不要單獨移動 SQLite 檔，WAL 可能仍有尚未合併的資料。
  6. 依正常工作時長實機連續紀錄，檢查保存筆數、錯誤事件及磁碟空間；如流程允許，再安全斷開 PRU 驗證重連。勿以真實過壓／過流製造警報測試。

## PRU 頁面差異補齊（2026-10-02，程式與打包驗證通過）

- 依 `artifacts/PRU_PARITY_AUDIT_2026-10-02.txt` 的 11 組差異修正；旗標名稱、UUID、指令 bytes 與輪詢時序維持手機定義。
- 驗收：動態八個旗標分色、通知詳細快照、事件等級、讀取逾時文字、原指令重試、bytes 預覽、操作鎖定、重連提示、可收合靜態資訊、載入／缺服務狀態、最近10筆事件與較早筆數。
- PC 額外 RAW／通知計數保留在預設收合的診斷區；不影響手機對應功能。已完成回歸測試、Qt 操作實跑及 fresh agent 驗收；實體 BLE 另列未驗證。
- 已實作：通知快照與詳細視窗、每筆事件 kind/level、讀取 timeout 轉成「逾時 5 s」、原指令重試與封包預覽、傳送／讀取鎖定、重連事件提示、八個動態／靜態 bit chip、Static 摘要收合與門檻分色、頁面狀態與診斷區。已完成回饋行為及生命週期的回歸驗證。
- 驗證進度：41 個 unittest 全過（exit 0，含新增11項）；擴充 `tests/ui_smoke.py` 在 qasync/Qt 中實際點擊通知詳細、Static 展開、重新進頁，全部通過；`main.py --ui-smoke` exit 0。已檢視 `artifacts/pru_feedback_full.png` 與 `artifacts/pru_alert_detail.png`，修正展開按鈕箭頭的字型缺字。
- 手機提示時長同步：notify 5秒、error 4秒、一般提示3秒；通知5秒節流維持不變。
- fresh agent 獨立驗收 PASS：重跑41項測試與擴充 Qt smoke；直接對照手機來源的256組 Dynamic 分色、256組 Static 分色與256組 Notify解析全通過，另驗證舊 session 的 action 不會觸發新頁。逐條11項驗收見 `artifacts/PRU_FIX_REVIEW_2026-10-02.txt`。
- PyInstaller 打包 exit 0；成品 `dist/pru_parity_20261002/PC_GIOSXSR_Demo.exe` 執行 `--ui-smoke` exit 0，大小40,075,876 bytes，SHA256 `62a37e3b80f655934d8ada06509e4b711038238c18bd93cbdbb794aab3372d4f`。未覆蓋舊EXE、未變更發布版號／推送／上傳。
- 本輪實機驗證尚未執行：關閉舊程式後執行上述EXE，連同一台PRU進測試頁；以正常可取得的警報或韌體測試模式確認八個旗標個別顏色及通知「詳細」；展開Static確認能力旗標，再返回／重新進頁確認收合重置。連線中斷後確認重連提示。若有安全的測試模式可產生0x88，應看到Over-voltage紅色、Charge Complete綠色；不要以真實過壓／過流方式製造測試條件。

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
4. 觸發警報確認計數每筆增加、保留20筆、顯示最近10筆及較早筆數、5秒內提示不洗版。送出 Control 後觀察 Tester／Alert／Validity 變化，3秒無變化只顯示觀察結果，不宣稱寫入失敗。
5. 返回掃描確認原設備仍連線，可連第二設備再切回第一設備；使用獨立斷線按鈕中止選取設備。
6. 使用正確且已知可用的 .bin：按設備更新並確認，設備應進 OTA；重新掃描並連線 `OTAServiceMgr`，選檔開始更新。完成後重連確認韌體版本與基本功能。此步會實際寫入設備韌體，未在本次自動測試執行。

## 明確平台差異

- Windows 的 WinRT 自動協商 MTU，替代手機 Android `requestMtu`；封包尺寸公式不變。
- 手機頁面以桌面控制項呈現；最小化／隱藏對應手機 background，單純失去焦點（例如確認對話框）不暂停。
- OTA 斷線仍返回掃描，但不把斷線本身宣稱為燒錄驗證成功；空 bin／短 ACK 顯示錯誤。
- 保留既有 PC 軟體更新功能；未執行發佈或上傳。
