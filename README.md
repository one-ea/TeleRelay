<p align="center">
  <h1 align="center">📮 TeleRelay</h1>
  <p align="center">一个轻量、安全的 Telegram 私聊中转机器人</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/python--telegram--bot-21.x-blue?logo=telegram&logoColor=white" alt="PTB">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/CPU-0.15+-orange" alt="Low CPU">
  </p>
</p>

---

## ✨ 功能特性

- 🔒 **验证码防护** — Emoji 点击验证，拦截机器人骚扰
- 💬 **全类型消息转发** — 文字、图片、视频、语音、文件、贴纸、GIF、位置、联系人
- 🚫 **封禁管理** — 一键封禁 / 解封骚扰用户
- 🛡️ **防刷屏** — 每用户限速，防止消息轰炸
- 🔴 **离开模式** — 不在时自动告知来访者
- 📢 **群发广播** — 向所有已验证用户发送通知
- 📊 **数据统计** — 追踪联系人数量和消息总量
- 💾 **数据持久化** — JSON 原子写入，重启不丢数据
- ⚡ **低 CPU 优化** — 适配 0.15 CPU 免费主机，长轮询 + 延迟保存
- 🌐 **多种部署方式** — 支持 Polling / Webhook 模式
- 🔧 **灵活配置** — 支持 config.py 文件 + 环境变量

## 📋 命令列表

### 所有用户
| 命令 | 说明 |
|---|---|
| `/start` | 开始使用 / 触发验证 |
| `/help` | 查看帮助信息 |

### 管理员专用
| 命令 | 说明 |
|---|---|
| `/ban <用户ID>` | 封禁用户 |
| `/unban <用户ID>` | 解封用户 |
| `/banlist` | 查看封禁列表 |
| `/list` | 查看联系人列表 |
| `/stats` | 运行统计数据 |
| `/away` | 切换离开模式 |
| `/setaway <消息>` | 设置离开自动回复 |
| `/broadcast <消息>` | 群发通知 |

## 🚀 快速部署

### 1. 获取 Bot Token

在 Telegram 中找到 [@BotFather](https://t.me/BotFather)，发送 `/newbot` 创建机器人并获取 Token。

### 2. 获取你的用户 ID

在 Telegram 中找到 [@userinfobot](https://t.me/userinfobot)，发送任意消息即可获取你的数字 ID。

### 3. 克隆项目

```bash
git clone https://github.com/one-ea/TeleRelay.git
cd TeleRelay
```

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 配置

**方式一：配置文件**

```bash
cp config.example.py config.py
```

编辑 `config.py`：

```python
BOT_TOKEN = "你的Bot Token"
OWNER_ID = 你的用户ID
```

**方式二：环境变量**（推荐用于云平台）

```bash
export BOT_TOKEN="你的Bot Token"
export OWNER_ID=你的用户ID
```

### 6. 启动

```bash
python bot.py
```

## 🌐 部署指南

<details>
<summary><b>Lunes / Pterodactyl 面板</b></summary>

1. 创建 Python 类型服务器
2. 上传所有项目文件
3. 在面板编辑 `config.py` 填入 Token 和 ID
4. **Startup 设置启动命令**：`bash start.sh`
5. 启动服务器

> ⚠️ 注意：不要使用 `&&` 连接命令，Pterodactyl 不支持。使用 `start.sh` 脚本替代。

</details>

<details>
<summary><b>Railway / Render</b></summary>

1. Fork 本仓库
2. 在平台新建项目，连接 GitHub 仓库
3. 设置环境变量 `BOT_TOKEN` 和 `OWNER_ID`
4. 部署即可（Bot 会自动读取环境变量）

</details>

<details>
<summary><b>VPS / 服务器</b></summary>

```bash
# 使用 screen 保持后台运行
screen -S telerelay
python bot.py
# Ctrl+A, D 分离会话
```

</details>

## ⚙️ 高级配置

通过环境变量自定义运行参数：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `BOT_TOKEN` | — | Bot Token（必填） |
| `OWNER_ID` | — | 管理员用户 ID（必填） |
| `BOT_MODE` | `polling` | 运行模式：`polling` / `webhook` |
| `WEBHOOK_URL` | — | Webhook 域名（webhook 模式必填） |
| `PORT` | `8443` | Webhook 监听端口 |
| `DATA_FILE` | `data.json` | 数据文件路径 |

## 📁 项目结构

```
TeleRelay/
├── bot.py                # 主程序
├── config.py             # 配置文件（不上传到 Git）
├── config.example.py     # 配置示例
├── requirements.txt      # Python 依赖
├── start.sh              # 启动脚本（Pterodactyl 兼容）
├── LICENSE               # MIT 许可证
├── README.md             # 项目说明
├── .gitignore            # Git 忽略规则
└── data.json             # 运行时数据（自动生成，不上传）
```

## 📄 开源许可

本项目采用 [MIT 许可证](LICENSE) 开源。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
