# Multi-Robot Configuration Examples

> **Note**: This document provides configuration examples and reference for multi-robot setups. For the recommended unified launcher approach, see [MULTI_ROBOT.md](./MULTI_ROBOT.md).
>
> The numbered scripts (`start_robot1.bat`, `start_robot2.bat`, etc.) shown here are convenience wrappers. The unified launcher (`start_robot.bat <config>`) is the current recommended approach for scalability.

## 設定檔方式啟動多個 Robot

每個 robot 使用獨立的 `.env` 檔案，可以設定不同的 AI 模型、API URL 和其他參數。

### 範例結構

```
robot/
├── .env.robot1.example      # Robot 1 設定範本
├── .env.robot2.example      # Robot 2 設定範本
├── .env.robot3.example      # Robot 3 設定範本
├── .env.robot1              # Robot 1 實際設定（不提交到 git）
├── .env.robot2              # Robot 2 實際設定（不提交到 git）
├── .env.robot3              # Robot 3 實際設定（不提交到 git）
├── start_robot1.bat/.sh     # Robot 1 啟動腳本
├── start_robot2.bat/.sh     # Robot 2 啟動腳本
└── start_robot3.bat/.sh     # Robot 3 啟動腳本
```

### 快速開始

1. **複製範本檔案**

```bash
cp .env.robot1.example .env.robot1
cp .env.robot2.example .env.robot2
cp .env.robot3.example .env.robot3
```

2. **編輯設定檔**

每個設定檔都可以獨立設定：
- Telegram Bot Token
- Robot ID
- 預設 AI Provider 和 Model
- API URLs（如果使用自訂端點）
- API Keys
- 其他參數

### 設定檔範例

#### `.env.robot1` - Claude 專用 Robot

```env
TELEAPP_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEAPP_ALLOWED_USER_ID=123456789
TELEAPP_APP=robot.py

# Robot Identity
ROBOT_ID=robot-claude

# Default Provider & Model
ROBOT_DEFAULT_PROVIDER=claude
ROBOT_DEFAULT_MODEL=claude-sonnet-4-6

# Provider Commands
ROBOT_CLAUDE_CMD=claude
ROBOT_CLAUDE_SKIP_PERMISSIONS=0
ROBOT_CLAUDE_MODEL_FLAG=--model

# API Key
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx

# Custom Models
ROBOT_CUSTOM_MODELS=claude-opus-4-7,claude-haiku-4-5
```

#### `.env.robot2` - OpenAI/Codex 專用 Robot

```env
TELEAPP_TOKEN=987654321:ZYXwvuTSRqponMLKjihGFEdcba
TELEAPP_ALLOWED_USER_ID=123456789
TELEAPP_APP=robot.py

# Robot Identity
ROBOT_ID=robot-codex

# Default Provider & Model
ROBOT_DEFAULT_PROVIDER=codex
ROBOT_DEFAULT_MODEL=gpt-5.3-codex

# Provider Commands
ROBOT_CODEX_CMD=codex
ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX=0
ROBOT_CODEX_SKIP_GIT_REPO_CHECK=0

# API Settings
OPENAI_API_KEY=sk-xxxxx
# ROBOT_CODEX_API_URL=https://api.openai.com/v1

# Custom Models
ROBOT_CUSTOM_MODELS=gpt-5.4,gpt-5.4-mini,deepseek-chat
```

#### `.env.robot3` - Gemini 專用 Robot

```env
TELEAPP_TOKEN=555666777:AABBccDDeeFFggHHiiJJkkLLmm
TELEAPP_ALLOWED_USER_ID=123456789
TELEAPP_APP=robot.py

# Robot Identity
ROBOT_ID=robot-gemini

# Default Provider & Model
ROBOT_DEFAULT_PROVIDER=gemini
ROBOT_DEFAULT_MODEL=gemini-2.5-pro

# Provider Commands
ROBOT_GEMINI_CMD=gemini
ROBOT_GEMINI_MODEL_FLAG=--model

# API Settings
GOOGLE_API_KEY=AIzaxxxxx
# ROBOT_GEMINI_API_URL=https://generativelanguage.googleapis.com

# Custom Models
ROBOT_CUSTOM_MODELS=gemini-2.5-flash,gemini-exp
```

### 進階設定範例

#### 使用自訂 API 端點

```env
# 使用 Azure OpenAI
ROBOT_CODEX_API_URL=https://your-resource.openai.azure.com
OPENAI_API_KEY=your-azure-key

# 使用自架 Claude API
ROBOT_CLAUDE_API_URL=https://your-claude-proxy.com/v1
ANTHROPIC_API_KEY=your-proxy-key
```

#### 不同的工作目錄

```env
# Robot 1 專注於前端專案
ROBOT_ID=robot-frontend
ROBOT_PROJECTS_ROOTS=C:\projects\frontend;C:\projects\web

# Robot 2 專注於後端專案
ROBOT_ID=robot-backend
ROBOT_PROJECTS_ROOTS=C:\projects\backend;C:\projects\api
```

#### 不同的 Google Calendar

```env
# Robot 1 使用個人日曆
ROBOT_ID=robot-personal
ROBOT_GOOGLE_CALENDAR_ENABLED=1
ROBOT_GOOGLE_CALENDAR_ID=primary

# Robot 2 使用工作日曆
ROBOT_ID=robot-work
ROBOT_GOOGLE_CALENDAR_ENABLED=1
ROBOT_GOOGLE_CALENDAR_ID=work@company.com
```

### 啟動腳本

#### `start_robot1.bat` (Windows)

```bat
@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run bootstrap_robot.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat

REM Load .env.robot1
for /f "usebackq tokens=*" %%a in (".env.robot1") do (
  set "%%a"
)

set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "TELEAPP_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined TELEAPP_HOT_RELOAD set "TELEAPP_HOT_RELOAD=0"
if not defined TELEAPP_WATCH_MODE set "TELEAPP_WATCH_MODE=app-file-only"
if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)

echo Starting Robot ID: %ROBOT_ID%
echo State file: .robot_state\robot_state_%ROBOT_ID%.json
echo.

"%TELEAPP_PYTHON%" -m teleapp "%TELEAPP_APP%" --python "%TELEAPP_PYTHON%"
```

#### `start_robot1.sh` (Linux/macOS)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi

source .venv/bin/activate

# Load .env.robot1
export $(grep -v '^#' .env.robot1 | xargs)

export HTTP_PROXY=""
export HTTPS_PROXY=""
export ALL_PROXY=""
export http_proxy=""
export https_proxy=""
export all_proxy=""
export TELEAPP_PYTHON="$(pwd)/.venv/bin/python"
export TELEAPP_HOT_RELOAD="${TELEAPP_HOT_RELOAD:-0}"
export TELEAPP_WATCH_MODE="${TELEAPP_WATCH_MODE:-app-file-only}"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

echo "Starting Robot ID: $ROBOT_ID"
echo "State file: .robot_state/robot_state_$ROBOT_ID.json"
echo ""

"$TELEAPP_PYTHON" -m teleapp "$TELEAPP_APP" --python "$TELEAPP_PYTHON"
```

### 快速生成腳本

使用以下命令快速生成多個 robot 的啟動腳本：

#### Windows

```bat
REM 複製並修改
copy start_robot.bat start_robot1.bat
copy start_robot.bat start_robot2.bat
copy start_robot.bat start_robot3.bat

REM 然後編輯每個檔案，在 call .venv\Scripts\activate.bat 後面加上：
REM for /f "usebackq tokens=*" %%a in (".env.robot1") do (set "%%a")
```

#### Linux/macOS

```bash
# 複製並修改
cp start_robot.sh start_robot1.sh
cp start_robot.sh start_robot2.sh
cp start_robot.sh start_robot3.sh

# 然後編輯每個檔案，在 source .venv/bin/activate 後面加上：
# export $(grep -v '^#' .env.robot1 | xargs)
```

## 啟動多個 Robot

### Windows

```bat
REM 在不同的 CMD 視窗中執行
start cmd /k start_robot1.bat
start cmd /k start_robot2.bat
start cmd /k start_robot3.bat
```

### Linux/macOS

```bash
# 在不同的終端或使用 tmux
./start_robot1.sh &
./start_robot2.sh &
./start_robot3.sh &

# 或使用 tmux
tmux new-session -d -s robot1 './start_robot1.sh'
tmux new-session -d -s robot2 './start_robot2.sh'
tmux new-session -d -s robot3 './start_robot3.sh'
```

## 監看 Robot 狀態

在任一 robot 的 Telegram 對話中輸入：

```
/robots
```

查看所有 robot 的狀態。

## 注意事項

1. **ROBOT_ID 必須唯一**: 每個 `.env` 檔案的 `ROBOT_ID` 必須不同
2. **TELEAPP_TOKEN 必須不同**: 每個 robot 需要不同的 Telegram bot token
3. **TELEAPP_ALLOWED_USER_ID 可以相同**: 如果你想用同一個 Telegram 帳號控制所有 robot
4. **State 檔案自動隔離**: 每個 robot 會自動使用 `robot_state_{ROBOT_ID}.json`
