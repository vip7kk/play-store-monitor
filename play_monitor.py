#!/usr/bin/env python3
"""
Google Play Store 上架监控 + Telegram 提醒机器人

运行模式：
  - Actions 模式（默认）：单次检查后退出，适合 GitHub Actions 定时触发
  - 本地持续模式：加 --daemon 参数，循环运行不退出

配置来源：
  - 优先从环境变量读取（适合 Actions Secrets）
  - 环境变量缺失时从 config.json 读取（适合本地运行）

特色功能：
  - 按应用配置上架国家：每个应用必须指定上架目标国家，只查询配置的国家
  - 按提交类型配置查询频率：首次提交（version=1）24h内不查、之后4h/6h一查；更新（version≥2）3h一查；周日一律不查。通过 state.json 比对 version 自动识别首次/更新，无需手动填 submit_time
  - 包名强制加密：所有包名使用 Fernet 加密存储，GitHub 仓库中不暴露真实包名，明文推送后自动加密
  - 自动清理：应用上架后若再次下架，自动从 GitHub JSON 中删除该包名
"""

import json
import time
import logging
import os
import sys
import argparse
import base64
import re
from datetime import datetime
from pathlib import Path

import requests
from google_play_scraper import app as gp_app

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ── 日志配置 ────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── 路径 ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"

DEFAULT_LANG = "en"  # 查询统一使用英文，避免语言问题

# ── 国家码 → 完整国家名称映射 ────────────────────────────────
COUNTRY_NAMES = {
    "us": "美国", "cn": "中国", "jp": "日本", "kr": "韩国",
    "de": "德国", "fr": "法国", "gb": "英国", "uk": "英国",
    "in": "印度", "br": "巴西", "au": "澳大利亚", "ca": "加拿大",
    "th": "泰国", "vn": "越南", "id": "印度尼西亚", "my": "马来西亚",
    "ph": "菲律宾", "mx": "墨西哥", "es": "西班牙", "it": "意大利",
    "nl": "荷兰", "se": "瑞典", "pl": "波兰", "tr": "土耳其",
    "sa": "沙特阿拉伯", "ae": "阿联酋", "za": "南非",
    "ru": "俄罗斯", "tw": "中国台湾", "hk": "中国香港", "sg": "新加坡",
    "nz": "新西兰", "ie": "爱尔兰", "be": "比利时", "ch": "瑞士",
    "at": "奥地利", "pt": "葡萄牙", "gr": "希腊", "dk": "丹麦",
    "no": "挪威", "fi": "芬兰", "cz": "捷克", "hu": "匈牙利",
    "ro": "罗马尼亚", "bg": "保加利亚", "sk": "斯洛伐克", "hr": "克罗地亚",
    "si": "斯洛文尼亚", "lt": "立陶宛", "lv": "拉脱维亚", "ee": "爱沙尼亚",
    "il": "以色列", "eg": "埃及", "ng": "尼日利亚", "ke": "肯尼亚",
    "ar": "阿根廷", "cl": "智利", "co": "哥伦比亚", "pe": "秘鲁",
    "ve": "委内瑞拉", "pk": "巴基斯坦", "bd": "孟加拉国", "lk": "斯里兰卡",
}


def country_code_to_name(code: str) -> str:
    """将国家码转换为完整国家名称，未找到时返回原始代码"""
    return COUNTRY_NAMES.get(code.lower(), code)


def countries_to_names(codes: list[str]) -> list[str]:
    """将国家码列表转换为完整国家名称列表"""
    return [country_code_to_name(c) for c in codes]


# ── 包名加密/解密 ───────────────────────────────────────────
FERNET_PREFIX = "gAAAAA"  # Fernet 加密 token 固定前缀（version byte 0x80 → base64 "gAAAAA")


def is_fernet_token(s: str) -> bool:
    """判断字符串是否是 Fernet 加密 token"""
    return s.startswith(FERNET_PREFIX)


def decrypt_package_name(encrypted_str: str, encrypt_key: str) -> str:
    """
    强制解密 Fernet 加密的包名。
    encrypt_key 为空时直接报错退出，不允许明文包名运行。
    """
    if not encrypt_key:
        logger.error("缺少 ENCRYPT_KEY！包名强制加密模式下必须提供解密密钥")
        sys.exit(1)
    if not HAS_CRYPTO:
        logger.error("缺少 cryptography 库，无法解密包名")
        sys.exit(1)
    try:
        f = Fernet(encrypt_key.encode())
        return f.decrypt(encrypted_str.encode()).decode()
    except Exception as e:
        logger.error(f"包名解密失败: {e}")
        return encrypted_str


def encrypt_package_name(plain_str: str, encrypt_key: str) -> str:
    """
    加密包名为 Fernet 格式（用于写入 GitHub JSON）。
    """
    f = Fernet(encrypt_key.encode())
    return f.encrypt(plain_str.encode()).decode()


# ── 配置加载（环境变量优先，config.json 兜底）───────────
def load_config() -> dict:
    """
    优先从环境变量读取配置，缺失项从 config.json 补充。
    环境变量：
      TG_BOT_TOKEN, TG_CHAT_ID, GH_CONFIG_URL
      GH_TOKEN（用于自动修改 GitHub JSON）
      GITHUB_REPOSITORY（Actions 自动提供）
      ENCRYPT_KEY（包名加密密钥）
      MONITOR_INTERVAL
    """
    file_config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            file_config = json.load(f)

    bot_token = os.environ.get("TG_BOT_TOKEN") or file_config.get("telegram", {}).get("bot_token", "")
    chat_id = os.environ.get("TG_CHAT_ID") or file_config.get("telegram", {}).get("chat_id", "")
    gh_url = os.environ.get("GH_CONFIG_URL") or file_config.get("github", {}).get("config_url", "")
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or file_config.get("github", {}).get("token", "")
    encrypt_key = os.environ.get("ENCRYPT_KEY") or file_config.get("monitor", {}).get("encrypt_key", "")

    if not bot_token:
        logger.error("缺少 Bot Token！设置 TG_BOT_TOKEN 环境变量或在 config.json 中填写")
        sys.exit(1)
    if not chat_id:
        logger.error("缺少 Chat ID！设置 TG_CHAT_ID 环境变量或在 config.json 中填写")
        sys.exit(1)
    if not gh_url:
        logger.error("缺少 GitHub 配置 URL！设置 GH_CONFIG_URL 环境变量或在 config.json 中填写")
        sys.exit(1)
    if not encrypt_key:
        logger.error("缺少 ENCRYPT_KEY！包名强制加密模式下必须提供密钥")
        sys.exit(1)

    config = {
        "telegram": {
            "bot_token": bot_token,
            "chat_id": chat_id,
        },
        "github": {
            "config_url": gh_url,
            "token": gh_token,
            "repository": os.environ.get("GITHUB_REPOSITORY") or file_config.get("github", {}).get("repository", ""),
            "refresh_interval_minutes": int(
                os.environ.get("GH_REFRESH_INTERVAL") or file_config.get("github", {}).get("refresh_interval_minutes", 30)
            ),
        },
        "monitor": {
            "check_interval_minutes": int(
                os.environ.get("MONITOR_INTERVAL") or file_config.get("monitor", {}).get("check_interval_minutes", 10)
            ),
            "encrypt_key": encrypt_key,
        },
    }
    logger.info(f"配置加载完成 | Token: {bot_token[:10]}... | Chat ID: {chat_id} | GH Token: {'有' if gh_token else '无'} | 加密: {'有' if encrypt_key else '无'}")
    return config


# ── 解析 GitHub raw URL → owner/repo/branch/path ───────────
def parse_gh_url(raw_url: str) -> dict:
    """
    从 GitHub raw URL 提取 owner, repo, branch, path。
    示例: https://raw.githubusercontent.com/vip7kk/play-store-monitor/main/monitor_apps.json
    """
    pattern = r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)"
    match = re.match(pattern, raw_url)
    if match:
        return {
            "owner": match.group(1),
            "repo": match.group(2),
            "branch": match.group(3),
            "path": match.group(4),
        }
    logger.warning(f"无法解析 GitHub URL: {raw_url}")
    return {}


# ── 从 GitHub 拉取监控列表 ──────────────────────────────────
def fetch_monitor_list(url: str, encrypt_key: str = "") -> list[dict]:
    """从 GitHub raw URL 拉取 JSON 文件，返回 app 列表（强制解密所有包名）"""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        apps = data.get("apps", [])
        logger.info(f"从 GitHub 拉取到 {len(apps)} 个应用")

        # 强制解密所有包名（包名一律为加密格式）
        for app_cfg in apps:
            original = app_cfg.get("package_name")
            # 清理可能残留的 encrypted 字段
            if "encrypted" in app_cfg:
                del app_cfg["encrypted"]
            # package_name 是必填字段，缺少时跳过并报错
            if not original:
                logger.error(f"⚠️ 条目缺少必填字段 package_name，跳过: {app_cfg}")
                continue
            decrypted = decrypt_package_name(original, encrypt_key)
            if decrypted != original:
                app_cfg["package_name_decrypted"] = decrypted
                logger.info(f"包名已解密: {original[:20]}... → {decrypted}")
            else:
                logger.warning(f"包名解密结果与原文相同，可能密钥错误: {original[:20]}...")

        return apps
    except Exception as e:
        logger.error(f"拉取 GitHub 配置失败: {e}")
        return []


# ── 检查 Play Store 状态（多国查询）───────────────────────
def check_play_store(package_name: str, countries: list[str], real_package_name: str | None = None) -> dict | None:
    """
    用 google-play-scraper 在多个国家/地区查询应用详情。
    任一国家能搜到即视为已上架，返回第一个成功的详情。
    全部失败则返回 None（未上架）。
    
    real_package_name: 解密后的真实包名（用于实际查询 Play Store）
    package_name: 显示用的包名（可能是加密字符串）
    """
    query_pkg = real_package_name or package_name
    for country in countries:
        try:
            result = gp_app(
                app_id=query_pkg,
                lang=DEFAULT_LANG,
                country=country,
            )
            info = {
                "title": result.get("title", ""),
                "score": result.get("score", 0),
                "installs": result.get("installs", ""),
                "version": result.get("version", ""),
                "free": result.get("free", True),
                "url": f"https://play.google.com/store/apps/details?id={query_pkg}",
                "found_in_country": country,
            }
            logger.info(f"{query_pkg} 在 {country_code_to_name(country)} 找到上架")
            return info
        except Exception:
            continue

    logger.info(f"{query_pkg} 在所有 {len(countries)} 个国家均未找到")
    return None


# ── 查询频率调度 ──────────────────────────────────────────
def should_check_app(app_cfg: dict, prev_state: dict, now: datetime) -> tuple[bool, str]:
    """
    根据提交类型（version）和当前时间判断是否应该检查某个应用。

    首次/更新识别规则（通过 state.json 比对 version）：
      - 应用不在 state 中 → 新应用，首次提交
      - 应用在 state 中，version 未变 → 保持原频率
      - 应用在 state 中，version 变化 → 更新，切换频率

    查询频率规则：
      - version=1（首次提交上架）：
        · first_seen_time 后 24 小时内不查询
        · 24 小时后：工作日每 4 小时，周六每 6 小时
        · 周日不查询
      - version≥2（更新）：
        · 每 3 小时查询一次
        · 周日不查询
      - 缺少 version 字段：默认按更新模式（version=2）处理

    返回 (should_check, reason)
    """
    real_pkg = app_cfg.get("package_name_decrypted", app_cfg.get("package_name", ""))
    version = app_cfg.get("version")

    if version is None:
        logger.warning(f"⚠️ {real_pkg} 缺少 version 字段，默认按更新模式（3 小时间隔）处理")
        version = 2

    # 周日一律不查询（weekday() 返回 6 = Sunday）
    if now.weekday() == 6:
        return False, "周日不查询"

    # 从 state 中获取历史信息，判断首次/更新
    prev = prev_state.get(real_pkg)
    is_first_submission = True  # 默认视为首次提交

    if prev:
        # 应用已在 state 中 → 不是首次出现
        is_first_submission = False
        prev_version = prev.get("version", 1)
        if prev_version != version:
            # version 变化 → 视为更新
            logger.info(f"🔄 {real_pkg} version 从 {prev_version} 变为 {version}，视为更新")

    if version == 1 and is_first_submission:
        # 首次提交且第一次出现：24 小时内不查询
        # first_seen_time 在 run_check_cycle 中首次记录时设置为当前时间
        first_seen_time = prev.get("first_seen_time") if prev else None
        if first_seen_time:
            try:
                first_seen_dt = datetime.fromisoformat(first_seen_time)
                hours_since_first = (now - first_seen_dt).total_seconds() / 3600
                if hours_since_first < 24:
                    return False, f"首次提交后 {hours_since_first:.1f}h，24h内不查询"
            except (ValueError, TypeError):
                logger.warning(f"⚠️ {real_pkg} first_seen_time 格式无效: {first_seen_time}")
        else:
            # 还没记录 first_seen_time（本轮首次发现），跳过本轮（下轮会记录）
            return False, "首次提交，尚未记录 first_seen_time，本轮跳过"

    if version == 1 and not is_first_submission:
        # version=1 但不是新应用 → 仍在首次提交模式
        first_seen_time = prev.get("first_seen_time")
        if first_seen_time:
            try:
                first_seen_dt = datetime.fromisoformat(first_seen_time)
                hours_since_first = (now - first_seen_dt).total_seconds() / 3600
                if hours_since_first < 24:
                    return False, f"首次提交后 {hours_since_first:.1f}h，24h内不查询"
            except (ValueError, TypeError):
                pass

    # 确定查询间隔
    if version == 1:
        if now.weekday() == 5:  # 周六
            interval_hours = 6
        else:  # 工作日
            interval_hours = 4
    else:
        # 更新模式
        interval_hours = 3

    # 判断距上次检查的时间
    if prev and prev.get("last_checked"):
        try:
            last_dt = datetime.fromisoformat(prev["last_checked"])
            hours_since_last = (now - last_dt).total_seconds() / 3600
            if hours_since_last < interval_hours:
                return False, f"距上次检查 {hours_since_last:.1f}h，需间隔 {interval_hours}h"
        except (ValueError, TypeError):
            pass  # 格式错误，直接检查

    return True, ""


# ── 加载 / 保存状态 ────────────────────────────────────────
def load_state() -> dict:
    """加载上次保存的状态文件"""
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    """持久化状态到 state.json"""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Telegram 发送通知 ──────────────────────────────────────
def send_telegram_message(bot_token: str, chat_id: str, text: str):
    """通过 Telegram Bot API 发送消息"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            logger.error(f"Telegram API 返回错误: {resp.status_code} {resp.text}")
        else:
            logger.info("Telegram 通知已发送")
    except Exception as e:
        logger.error(f"Telegram 通知发送失败: {e}")


def format_app_info(app_config: dict, play_info: dict | None, app_countries: list[str] | None = None, real_package_name: str | None = None) -> str:
    """格式化应用信息为 Telegram 消息文本"""
    # 优先使用解密后的真实包名用于显示和链接
    display_pkg = real_package_name or app_config.get("package_name", "")
    name = app_config.get("app_name", display_pkg)
    note = app_config.get("note", "")
    countries_str = ""
    if app_countries:
        # 国家码转换为完整国家名称
        country_names = countries_to_names(app_countries)
        countries_str = f"\n*目标国家*: {', '.join(country_names)}"

    if play_info:
        # 上架国家也显示完整名称，不写"区"
        found_country_code = play_info.get("found_in_country", "")
        found_country_name = country_code_to_name(found_country_code) if found_country_code else ""
        country_tag = f"（{found_country_name}）" if found_country_name else ""
        return (
            f"🎉 *应用已上架{country_tag}！*\n\n"
            f"*应用名称*: {play_info['title']}\n"
            f"*包名*: `{display_pkg}`\n"
            f"*版本*: {play_info['version']}\n"
            f"*评分*: {play_info['score']}\n"
            f"*安装量*: {play_info['installs']}\n"
            f"*备注*: {note}{countries_str}\n\n"
            f"[查看应用]({play_info['url']})"
        )
    else:
        return (
            f"⚠️ *应用未上架*\n\n"
            f"*包名*: `{display_pkg}`\n"
            f"*预期名称*: {name}\n"
            f"*备注*: {note}{countries_str}"
        )


# ── 自动删除下架包名 ──────────────────────────────────────
def remove_package_from_github(package_name: str, config: dict, encrypt_key: str) -> bool:
    """
    应用上架后又下架时，自动从 GitHub 的 monitor_apps.json 中删除该包名。
    使用 GitHub Contents API 读取文件 → 删除对应条目 → 提交更新。
    
    package_name: 真实包名（已解密）
    encrypt_key: 加密密钥，用于匹配加密包名
    """
    gh_token = config["github"].get("token")
    gh_url = config["github"]["config_url"]

    if not gh_token:
        logger.warning("缺少 GH_TOKEN / GITHUB_TOKEN，无法自动删除下架包名（仅发送通知）")
        return False

    url_info = parse_gh_url(gh_url)
    if not url_info:
        logger.warning("无法解析 GitHub URL，跳过自动删除")
        return False

    owner = url_info["owner"]
    repo = url_info["repo"]
    branch = url_info["branch"]
    file_path = url_info["path"]
    api_base = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github+json",
    }

    # 1. 获取当前文件内容 + SHA
    try:
        resp = requests.get(api_base, headers=headers, params={"ref": branch}, timeout=15)
        resp.raise_for_status()
        file_data = resp.json()
        sha = file_data["sha"]
        content = base64.b64decode(file_data["content"]).decode("utf-8")
        current_json = json.loads(content)
    except Exception as e:
        logger.error(f"读取 GitHub JSON 失败: {e}")
        return False

    # 2. 删除对应包名（解密后匹配真实包名）
    original_count = len(current_json.get("apps", []))
    new_apps = []
    for app in current_json.get("apps", []):
        stored_name = app.get("package_name", "")
        # 所有包名都是加密格式，解密后比较
        decrypted_name = decrypt_package_name(stored_name, encrypt_key)
        if decrypted_name != package_name:
            new_apps.append(app)
    
    current_json["apps"] = new_apps
    new_count = len(current_json["apps"])

    if new_count == original_count:
        logger.warning(f"{package_name} 不在 JSON 中，无需删除")
        return True

    # 3. 提交更新到 GitHub
    new_content = json.dumps(current_json, indent=2, ensure_ascii=False)
    encoded = base64.b64encode(new_content.encode("utf-8")).decode()

    try:
        resp = requests.put(api_base, headers=headers, json={
            "message": f"auto: remove delisted package {package_name}",
            "content": encoded,
            "sha": sha,
            "branch": branch,
        }, timeout=15)
        resp.raise_for_status()
        logger.info(f"✅ 已从 GitHub JSON 中删除下架包名 {package_name}（{original_count} → {new_count}）")
        return True
    except Exception as e:
        logger.error(f"更新 GitHub JSON 失败: {e}")
        return False


# ── 单次检查周期 ──────────────────────────────────────────
def run_check_cycle(config: dict, first_run: bool = False):
    """执行一次完整的检查周期"""
    tg = config["telegram"]
    gh = config["github"]
    mon = config["monitor"]
    encrypt_key = mon.get("encrypt_key", "")
    now = datetime.now()

    # 1. 拉取监控列表（自动解密）
    apps = fetch_monitor_list(gh["config_url"], encrypt_key=encrypt_key)
    if not apps:
        logger.warning("监控列表为空，跳过本轮")
        return

    # 2. 加载上次状态
    prev_state = load_state()
    new_state = {}

    # 3. 逐个检查（根据频率调度决定是否查询）
    packages_to_remove = []  # 收集需要从 JSON 删除的包名

    for app_cfg in apps:
        pkg = app_cfg.get("package_name")
        # package_name 必填，缺少时跳过
        if not pkg:
            logger.error(f"⚠️ 条目缺少必填字段 package_name，跳过: {app_cfg}")
            continue
        real_pkg = app_cfg.get("package_name_decrypted", pkg)  # 解密后的真实包名
        
        # 每个应用必须指定 countries，否则跳过
        app_countries = app_cfg.get("countries")
        if not app_countries or len(app_countries) == 0:
            logger.warning(f"⚠️ {real_pkg} 未配置 countries 字段，跳过检查（请在 monitor_apps.json 中指定上架目标国家）")
            # 保留之前的状态
            if real_pkg in prev_state:
                new_state[real_pkg] = prev_state[real_pkg]
            continue

        # 根据提交类型和频率调度判断是否应该查询
        should_check, reason = should_check_app(app_cfg, prev_state, now)
        if not should_check:
            logger.info(f"⏭️ {real_pkg}: {reason}")
            # 保留之前的状态（不更新 last_checked）
            if real_pkg in prev_state:
                new_state[real_pkg] = prev_state[real_pkg]
            continue

        logger.info(f"检查: {real_pkg} (version={app_cfg.get('version', '?')}) | 目标国家: {','.join(countries_to_names(app_countries))}")

        play_info = check_play_store(pkg, app_countries, real_package_name=real_pkg)
        is_live = play_info is not None

        new_state[real_pkg] = {
            "live": is_live,
            "last_checked": datetime.now().isoformat(),
            "version": app_cfg.get("version", 2),
        }

        # 首次出现的应用：记录 first_seen_time（用于 24h 延迟计算）
        prev = prev_state.get(real_pkg)
        if prev is None:
            new_state[real_pkg]["first_seen_time"] = datetime.now().isoformat()
        elif prev.get("first_seen_time"):
            # 已有应用，保留原有的 first_seen_time
            new_state[real_pkg]["first_seen_time"] = prev["first_seen_time"]
            # version 变化时保留原有 first_seen_time（更新不需要 24h 延迟）
        if prev is None and first_run:
            logger.info(f"首次检查 {real_pkg}: {'已上架' if is_live else '未上架'}")
            msg = format_app_info(app_cfg, play_info, app_countries, real_package_name=real_pkg)
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        elif prev is None and not first_run:
            logger.info(f"新增监控 {real_pkg}: {'已上架' if is_live else '未上架'}")
            msg = f"📋 *新增监控应用*\n\n{format_app_info(app_cfg, play_info, app_countries, real_package_name=real_pkg)}"
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        elif not prev["live"] and is_live:
            logger.info(f"🎉 {real_pkg} 新上架！")
            msg = format_app_info(app_cfg, play_info, app_countries, real_package_name=real_pkg)
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        elif prev["live"] and not is_live:
            # 从上架 → 下架：发送通知 + 自动从 JSON 删除
            logger.warning(f"🚨 {real_pkg} 已下架，将从监控列表中自动删除")
            msg = (
                f"🚨 *应用已下架，自动移除监控*\n\n"
                f"*包名*: `{real_pkg}`\n"
                f"*预期名称*: {app_cfg.get('app_name', '')}\n"
                f"*备注*: 该包名已从监控列表 JSON 中自动删除，后续不再检查"
            )
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
            packages_to_remove.append(real_pkg)
            # 下架的包名不再保留状态
            del new_state[real_pkg]
        else:
            logger.info(f"{real_pkg}: 状态无变化 ({'已上架' if is_live else '未上架'})")

        time.sleep(1)

    # 4. 自动删除下架包名
    for pkg in packages_to_remove:
        removed = remove_package_from_github(pkg, config, encrypt_key=encrypt_key)
        if not removed:
            logger.warning(f"无法自动删除 {pkg}，下次运行时仍会检查")

    # 5. 保存新状态
    save_state(new_state)


# ── 主入口 ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Google Play Store 上架监控 + Telegram 提醒机器人")
    parser.add_argument("--daemon", action="store_true", help="持续运行模式（本地服务器）")
    parser.add_argument("--first-run", action="store_true", help="首次运行，通知所有应用当前状态")
    args = parser.parse_args()

    config = load_config()

    if args.daemon:
        interval = config["monitor"].get("check_interval_minutes", 10) * 60
        logger.info("=" * 50)
        logger.info("本地持续运行模式启动")
        logger.info(f"检查间隔: {interval // 60} 分钟 | 查询国家从各应用配置获取")
        logger.info("=" * 50)

        tg = config["telegram"]
        send_telegram_message(
            tg["bot_token"], tg["chat_id"],
            "🟢 *Play Store 监控机器人已启动（本地模式）*\n\n将定期检查应用上架状态，变化时即时通知。上架后下架的包名会自动从列表删除。"
        )

        first = True
        while True:
            try:
                run_check_cycle(config, first_run=first)
                first = False
                logger.info(f"本轮检查完成，等待 {interval // 60} 分钟后再次检查...")
                time.sleep(interval)
            except KeyboardInterrupt:
                logger.info("手动停止，退出")
                send_telegram_message(tg["bot_token"], tg["chat_id"], "🔴 *监控机器人已停止*")
                break
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                time.sleep(30)
    else:
        logger.info("=" * 50)
        logger.info("Actions 单次运行模式")
        logger.info("=" * 50)
        run_check_cycle(config, first_run=args.first_run)
        logger.info("单次检查完成，退出")


if __name__ == "__main__":
    main()
