#!/usr/bin/env python3
"""
Google Play Store 上架监控 + Telegram 提醒机器人

运行模式：
  - Actions 模式（默认）：单次检查后退出，适合 GitHub Actions 定时触发
  - 本地持续模式：加 --daemon 参数，循环运行不退出

配置来源：
  - 优先从环境变量读取（适合 Actions Secrets）
  - 环境变量缺失时从 config.json 读取（适合本地运行）
"""

import json
import time
import logging
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

import requests
from google_play_scraper import app as gp_app

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

# ── 配置加载（环境变量优先，config.json 兜底）───────────
def load_config() -> dict:
    """
    优先从环境变量读取敏感配置，缺失项从 config.json 补充。
    环境变量命名：
      TG_BOT_TOKEN, TG_CHAT_ID, GH_CONFIG_URL, MONITOR_INTERVAL, MONITOR_LANG, MONITOR_COUNTRY
    """
    # 先尝试读 config.json
    file_config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            file_config = json.load(f)

    # 环境变量覆盖
    bot_token = os.environ.get("TG_BOT_TOKEN") or file_config.get("telegram", {}).get("bot_token", "")
    chat_id = os.environ.get("TG_CHAT_ID") or file_config.get("telegram", {}).get("chat_id", "")
    gh_url = os.environ.get("GH_CONFIG_URL") or file_config.get("github", {}).get("config_url", "")

    if not bot_token:
        logger.error("缺少 Bot Token！设置 TG_BOT_TOKEN 环境变量或在 config.json 中填写")
        sys.exit(1)
    if not chat_id:
        logger.error("缺少 Chat ID！设置 TG_CHAT_ID 环境变量或在 config.json 中填写")
        sys.exit(1)
    if not gh_url:
        logger.error("缺少 GitHub 配置 URL！设置 GH_CONFIG_URL 环境变量或在 config.json 中填写")
        sys.exit(1)

    config = {
        "telegram": {
            "bot_token": bot_token,
            "chat_id": chat_id,
        },
        "github": {
            "config_url": gh_url,
            "refresh_interval_minutes": int(os.environ.get("GH_REFRESH_INTERVAL") or file_config.get("github", {}).get("refresh_interval_minutes", 30)),
        },
        "monitor": {
            "check_interval_minutes": int(os.environ.get("MONITOR_INTERVAL") or file_config.get("monitor", {}).get("check_interval_minutes", 10)),
            "language": os.environ.get("MONITOR_LANG") or file_config.get("monitor", {}).get("language", "en"),
            "country": os.environ.get("MONITOR_COUNTRY") or file_config.get("monitor", {}).get("country", "us"),
        },
    }
    logger.info(f"配置加载完成 | Bot Token: {bot_token[:10]}... | Chat ID: {chat_id}")
    return config


# ── 从 GitHub 拉取监控列表 ──────────────────────────────────
def fetch_monitor_list(url: str) -> list[dict]:
    """从 GitHub raw URL 拉取 JSON 文件，返回 app 列表"""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        apps = data.get("apps", [])
        logger.info(f"从 GitHub 拉取到 {len(apps)} 个应用")
        return apps
    except Exception as e:
        logger.error(f"拉取 GitHub 配置失败: {e}")
        return []


# ── 检查 Play Store 状态 ───────────────────────────────────
def check_play_store(package_name: str, lang: str = "en", country: str = "us") -> dict | None:
    """
    用 google-play-scraper 查询应用详情。
    如果应用存在返回详情 dict，不存在返回 None。
    """
    try:
        result = gp_app(
            app_id=package_name,
            lang=lang,
            country=country,
        )
        return {
            "title": result.get("title", ""),
            "score": result.get("score", 0),
            "installs": result.get("installs", ""),
            "version": result.get("version", ""),
            "free": result.get("free", True),
            "url": f"https://play.google.com/store/apps/details?id={package_name}",
        }
    except Exception as e:
        logger.debug(f"{package_name} 未上架或查询失败: {e}")
        return None


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


def format_app_info(app_config: dict, play_info: dict | None) -> str:
    """格式化应用信息为 Telegram 消息文本"""
    pkg = app_config.get("package_name", "")
    name = app_config.get("app_name", pkg)
    note = app_config.get("note", "")

    if play_info:
        return (
            f"🎉 *应用已上架！*\n\n"
            f"*应用名称*: {play_info['title']}\n"
            f"*包名*: `{pkg}`\n"
            f"*版本*: {play_info['version']}\n"
            f"*评分*: {play_info['score']}\n"
            f"*安装量*: {play_info['installs']}\n"
            f"*备注*: {note}\n\n"
            f"[查看应用]({play_info['url']})"
        )
    else:
        return (
            f"⚠️ *应用未上架*\n\n"
            f"*包名*: `{pkg}`\n"
            f"*预期名称*: {name}\n"
            f"*备注*: {note}"
        )


# ── 单次检查周期 ──────────────────────────────────────────
def run_check_cycle(config: dict, first_run: bool = False):
    """执行一次完整的检查周期"""
    tg = config["telegram"]
    gh = config["github"]
    mon = config["monitor"]

    # 1. 拉取监控列表
    apps = fetch_monitor_list(gh["config_url"])
    if not apps:
        logger.warning("监控列表为空，跳过本轮")
        return

    # 2. 加载上次状态
    prev_state = load_state()
    new_state = {}

    # 3. 逐个检查
    for app_cfg in apps:
        pkg = app_cfg["package_name"]
        logger.info(f"检查: {pkg} ({app_cfg.get('app_name', '')})")

        play_info = check_play_store(pkg, mon.get("language", "en"), mon.get("country", "us"))
        is_live = play_info is not None

        # 记录当前状态（仅保留 live 标记，不含 play_info，减少 state.json 大小）
        new_state[pkg] = {
            "live": is_live,
            "last_checked": datetime.now().isoformat(),
        }

        # 与上次对比，检测变化
        prev = prev_state.get(pkg)
        if prev is None and first_run:
            # Actions 首次运行：通知当前状态
            logger.info(f"首次检查 {pkg}: {'已上架' if is_live else '未上架'}")
            msg = format_app_info(app_cfg, play_info)
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        elif prev is None and not first_run:
            # 非首次但有新包名加入监控列表
            logger.info(f"新增监控 {pkg}: {'已上架' if is_live else '未上架'}")
            msg = f"📋 *新增监控应用*\n\n{format_app_info(app_cfg, play_info)}"
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        elif not prev["live"] and is_live:
            # 从未上架 → 上架 ✅
            logger.info(f"🎉 {pkg} 新上架！")
            msg = format_app_info(app_cfg, play_info)
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        elif prev["live"] and not is_live:
            # 从上架 → 下架 ⚠️
            logger.warning(f"⚠️ {pkg} 可能已下架")
            msg = f"🚨 *应用可能下架！*\n\n*包名*: `{pkg}`\n*预期名称*: {app_cfg.get('app_name', '')}"
            send_telegram_message(tg["bot_token"], tg["chat_id"], msg)
        else:
            logger.info(f"{pkg}: 状态无变化 ({'已上架' if is_live else '未上架'})")

        # 避免请求过快
        time.sleep(1)

    # 4. 保存新状态
    save_state(new_state)


# ── 主入口 ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Google Play Store 上架监控 + Telegram 提醒机器人")
    parser.add_argument("--daemon", action="store_true", help="持续运行模式（本地服务器）")
    parser.add_argument("--first-run", action="store_true", help="首次运行，通知所有应用当前状态")
    args = parser.parse_args()

    config = load_config()

    if args.daemon:
        # ── 本地持续运行模式 ──
        interval = config["monitor"].get("check_interval_minutes", 10) * 60
        logger.info("=" * 50)
        logger.info("本地持续运行模式启动")
        logger.info(f"检查间隔: {interval // 60} 分钟")
        logger.info("=" * 50)

        tg = config["telegram"]
        send_telegram_message(
            tg["bot_token"], tg["chat_id"],
            "🟢 *Play Store 监控机器人已启动（本地模式）*\n\n将定期检查应用上架状态，变化时即时通知。"
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
        # ── Actions 单次运行模式 ──
        logger.info("=" * 50)
        logger.info("Actions 单次运行模式")
        logger.info("=" * 50)
        run_check_cycle(config, first_run=args.first_run)
        logger.info("单次检查完成，退出")


if __name__ == "__main__":
    main()
