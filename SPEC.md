# Robot Agent 安全許可權系統 — 實作規格書

## 1. 目標

建立三層權限模式，讓 AI agent 在不同模式下只能操作允許的檔案區域，防止誤改系統關鍵目錄。

---

## 2. 三層權限模式

| 模式 | 可寫範圍 | 不可寫範圍 | 觸發方式 |
|------|---------|-----------|---------|
| **user** | `~/projects` | `~/robot`、`~/teleapp` | 預設模式 |
| **developer** | `~/projects`、`~/robot` | `~/teleapp` | `/mode developer` |
| **superuser** | 無限制 | 無 | `/mode superuser` |

> 平台：WSL Linux、native Linux、macOS（排除 PowerShell/Windows）

---

## 3. 三層保護架構

外部設定檔 `~/.config/robot/permissions.json` 透過三層機制防止篡改：

### Layer 1 — 隔離位置
放在 `$HOME/.config/robot/`（非專案目錄），無法被 agent 常规扫描发现。

### Layer 2 — OS 寫入保護
- Linux/macOS：`chmod 444`（唯讀）
- Linux 額外：`chattr +i`（immutable flag，root 仍可移除）
- macOS 額外：`chflags schg`（system immutable）

### Layer 3 — HMAC-SHA256 簽章驗證
- 簽章範圍：`rules` 欄位的 JSON（不含 `signature`）
- 金鑰：系統環境變數 `ROBOT_PERMISSION_KEY`
- 載入時比對簽章，不符則拒絕讀取並記錄警告

---

## 4. 設定檔格式

**`~/.config/robot/permissions.json`**

```json
{
  "version": "1.0",
  "rules": {
    "user": {
      "whitelist": ["${HOME}/projects"],
      "blacklist": ["${HOME}/robot", "${HOME}/teleapp"]
    },
    "developer": {
      "whitelist": ["${HOME}/projects", "${HOME}/robot"],
      "blacklist": ["${HOME}/teleapp"]
    },
    "superuser": {
      "whitelist": ["*"],
      "blacklist": []
    }
  },
  "signature": "<hmac_sha256_hex>"
}
```

**${HOME}** 在載入時替換為實際路徑。

---

## 5. 簽章工具

**`scripts/sign_permissions.py`**（放在專案外，獨立執行）

```python
import hmac, hashlib, json, sys, os
from pathlib import Path

key = os.environ["ROBOT_PERMISSION_KEY"]
path = Path(sys.argv[1])
data = json.loads(path.read_text())
payload = json.dumps(data["rules"], sort_keys=True, ensure_ascii=False)
sig = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
data["signature"] = sig
path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"Signed: {path}")
```

用法：`ROBOT_PERMISSION_KEY=your_key python scripts/sign_permissions.py ~/.config/robot/permissions.json`

---

## 6. 核心模組

**`robot/security.py`**

```python
import os, hmac, hashlib, json
from pathlib import Path

PROJECTS_ROOT = Path("~/projects").expanduser()
ROBOT_ROOT    = Path("~/robot").expanduser()
TELEAPP       = Path("~/teleapp").expanduser()

def check_write_allowed(abs_path: Path, mode: str) -> bool:
    if mode == "superuser":
        return True
    resolved = abs_path.resolve()
    # 黑名單先擋
    for blocked in [TELEAPP]:
        if str(resolved).startswith(str(blocked.resolve())):
            return False
    if mode == "developer":
        return str(resolved).startswith(str(PROJECTS_ROOT.resolve())) or \
               str(resolved).startswith(str(ROBOT_ROOT.resolve()))
    # user mode
    return str(resolved).startswith(str(PROJECTS_ROOT.resolve())) and \
           not str(resolved).startswith(str(ROBOT_ROOT.resolve()))
```

---

## 7. 實作步驟

| 順序 | 項目 | 優先順序 | 預計 effort |
|------|------|---------|------------|
| 1 | `robot/security.py` 核心模組 | 高 | 1 小時 |
| 2 | `scripts/sign_permissions.py` 簽章工具 | 高 | 30 分鐘 |
| 3 | 建立 `~/.config/robot/permissions.json` 並設定 OS 保護 | 高 | 30 分鐘 |
| 4 | 鉤入 subagent tool call 攔截層 | 高 | 2 小時 |
| 5 | 單元測試（路徑正規化 + HMAC 驗證） | 中 | 1 小時 |
| 6 | 更新 AGENTS.md 文件 | 中 | 30 分鐘 |

---

## 8. 待辦追蹤

- [ ] `robot/security.py` 實作
- [ ] `scripts/sign_permissions.py` 建立
- [ ] `~/.config/robot/permissions.json` 建立 + OS 保護
- [ ] tool call 攔截層整合
- [ ] 單元測試
- [ ] 文件更新