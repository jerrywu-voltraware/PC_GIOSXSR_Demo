# 版本更新與發佈流程

本專案使用 GitHub Releases 作為更新來源。App 啟動後會檢查最新 release；如果發現比目前版本新的 tag，會通知使用者並下載 release 裡的 `PC_GIOSXSR_Demo.exe`。

## 1. 更新版本號

修改 `app/version.py`：

```python
APP_VERSION = "0.1.1"
```

版本 tag 請使用相同版本並加上 `v` 前綴，例如 `v0.1.1`。

## 2. 建置 exe

在專案根目錄執行：

```powershell
pyinstaller --clean PC_GIOSXSR_Demo.spec
```

建置完成後，新的執行檔會在：

```text
dist\PC_GIOSXSR_Demo.exe
```

## 3. 測試

至少確認：

- `python -m py_compile main.py app\version.py app\updater.py app\windows\main_window.py`
- 從 `dist\PC_GIOSXSR_Demo.exe` 啟動後，主畫面可以正常開啟。
- 手動檢查更新選單可開啟，不會造成程式當掉。

## 4. 提交

```powershell
git status
git add app/version.py app/updater.py app/windows/main_window.py VERSION_UPDATE_WORKFLOW.md .gitignore
git commit -m "Bump version to v0.1.1"
git push
```

## 5. 建立 GitHub Release

```powershell
git tag v0.1.1
git push origin v0.1.1
gh release create v0.1.1 dist\PC_GIOSXSR_Demo.exe --title "v0.1.1" --notes "更新內容說明"
```

重點是 release asset 名稱必須是：

```text
PC_GIOSXSR_Demo.exe
```

App 的自動更新檢查會用這個檔名尋找下載附件。

## 6. 使用者端更新行為

已安裝的 App 啟動後會向 GitHub Releases 檢查最新版本：

- 如果沒有新版本，背景靜默結束。
- 如果有新版本，通知使用者並下載 `PC_GIOSXSR_Demo.exe`。
- 下載完成後，使用者可選擇立即重啟安裝。
- App 會在關閉後用新的 exe 取代目前執行檔，然後重新啟動。
