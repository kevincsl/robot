# QUICK REFERENCE

一頁式速查表（Telegram 操作版）。

## 1) 最常用 10 條指令

- `/status`：看目前狀態
- `/help`：看完整指令
- `/provider codex`：切 provider
- `/model gpt-5.4`：切模型
- `/brain`：開第二大腦選單
- `/braininbox <內容>`：先收集想法
- `/brainsearch <關鍵字>`：找筆記
- `/brainbatchauto 5`：自動整理最近 Inbox/Daily
- `/brainweb <url>`：抓網頁到 Daily（含摘要+tags）
- `/brainschedule <自然語言>`：新增行程

## 2) 三條最短流程

### A. 每日收集整理
1. `/braininbox 今天要補報表權限控管`
2. `/brainbatchauto 5`
3. `/braindaily`

### B. 快速找資料
1. `/brainsearch 匯出報表`
2. 點搜尋結果打開
3. 需要補充就再 `/braininbox ...`

### C. 網址收錄
1. `/brainweb https://www.koc.com.tw/archives/638837`
2. 看回覆的 `tags` 與 `摘要重點`
3. 後續用 `/brainsearch nvidia` 找回

## 3) 什麼時候用哪個

- 有想法但還沒分類：`/braininbox`
- 想一次整理近期素材：`/brainbatchauto`
- 想查過去資料：`/brainsearch`
- 想保留今天日誌：`brain -> 寫入今日`
- 有日期時間事件：`/brainschedule`
- 想做日/週回顧：`/braindaily`、`/brainweekly`

## 4) 常見錯誤

- `Unknown command`：先 `/help`，再確認版本是否重啟到最新版
- 指令被當聊天文字：確認有加 `/`
- `brainbatchauto` 看起來沒變：它是「新增整理後筆記」，不會刪原文
- `brainweb` 失敗：先確認 URL 可公開存取

## 5) 建議固定節奏

- 每天：收集（Inbox）-> 整理（batchauto）-> 收尾（daily）
- 每週：回顧（weekly）-> 決策（braindecide）

---

完整手冊請看：`FEATURES_GUIDE.md`
