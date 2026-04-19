# OpenAI Forward

[繁體中文](./README.md) | [English](./README_EN.md)

OpenAI API 轉發服務，適合部署在可連線到 OpenAI API 的主機上，讓其他環境透過這個服務間接存取 OpenAI。

## 專案出處

本專案修改自原始專案：

- 原作者 GitHub：`beidongjiedeguang`
- 原始專案網址：`https://github.com/beidongjiedeguang/openai-forward`
- 目前版本說明：依原始專案 fork / clone 後持續修改

此 README 已改寫為繁體中文，後續內容以目前這個修改版本為準。

## 功能

- 支援轉發 OpenAI API 請求
- 支援串流回應
- 支援自訂路由前綴
- 支援 Docker 部署
- 支援 pip 安裝執行
- 支援使用預設 OpenAI API Key
- 支援以自訂 `FORWARD_KEY` 取代直接暴露 OpenAI API Key
- 支援記錄聊天內容日誌
- 支援 Cloudflare、Railway、Render 等部署方式

## 使用情境

這個專案主要用來解決某些環境無法直接連到 OpenAI API 的問題。

原本客戶端會呼叫：

```text
https://api.openai.com/v1/chat/completions
```

部署本服務後，可改為呼叫：

```text
http://{your-host}:{port}/v1/chat/completions
```

也就是由本服務接收請求，再轉發到真正的 OpenAI API。

## 快速開始

### 用 pip 安裝

```bash
pip install openai-forward
```

啟動服務：

```bash
openai-forward run --port=8000 --workers=1
```

若要同時指定預設 API Key：

```bash
openai-forward run --port=8000 --workers=1 --api_key "sk-xxxx"
```

### 用 Docker 執行

```bash
docker run --name="openai-forward" -d -p 9999:8000 beidongjiedeguang/openai-forward:latest
```

如果要提供預設 API Key，可在啟動時加入環境變數：

```bash
docker run --name="openai-forward" -d ^
  -p 9999:8000 ^
  -e OPENAI_API_KEY="sk-xxxx" ^
  beidongjiedeguang/openai-forward:latest
```

## 使用方式

### Python

```python
import openai

openai.api_base = "http://{your-host}:{port}/v1"
openai.api_key = "sk-xxxx"
```

### JavaScript / TypeScript

```ts
import { Configuration } from "openai";

const configuration = new Configuration({
  basePath: "http://{your-host}:{port}/v1",
  apiKey: "sk-xxxx",
});
```

### curl

```bash
curl http://{your-host}:{port}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-xxxx" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### 圖片生成

```bash
curl http://{your-host}:{port}/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-xxxx" \
  -d '{
    "prompt": "A photo of a cat",
    "n": 1,
    "size": "512x512"
  }'
```

## 部署選項

可參考 [deploy.md](./deploy.md)。

支援方式包括：

- pip 部署
- Docker 部署
- Cloudflare 部署
- Railway 部署
- Render 部署

## 設定

### `openai-forward run` 參數

| 參數 | 說明 | 預設值 |
| --- | --- | --- |
| `--port` | 服務埠號 | `8000` |
| `--workers` | worker 數量 | `1` |
| `--base_url` | 目標 OpenAI API 位址 | `https://api.openai.com` |
| `--api_key` | 預設 OpenAI API Key | `None` |
| `--forward_key` | 自訂轉發驗證 Key | `None` |
| `--route_prefix` | 路由前綴 | `None` |
| `--log_chat` | 是否記錄聊天內容 | `False` |

### 環境變數

可透過 `.env` 設定：

| 變數 | 說明 | 預設值 |
| --- | --- | --- |
| `OPENAI_BASE_URL` | 上游 OpenAI API 位址 | `https://api.openai.com` |
| `OPENAI_API_KEY` | 預設 OpenAI API Key，可放多組，以空白分隔 | 空 |
| `FORWARD_KEY` | 對外暴露的轉發驗證 Key，可放多組，以空白分隔 | 空 |
| `ROUTE_PREFIX` | 路由前綴 | 空 |
| `LOG_CHAT` | 是否記錄聊天內容 | `false` |
| `IP_WHITELIST` | IP 白名單，以空白分隔 | 空 |
| `IP_BLACKLIST` | IP 黑名單，以空白分隔 | 空 |

## 驗證邏輯說明

- 若請求直接帶 OpenAI API Key，服務會沿用該 Key 轉發。
- 若啟用 `FORWARD_KEY`，外部可傳送 `FORWARD_KEY`，再由服務替換成真正的 OpenAI API Key。
- 若設定了預設 `OPENAI_API_KEY` 且未設定 `FORWARD_KEY`，服務可進入免驗證轉發模式。
- 若設定多組 `OPENAI_API_KEY`，目前程式會以輪詢方式使用。

## 聊天記錄

若啟用 `LOG_CHAT=true`，服務會將聊天內容記錄到 `./Log/chat.log`。

這個功能適合除錯與追查，但上線前應評估：

- 是否會記錄敏感資料
- 是否符合你的隱私與合規要求
- 是否需要搭配檔案輪替與保存政策

## 已知限制

- 專案目前仍偏向舊版 OpenAI 相容介面
- 部分檔案與註解仍有舊編碼殘留
- 測試與現代 Python / Windows 開發流程仍需整理
- 某些功能路徑尚未完整實作

## 開發

安裝依賴：

```bash
pip install -r requirements.txt
```

若要使用完整打包資訊與額外設定，請參考 [pyproject.toml](./pyproject.toml)。

執行測試：

```bash
pytest -q
```

## 授權

本專案沿用原始專案授權，詳見 [LICENSE](./LICENSE)。
