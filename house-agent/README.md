# House Agent
House Agent 是一個面向台灣不動產經紀人考試的學習系統，提供題庫練習、申論題評分、模擬考、錯題複習、歷屆試題瀏覽，以及法條與題目關聯分析。系統也包含管理後台，可用來更新法條、檢查重關聯結果、管理使用者與查看審計紀錄。

---

## 功能概覽
- 題庫練習：依科目或章節抽選選擇題，記錄作答結果與學習統計。
- 申論題練習：提交文字答案後，由本機 `gemini` CLI 評分並回傳優缺點、改寫建議與關鍵法條。
- 模擬考：自動組卷、立即計分，並依各科錯題與法條權重產生複習建議。
- 錯題複習：依錯誤率與法條重要度排序，優先回看高風險題目。
- 法條總覽：瀏覽已收錄法規、條文內容、題庫引用次數與重要度。
- 歷屆試題：瀏覽本地匯入的考古題檔案與已匯入題目。
- 管理後台：法條更新、重關聯摘要、使用者管理、審計紀錄。

---

## 技術需求
- Python 3.11+
- Windows、macOS 或 Linux
- `pip`
- 若要使用申論題評分：
  - 本機需可執行 `gemini` CLI
  - `gemini -p "<prompt>"` 必須能正常回傳 JSON
- 若要使用 OAuth：
  - 需提供 Google / GitHub OAuth client id 與 secret

---

## 安裝與啟動
### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 啟動服務

```bash
uvicorn app.main:app --reload
```

### 3. 開啟網站

```text
http://localhost:8000
```

---

## 主要頁面
- `/`：首頁，顯示各科覆蓋率與近期作答統計。
- `/login`：登入頁，支援本機帳號與 OAuth。
- `/quiz`：選擇題練習。
- `/essay`：申論題練習。
- `/mock-exam`：模擬考。
- `/wrong`：錯題複習。
- `/laws`：法條總覽。
- `/exam-papers`：歷屆試題瀏覽。
- `/admin`：管理後台。
- `/admin/users`：使用者管理。
- `/admin/audit-logs`：審計紀錄。

---

## 一般使用流程
### 每日練習
1. 登入系統。
2. 到 `/quiz` 做選擇題。
3. 到 `/wrong` 回看高錯誤率題目。
4. 需要法條時，從題目中的法條連結跳到 `/laws/{law_id}` 查看條文。

### 申論題
1. 進入 `/essay`。
2. 作答後送出。
3. 系統會顯示分數、優點、待加強處、建議改寫版本與關鍵法條。

### 模擬考
1. 進入 `/mock-exam`。
2. 完成整份考卷並交卷。
3. 在結果頁查看總分、各科成績與複習建議。

---

## 管理流程
### 預設管理員
- 帳號：`admin`
- 密碼：`admin1234`

這是方便本機開發用的預設帳號。若要在多人或正式環境使用，應自行更換。

### 法條維護
1. 進入 `/admin`。
2. 使用 `更新法條` 抓取最新法規內容。
3. 使用 `重跑關聯重評` 重新綁定題目與法條。
4. 檢查最近一次重關聯摘要：
   - `對轉錯`
   - `錯轉對`
   - `僅連結變動`
   - 高風險題目清單

### 使用者管理
在 `/admin/users` 可以：
- 搜尋帳號、顯示名稱、email、provider id
- 篩選狀態、角色、登入來源
- 切換管理員權限
- 啟用或停用帳號
- 切換登入政策（本機登入 / 僅 OAuth）

### 審計紀錄
在 `/admin/audit-logs` 可以：
- 依操作者、目標、動作搜尋
- 查看帳號狀態與登入政策變更記錄

---

## OAuth 設定
### Google OAuth

```bash
set GOOGLE_CLIENT_ID=your_google_client_id
set GOOGLE_CLIENT_SECRET=your_google_client_secret
```

Redirect URI:

```text
http://localhost:8000/auth/google/callback
```

### GitHub OAuth

```bash
set GITHUB_CLIENT_ID=your_github_client_id
set GITHUB_CLIENT_SECRET=your_github_client_secret
```

Callback URL:

```text
http://localhost:8000/auth/github/callback
```

可用 `/health/oauth` 檢查目前是否已啟用 Google / GitHub OAuth。

---

## 法條資料
目前系統收錄的是本專案定義的考試範圍法規，不是全法規資料庫。法條抓取與稽核腳本位於：

```bash
python scripts/fetch_laws.py
python scripts/audit_laws.py
```

法規目錄定義在：

```text
app/law_catalog.py
```

---

## 歷屆試題資料
歷屆試題頁會讀取本地 manifest 與已下載檔案，並同步到資料庫索引。若你有對應的抓取腳本與資料來源，可在匯入後從 `/exam-papers` 瀏覽。

相關程式：
- `app/services/exam_papers.py`
- `app/services/exam_question_import.py`

---

## 測試

```bash
pytest -q
```

---

## 已知限制
- 申論題評分依賴本機 `gemini` CLI；若未安裝或無法執行，`/essay` 評分會失敗。
- 法條收錄範圍以 `app/law_catalog.py` 為準，不是全法規庫。
- 歷屆試題是否可瀏覽，取決於本地是否已有對應 manifest 與檔案。
- 管理後台目前仍保留部分英文字串，例如 `active`、`disabled`、`mixed`、`oauth-only`。

---

## 建議下一步
- 若要做正式部署，先處理：
  - 預設管理員帳號密碼
  - OAuth secret 管理
  - `gemini` CLI 可用性檢查
  - 法條與歷屆試題的固定更新流程
