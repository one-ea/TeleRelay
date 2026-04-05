#!/bin/bash
# TeleRelay 启动脚本（兼容 Pterodactyl 面板）

echo "📦 安装依赖..."
pip install -r requirements.txt --quiet 2>/dev/null

echo "🚀 启动 TeleRelay..."
python3 bot.py
