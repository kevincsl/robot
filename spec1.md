# spec1.md
# Robot × Teleapp 通訊邊界重構詳細規格（v1.3）

- 文件狀態：Draft for Review
- 日期：2026-05-09
- 作者：Robot 專案重構草案
- 相關專案：`/home/kevin/robot`、`/home/kevin/teleapp`

## 0. 修正紀錄（spec 1.1）

本版根據評估意見調整：

1. 將清除 `TELEAPP_TOKEN` 的高風險步驟延後，要求 Phase 3 穩定運行 7 天後才可執行。
2. 補充「資料流可雙向、程式依賴仍單向」原則：允許 `teleapp -> robot` 以 HTTP 回傳事件，不允許 import 業務邏輯。
3. 新增 `POST /api/commands/receive` 端點，定義 teleapp 傳遞使用者命令給 robot 的契約。
4. API key 命名統一為 `TELEAPP_ROBOT_API_KEY`，header 維持 `X-Robot-Api-Key`。
5. 稽核欄位 `payload_digest` 明確指定 `SHA-256`，並加入 `digest_algorithm` 與 `payload_len`。
6. 將 Phase 0 設為硬性 Gate：未完成依賴盤點不得進入 Phase 1。
7. 新增相容期規格：fallback 僅短期保留，設定最晚下線日與失效條件。

## 0.1 修正紀錄（spec 1.2）

本版根據現有程式碼盤點補上「實際專案修改方案」：

1. 明確區分目前兩條入口：`robot.py -> robot.hosted_app`（teleapp 託管）與 `robot.entry --standalone -> robot.app`（直接 polling）。
2. 將 Phase 0 擴充為實際耦合點盤點，包含 `robot/control.py`、`robot/hosted_app.py`、`robot/app.py`、`scripts/skills/send_tg_file.py`、`.env*.example` 與 README。
3. 補上 `robot` 端先做 adapter 的安全遷移路線：先集中呼叫、再替換 token、最後移除直連 Telegram。
4. 補上 `teleapp` 端 API 實作的邊界限制：需先取得使用者批准後才可修改 `/home/kevin/teleapp`。
5. 將 `send_tg_file.py` 類技能腳本列為第二階段處理，避免破壞目前圖片/影片/瀏覽器截圖回傳能力。
6. 補上每個階段的檔案層級修改清單與驗收條件，讓實作可以拆成小 PR/小變更。

## 0.2 修正紀錄（spec 1.3）

本版新增 Telegram rate limit 穩定區保護條款：

1. 將現有 Telegram rate limit / RetryAfter / typing backoff 行為列為不可破壞區域。
2. Phase B 前不得重寫 `robot/hosted_app.py` 內已穩定的 typing 節流與 backoff 邏輯。
3. 任何改動若觸及 typing、RetryAfter、Telegram 發送頻率、事件 queue，必須先補測試並通過既有 rate limit 相關測試。
4. 遷移到 teleapp API 時，需保持「降低頻率、尊重 RetryAfter、失敗時 backoff、不重複送 typing」這四個行為不變。

## 1. 目標與背景

目前 `robot` 與 Telegram 通訊存在耦合：

1. `robot` 直接讀取/依賴 Telegram 相關環境變數（如 `TELEAPP_TOKEN`）。
2. `robot` 在流程層與通道層責任交疊，違反邊界分離。
3. 後續若擴充 Slack/LINE，安全與維運成本會線性上升。

本規格要完成：

1. 通道憑證集中到 `teleapp`。
2. `robot` 只經由 `teleapp` API 發送訊息。
3. 預設單通道發送（安全），保留受控跨通道轉發（功能）。

## 2. 非目標（Out of Scope）

1. 不在此階段做前端 UI 重構。
2. 不在此階段新增 Slack/LINE 全新功能集合。
3. 不在此階段重寫既有任務編排核心。
4. 不要求一次性清除所有歷史技術債，採分階段收斂。

## 3. 邊界定義

### 3.1 系統責任

1. `robot`：任務理解、流程編排、內容生成、是否轉發的決策。
2. `teleapp`：通道連線、通道憑證、訊息實際投遞、重試與通道錯誤處理。
3. `projects`：任務資料、報告、產物檔案。

### 3.2 依賴方向

只允許：`robot -> teleapp`（API/CLI 契約）

禁止：

1. `teleapp -> robot` import 業務模組。
2. `robot` 直接使用 Telegram SDK/API 發送。

補充（資料回傳例外）：

1. 允許 `teleapp -> robot` 透過 HTTP 被動端點回傳使用者命令事件（例如 `/api/commands/receive`）。
2. 此例外僅限資料傳遞，不改變程式依賴方向；`teleapp` 仍不得 import `robot` 的業務模組（agents、state、routing）。

### 3.3 憑證原則

1. `TELEAPP_TOKEN`、`TELEAPP_ALLOWED_USER_ID` 只存在 `teleapp`。
2. `robot` 僅保留 `TELEAPP_BASE_URL`、`TELEAPP_ROBOT_API_KEY`（可選）。
3. token 輪替不應需要改動 `robot` 程式碼。

## 4. 通訊模式與安全策略

### 4.1 模式

1. `single`（預設）
   - 一次事件只送一個通道。
   - 使用情境：一般通知、日常互動。

2. `relay`（明確指令才可啟用）
   - 來源通道（例如 TG）中由使用者明確下令，轉發到目標通道（例如 Slack）。
   - 不允許自動廣播。

### 4.2 安全控制

1. 目標白名單：可發送目標必須在允許清單。
2. 預覽確認：`relay` 可設定為必須二次確認。
3. mention 限制：預設 `none`，禁止預設 `@channel`。
4. 稽核日誌：所有 `relay` 必記錄。
5. 速率限制：每使用者每分鐘 `relay` 次數上限（預設 5，可配置）。

### 4.3 Telegram Rate Limit 保護原則

目前 Telegram rate limit / RetryAfter / typing backoff 相關修改已穩定，遷移期間不得破壞既有行為。

保護原則：

1. 不得移除或放寬 typing 最小發送間隔。
2. 不得忽略 Telegram `RetryAfter`，必須依回傳秒數或現有預設 backoff 延後下一次發送。
3. 不得在事件 queue、heartbeat、status 更新時增加額外 Telegram API 呼叫。
4. 不得將 typing action 從「節流後發送」改成「每個狀態事件都發送」。
5. 若 teleapp API 尚未支援 typing action，robot 端 typing 可暫時 noop，但不得用新的直連 Telegram 實作替代。

現有穩定行為視為遷移 Gate：

1. `_typing_min_interval_seconds()` 的 clamp 行為需保留。
2. `_TypingController.maybe_send()` 的 `RetryAfter` backoff 行為需保留。
3. `_TypingController.start()` 的 idempotent 行為需保留。
4. `_TypingController.stop()` 需能取消既有 typing loop。

## 5. API 規格（teleapp）

Base URL：`http://127.0.0.1:8787`（可配置）

### 5.1 Health Check

`GET /api/health`

Response:

```json
{
  "ok": true,
  "service": "teleapp",
  "version": "x.y.z",
  "time": "2026-05-09T09:00:00Z"
}
```

### 5.2 查詢可用通道

`GET /api/channels`

Response:

```json
{
  "ok": true,
  "channels": ["tg", "slack"],
  "relay_whitelist": {
    "slack": ["#proj-planning", "#team-updates"]
  }
}
```

### 5.3 發送訊息

`POST /api/messages/send`

Headers:

1. `Content-Type: application/json`
2. `X-Robot-Api-Key: <key>`（若啟用）

Request（single）：

```json
{
  "request_id": "b6b7d6fe-7830-4d45-8620-6ec7b95d87f7",
  "mode": "single",
  "channel": "tg",
  "recipient": "12345678",
  "payload": {
    "type": "text",
    "text": "任務完成"
  },
  "operator_id": "owner-001"
}
```

Request（relay）：

```json
{
  "request_id": "35111f5d-9f72-4384-91f8-1f8bcd57fd2f",
  "mode": "relay",
  "source_channel": "tg",
  "target_channel": "slack",
  "target_id": "#proj-planning",
  "payload": {
    "type": "summary",
    "text": "專案規劃摘要..."
  },
  "operator_id": "owner-001",
  "require_preview": true,
  "mention_policy": "none"
}
```

Response（成功）：

```json
{
  "ok": true,
  "request_id": "35111f5d-9f72-4384-91f8-1f8bcd57fd2f",
  "delivery_id": "dlv_20260509_0001",
  "mode": "relay",
  "channel": "slack",
  "target": "#proj-planning",
  "status": "sent"
}
```

Response（失敗）：

```json
{
  "ok": false,
  "request_id": "35111f5d-9f72-4384-91f8-1f8bcd57fd2f",
  "error": {
    "code": "TARGET_NOT_ALLOWED",
    "message": "target_id is not in relay whitelist"
  }
}
```

### 5.4 錯誤碼

1. `INVALID_MODE`
2. `MISSING_REQUIRED_FIELD`
3. `TARGET_NOT_ALLOWED`
4. `PREVIEW_REQUIRED`
5. `RATE_LIMITED`
6. `CHANNEL_UNAVAILABLE`
7. `DELIVERY_FAILED`
8. `UNAUTHORIZED`

### 5.5 接收通道命令事件（teleapp -> robot）

`POST /api/commands/receive`

用途：

1. `teleapp` 接到通道訊息後，將標準化命令事件轉交給 `robot`。
2. `robot` 僅暴露此被動端點接收事件，不需讓 `teleapp` import 內部邏輯。

Headers：

1. `Content-Type: application/json`
2. `X-Robot-Api-Key: <key>`
3. `X-Signature: <hmac-sha256>`（建議）

Request：

```json
{
  "request_id": "cmd_7f8fd341-1204-47bb-b2d8-0640e03888f4",
  "source_channel": "tg",
  "chat_id": "12345678",
  "user_id": "5668273780",
  "text": "/mode developer",
  "timestamp": "2026-05-09T09:00:00Z",
  "nonce": "9a1b2c3d4e"
}
```

Response：

```json
{
  "ok": true,
  "request_id": "cmd_7f8fd341-1204-47bb-b2d8-0640e03888f4",
  "accepted": true
}
```

安全要求：

1. 驗證 API key / signature。
2. 驗證 `timestamp` 時效（例如 300 秒內）。
3. 以 `request_id + nonce` 做去重，防止重放。

## 6. Robot 端設計變更

### 6.1 新增 Message Adapter

新增模組（建議）：`robot/messaging/teleapp_client.py`

責任：

1. 包裝 HTTP 呼叫與 timeout/retry。
2. 將 `robot` 內部訊息模型轉成 `teleapp` API payload。
3. 統一錯誤轉譯，避免業務層直接處理通道細節。

### 6.2 設定項

`robot` 新增：

1. `TELEAPP_BASE_URL`（必填）
2. `TELEAPP_ROBOT_API_KEY`（選填，但建議啟用）
3. `MESSAGE_BACKEND=teleapp`（預設）
4. `MESSAGE_MODE_DEFAULT=single`

`robot` 移除：

1. `TELEAPP_TOKEN`
2. `TELEAPP_ALLOWED_USER_ID`

### 6.3 呼叫流程

1. `robot` 產出訊息內容。
2. 判定模式：預設 `single`；收到明確跨通道命令則 `relay`。
3. 呼叫 `teleapp_client.send()`。
4. 接收結果：成功則回報；失敗則給可讀錯誤並寫事件日誌。

## 7. Teleapp 端設計變更

### 7.1 API Server

新增或擴充 API 入口（可 FastAPI/Flask，依現況選型）。

最低需求：

1. `GET /api/health`
2. `GET /api/channels`
3. `POST /api/messages/send`

### 7.2 驗證與治理

1. API key 驗證（若啟用）。
2. `relay` 白名單驗證。
3. 內容長度與格式檢查。
4. `request_id` 去重（idempotency window：5 分鐘）。

### 7.3 投遞子系統

1. 通道 adapter（tg/slack）分離。
2. 暫時失敗採指數退避重試（例如 0.5s、1s、2s）。
3. 回傳統一 `delivery_id` 供追蹤。

## 8. 稽核與日誌規格

### 8.1 稽核事件（至少）

1. `event_time`
2. `request_id`
3. `operator_id`
4. `mode`（single/relay）
5. `source_channel`（relay 必填）
6. `target_channel`
7. `target_id`
8. `payload_digest`（SHA-256 digest，避免全文落敏感資料）
9. `digest_algorithm`（固定 `sha256`）
10. `payload_len`
11. `result`（sent/failed/rejected）
12. `error_code`（若失敗）

### 8.2 日誌保留

1. 稽核日誌保留 90 天（預設）。
2. 失敗事件保留 180 天（排錯需要）。

## 9. 遷移計畫（可執行版本）

### Phase 0：盤點（D1）

1. 掃描 `robot` 中 token 讀取與 Telegram 直連點。
2. 建立「呼叫點 -> 新 adapter」對應表。
3. 產出風險清單。

產出物：

1. `docs/migration/tg_dependency_inventory.md`
2. Gate：未完成盤點文件，不得進入 Phase 1。

### Phase 1：teleapp API 最小可用（D2-D3）

1. 實作 health/channels/messages 三個 API。
2. 加入白名單、錯誤碼、基本重試。
3. 本地 smoke test。

產出物：

1. API 規格文件
2. `curl` 測試腳本

### Phase 2：robot adapter 接線（D4-D5）

1. 新增 `teleapp_client`。
2. 把既有通知路徑改走 adapter。
3. 加入 `MESSAGE_BACKEND` feature flag。

產出物：

1. 功能測試通過（single/relay）

### Phase 3：安全策略上線（D6）

1. 啟用 `relay` 白名單與預覽確認策略。
2. 啟用稽核日誌。
3. 壓測基本速率限制。

### Phase 4：清理與切換完成（D7）

1. 前置條件：Phase 3 上線後穩定運行至少 7 天，且達到可觀測門檻（成功率、錯誤率、延遲）。
2. 自 `robot` `.env*`、README 移除 TG token 設定。
3. 移除/封存 `robot` 直連 Telegram 路徑。
4. 更新 runbook 與回滾指引。

## 10. 驗收標準（DoD）

必須全部滿足：

1. `robot` 程式碼中不再需要 `TELEAPP_TOKEN`。
2. `robot` 所有訊息發送皆經 `teleapp` API。
3. `single` 模式可穩定投遞。
4. `relay` 模式僅在明確指令下生效，且白名單有效。
5. 稽核紀錄可追溯單筆跨通道轉發。
6. Token 輪替不需變更 `robot`。

## 11. 測試計畫

### 11.1 單元測試

1. `robot` adapter payload mapping。
2. `teleapp` request validation。
3. 錯誤碼映射與例外處理。
4. Telegram typing throttle、RetryAfter backoff、idempotent start/stop regression tests。

### 11.2 整合測試

1. TG 單通道發送成功。
2. TG -> Slack relay（白名單內）成功。
3. TG -> Slack relay（白名單外）拒絕。
4. preview required 未確認時拒送。

### 11.3 迴歸測試

1. 既有任務流程（報告生成、通知回覆）不退化。
2. `robot` 在 teleapp 暫時不可用時的錯誤提示可讀。
3. Telegram rate limit 相關測試全部通過，且不增加高頻 typing/status 發送。

## 12. 回滾策略

1. 開關回退：`MESSAGE_BACKEND=legacy`（僅短期，最多 2 週）。
2. 若 API 不穩：回退前版本 `teleapp`，保留稽核。
3. 回滾必須記錄原因、時間、影響範圍。

## 12.1 相容期與下線條件

1. 相容期內允許 fallback，但需標記為暫時措施並記錄觸發原因。
2. 設定 fallback 最晚下線日（建議為 Phase 3 上線後第 14 天）。
3. 若連續 7 天無 fallback 觸發，應提前關閉 fallback。
4. 若 fallback 觸發頻率高於門檻，暫停 Phase 4 並先修復根因。

## 13. 開放議題（待定）

1. API key 是否 mandatory（建議是）。
2. preview 是否對所有 relay 強制（建議可配置，預設 true）。
3. relay payload 是否支援附件（建議第二階段再開）。
4. 稽核日誌儲存位置（檔案/DB）。

## 14. 給 Claude 評估重點

請重點評估：

1. 邊界是否足夠清晰且可執行。
2. `single + relay` 模式是否有遺漏的安全風險。
3. API 欄位是否足夠支援稽核與故障排查。
4. 遷移步驟是否能低風險落地。
5. 回滾策略是否實務可行。

## 15. 補充建議（Claude 評估後新增）

### 15.1 Phase 0 應同步掃描 teleapp 端

現有 Phase 0 僅針對 `robot`，但遷移需要完整盤點兩端。建議同步產出：

- `docs/migration/tg_dependency_inventory.md`（robot 端）
- `docs/migration/teleapp_api_contract.md`（teleapp 端需實作的 API 清單）

### 15.2 Robot 接收端點實作指引（章節 6.4）

`POST /api/commands/receive` 在 robot 端除接收外，還需定義後續處理：

1. 解析命令類型（`/mode`、`/status`、自由文字等）。
2. 寫入 `ChatStateStore` 觸發對應處理流程。
3. 即時回傳 `accepted: true`，非同步執行實際邏輯。

建議新增章節「6.4 Command Receive 處理流程」：

```
teleapp 發送命令 → robot 接收並回 ACK → 寫入 queue → async 處理
```

### 15.3 單通道模式下的 chat_id 綁定機制

`single` 模式中，`recipient` 欄位需要 teleapp 維護一份「robot_id → chat_id」的對應表。建議在章節 7 新增：

- teleapp 內部維護 `robot_instances` map：`{robot_id: {chat_id, last_seen, channel}}`
- 訊息投遞時直接查表，robot 無需重複攜帶 `recipient`

### 15.4 Robot 端對 teleapp 的健康偵測

建議在章節 6 新增被動健康偵測（不主動輪詢，改在被拒絕時記錄）：

- `teleapp_client` 內建計數器，連續失敗 N 次後寫 WARNING 事件日誌
- 避免 robot 在 teleapp 不可用時重複嘗試而產生無效重試流量

### 15.5 X-Signature 簽章格式明確定義

章節 5.5 的 `X-Signature` 目前為建議欄位。建議明確化：

- 格式：`HMAC-SHA256(secret_key, request_id + nonce + timestamp)`
- 建議同時對 `text` 欄位做 HMAC，防止內容篡改
- 若無 `X-Signature`，至少需有 API key 驗證（不可完全無驗證）

### 15.6 relay 模式的 abuse 保護

除了速率限制外，建議在章節 7 新增：

- `relay` 白名單應存於 teleapp 的設定檔，而非純記憶體（重啟後應保留）
- `require_preview: true` 時，確認超時時間建議設定（建議 5 分鐘，超時自動取消）

### 15.7 開放議題更新

根據評估，新增為共識的選項：

- ✅ API key 建議為 mandatory（安全預設）
- ✅ preview 對 relay 預設 true，可關閉
- ❓ relay 附件：推遲至第二階段
- ❓ 稽核日誌儲存位置：建議初期用檔案（JSON Lines），後期再遷移到 DB

## 16. 實際專案修改方案（Codex 補充）

本節將規格落到目前 `/home/kevin/robot` 的實際檔案與遷移順序。原則是先降低耦合、保留可回退能力，再逐步移除 `robot` 對 Telegram token 的直接依賴。

### 16.1 現況判斷

目前 `robot` 有兩條啟動入口：

1. `robot.py -> robot.hosted_app`：主要路徑，由 `teleapp robot.py` 或 `robotctl` 啟動，透過 stdin/stdout 與 teleapp supervisor 溝通。
2. `robot.entry --standalone -> robot.app`：開發/除錯用直接 Telegram polling，已透過 `ROBOT_ALLOW_DIRECT_POLLING` 限制。

現階段最安全的遷移策略不是立刻刪除 `robot.app`，而是：

1. 先把 `robot.hosted_app` 內的 Telegram 直連行為抽離。
2. 再把 `robot.control` 的啟動設定從「token 驅動」改成「teleapp endpoint / config 驅動」。
3. 最後才處理 standalone polling 與歷史文件。

### 16.2 已知耦合點與處理策略

| 檔案 | 現況耦合 | 修改策略 | 階段 |
|---|---|---|---|
| `robot/control.py` | 讀取 `TELEAPP_TOKEN`、產生 `.robots/*.env`、檢查 token | 改為讀取 `TELEAPP_BASE_URL` / `TELEAPP_ROBOT_API_KEY`，token 檢查延後到 teleapp 健康檢查 | Phase 2 |
| `robot/hosted_app.py` | `_TelegramTypingClient(os.getenv(\"TELEAPP_TOKEN\"))` 直接建立 Telegram bot | 改成 `TypingNotifier` adapter；短期允許 noop，長期由 teleapp API 發 typing action | Phase 2 |
| `robot/app.py` | 直接 import `telegram`、`TeleApp`、`TelegramGateway` | 保留為 standalone/debug legacy；預設不進主路徑，Phase 4 後再評估移除 | Phase 4+ |
| `robot/config.py` | 仍可能讀取 `TELEAPP_TOKEN` | 改為不提供 token fingerprint；診斷改顯示 teleapp endpoint 狀態 | Phase 3 |
| `robot/diagnostics.py` | 產生 token fingerprint | 改為顯示 `TELEAPP_BASE_URL`、API key 是否設定（不顯示內容） | Phase 3 |
| `scripts/skills/send_tg_file.py` | 直接讀 `.env` token 並呼叫 Telegram API | 第二階段改為呼叫 teleapp file API；第一階段先保留，避免破壞圖片/影片回傳 | Phase 5 |
| `scripts/skills/image_edit_loop.py` | 呼叫 `send_tg_file.py` | 跟隨 `send_tg_file.py`，不單獨改 | Phase 5 |
| `.env*.example` | 教使用者在 robot 側設定 Telegram token | 新增 endpoint 範本；token 欄位移到 teleapp 文件 | Phase 4 |
| `README*.md` | 文件仍要求 robot 設定 token | 改為 robot 只設定 teleapp endpoint；token 輪替在 teleapp | Phase 4 |
| `AGENTS.md` | 技能仍描述從 robot `.env` 讀 TG token | 規格落地後改成透過 teleapp 傳送檔案 | Phase 5 |

### 16.3 修改順序（建議落地版）

Phase A：只盤點，不改行為

1. 建立 `docs/migration/tg_dependency_inventory.md`。
2. 將上表轉成實際盤點文件，標記每個呼叫點的風險等級。
3. 驗收：盤點文件列出所有 `TELEAPP_TOKEN`、`TELEAPP_ALLOWED_USER_ID`、Telegram SDK、Telegram API URL 使用點。

Phase B：robot 端先建立 adapter，但保持舊行為

1. 新增 `robot/messaging/teleapp_client.py`。
2. 新增 `robot/messaging/typing.py`，統一封裝 typing action。
3. `robot/hosted_app.py` 不再直接知道 Telegram token，只呼叫 typing adapter。
4. 驗收：既有 TG 對話、typing 狀態與 agent 回覆仍可運作。

Phase C：teleapp API 接入（需另行批准修改 `/home/kevin/teleapp`）

1. 在 teleapp 實作 `GET /api/health`、`POST /api/messages/send`、`POST /api/commands/receive`。
2. 新增 API key / HMAC 驗證。
3. 新增 relay 白名單與 JSON Lines 稽核日誌。
4. 驗收：使用 curl 可完成 single 發送、relay 白名單拒絕、health check。

Phase D：robotctl 與設定遷移

1. `robot/control.py` 的 `build_launch_spec()` 不再要求 `TELEAPP_TOKEN`。
2. `_write_robot_config()` 不再產生 token 欄位，改產生 `TELEAPP_BASE_URL`、`TELEAPP_ROBOT_API_KEY`、`MESSAGE_BACKEND=teleapp`。
3. 診斷流程不再檢查 token，改檢查 teleapp health。
4. 驗收：新建 `.robots/*.env` 不含 Telegram token，舊設定仍可在相容期啟動。

Phase E：文件與範本切換

1. 更新 `.env.example`、`.env.robot*.example`。
2. 更新 README / RUNBOOK。
3. 更新 AGENTS 技能說明，標記 `send_tg_file.py` 為 legacy。
4. 驗收：文件不再要求在 robot 側填 Telegram token。

Phase F：技能腳本改走 teleapp file API

1. teleapp 補 `POST /api/files/send` 或在 `POST /api/messages/send` 支援附件 payload。
2. `scripts/skills/send_tg_file.py` 改成 legacy wrapper：優先呼叫 teleapp API，僅相容期 fallback 到 Telegram API。
3. `chromeontg`、`imagegen`、`videogen`、`image-edit-loop` 全部改用同一傳檔入口。
4. 驗收：圖片、影片、文件仍能送出，且 robot 端不需要 TG token。

### 16.4 關鍵設計修正

1. `recipient` 不應長期由 robot 保存。長期應由 teleapp 維護 `robot_id -> channel/chat_id` 對應表，robot 只傳 `robot_id` 或 logical recipient。
2. typing action 不應由 `robot` 直接呼叫 Telegram API。若 teleapp API 尚未完成，typing 可暫時 noop，不應為了 typing 保留 token。
3. `robot.app` 應標記為 standalone legacy。它可以保留作為除錯工具，但不得是 production 主路徑。
4. `send_tg_file.py` 的改造應晚於 messages API。它牽涉多個技能，過早改動會擴大風險。
5. `TELEAPP_ROBOT_API_KEY` 應視為 mandatory。規格中雖保留「可選」字樣，但實作預設應要求設定，僅本機開發可關閉。
6. Telegram rate limit 相關邏輯屬於穩定保護區。遷移時應先包 adapter，不應重寫節流、RetryAfter backoff、typing loop 與事件 queue 的互動方式。

### 16.5 實作前置限制

1. 本文件位於 `/home/kevin/robot`，可直接修改。
2. `/home/kevin/teleapp` 屬於另一個專案邊界；依目前專案規則，實作修改前需由使用者在當前對話明確批准。
3. 在未批准修改 teleapp 前，robot 端只能完成盤點、adapter 草稿、文件與測試替身，不應直接改 teleapp 原始碼。

### 16.6 建議第一個實作任務

第一個任務應是 Phase A，而不是直接寫 API：

1. 新增 `docs/migration/tg_dependency_inventory.md`。
2. 將目前掃描結果分類為：設定耦合、啟動耦合、執行期耦合、技能腳本耦合、文件耦合。
3. 每個耦合點標記「可立即改」、「需 teleapp API 後再改」、「Phase 5 再改」。

完成 Phase A 後，再決定 Phase B 的 adapter 介面，這樣後續實作不會漏掉 `send_tg_file.py` 與 `hosted_app.py` 這類容易被忽略但實際會斷功能的路徑。

### 16.7 Rate Limit 保護清單

以下檔案與行為在遷移期間需特別保護：

| 檔案 | 穩定行為 | 遷移限制 |
|---|---|---|
| `robot/hosted_app.py` | `_TypingController` 控制 typing action 的節流、backoff、取消與去重 | Phase B 僅允許抽 adapter，不允許重寫演算法 |
| `robot/hosted_app.py` | `_TelegramTypingClient` 捕捉 `RetryAfter` 並延後下一次發送 | teleapp API 實作需保留等價 backoff 語意 |
| `tests/test_app.py` | typing throttle、RetryAfter、backoff、idempotent 測試 | 觸及 typing 相關程式碼前必須先跑並通過 |
| `robot/agents.py` / `robot/routing.py` | 透過 event raw `typing=active/stop` 控制狀態 | 不得新增高頻 status 事件或改成每次 heartbeat 都觸發 typing |

實作規則：

1. 修改 `robot/hosted_app.py` 前，先新增或保留 rate limit regression tests。
2. 若 adapter 改動導致 typing 行為不明確，預設選擇「少送」而不是「多送」。
3. teleapp API 若新增 typing endpoint，必須支援 per-chat 節流與 `RetryAfter` backoff。
4. Phase B、Phase C、Phase D 的驗收都需包含 rate limit regression 測試。
5. 任何移除 `TELEAPP_TOKEN` 的動作不得以犧牲 typing backoff 穩定性為代價。
