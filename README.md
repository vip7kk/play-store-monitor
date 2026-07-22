# Google Play Store 上架监控 - Telegram 提醒机器人

实时监控 Google Play 应用上架状态，变化时通过 Telegram 自动通知。支持 **GitHub Actions 定时运行** 和 **本地持续运行** 两种模式。

## ✨ 核心特性

- **按应用配置上架国家**：每个应用必须指定上架目标国家，只查询配置的国家，无默认列表兜底
- **按提交类型配置查询频率**：首次提交（version=1）24h 内不查，之后工作日 4h/周六 6h；更新（version≥2）每 3h；周日一律不查。通过 state.json 比对 version 自动识别首次/更新
- **包名强制加密**：推送明文包名到 GitHub 后自动加密，仓库中永远只存储加密后的包名，不允许明文，无需手动加密
- **自动清理**：应用上架后若再次下架，自动从 GitHub JSON 中删除该包名，无需手动维护
- **状态对比**：通过 state.json 记录上次状态，仅在变化时推送通知（避免重复打扰）
- **双模式运行**：GitHub Actions 定时触发（推荐）或本地服务器持续运行
- **安全配置**：敏感信息通过 GitHub Actions Secrets 管理，不硬编码在代码中

## 📁 项目结构

```
├── play_monitor.py           # 核心监控脚本（支持环境变量 + config.json 双配置源）
├── encrypt_packages.py       # 自动加密脚本（push 明文包名后自动触发加密）
├── .github/workflows/        # GitHub Actions 工作流配置
│   ├── monitor.yml           # 每小时自动触发（周一至周六），支持手动运行
│   └── encrypt.yml           # push monitor_apps.json 时自动加密明文包名
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
- `encrypt_packages.py`
- `.github/workflows/monitor.yml`
- `.github/workflows/encrypt.yml`
- `monitor_apps.json`
- `requirements.txt`

#### 3. 编辑监控列表

修改仓库中的 `monitor_apps.json`。**直接写明文包名，push 到 GitHub 后自动加密**，仓库中不会保留明文：

```json
{
  "apps": [
    {
      "package_name": "com.example.myapp",
      "note": "2026-07-20 提交审核",
      "countries": ["mx"],
      "version": 1
    }
  ]
}
```

> 包名强制加密，不允许明文。push 到 GitHub 后 `encrypt.yml` workflow 会自动用 Fernet 加密包名并推回仓库，明文包名会被替换为加密字符串。不需要 `"encrypted"` 字段，通过 Fernet token 格式自动区分加密/明文。

加密后的 JSON 示例（自动加密的结果）：

```json
{
  "apps": [
    {
      "package_name": "gAAAAABqXxv...（加密字符串）",
      "note": "待上架监控",
      "countries": ["mx"],
      "version": 1
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `package_name` | ✅ | 应用包名（**必填**，加密或明文均可，缺少时该条目会被跳过） |
| `countries` | ✅ | 上架目标国家列表，只查询这些国家。**必填，未配置时跳过检查** |
| `version` | ✅ | 提交类型版本号。**1 = 首次提交上架**，**≥2 = 更新**，决定查询频率。首次/更新通过 state.json 比对自动识别 |
| `encrypted` | ❌ | 已废弃，不再使用（包名格式自动区分加密/明文） |
| `note` | ❌ | 备注，会显示在通知消息中 |
| `app_name` | ❌ | 应用名称（脚本会自动从 Play Store 获取，可不填） |

> 推送明文包名后，`encrypt.yml` workflow 会自动加密，仓库中只保留加密格式。详见 [🔒 包名强制加密](#-包名强制加密) 章节。

#### 4. 配置 GitHub Actions Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加以下 4 个 Secrets：

| Secret 名称 | 值 | 说明 |
|---|---|---|
| `TG_BOT_TOKEN` | `123456:ABC-DEF...` | Telegram Bot Token |
| `TG_CHAT_ID` | `-5541367556` 或 `987654321` | 目标 Chat ID（群组为负数） |
| `GH_CONFIG_URL` | `https://raw.githubusercontent.com/用户名/仓库名/main/monitor_apps.json` | 监控列表 JSON 的 raw URL |
| `ENCRYPT_KEY` | `tnDtrmbSFYEB3w5e_--...` | Fernet 加密密钥（包名加密时必填） |

> `GITHUB_TOKEN` 由 Actions 自动提供，无需手动配置。

#### 5. 启用 Actions 并运行

1. 进入仓库 **Actions** 页面，启用 GitHub Actions
2. 点击 **Play Store Monitor** 工作流
3. 点击 **Run workflow** 可手动触发

首次运行时，选择 `first_run` 为 `true`，会通知所有应用的当前状态。之后每小时自动检查一次（周一至周六），脚本内部根据各应用的 `version` 字段决定实际查询频率，周日不运行。

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
    "encrypt_key": "YOUR_FERNET_KEY"
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
| **新上架** 🎉 | 应用详情（名称、版本、评分、安装量、发现区域、目标国家） |
| **新增监控** 📋 | 新加入 JSON 的应用首次检查结果 |
| **疑似下架** 🚨 | 下架通知 + **自动从 JSON 删除包名** |
| **状态不变** | 静默，只记录日志 |

Telegram 上架消息示例：

```
🎉 应用已上架（jp 区）！

应用名称: My App
包名: com.example.myapp
版本: 1.0.0
评分: 4.5
安装量: 10,000+
备注: 2026-07-20 提交审核
目标国家: jp, kr, de, fr

查看应用 → https://play.google.com/store/apps/details?id=com.example.myapp
```

下架消息示例：

```
🚨 应用已下架，自动移除监控

包名: com.example.myapp
预期名称: My App
备注: 该包名已从监控列表 JSON 中自动删除，后续不再检查
```

## 🌍 按应用配置上架国家

每个应用必须在 `monitor_apps.json` 中通过 `countries` 字段指定上架目标国家，脚本只查询这些国家。**未配置 countries 的应用会被跳过并记录警告日志。**

```json
{
  "package_name": "com.example.myapp",
  "countries": ["mx"]
}
```

> `countries` 是必填字段，没有默认列表兜底。请为每个应用明确指定上架目标国家。

## ⏱️ 查询频率调度

每个应用通过 `version` 字段区分提交类型，不同类型使用不同的查询频率。首次/更新通过 `state.json` 比对 `version` 自动识别：

| 提交类型 | version | 查询频率 | 周六 | 周日 |
|----------|---------|----------|------|------|
| **首次提交上架** | 1 | 首次发现后 24h 内不查，之后每 4h | 每 6h | 不查 |
| **更新** | ≥2 | 每 3h | 每 3h | 不查 |

> 缺少 `version` 字段时默认按更新模式（每 3h）处理。首次/更新识别不再需要 `submit_time`，脚本通过 `state.json` 中的 `first_seen_time` 和 `version` 比对自动判断。

### 首次提交上架示例

```json
{
  "package_name": "com.example.myapp",
  "countries": ["mx"],
  "version": 1
}
```

- 首次出现在 `monitor_apps.json` 中的应用，脚本自动在 `state.json` 中记录 `first_seen_time`（当前时间）
- 24 小时后才开始查询，工作日每 4 小时、周六每 6 小时

### 更新示例

```json
{
  "package_name": "com.example.myapp",
  "countries": ["mx"],
  "version": 2,
  "note": "1.1 版本更新"
}
```

- 将 `version` 从 `1` 改为 `2`（或更大值），脚本比对 `state.json` 中记录的旧 version 后识别为更新
- 更新模式无需 `submit_time`，直接按 3 小时间隔查询
- 周日不查询

### 工作原理

GitHub Actions 每小时触发一次脚本（周一至周六），脚本内部根据每个应用的 `version` 和上次检查时间判断是否应该查询：
- 未到查询间隔 → 跳过并保留上次状态
- 周日 → 全部跳过
- 首次提交 24h 内 → 跳过（`first_seen_time` 在首次出现时自动记录到 `state.json`）
- version 变化 → 自动识别为更新，切换查询频率

## ⚙️ 参数说明

| 参数 | 环境变量 | config.json 键 | 说明 | 默认值 |
|------|----------|----------------|------|--------|
| Bot Token | `TG_BOT_TOKEN` | `telegram.bot_token` | Telegram Bot Token | - |
| Chat ID | `TG_CHAT_ID` | `telegram.chat_id` | 目标 Chat ID | - |
| GitHub 配置 URL | `GH_CONFIG_URL` | `github.config_url` | monitor_apps.json 的 raw URL | - |
| GitHub Token | `GH_TOKEN` | `github.token` | 用于自动删除下架包名 | - |
| `加密密钥` | `ENCRYPT_KEY` | `monitor.encrypt_key` | Fernet 加密密钥（必填，包名强制加密） | - |
| 检查间隔 | `MONITOR_INTERVAL` | `monitor.check_interval_minutes` | 本地模式检查频率（分钟） | 10 |
| 仓库 | `GITHUB_REPOSITORY` | `github.repository` | Actions 自动提供 | - |

> **查询国家**由各应用在 `monitor_apps.json` 的 `countries` 字段单独配置，无全局默认列表。

## 🔧 运行模式对比

| 特性 | GitHub Actions | 本地持续运行 |
|------|---------------|-------------|
| 成本 | 免费（GitHub 提供） | 需服务器 |
| 运行方式 | 每小时触发（周一至周六） | 持续循环 |
| 敏感配置 | Secrets 加密存储 | config.json（不入库） |
| 自动加密包名 | ✅ push 后自动加密 | ❌ 需手动加密 |
| 自动删除下架包名 | ✅ 使用 GITHUB_TOKEN | ✅ 需配置 GitHub Token |
| 手动触发 | ✅ Run workflow 按钮 | ❌ 需重启进程 |
| 首次通知 | ✅ first_run 选项 | ✅ --first-run 参数 |

## 🔐 安全说明

- **包名强制加密**：推送明文包名到 GitHub 后，`encrypt.yml` workflow 自动用 Fernet 加密并推回仓库。包名强制加密，不允许明文。通过 Fernet token 格式（`gAAAAA` 前缀）自动区分加密/明文，不再使用 `encrypted` 字段
- **GitHub Actions**：Bot Token、Chat ID、加密密钥等敏感信息通过 Secrets 加密存储，代码中不包含任何密钥
- **本地运行**：`config.json` 不应提交到仓库（已在 .gitignore 中排除），使用 `config.example.json` 作为模板
- **GitHub Token**：自动删除下架包名需要 Token 权限（Actions 使用自动生成的 GITHUB_TOKEN，本地运行需手动配置 Classic PAT，需 `repo` + `workflow` 权限）

## 🔒 包名强制加密

包名强制加密，不允许明文。推送明文包名到 GitHub 仓库后，`encrypt.yml` workflow 会自动加密并推回，仓库中只保留加密后的包名。

### 工作流程

```
你 push monitor_apps.json（含明文包名）
        ↓
GitHub 触发 encrypt.yml workflow
        ↓
encrypt_packages.py 读取文件，找出不以 "gAAAAA" 开头的包名（即明文）
        ↓
用 ENCRYPT_KEY (Fernet) 加密包名
        ↓
清理 "encrypted" 字段（不再需要，格式自动区分）
        ↓
将加密后的内容推回 GitHub（明文包名被替换为加密字符串）
        ↓
仓库中只保留加密后的包名，无法看到真实包名
```

### 判断规则

不再使用 `"encrypted"` 字段。Fernet 加密 token 以 `gAAAAA` 开头（version byte 0x80 的 base64 编码），以此自动区分：
- **以 `gAAAAA` 开头** → 已加密的包名，跳过
- **不以 `gAAAAA` 开头** → 明文包名，需要加密

### 防止无限循环

加密脚本推送的 commit 由 `github-actions[bot]` 发起，`encrypt.yml` 会自动跳过这类 push，不会再次触发加密，避免无限循环。

### 前置条件

`ENCRYPT_KEY` GitHub Secret 是必填项。缺少密钥时监控脚本会报错退出。

生成加密密钥：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

输出示例：`tnDtrmbSFYEB3w5e_--vNcN9QNOrIy0wGt1I00sqz6c=`

将此密钥保存到 GitHub Secrets（`ENCRYPT_KEY`）。

### 使用方式

**直接写明文包名，push 后自动加密：**

```json
{
  "apps": [
    {
      "package_name": "com.example.myapp",
      "note": "2026-07 提交审核",
      "countries": ["mx"],
      "version": 1
    }
  ]
}
```

push 后几秒钟，workflow 自动完成加密，文件变为：

```json
{
  "apps": [
    {
      "package_name": "gAAAAABqXxvZosXaR2ToFeTa4cOU...",
      "note": "2026-07 提交审核",
      "countries": ["mx"],
      "version": 1
    }
  ]
}
```

- 不需要 `"encrypted"` 字段，包名格式自动区分加密/明文
- 加密后即使仓库是公开的，也无法看到真实包名
- 脚本运行时自动使用 `ENCRYPT_KEY` 解密，通知消息中显示真实包名

### 手动加密（可选）

如果不想等自动加密，也可以手动加密包名后再写入：

```bash
python -c "
from cryptography.fernet import Fernet
key = 'YOUR_ENCRYPT_KEY'
f = Fernet(key.encode())
print(f.encrypt('com.example.myapp'.encode()).decode())
"
```

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

每个应用必须在 `countries` 字段中指定上架目标国家。脚本只查询这些国家，任一国家上架即视为已上架，通知中会标注发现的国家区域。

**Q: 如何减少无效查询？**

在 `monitor_apps.json` 中为每个应用只列出计划上架的国家。例如只上架墨西哥的应用：`"countries": ["mx"]`

**Q: 忘记配置 package_name 会怎样？**

未配置 `package_name` 的条目会被跳过，日志中会记录错误。`package_name` 和 `countries` 都是必填字段，请确保每个应用条目都填写。

**Q: 忘记配置 countries 会怎样？**

未配置 `countries` 的应用会被跳过，日志中会记录警告。请确保每个应用条目都有 `countries` 字段。

**Q: 下架的包名会一直占用监控资源吗？**

不会。应用上架后再次下架时，脚本会自动从 GitHub 的 monitor_apps.json 中删除该包名，后续不再检查。

**Q: 忘记配置 version 会怎样？**

缺少 `version` 字段时默认按更新模式（每 3 小时）处理。建议明确填写，首次提交上架填 `1`，更新填 `2` 或更大值。

**Q: 如何判断首次提交还是更新？**

脚本通过 `state.json` 自动判断：
- 应用首次出现在 `monitor_apps.json` 中（不在 state 里）→ 首次提交，自动记录 `first_seen_time`，24h 后开始查询
- 将应用的 `version` 从 `1` 改为 `2` 或更大值 → 更新，脚本比对 state 中记录的旧 version 后自动切换查询频率
- 不需要手动填写 `submit_time`，首次发现的自动记录时间

**Q: 如何添加新的监控应用？**

直接编辑 GitHub 仓库中的 `monitor_apps.json`，添加新的包名条目（必须指定 `countries` 和 `version`）。首次提交填 `"version": 1`，更新填 `"version": 2`。**直接写明文包名即可，push 后自动加密**，无需手动加密。脚本会自动记录首次发现时间，24h 后开始查询。

**Q: 包名加密后忘记了密钥怎么办？**

密钥丢失后无法解密包名。请妥善保管 `ENCRYPT_KEY`，建议同时备份到安全的地方。

**Q: 明文包名推送后多久会被加密？**

push 到 GitHub 后，`encrypt.yml` workflow 通常在几秒到十几秒内触发完成加密。加密完成后仓库中明文包名会被替换为加密字符串。

**Q: 自动加密会无限循环吗？**

不会。加密脚本推送的 commit 由 `github-actions[bot]` 发起，`encrypt.yml` workflow 会自动跳过这类 push（`if: github.actor != 'github-actions[bot]'`），不会再次触发。

**Q: 包名支持明文吗？**

不支持。包名强制加密，明文推送后会被自动加密替换。监控脚本运行时缺少 `ENCRYPT_KEY` 会直接报错退出。

**Q: 旧的 `encrypted` 字段还在用吗？**

不再使用。`encrypted` 字段已废弃，加密/明文通过 Fernet token 格式自动区分（加密包名以 `gAAAAA` 开头）。encrypt_packages.py 会自动清理残留的 `encrypted` 字段。
