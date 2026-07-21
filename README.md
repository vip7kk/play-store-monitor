# Google Play Store 上架监控 - Telegram 提醒机器人

实时监控 Google Play 应用上架状态，变化时通过 Telegram 自动通知。

## 📁 项目结构

```
├── config.json              # 主配置（Bot Token、GitHub URL、轮询间隔）
├── monitor_apps_example.json # 监控列表示例（实际使用 GitHub 仓库中的 JSON）
├── play_monitor.py           # 核心监控脚本
├── start.py                  # 一键启动（自动创建 venv + 安装依赖）
├── requirements.txt          # Python 依赖
├── state.json                # 运行时状态（自动生成，勿手动编辑）
└── logs/                     # 运行日志（自动生成）
```

## 🚀 快速开始

### 1. 创建 Telegram Bot

1. 在 Telegram 搜索 **@BotFather**，发送 `/newbot`
2. 按提示设置 Bot 名称，获得 **Bot Token**
3. 获取你的 **Chat ID**：向 @userinfobot 发消息即可获得

### 2. 准备 GitHub 监控列表

在你的 GitHub 仓库中创建 JSON 文件（如 `monitor_apps.json`），格式如下：

```json
{
  "apps": [
    {
      "package_name": "com.example.myapp",
      "app_name": "我的应用",
      "note": "2026-07-20 提交审核"
    }
  ]
}
```

获取 raw URL：`https://raw.githubusercontent.com/用户名/仓库名/main/monitor_apps.json`

### 3. 编辑配置

修改 `config.json`：

```json
{
  "telegram": {
    "bot_token": "123456:ABC-DEF...",    ← 你的 Bot Token
    "chat_id": "987654321"               ← 你的 Chat ID
  },
  "github": {
    "config_url": "https://raw.githubusercontent.com/.../monitor_apps.json",
    "refresh_interval_minutes": 30       ← GitHub 配置刷新间隔
  },
  "monitor": {
    "check_interval_minutes": 10,        ← Play Store 检查间隔（分钟）
    "language": "en",
    "country": "us"
  }
}
```

### 4. 启动

```bash
python start.py
```

脚本会自动创建虚拟环境、安装依赖、启动监控。

## 📬 通知效果

- **首次检查**：通知每个应用的当前上架状态
- **新上架** 🎉：应用从不可搜到变为可搜到时，立即推送详情
- **疑似下架** 🚨：已上架应用突然不可搜到时，告警通知
- **状态不变**：静默，只记录日志

Telegram 消息示例：

```
🎉 应用已上架！

应用名称: My App
包名: com.example.myapp
版本: 1.0.0
评分: 4.5
安装量: 10,000+
备注: 2026-07-20 提交审核

查看应用 → https://play.google.com/store/apps/details?id=com.example.myapp
```

## ⚙️ 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `check_interval_minutes` | Play Store 检查频率 | 10 |
| `refresh_interval_minutes` | GitHub 配置刷新频率 | 30 |
| `language` | Play Store 查询语言 | en |
| `country` | Play Store 查询国家 | us |

## 🔧 部署建议

- **长期运行**：部署在服务器上，用 `systemd` 或 `supervisor` 保持进程
- **定时模式**：也可改用 cron 定时执行单次检查后退出
- **多 Chat ID**：如需通知群组，`chat_id` 填群组 ID（需 Bot 已加入群组）
