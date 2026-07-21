#!/usr/bin/env python3
"""
自动加密 monitor_apps.json 中的明文包名

当用户推送明文包名到 GitHub 仓库时，此脚本由 encrypt.yml workflow 自动触发：
1. 从 GitHub 仓库读取 monitor_apps.json
2. 找出所有未加密（没有 "encrypted": true）的包名
3. 用 ENCRYPT_KEY（Fernet）加密这些包名
4. 将加密后的内容更新到 GitHub 仓库
5. 如果没有任何明文包名需要加密，则不做任何操作
"""

import json
import base64
import os
import sys
import logging

import requests

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_env_config() -> dict:
    """从环境变量读取配置"""
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")  # e.g. "vip7kk/play-store-monitor"
    encrypt_key = os.environ.get("ENCRYPT_KEY", "")
    
    if not repository:
        logger.error("缺少 GITHUB_REPOSITORY 环境变量")
        sys.exit(1)
    if not encrypt_key:
        logger.error("缺少 ENCRYPT_KEY 环境变量")
        sys.exit(1)
    if not HAS_CRYPTO:
        logger.error("缺少 cryptography 库，无法加密")
        sys.exit(1)
    
    return {
        "gh_token": gh_token,
        "owner": repository.split("/")[0],
        "repo": repository.split("/")[1],
        "encrypt_key": encrypt_key,
    }


def encrypt_package_name(plain_str: str, encrypt_key: str) -> str:
    """用 Fernet 加密包名"""
    f = Fernet(encrypt_key.encode())
    return f.encrypt(plain_str.encode()).decode()


def fetch_file_from_github(owner: str, repo: str, path: str, branch: str = "main", gh_token: str = "") -> tuple[str, str, dict]:
    """
    从 GitHub Contents API 获取文件内容，返回 (content, sha, json_data)
    """
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github+json",
    }
    params = {"ref": branch}
    
    resp = requests.get(api_url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    file_data = resp.json()
    sha = file_data["sha"]
    content = base64.b64decode(file_data["content"]).decode("utf-8")
    json_data = json.loads(content)
    
    return content, sha, json_data


def push_file_to_github(owner: str, repo: str, path: str, content: str, sha: str, branch: str = "main", gh_token: str = "", message: str = "") -> bool:
    """
    将更新后的文件内容推送回 GitHub
    """
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github+json",
    }
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    
    payload = {
        "message": message or "auto: encrypt plaintext package names",
        "content": encoded,
        "sha": sha,
        "branch": branch,
    }
    
    resp = requests.put(api_url, headers=headers, json=payload, timeout=15)
    if resp.status_code in (200, 201):
        logger.info(f"✅ 文件已推送到 GitHub: {path}")
        return True
    else:
        logger.error(f"推送失败: {resp.status_code} {resp.text}")
        return False


def encrypt_plain_packages(config: dict) -> bool:
    """
    主逻辑：找出所有明文包名，加密后推回 GitHub
    
    返回 True 表示有包名被加密（文件已更新）
    返回 False 表示没有需要加密的包名（无需操作）
    """
    owner = config["owner"]
    repo = config["repo"]
    encrypt_key = config["encrypt_key"]
    gh_token = config["gh_token"]
    file_path = "monitor_apps.json"
    
    # 1. 从 GitHub 读取当前文件
    _, sha, json_data = fetch_file_from_github(owner, repo, file_path, gh_token=gh_token)
    apps = json_data.get("apps", [])
    logger.info(f"读取到 {len(apps)} 个应用配置")
    
    # 2. 找出明文包名并加密
    changed = False
    encrypted_names = []  # 记录被加密的包名（用于提交消息）
    
    for app_cfg in apps:
        is_encrypted = app_cfg.get("encrypted", False)
        
        if not is_encrypted:
            plain_name = app_cfg.get("package_name", "")
            if not plain_name:
                logger.warning(f"跳过空包名条目")
                continue
            
            # 加密包名
            encrypted_name = encrypt_package_name(plain_name, encrypt_key)
            app_cfg["package_name"] = encrypted_name
            app_cfg["encrypted"] = True
            changed = True
            encrypted_names.append(plain_name)
            logger.info(f"✅ 包名已加密: {plain_name} → {encrypted_name[:30]}...")
        else:
            logger.info(f"包名已是加密状态，跳过: {app_cfg.get('package_name', '')[:30]}...")
    
    if not changed:
        logger.info("所有包名均已加密，无需操作")
        return False
    
    # 3. 推送更新到 GitHub
    new_content = json.dumps(json_data, indent=2, ensure_ascii=False)
    commit_msg = f"auto: encrypt package names ({', '.join(encrypted_names)})"
    
    success = push_file_to_github(owner, repo, file_path, new_content, sha, gh_token=gh_token, message=commit_msg)
    if success:
        logger.info(f"🎉 自动加密完成，共加密 {len(encrypted_names)} 个包名")
    return success


def main():
    config = load_env_config()
    encrypt_plain_packages(config)


if __name__ == "__main__":
    main()
