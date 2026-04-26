# Security Patch for Robot Project

## 概述

本修補程式解決了 robot 專案中發現的嚴重安全漏洞，包括命令注入和路徑遍歷攻擊。

## 修復的漏洞

### 1. 命令注入漏洞 (Critical)
- **位置**: `robot/routing.py` - `_run_sendmail()` 函數
- **問題**: 未驗證用戶輸入的命令參數
- **修復**: 新增 `validate_command_args()` 驗證所有參數

### 2. 路徑遍歷漏洞 (Critical)
- **位置**: `robot/routing.py` - `_resolve_input_path()` 函數
- **問題**: 未限制檔案路徑在允許的目錄內
- **修復**: 新增 `validate_path_traversal()` 驗證路徑安全性

### 3. 檔案大小限制 (High)
- **問題**: 未限制上傳檔案大小，可能導致 DoS
- **修復**: 新增 `sanitize_file_size()` 檢查檔案大小

### 4. 錯誤訊息洩漏 (Medium)
- **問題**: 錯誤訊息可能包含敏感路徑和系統資訊
- **修復**: 新增 `sanitize_error_message()` 過濾敏感資訊

## 安裝步驟

### 1. 新增安全模組

已建立 `robot/security.py` 模組，包含以下功能：

```python
from robot.security import (
    validate_path_traversal,
    validate_command_args,
    sanitize_file_size,
    sanitize_error_message,
    SecurityError,
)
```

### 2. 修改 routing.py

需要修改以下函數：

#### 修改 `_resolve_input_path()` (line 618-631)

**原始程式碼**:
```python
def _resolve_input_path(raw_path: str, *, project_path: str, settings: Settings) -> Path:
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if candidate.is_absolute():
        return candidate
    search_roots: list[Path] = []
    if project_path.strip():
        search_roots.append(Path(project_path).expanduser())
    search_roots.append(settings.project_root)
    search_roots.append(_sendmail_root_path())
    for root in search_roots:
        resolved = root / candidate
        if resolved.exists():
            return resolved
    return settings.project_root / candidate
```

**修復後**:
```python
def _resolve_input_path(raw_path: str, *, project_path: str, settings: Settings) -> Path:
    from robot.security import validate_path_traversal, SecurityError
    
    candidate = Path(str(raw_path or "").strip()).expanduser()
    
    # Build allowed roots
    allowed_roots: list[Path] = []
    if project_path.strip():
        allowed_roots.append(Path(project_path).expanduser())
    allowed_roots.append(settings.project_root)
    allowed_roots.append(_sendmail_root_path())
    
    # If absolute path, validate it's within allowed roots
    if candidate.is_absolute():
        try:
            return validate_path_traversal(candidate, allowed_roots, must_exist=False)
        except SecurityError as exc:
            raise ValueError(f"Path validation failed: {exc}") from exc
    
    # For relative paths, try each root
    for root in allowed_roots:
        resolved = root / candidate
        try:
            validated = validate_path_traversal(resolved, allowed_roots, must_exist=False)
            if validated.exists():
                return validated
        except SecurityError:
            continue
    
    # Default to project root, but still validate
    default_path = settings.project_root / candidate
    try:
        return validate_path_traversal(default_path, allowed_roots, must_exist=False)
    except SecurityError as exc:
        raise ValueError(f"Path validation failed: {exc}") from exc
```

#### 修改 `_run_sendmail()` (line 708-749)

**原始程式碼**:
```python
def _run_sendmail(
    settings: Settings,
    *,
    args: list[str],
) -> tuple[bool, str]:
    sendmail_root = _sendmail_root_path()
    sendmail_script = sendmail_root / "sendmail.py"
    if not sendmail_root.exists():
        return False, f"sendmail root not found: {sendmail_root}"
    if not sendmail_script.exists():
        return False, f"sendmail script not found: {sendmail_script}"

    command = [sys.executable, str(sendmail_script), *args]
    env = _load_sendmail_env(sendmail_root)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(settings.project_root),
            env=env,
        )
    except (FileNotFoundError, OSError) as exc:
        return False, f"sendmail execution failed: {exc}"
    except subprocess.TimeoutExpired:
        return False, "sendmail execution timed out after 120 seconds."

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    lines = [
        f"ok: {completed.returncode == 0}",
        f"return_code: {completed.returncode}",
        f"command: {' '.join(command)}",
    ]
    if stdout_text:
        lines.append("stdout:")
        lines.append(stdout_text)
    if stderr_text:
        lines.append("stderr:")
        lines.append(stderr_text)
    return completed.returncode == 0, "\n".join(lines)
```

**修復後**:
```python
def _run_sendmail(
    settings: Settings,
    *,
    args: list[str],
) -> tuple[bool, str]:
    from robot.security import validate_command_args, sanitize_error_message, SecurityError
    
    sendmail_root = _sendmail_root_path()
    sendmail_script = sendmail_root / "sendmail.py"
    if not sendmail_root.exists():
        return False, f"sendmail root not found: {sendmail_root}"
    if not sendmail_script.exists():
        return False, f"sendmail script not found: {sendmail_script}"

    # Validate all arguments for security
    try:
        validated_args = validate_command_args(args)
    except SecurityError as exc:
        error_msg = sanitize_error_message(str(exc), settings.project_root)
        return False, f"sendmail argument validation failed: {error_msg}"

    command = [sys.executable, str(sendmail_script), *validated_args]
    env = _load_sendmail_env(sendmail_root)
    
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(settings.project_root),
            env=env,
        )
    except (FileNotFoundError, OSError) as exc:
        error_msg = sanitize_error_message(str(exc), settings.project_root)
        return False, f"sendmail execution failed: {error_msg}"
    except subprocess.TimeoutExpired:
        return False, "sendmail execution timed out after 120 seconds."

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    
    # Sanitize output to avoid leaking sensitive info
    stdout_text = sanitize_error_message(stdout_text, settings.project_root)
    stderr_text = sanitize_error_message(stderr_text, settings.project_root)
    
    lines = [
        f"ok: {completed.returncode == 0}",
        f"return_code: {completed.returncode}",
        # Don't include full command in output (may contain sensitive data)
        "command: sendmail.py [args redacted]",
    ]
    if stdout_text:
        lines.append("stdout:")
        lines.append(stdout_text)
    if stderr_text:
        lines.append("stderr:")
        lines.append(stderr_text)
    return completed.returncode == 0, "\n".join(lines)
```

#### 修改文件匯入功能 (line 1737-1758)

在 `handle_request()` 函數中，文件處理部分需要加入大小檢查：

**在 line 1745 之後加入**:
```python
from robot.security import sanitize_file_size, SecurityError

# ... existing code ...

if ctx.document is not None and not command:
    local_path = str(ctx.document.local_path or "").strip()
    if not local_path:
        return "文件已收到，但目前沒有可讀取的本機路徑。請重新上傳後再試。"
    
    # Add file size check
    try:
        sanitize_file_size(Path(local_path), max_size_mb=50)
    except SecurityError as exc:
        return f"文件大小驗證失敗: {exc}"
    
    # ... rest of existing code ...
```

### 3. 修改 config.py

#### 修改 load_dotenv 設定 (line 11)

**原始程式碼**:
```python
load_dotenv(override=True, encoding="utf-8-sig")
```

**修復後**:
```python
import logging

# Don't override existing environment variables (security best practice)
load_dotenv(override=False, encoding="utf-8-sig")

# Log warning if .env file would override existing vars
if Path(".env").exists():
    from dotenv import dotenv_values
    env_vars = dotenv_values(".env")
    for key in env_vars:
        if key in os.environ:
            logging.warning(f"Environment variable {key} already set, not overriding from .env")
```

## 測試

### 測試路徑遍歷防護

```python
from robot.security import validate_path_traversal, SecurityError
from pathlib import Path

# 應該拋出 SecurityError
try:
    validate_path_traversal(
        Path("../../etc/passwd"),
        [Path("/home/user/project")]
    )
except SecurityError:
    print("✓ Path traversal blocked")

# 應該成功
try:
    validate_path_traversal(
        Path("/home/user/project/file.txt"),
        [Path("/home/user/project")]
    )
    print("✓ Valid path accepted")
except SecurityError:
    print("✗ Valid path rejected")
```

### 測試命令注入防護

```python
from robot.security import validate_command_args, SecurityError

# 應該拋出 SecurityError
dangerous_args = [
    "-t", "user@example.com; rm -rf /",
    "-s", "test",
]

try:
    validate_command_args(dangerous_args)
except SecurityError:
    print("✓ Command injection blocked")

# 應該成功
safe_args = ["-t", "user@example.com", "-s", "test"]
try:
    validate_command_args(safe_args)
    print("✓ Safe arguments accepted")
except SecurityError:
    print("✗ Safe arguments rejected")
```

## 部署檢查清單

- [ ] 備份現有的 `robot/routing.py`
- [ ] 部署 `robot/security.py`
- [ ] 更新 `robot/routing.py` 中的三個函數
- [ ] 更新 `robot/config.py` 中的 load_dotenv 設定
- [ ] 執行測試確認功能正常
- [ ] 檢查日誌確認沒有安全警告
- [ ] 更新文檔說明新的安全限制

## 額外建議

### 1. 環境變數安全
在 `.env.example` 中加入註解：
```bash
# SECURITY WARNING: Never commit .env file to version control
# SECURITY WARNING: Use strong, unique tokens for production
TELEAPP_TOKEN=<your telegram bot token>
```

### 2. 日誌記錄
建議在 `robot/` 目錄下建立 `logging_config.py`：
```python
import logging

def setup_security_logging():
    logger = logging.getLogger("robot.security")
    logger.setLevel(logging.WARNING)
    handler = logging.FileHandler(".robot_state/security.log")
    handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    logger.addHandler(handler)
    return logger
```

### 3. 速率限制
考慮加入速率限制防止 DoS：
```python
from collections import defaultdict
from time import time

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
    
    def is_allowed(self, user_id: int) -> bool:
        now = time()
        # Clean old requests
        self.requests[user_id] = [
            req_time for req_time in self.requests[user_id]
            if now - req_time < self.window_seconds
        ]
        
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True
```

## 回滾計畫

如果修補後出現問題：

1. 恢復備份的 `robot/routing.py`
2. 刪除 `robot/security.py`
3. 恢復 `robot/config.py` 中的 `load_dotenv(override=True)`
4. 重啟服務

## 聯絡資訊

如有問題或發現新的安全漏洞，請立即報告。

---

**修補日期**: 2026-04-25  
**版本**: 0.1.1-security-patch-1  
**嚴重程度**: Critical
