<p align="center">
  <h1 align="center">📮 TeleRelay</h1>
  <p align="center">轻量、安全的 Telegram 私聊中转机器人</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/python--telegram--bot-21.x-blue?logo=telegram&logoColor=white" alt="PTB">
    <img src="https://img.shields.io/badge/version-2.2-green" alt="Version">
    <img src="https://img.shields.io/badge/CPU-0.15+-orange" alt="Low CPU">
    <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
    <a href="https://linux.do"><img src="https://img.shields.io/badge/LINUX%20DO-社区支持-blue?logo=discourse&logoColor=white" alt="LINUX DO"></a>
  </p>
</p>

---

## ✨ 功能

| 分类 | 特性 |
|------|------|
| 🔒 **安全** | Emoji 点击验证 · 防刷屏限速 · 封禁管理 · Markdown 注入防护 |
| 💬 **消息** | 文字 · 图片 · 视频 · 语音 · 文件 · 贴纸 · GIF · 位置 · 联系人 |
| 📊 **管理** | 联系人列表 · 运行统计 · 群发广播 · 离开自动回复 |
| 💾 **数据** | JSON 原子写入 · 延迟合并保存 · 优雅关机落盘 |
| ⚡ **性能** | 0.15 CPU 适配 · 长轮询低功耗 · 串行处理无峰值 |
| 🌐 **部署** | Polling / Webhook · 环境变量 + 配置文件 · Pterodactyl 兼容 |

## 📋 命令

### 所有用户

| 命令 | 说明 |
|------|------|
| `/start` | 开始使用 / 触发验证 |
| `/help` | 查看帮助信息 |

### 管理员

| 命令 | 说明 |
|------|------|
| `/ban <ID>` | 封禁用户 |
| `/unban <ID>` | 解封用户 |
| `/banlist` | 查看封禁列表 |
| `/list` | 查看联系人列表（按消息量排序） |
| `/stats` | 运行统计 |
| `/away` | 切换离开模式 |
| `/setaway <消息>` | 设置离开自动回复 |
| `/broadcast <消息>` | 群发通知 |

> 💡 回复转发的消息即可直接回复对应用户，无需命令。

## 🚀 快速开始

### 1. 准备

- 在 Telegram 找 [@BotFather](https://t.me/BotFather)，发送 `/newbot` 获取 Bot Token
- 在 Telegram 找 [@userinfobot](https://t.me/userinfobot)，获取你的数字 ID

### 2. 部署

```bash
git clone https://github.com/one-ea/TeleRelay.git
cd TeleRelay
pip install -r requirements.txt
```

### 3. 配置

**方式一：配置文件（推荐本地）**

```bash
cp config.example.py config.py
```

编辑 `config.py`：

```python
BOT_TOKEN = "你的Bot Token"
OWNER_ID = 你的用户ID
```

**方式二：环境变量（推荐云平台）**

```bash
export BOT_TOKEN="你的Bot Token"
export OWNER_ID=你的用户ID
```

### 4. 启动

```bash
python bot.py
```

> ⚠️ **首次启动前**，请先在 Telegram 上给你的 Bot 发送 `/start`，否则启动通知无法送达。

## 🌐 部署指南

<details>
<summary><b>📦 Lunes / Pterodactyl 面板</b></summary>

1. 创建 Python 类型服务器
2. 上传所有项目文件
3. 在面板编辑 `config.py`，填入 Token 和 ID
4. **Startup Command 设置为**：`bash start.sh`
5. 启动服务器

> ⚠️ 不要使用 `&&` 连接命令，Pterodactyl 不支持。`start.sh` 已处理依赖安装。

</details>

<details>
<summary><b>☁️ Railway / Render</b></summary>

1. Fork 本仓库
2. 在平台新建项目，连接 GitHub 仓库
3. 设置环境变量 `BOT_TOKEN` 和 `OWNER_ID`
4. 部署即可

</details>

<details>
<summary><b>🖥️ VPS / 服务器</b></summary>

```bash
screen -S telerelay
python bot.py
# Ctrl+A, D 分离会话
```

</details>

## ⚙️ 高级配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `BOT_TOKEN` | — | Bot Token（必填） |
| `OWNER_ID` | — | 管理员用户 ID（必填） |
| `BOT_MODE` | `polling` | 运行模式：`polling` / `webhook` |
| `WEBHOOK_URL` | — | Webhook 域名（webhook 模式必填） |
| `PORT` | `8443` | Webhook 监听端口 |
| `DATA_FILE` | `data.json` | 数据文件路径 |

## 🔒 安全特性

- **验证码防护** — 6 选 1 Emoji 验证，拦截自动化骚扰
- **防刷屏** — 每用户 3 秒冷却，过期记录自动清理
- **Markdown 注入防护** — 用户名特殊字符自动转义
- **原子文件写入** — `os.replace()` 防断电数据损坏
- **内存保护** — 待验证队列上限 100，限速记录定期清理
- **敏感信息隔离** — `config.py` 和 `data.json` 通过 `.gitignore` 排除

## 📁 项目结构

```
TeleRelay/
├── bot.py              # 主程序 (v2.2)
├── config.py           # 配置文件（不上传 Git）
├── config.example.py   # 配置示例
├── data.json           # 运行时数据（自动生成，不上传）
├── start.sh            # Pterodactyl 启动脚本
├── requirements.txt    # 依赖 (python-telegram-bot==21.10)
├── .gitignore          # Git 忽略规则
├── LICENSE             # MIT 许可证
└── README.md           # 本文档
```

## 📄 许可证

[MIT License](LICENSE) — 自由使用、修改和分发。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 🌐 社区

本项目受到 [LINUX DO](https://linux.do) 社区的支持与推广。
