# Robot 管理工具快速參考

## 啟動 Robot

### 單一 Robot
```bash
robotctl run default
robotctl run robot1
```

### 所有 Robot（背景執行）
```bash
robotctl start all
```

## 管理 Robot

### 查看狀態
```bash
robotctl status
```

### 停止特定 Robot
```bash
robotctl stop robot1
```

### 停止所有 Robot
```bash
robotctl stop all
```

### 重啟特定 Robot
```bash
robotctl restart robot1
```

### 查看日誌
```bash
robotctl logs robot1 -f
```

## 檔案說明

- `robotctl` - 統一啟動 / 監看 / 停止 / 重啟 / 看 log CLI
- `robotctl.py` - repo 內直接執行的 Python 入口
- `start_robot.*`、`manage_robots.*`、`start_all.*`、`stop_all.*` - 舊 wrapper，相容保留
- `.robot_state/*.log` - Robot 執行日誌
- `.robots/*.env` - 建議使用的 Robot 配置檔
- `.robots/default.env` - 預設單機配置

## 新增 Robot

1. 互動建立：
   ```bash
   robotctl add robot5
   ```
2. 或自行建立 `.robots/robot5.env`
3. 啟動：
   ```bash
   robotctl start robot5
   ```

詳細說明請參考 [MULTI_ROBOT.md](./MULTI_ROBOT.md)
