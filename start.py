#!/usr/bin/env python3
"""一键启动脚本 - 自动创建 venv 并安装依赖后运行监控机器人"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
VENV_DIR = BASE_DIR / ".venv"

def ensure_venv():
    """确保虚拟环境存在并依赖已安装"""
    if not (VENV_DIR / "Scripts" / "python.exe").exists() if sys.platform == "win32" else not (VENV_DIR / "bin" / "python").exists():
        print("创建虚拟环境...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    pip_path = str(VENV_DIR / "Scripts" / "pip.exe") if sys.platform == "win32" else str(VENV_DIR / "bin" / "pip")
    python_path = str(VENV_DIR / "Scripts" / "python.exe") if sys.platform == "win32" else str(VENV_DIR / "bin" / "python")

    print("安装依赖...")
    subprocess.run([pip_path, "install", "-r", str(BASE_DIR / "requirements.txt")], check=True)

    return python_path

def main():
    python_path = ensure_venv()
    print("启动监控机器人...")
    subprocess.run([python_path, str(BASE_DIR / "play_monitor.py")])

if __name__ == "__main__":
    main()
