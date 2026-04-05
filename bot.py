"""
私聊中转机器人 v2.0
功能：验证通过后转发消息（支持文字/表情包/图片/文件/视频/语音等）
新增：数据持久化、封禁管理、防刷屏、离开模式、统计、帮助菜单
优化：支持 Webhook 模式，适配低 CPU 主机
"""
import asyncio
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

from config import BOT_TOKEN, OWNER_ID

# ──────────────────── 日志 ────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.WARNING,  # 降低日志级别，减少 CPU 开销
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # 只有我们自己的日志用 INFO

# ──────────────────── 数据持久化 ────────────────────
DATA_FILE = "data.json"

def load_data():
    """从 JSON 文件加载持久化数据（验证用户、封禁列表、统计等）。"""
    default = {
        "verified_users": [],
        "banned_users": [],
        "user_info": {},      # user_id -> {name, username, first_seen, msg_count}
        "away_mode": False,
        "away_message": "主人暂时不在，看到后会回复你的 ✨",
        "total_forwarded": 0,
    }
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并默认值（防止旧版数据缺少新字段）
            for k, v in default.items():
                if k not in saved:
                    saved[k] = v
            return saved
        except Exception as e:
            logger.warning(f"数据文件读取失败，使用默认值: {e}")
    return default

# ──────────────────── 延迟保存（减少磁盘写入） ────────────────────
_save_pending = False
_save_task = None

def save_data():
    """延迟保存数据，合并短时间内的多次写入，减少 CPU 和 IO 开销。"""
    global _save_pending, _save_task
    _save_pending = True
    if _save_task is None or _save_task.done():
        try:
            loop = asyncio.get_running_loop()
            _save_task = loop.create_task(_deferred_save())
        except RuntimeError:
            # 没有事件循环时直接保存
            _do_save()

async def _deferred_save():
    """等待 5 秒后再保存，合并多次写入。"""
    global _save_pending
    await asyncio.sleep(5)
    if _save_pending:
        _do_save()
        _save_pending = False

def _do_save():
    """实际写入磁盘。"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"数据保存失败: {e}")

def force_save():
    """强制立即保存（用于关机前）。"""
    global _save_pending
    if _save_pending:
        _do_save()
        _save_pending = False

data = load_data()
verified_users = set(data["verified_users"])
banned_users = set(data["banned_users"])
pending_users = {}  # user_id: {"answer": str}

# ──────────────────── 防刷屏 ────────────────────
user_last_msg_time = {}  # user_id -> last timestamp
RATE_LIMIT_SECONDS = 3   # 同一用户最少间隔秒数

def is_rate_limited(user_id: int) -> bool:
    """检查用户是否发送过于频繁。"""
    now = time.time()
    last = user_last_msg_time.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    user_last_msg_time[user_id] = now
    return False

# ──────────────────── 用户信息记录 ────────────────────
def record_user(user) -> str:
    """记录用户信息，返回格式化显示名。"""
    uid = str(user.id)
    name = user.first_name or "未知"
    username = user.username or ""
    display = f"{name} (@{username})" if username else name

    if uid not in data["user_info"]:
        data["user_info"][uid] = {
            "name": name,
            "username": username,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "msg_count": 0,
        }
    else:
        data["user_info"][uid]["name"] = name
        data["user_info"][uid]["username"] = username

    data["user_info"][uid]["msg_count"] += 1
    save_data()
    return display

# ──────────────────── Captcha ────────────────────
CAPTCHAS = [
    ("请点击 🐶", "🐶"), ("请点击 🐱", "🐱"), ("请点击 🐼", "🐼"),
    ("请点击 🦊", "🦊"), ("请点击 🐸", "🐸"), ("请点击 🦁", "🦁"),
    ("请点击 🐨", "🐨"), ("请点击 🐯", "🐯"), ("请点击 🐰", "🐰"),
]

def generate_captcha():
    q, a = random.choice(CAPTCHAS)
    all_emojis = [c[1] for c in CAPTCHAS]
    # 随机选 6 个（含正确答案）
    pool = [e for e in all_emojis if e != a]
    random.shuffle(pool)
    options = pool[:5] + [a]
    random.shuffle(options)
    buttons = [InlineKeyboardButton(e, callback_data=f"verify:{e}") for e in options]
    # 两行排列，更美观
    keyboard = InlineKeyboardMarkup([buttons[:3], buttons[3:]])
    return q, a, keyboard


# ══════════════════════════════════════════════════
#                    命令处理
# ══════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id == OWNER_ID:
        await update.message.reply_text(
            "👑 *管理员模式*\n\n"
            "直接回复转发消息即可回复用户\n"
            "输入 /help 查看所有命令",
            parse_mode="Markdown",
        )
        return

    if user_id in banned_users:
        await update.message.reply_text("🚫 你已被禁止使用此机器人。")
        return

    if user_id in verified_users:
        await update.message.reply_text("✅ 你已通过验证，直接发消息即可转达给主人。")
    else:
        q, answer, keyboard = generate_captcha()
        pending_users[user_id] = {"answer": answer}
        await update.message.reply_text(
            f"🤖 你想联系主人，请先完成验证：\n\n{q}",
            reply_markup=keyboard,
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id == OWNER_ID:
        text = (
            "👑 *管理员命令*\n\n"
            "💬 *回复用户* — 直接回复转发消息\n"
            "━━━━━━━━━━━━━━━━\n"
            "/ban `用户ID` — 封禁用户\n"
            "/unban `用户ID` — 解封用户\n"
            "/banlist — 查看封禁列表\n"
            "━━━━━━━━━━━━━━━━\n"
            "/list — 查看联系过的用户\n"
            "/stats — 查看运行统计\n"
            "━━━━━━━━━━━━━━━━\n"
            "/away — 切换离开模式\n"
            "/setaway `消息内容` — 设置离开自动回复\n"
            "━━━━━━━━━━━━━━━━\n"
            "/broadcast `消息` — 群发给所有已验证用户\n"
            "/help — 显示此帮助"
        )
    else:
        text = (
            "📮 *私聊中转机器人*\n\n"
            "通过这个机器人，你可以匿名联系主人。\n\n"
            "1️⃣ 发送 /start 开始验证\n"
            "2️⃣ 完成验证后直接发消息\n"
            "3️⃣ 支持文字、图片、视频、文件、语音等\n"
            "4️⃣ 主人回复后你会收到通知"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("用法: /ban 用户ID")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 用户 ID 必须是数字")
        return

    banned_users.add(target)
    verified_users.discard(target)
    data["banned_users"] = list(banned_users)
    data["verified_users"] = list(verified_users)
    save_data()

    info = data["user_info"].get(str(target), {})
    name = info.get("name", "未知")
    await update.message.reply_text(f"🚫 已封禁用户: {name} (ID: {target})")

    # 通知被封禁的用户
    try:
        await context.bot.send_message(target, "🚫 你已被管理员禁止使用此机器人。")
    except Exception:
        pass


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("用法: /unban 用户ID")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 用户 ID 必须是数字")
        return

    banned_users.discard(target)
    data["banned_users"] = list(banned_users)
    save_data()

    info = data["user_info"].get(str(target), {})
    name = info.get("name", "未知")
    await update.message.reply_text(f"✅ 已解封用户: {name} (ID: {target})")


async def cmd_banlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not banned_users:
        await update.message.reply_text("📋 封禁列表为空")
        return

    lines = ["🚫 *封禁列表*\n"]
    for uid in banned_users:
        info = data["user_info"].get(str(uid), {})
        name = info.get("name", "未知")
        username = info.get("username", "")
        tag = f" @{username}" if username else ""
        lines.append(f"• {name}{tag} — `{uid}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not data["user_info"]:
        await update.message.reply_text("📋 还没有用户联系过你")
        return

    # 按消息数排序
    sorted_users = sorted(
        data["user_info"].items(),
        key=lambda x: x[1].get("msg_count", 0),
        reverse=True,
    )

    lines = ["📋 *联系人列表*\n"]
    for uid, info in sorted_users[:20]:  # 最多显示 20 个
        name = info.get("name", "未知")
        username = info.get("username", "")
        tag = f" @{username}" if username else ""
        count = info.get("msg_count", 0)
        first = info.get("first_seen", "?")
        status = "🚫" if int(uid) in banned_users else "✅"
        lines.append(f"{status} {name}{tag}\n    ID: `{uid}` | 消息: {count} | 首次: {first}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    total_users = len(data["user_info"])
    total_verified = len(verified_users)
    total_banned = len(banned_users)
    total_msgs = data["total_forwarded"]
    away = "🟢 在线" if not data["away_mode"] else "🔴 离开"

    text = (
        "📊 *运行统计*\n\n"
        f"👥 总联系人数: {total_users}\n"
        f"✅ 已验证: {total_verified}\n"
        f"🚫 已封禁: {total_banned}\n"
        f"💬 总转发消息: {total_msgs}\n"
        f"📡 当前状态: {away}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    data["away_mode"] = not data["away_mode"]
    save_data()

    if data["away_mode"]:
        await update.message.reply_text(
            f"🔴 已开启离开模式\n\n自动回复: {data['away_message']}\n\n"
            "用 /setaway 修改自动回复内容",
        )
    else:
        await update.message.reply_text("🟢 已关闭离开模式，你回来啦！")


async def cmd_setaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text(f"用法: /setaway 消息内容\n\n当前: {data['away_message']}")
        return

    data["away_message"] = " ".join(context.args)
    save_data()
    await update.message.reply_text(f"✅ 离开自动回复已更新:\n{data['away_message']}")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("用法: /broadcast 消息内容")
        return

    text = "📢 *来自管理员的通知*\n\n" + " ".join(context.args)
    success, fail = 0, 0
    for uid in list(verified_users):
        try:
            await context.bot.send_message(uid, text, parse_mode="Markdown")
            success += 1
        except Exception:
            fail += 1

    await update.message.reply_text(f"📢 群发完成\n✅ 成功: {success}\n❌ 失败: {fail}")


# ══════════════════════════════════════════════════
#                   验证回调
# ══════════════════════════════════════════════════

async def handle_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data_str = query.data

    if not data_str.startswith("verify:"):
        return

    selected = data_str.split(":", 1)[1]

    if user_id not in pending_users:
        await query.edit_message_text("⏰ 验证已过期，请重新发送 /start")
        return

    if selected == pending_users[user_id]["answer"]:
        verified_users.add(user_id)
        del pending_users[user_id]
        data["verified_users"] = list(verified_users)
        save_data()
        await query.edit_message_text("✅ 验证通过！你的消息将转达给主人。主人回复后你会收到通知。")

        # 通知管理员
        user = query.from_user
        name = user.first_name or "未知"
        username = f" @{user.username}" if user.username else ""
        await context.bot.send_message(
            OWNER_ID,
            f"🆕 新用户通过验证: {name}{username}\nID: `{user_id}`",
            parse_mode="Markdown",
        )
    else:
        await query.answer("❌ 选择错误，请重试", show_alert=True)


# ══════════════════════════════════════════════════
#                 消息转发逻辑
# ══════════════════════════════════════════════════

async def forward_to_owner(context, user_id: int, display_name: str, message):
    """将用户消息转发给主人，支持各种消息类型。"""
    header = f"💬 来自 *{display_name}* 的消息：\n用户 ID: `{user_id}`\n"
    caption_suffix = f"\n\n💬 {display_name} | ID: {user_id}"
    msg = message

    try:
        if msg.text:
            await context.bot.send_message(OWNER_ID, f"{header}\n{msg.text}", parse_mode="Markdown")

        elif msg.sticker:
            await context.bot.send_message(OWNER_ID, header, parse_mode="Markdown")
            await context.bot.send_sticker(OWNER_ID, msg.sticker.file_id)

        elif msg.photo:
            photo = msg.photo[-1]
            cap = (msg.caption or "") + caption_suffix
            await context.bot.send_photo(OWNER_ID, photo.file_id, caption=cap)

        elif msg.video:
            cap = (msg.caption or "") + caption_suffix
            await context.bot.send_video(OWNER_ID, msg.video.file_id, caption=cap)

        elif msg.video_note:
            await context.bot.send_message(OWNER_ID, header, parse_mode="Markdown")
            await context.bot.send_video_note(OWNER_ID, msg.video_note.file_id)

        elif msg.voice:
            await context.bot.send_message(OWNER_ID, header, parse_mode="Markdown")
            await context.bot.send_voice(OWNER_ID, msg.voice.file_id)

        elif msg.audio:
            cap = (msg.caption or "") + caption_suffix
            await context.bot.send_audio(OWNER_ID, msg.audio.file_id, caption=cap)

        elif msg.document:
            cap = (msg.caption or "") + caption_suffix
            await context.bot.send_document(OWNER_ID, msg.document.file_id, caption=cap)

        elif msg.animation:
            cap = (msg.caption or "") + caption_suffix
            await context.bot.send_animation(OWNER_ID, msg.animation.file_id, caption=cap)

        elif msg.location:
            await context.bot.send_message(OWNER_ID, header, parse_mode="Markdown")
            await context.bot.send_location(OWNER_ID, msg.location.latitude, msg.location.longitude)

        elif msg.contact:
            await context.bot.send_message(OWNER_ID, header, parse_mode="Markdown")
            await context.bot.send_contact(
                OWNER_ID,
                phone_number=msg.contact.phone_number,
                first_name=msg.contact.first_name,
                last_name=msg.contact.last_name or "",
            )

        else:
            await context.bot.send_message(OWNER_ID, header, parse_mode="Markdown")
            await msg.forward(OWNER_ID)

        # 更新统计
        data["total_forwarded"] += 1
        save_data()

    except Exception as e:
        logger.error(f"转发消息失败 (user={user_id}): {e}")


async def reply_to_user(context, target_id: int, message):
    """将主人的回复原样转发给用户，支持各种消息类型。"""
    prefix = "💬 主人回复：\n"
    msg = message

    try:
        if msg.text:
            await context.bot.send_message(target_id, f"{prefix}{msg.text}")
        elif msg.sticker:
            await context.bot.send_sticker(target_id, msg.sticker.file_id)
        elif msg.photo:
            photo = msg.photo[-1]
            await context.bot.send_photo(target_id, photo.file_id, caption=msg.caption or "")
        elif msg.video:
            await context.bot.send_video(target_id, msg.video.file_id, caption=msg.caption or "")
        elif msg.video_note:
            await context.bot.send_video_note(target_id, msg.video_note.file_id)
        elif msg.voice:
            await context.bot.send_voice(target_id, msg.voice.file_id)
        elif msg.audio:
            await context.bot.send_audio(target_id, msg.audio.file_id, caption=msg.caption or "")
        elif msg.document:
            await context.bot.send_document(target_id, msg.document.file_id, caption=msg.caption or "")
        elif msg.animation:
            await context.bot.send_animation(target_id, msg.animation.file_id, caption=msg.caption or "")
        elif msg.location:
            await context.bot.send_location(target_id, msg.location.latitude, msg.location.longitude)
        else:
            await msg.forward(target_id)
        return True
    except Exception as e:
        logger.error(f"回复用户失败 (target={target_id}): {e}")
        return False


def extract_user_id_from_header(text: str):
    """从转发头部提取用户 ID。"""
    if not text:
        return None
    # 支持多种格式
    for marker in ["用户 ID:", "ID:"]:
        if marker in text:
            try:
                segment = text.split(marker)[1].split("\n")[0].strip()
                # 去掉 Markdown 格式的反引号
                segment = segment.strip("`")
                return int(segment)
            except (ValueError, IndexError):
                continue
    return None


# ══════════════════════════════════════════════════
#                 主消息处理
# ══════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message

    if not msg:
        return

    # 忽略命令
    if msg.text and msg.text.startswith("/"):
        return

    # ── 管理员逻辑 ──
    if user_id == OWNER_ID:
        if msg.reply_to_message:
            replied = msg.reply_to_message
            source_text = replied.text or replied.caption or ""
            target_id = extract_user_id_from_header(source_text)
            if target_id:
                ok = await reply_to_user(context, target_id, msg)
                if ok:
                    await msg.reply_text(f"✅ 已回复用户 `{target_id}`", parse_mode="Markdown")
                else:
                    await msg.reply_text("❌ 回复失败，用户可能已删除对话")
                return
        await msg.reply_text("💡 请回复某条转发消息来回复对应用户。\n输入 /help 查看更多命令。")
        return

    # ── 封禁用户 ──
    if user_id in banned_users:
        return  # 静默忽略

    # ── 防刷屏 ──
    if is_rate_limited(user_id):
        await msg.reply_text("⏳ 发送太频繁了，请稍等几秒...")
        return

    # ── 未验证用户 ──
    if user_id not in verified_users:
        q, answer, keyboard = generate_captcha()
        pending_users[user_id] = {"answer": answer}
        await msg.reply_text(
            f"🤖 请先完成验证：\n\n{q}",
            reply_markup=keyboard,
        )
        return

    # ── 已验证用户，转发给主人 ──
    display_name = record_user(update.effective_user)
    await forward_to_owner(context, user_id, display_name, msg)

    # 离开模式自动回复
    if data["away_mode"]:
        await msg.reply_text(f"✅ 已发送！\n\n🔴 {data['away_message']}")
    else:
        await msg.reply_text("✅ 已发送给主人，等待回复...")


# ══════════════════════════════════════════════════
#                   启动与初始化
# ══════════════════════════════════════════════════

async def post_init(application: Application):
    """启动时通知管理员，并设置命令菜单。"""
    # 设置 Bot 命令菜单
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "开始使用 / 验证"),
        BotCommand("help", "帮助信息"),
    ])

    verified_count = len(verified_users)
    banned_count = len(banned_users)
    away_status = "🔴 离开模式" if data["away_mode"] else "🟢 在线"

    await application.bot.send_message(
        OWNER_ID,
        f"🤖 *DM Gateway Bot v2.0 已启动！*\n\n"
        f"📡 状态: {away_status}\n"
        f"✅ 已验证用户: {verified_count}\n"
        f"🚫 已封禁用户: {banned_count}\n"
        f"💬 历史转发: {data['total_forwarded']}",
        parse_mode="Markdown",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """全局错误处理。"""
    logger.error(f"发生异常: {context.error}", exc_info=context.error)


def setup_handlers(app: Application):
    """注册所有处理器。"""
    # 命令处理
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("banlist", cmd_banlist))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("away", cmd_away))
    app.add_handler(CommandHandler("setaway", cmd_setaway))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # 验证回调
    app.add_handler(CallbackQueryHandler(handle_verify_callback))

    # 消息处理（放最后，优先级最低）
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    # 错误处理
    app.add_error_handler(error_handler)


def main():
    if not BOT_TOKEN or not OWNER_ID:
        logger.error("请在 config.py 中设置 BOT_TOKEN 和 OWNER_ID")
        return

    # 读取环境变量配置
    webhook_url = os.environ.get("WEBHOOK_URL", "")  # 例如 https://your-domain.com/webhook
    port = int(os.environ.get("PORT", "8443"))
    mode = os.environ.get("BOT_MODE", "polling")  # 'webhook' 或 'polling'

    # 优化连接池大小，减少资源占用
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(False)  # 串行处理，降低 CPU 峰值
        .build()
    )

    setup_handlers(app)

    # 关机时保存数据
    import atexit
    atexit.register(force_save)

    if mode == "webhook" and webhook_url:
        # ── Webhook 模式（推荐：0 空转 CPU）──
        logger.info(f"Bot v2.0 starting in WEBHOOK mode on port {port}...")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=f"{webhook_url}/webhook",
            drop_pending_updates=True,
        )
    else:
        # ── Polling 模式（降低频率）──
        logger.info("Bot v2.0 starting in POLLING mode (low CPU)...")
        app.run_polling(
            drop_pending_updates=True,
            poll_interval=2.0,       # 每 2 秒轮询一次（默认 0 秒，非常耗 CPU）
            timeout=30,              # 长轮询超时 30 秒
        )


if __name__ == "__main__":
    main()
