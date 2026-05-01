# House Agent

不動產經紀人考試的教學、複習、模擬考、法條關聯與歷屆試題整合系統。

## 目前功能

- 題庫練習、錯題複習、申論題練習
- 模擬考與固定 `60` 分及格標準
- 歷屆試題匯入與法條關聯
- 依科目統計法條出題次數、重要度與學習權重
- 管理後台專責處理法條更新、法條稽核、使用者管理
- 多使用者資料隔離：每個使用者只看到自己的學習狀態

## 驗證與權限

- 一般使用者：
  - 可用本機帳號登入
  - 若已設定 Google OAuth，可直接用 Google 登入
  - 只能看到自己的測驗紀錄、統計、錯題與模擬考結果
- 管理者：
  - 可登入 `/admin`
  - 可更新法條、執行法條稽核、管理使用者權限

## OAuth 登入

目前已實作：

- Google OAuth / OIDC 登入
- GitHub OAuth 登入
- 本機帳號登入保留作為管理員與備援登入
- OAuth 身分綁定資料表 `user_identities`

### Google

啟用前請先在 Google Cloud Console 建立 OAuth Client，然後設定環境變數：

```bash
set GOOGLE_CLIENT_ID=你的_client_id
set GOOGLE_CLIENT_SECRET=你的_client_secret
```

Google Console 的 redirect URI 請加入：

```text
http://localhost:8000/auth/google/callback
```

### GitHub

請在 GitHub OAuth Apps 建立應用，然後設定環境變數：

```bash
set GITHUB_CLIENT_ID=你的_client_id
set GITHUB_CLIENT_SECRET=你的_client_secret
```

GitHub 的 callback URL 請設定：

```text
http://localhost:8000/auth/github/callback
```

若未設定對應環境變數，系統會自動停用該 provider 的登入按鈕，只保留已配置的登入方式。

## 預設管理員

- 帳號：`admin`
- 密碼：`admin1234`

建議上線前立即改密碼。

## 密碼安全

- 本機帳號已改用 `bcrypt`
- 舊的 `SHA-256` 帳號會在首次成功登入後自動升級為 `bcrypt`

## 法條維護

法條更新與稽核已移到管理後台，不提供一般使用者操作。

若要用腳本手動執行：

```bash
python scripts/fetch_laws.py
python scripts/audit_laws.py
```

## 啟動

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

開啟：

```text
http://localhost:8000
```
