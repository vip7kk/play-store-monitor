# Google Play Store 上架监控 - Telegram 提醒机器人

实时监控 Google Play 应用上架状态，变化时通过 Telegram 自动通知。支持 **GitHub Actions 定时运行** 和 **本地持续运行** 两种模式。

## ✨ 核心特性

- **多国查询**：自动遍历 30 个国家/地区，任一地区上架即视为已上架
- **自动清理**：应用上架后若再次下架，自动从 GitHub JSON 中删除该包名，无需手动维护
- **状态对比**：通过 state.json 记录上次状态，仅在变化时推送通知（避免重复打扰）
- **双模式运行**：GitHub Actions 定时触发（推荐）或本地服务器持续运行
- **安全配置**：敏感信息通过 GitHub Actions Secrets 管理，不硬编码在代码中

## 📁 项目结构

```
├── play_monitor.py           # 核心监控脚本（支持环境变量 + config.json 双配置源）
├── .github/workflows/        # GitHub Actions 工作流配置
│   └── monitor.yml           # 每 10 分钟自动触发，支持手动运行
├── monitor_apps.json         # 监控列表（包名列表，存储在 GitHub 仓库）
├── config.example.json       # 本地运行配置模板（含说明）
├── config.json               # 本地运行实际配置（不入库，敏感信息）
├── start.py                  # 一键启动（自动创建 venv + 安装依赖）
├── requirements.txt          # Python 依赖
├── state.json                # 运行时状态（自动生成，勿手动编辑）
└── logs/                     # 运行日志（自动生成）
```

## 🚀 快速开始

### 方式一：GitHub Actions 定时运行（推荐）

无需服务器，完全免费运行在 GitHub 上。

#### 1. 创建 Telegram Bot

1. 在 Telegram 搜索 **@BotFather**，发送 `/newbot`
2. 按提示设置 Bot 名称，获得 **Bot Token**
3. 将 Bot 加入目标群组，获取 **Chat ID**（向 @userinfobot 发消息获取个人 ID；群组 ID 需通过 Bot API `getUpdates` 获取）
4. 确认 Bot 在群组中有发消息权限

#### 2. Fork 或创建仓库

将本项目推送到你的 GitHub 仓库，确保包含以下文件：
- `play_monitor.py`
- `.github/workflows/monitor.yml`
- `monitor_apps.json`
- `requirements.txt`

#### 3. 编辑监控列表

修改仓库中的 `monitor_apps.json`：

```json
{
  "apps": [
    {
      "package_name": "com.example.myapp",
      "note": "2026-07-20 提交审核"
    },
    {
      "package_name": "com.another.app",
      "note": "待上架"
    }
  ]
}
```

> `app_name` 字段可选，脚本会自动从 Play Store 获取实际应用名称。

#### 4. 配置 GitHub Actions Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加以下 3 个 Secrets：

| Secret 名称 | 值 | 说明 |
|---|---|---|
| `TG_BOT_TOKEN` | `123456:ABC-DEF...` | Telegram Bot Token |
| `TG_CHAT_ID` | `-5541367556` 或 `987654321` | 目标 Chat ID（群组为负数） |
| `GH_CONFIG_URL` | `https://raw.githubusercontent.com/用户名/仓库名/main/monitor_apps.json` | 监控列表 JSON 的 raw URL |

> `GITHUB_TOKEN` 由 Actions 自动提供，无需手动配置。

#### 5. 启用 Actions 并运行

1. 进入仓库 **Actions** 页面，启用 GitHub Actions
2. 点击 **Play Store Monitor** 工作流
3. 点击 **Run workflow** 可手动触发

首次运行时，选择 `first_run` 为 `true`，会通知所有应用的当前状态。之后每 10 分钟自动检查一次，仅在状态变化时推送通知。

### 方式二：本地持续运行

适合有服务器或想本地调试的场景。

#### 1. 创建 Telegram Bot（同上）

#### 2. 编辑配置

复制模板并填写：

```bash
cp config.example.json config.json
```

修改 `config.json`：

```json
{
  "telegram": {
    "bot_token": "123456:ABC-DEF...",
    "chat_id": "-5541367556"
  },
  "github": {
    "config_url": "https://raw.githubusercontent.com/.../monitor_apps.json",
    "token": "",
    "refresh_interval_minutes": 30
  },
  "monitor": {
    "check_interval_minutes": 10,
    "countries": ["us", "cn", "jp", "kr", "de", "fr", "gb", "in", "br", "ru", "au", "ca", "tw", "hk", "sg"]
  }
}
```

> `github.token` 用于自动删除下架包名功能，填入 GitHub Personal Access Token（需 `repo` 权限）。如不填写，下架时仅发送通知，不自动清理 JSON。

#### 3. 启动

```bash
python start.py
```

脚本会自动创建虚拟环境、安装依赖、启动监控。

或手动启动持续模式：

```bash
# 持续运行（每 10 分钟检查一次）
python play_monitor.py --daemon

# 首次运行（通知所有应用当前状态）
python play_monitor.py --daemon --first-run
```

## 📬 通知效果

| 场景 | 通知内容 |
|------|----------|
| **首次检查** | 每个应用的当前上架状态（需 `--first-run` 或 Actions `first_run=true`） |
| **新上架** 🎉 | 应用详情（名称、版本、评分、安装量、发现区域） |
| **新增监控** 📋 | 新加入 JSON 的应用首次检查结果 |
| **疑似下架** 🚨 | 下架通知 + **自动从 JSON 删除包名** |
| **状态不变** | 静默，只记录日志 |

Telegram 上架消息示例：

```
🎉 应用已上架（us 区）！

应用名称: My App
包名: com.example.myapp
版本: 1.0.0
评分: 4.5
安装量: 10,000+
备注: 2026-07-20 提交审核

查看应用 → https://play.google.com/store/apps/details?id=com.example.myapp
```

下架消息示例：

```
🚨 应用已下架，自动移除监控

包名: com.example.myapp
预期名称: My App
备注: 该包名已从监控列表 JSON 中自动删除，后续不再检查
```

## 🌍 多国查询

默认查询以下 30 个国家/地区，任一国家发现应用即视为已上架：

```
us, cn, jp, kr, de, fr, gb, in, br, ru,
au, ca, tw, hk, sg, th, vn, id, my, ph,
mx, es, it, nl, se, pl, tr, sa, ae, za
```

可通过环境变量 `COUNTRIES_TO_CHECK` 或 `config.json` 自定义国家列表：

```bash
# Actions 中设置环境变量（Settings → Secrets → Actions → Variables）
COUNTRIES_TO_CHECK=us,cn,jp,kr

# 本地 config.json
"countries": ["us", "cn", "jp", "kr"]
```

## ⚙️ 参数说明

| 参数 | 环境变量 | config.json 键 | 说明 | 默认值 |
|------|----------|----------------|------|--------|
| Bot Token | `TG_BOT_TOKEN` | `telegram.bot_token` | Telegram Bot Token | - |
| Chat ID | `TG_CHAT_ID` | `telegram.chat_id` | 目标 Chat ID | - |
| GitHub 配置 URL | `GH_CONFIG_URL` | `github.config_url` | monitor_apps.json 的 raw URL | - |
| GitHub Token | `GH_TOKEN` | `github.token` | 用于自动删除下架包名 | - |
| 查询国家 | `COUNTRIES_TO_CHECK` | `monitor.countries` | 查询国家列表（逗号分隔） | 30 国全量 |
| 检查间隔 | `MONITOR_INTERVAL` | `monitor.check_interval_minutes` | 本地模式检查频率（分钟） | 10 |
| 仓库 | `GITHUB_REPOSITORY` | `github.repository` | Actions 自动提供 | - |

> **配置优先级**：环境变量 > config.json > 默认值

## 🔧 运行模式对比

| 特性 | GitHub Actions | 本地持续运行 |
|------|---------------|-------------|
| 成本 | 免费（GitHub 提供） | 需服务器 |
| 运行方式 | 每 10 分钟触发单次 | 持续循环 |
| 敏感配置 | Secrets 加密存储 | config.json（不入库） |
| 自动删除下架包名 | ✅ 使用 GITHUB_TOKEN | ✅ 需配置 GitHub Token |
| 手动触发 | ✅ Run workflow 按钮 | ❌ 需重启进程 |
| 首次通知 | ✅ first_run 选项 | ✅ --first-run 参数 |

## 🔐 安全说明

- **GitHub Actions**：Bot Token、Chat ID 等敏感信息通过 Secrets 加密存储，代码中不包含任何密钥
- **本地运行**：`config.json` 不应提交到仓库（已在 .gitignore 中排除），使用 `config.example.json` 作为模板
- **GitHub Token**：自动删除下架包名需要 Token 权限（Actions 使用自动生成的 GITHUB_TOKEN，本地运行需手动配置 Classic PAT，需 `repo` + `workflow` 权限）

## 💡 常见问题

**Q: 如何获取群组 Chat ID？**

将 Bot 加入群组后，向 Bot 发送一条消息，然后访问：
```
https://api.telegram.org/bot{TOKEN}/getUpdates
```
在返回的 JSON 中找到 `chat.id`（群组 ID 为负数）。

**Q: Actions 工作流没看到 Run workflow 按钮？**

新仓库需要先进入 Actions 页面启用 GitHub Actions，然后才能看到手动运行按钮。

**Q: 应用只在某个国家上架，其他国家搜不到？**

本项目支持多国查询，默认遍历 30 个国家，任一国家上架即视为已上架。通知中会标注发现的国家区域。

**Q: 下架的包名会一直占用监控资源吗？**

不会。应用上架后再次下架时，脚本会自动从 GitHub 的 monitor_apps.json 中删除该包名，后续不再检查。

**Q: 如何添加新的监控应用？**

直接编辑 GitHub 仓库中的 `monitor_apps.json`，添加新的包名条目。下一轮检查会自动发现并监控新应用。
