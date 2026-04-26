# Robot 管理工具快速參考

## 啟動 Robot

### 單一 Robot
```bat
start_robot.bat robot1
```

### 所有 Robot（背景執行）
```bat
start_all.bat
```

## 管理 Robot

### 查看狀態
```bat
manage_robots.bat status
```

### 停止特定 Robot
```bat
manage_robots.bat stop robot1
```

### 停止所有 Robot
```bat
stop_all.bat
```

### 查看日誌
```bat
manage_robots.bat logs robot1
```

## 檔案說明

- `start_robot.bat` - 統一啟動腳本（支援單一/全部模式）
- `start_all.bat` - 快捷：啟動所有 robot
- `stop_all.bat` - 快捷：停止所有 robot
- `manage_robots.bat` - Robot 管理工具
- `.robot_state/*.log` - Robot 執行日誌
- `.env.robot*` - Robot 配置檔

## 新增 Robot

1. 複製配置檔範例：
   ```bat
   copy .env.robot1.example .env.robot5
   ```

2. 編輯 `.env.robot5`，設定：
   - `ROBOT_ID=robot-5`
   - `TELEAPP_TOKEN=你的_bot_token`
   - 其他設定

3. 啟動：
   ```bat
   start_robot.bat robot5
   ```

詳細說明請參考 [MULTI_ROBOT.md](./MULTI_ROBOT.md)
