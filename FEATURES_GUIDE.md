# FEATURES GUIDE

完整功能使用手冊（Telegram 使用者版）。

## 1. 你可以用它做什麼

`robot` 主要分成 4 類能力：

- 系統控制：查狀態、切模型、切專案、重置對話執行緒
- AI 任務：把自然語言需求交給 Codex/Gemini/Copilot
- 第二大腦（Brain）：快速收集、整理、搜尋、摘要、行程管理
- 自動化排程：定時執行 AI 任務與 Brain 摘要提醒

## 2. 最快上手流程（每天照做）

1. 白天想到什麼先收進去
- `/braininbox <內容>`
- 範例：`/braininbox 客戶希望匯出報表可選時間範圍`

2. 需要留日誌就寫進 Daily
- `/brainread` 可先看今日內容
- 使用 `brain` 選單按「寫入今日」輸入內容

3. 晚上做一次整理
- `/brainbatchauto 5`
- 會把近期 Inbox/Daily 自動分流成 Project/Knowledge/Resource

4. 需要找資料時
- `/brainsearch <關鍵字>`
- 範例：`/brainsearch 匯出報表`

## 3. 指令總覽（含用途與範例）

### 3.1 系統與模型

- `/status`
用途：看目前 provider/model、佇列、執行狀態、風險旗標
- `/doctor`
用途：快速健康檢查
- `/provider [codex|gemini|copilot]`
範例：`/provider codex`
- `/model [name]`
範例：`/model gpt-5.4`
- `/models`
用途：列出當前 provider 可用模型
- `/projects`
用途：列出可切換專案
- `/project [key-or-label]`
範例：`/project robot`

### 3.2 AI 任務（一般對話 / 執行）

- 直接輸入自然語言
用途：交給目前 provider 執行
範例：`幫我檢查目前 queue 變慢原因`
- `/run <goal>`
用途：明確建立 provider 執行工作
- `/agent <goal>`
用途：走 auto-dev 流程（可帶 profile/config）
- `/agentresume [run_id_or_path]`
用途：續跑上次 auto-dev

### 3.3 第二大腦（Brain）

- `/brain`
用途：開啟 Brain 功能選單（按鈕）
- `/brainread`
用途：讀今日 Daily Note
- `/braininbox <text>`
用途：建立 Inbox 筆記
- `/brainweb <url>`
用途：抓網頁內容寫入今日 Daily，附帶 tags 與 3 點摘要
範例：`/brainweb https://www.koc.com.tw/archives/638837`
- `/brainsearch <query>`
用途：搜尋 secondbrain 並提供可點選結果
- `/brainorganize`
用途：手動把一段內容整理為 Project/Knowledge/Resource
- `/brainbatch`
用途：從最近 Inbox/Daily 選一篇手動整理
- `/brainbatchauto [limit]`
用途：自動批次整理近期 Inbox/Daily
範例：`/brainbatchauto 10`
- `/brainproject <title>`
用途：直接建立 Project note
- `/brainknowledge <title>`
用途：直接建立 Knowledge note
- `/brainresource <title>`
用途：直接建立 Resource note
- `/brainschedule <text>`
用途：新增行程（支援自然語言）
範例：`/brainschedule 明天早上10點開會`
- `/brainremind`
用途：列出近期需要整理/回顧提醒
- `/braindaily`
用途：產生每日摘要
- `/brainweekly`
用途：產生每週摘要
- `/braindecide <question>`
用途：建立決策支援筆記
- `/brainsummary`
用途：建立每週摘要筆記模板

### 3.4 自動化

- `/brainauto [on|off|status]`
用途：開關 Brain 自動化
- `/brainautodaily HH:MM`
用途：設定每日摘要時間
- `/brainautoweekly <weekday 0-6> HH:MM`
用途：設定每週摘要時間
- `/schedule YYYY-MM-DD HH:MM <goal>`
用途：排程 auto-dev 任務
- `/schedules`
用途：查看目前所有 auto-dev 排程（含執行時間與目標）
- `/clearschedule`（同義：`/clearschedules`）
用途：清除目前聊天的所有 auto-dev 排程

## 4. 實際使用場景

### 場景 A：需求很雜，先收集再整理

1. 白天連續輸入：
- `/braininbox 客戶要新增多語系欄位`
- `/braininbox 報表下載要加權限控管`
- `/braininbox https://example.com/jwt-best-practices`

2. 晚上整理：
- `/brainbatchauto 10`

3. 查詢：
- `/brainsearch 權限控管`

### 場景 B：會議後快速沉澱

1. 會議中把片段寫進 Daily（Brain 選單 -> 寫入今日）
2. 會後用 `/brainbatchauto 5`
3. 用 `/braindaily` 看今天焦點，用 `/brainweekly` 做週回顧

### 場景 C：網址收錄與回顧

1. 輸入：
- `/brainweb https://www.koc.com.tw/archives/638837`

2. 系統會回：
- 已寫入路徑
- title
- tags
- 摘要重點（3 點）

3. 之後用 `/brainsearch nvidia` 或 `/brainsearch openclaw` 找回

## 5. 輸入建議（讓結果更準）

- `braininbox` 內容盡量一句一件事，避免混太多主題
- `brainschedule` 盡量含日期/時間，例：`明天 10:00 跟 PM 開會`
- `brainbatchauto` 先從小量開始，建議 `3` 或 `5`
- `/schedule` 請固定格式：`YYYY-MM-DD HH:MM`，例：`/schedule 2026-05-01 10:00 修正 routing fallback`
- 關鍵資料（網址、檔名、專案名）盡量保留原字串

## 6. 常見問題

- Q: 我打指令出現 `Unknown command`？
- A: 先 `/help` 看指令是否在清單中；若剛更新版本，重啟服務後再試。

- Q: 我打指令變成一般對話？
- A: 請確認有加 `/`，例如 `/brainsearch`，不是 `brainsearch`。

- Q: `brainbatchauto` 看不出差別？
- A: 目前是「新增整理後筆記」，不會自動刪除原 Inbox/Daily；請看回覆中的 `source -> path`。

- Q: `/brainweb` 抓不到網頁？
- A: 可能是網站阻擋、網路連線或 URL 格式問題；先測公開頁面，再確認網址可直接用瀏覽器開啟。

## 7. 推薦固定節奏

- 每天：
1. 收集（`/braininbox`）
2. 整理（`/brainbatchauto 5`）
3. 收尾（`/braindaily`）

- 每週：
1. 回顧（`/brainweekly`）
2. 決策（`/braindecide <問題>`）
