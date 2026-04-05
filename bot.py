"""
TeleRelay — 私聊中转机器人 v2.1
功能：验证通过后转发消息（支持文字/表情包/图片/文件/视频/语音等）
特性：数据持久化、封禁管理、防刷屏、离开模式、统计、帮助菜单
优化：低 CPU 适配、延迟保存、环境变量配置、Webhook 支持
"""
import asyncio
import atexit
import json
import logging
import os
import random
import time
from datetime import datetime

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ──────────────────── 配置 ────────────────────
# 优先使用环境变量，其次使用 config.py
try:
    from config import BOT_TOKEN, OWNER_ID
except ImportError:
    BOT_TOKEN = ""
    OWNER_ID = 0

BOT_TOKEN = os.environ.get("BOT_TOKEN", BOT_TOKEN)
OWNER_ID = int(os.environ.get("OWNER_ID", OWNER_ID))

# ──────────────────── 日志 ────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.WARNING,
)
logger = logging.getLogger("TeleRelay")
logger.setLevel(logging.INFO)

# ──────────────────── 常量 ────────────────────
VERSION = "2.1"
DATA_FILE = os.environ.get("DATA_FILE", "data.json")
RATE_LIMIT_SECONDS = 3

# ──────────────────── 数据持久化 ────────────────────
_DEFAULT_DATA = {
    "verified_users": [],
    "banned_users": [],
    "user_info": {},
    "away_mode": False,
    "away_message": "主人暂时不在，看到后会回复你的 ✨",
    "total_forwarded": 0,
}


def load_data() -> dict:
    """从 JSON 文件加载持久化数据。"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in _DEFAULT_DATA.items():
                saved.setdefault(k, v)
            return saved
        except Exception as e:
            logger.warning(f"数据文件读取失败，使用默认值: {e}")
    return _DEFAULT_DATA.copy()


# ──────────────── 延迟保存（减少 IO） ────────────────
_save_pending = False
_save_task = None


def save_data():
    """延迟 5 秒保存，合并多次写入。"""
    global _save_pending, _save_task
    _save_pending = True
    if _save_task is None or _save_task.done():
        try:
            _save_task = asyncio.get_running_loop().create_task(_deferred_save())
        except RuntimeError:
            _do_save()


async def _deferred_save():
    global _save_pending
    await asyncio.sleep(5)
    if _save_pending:
        _do_save()
        _save_pending = False


def _do_save():
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)  # 原子写入，防止损坏
    except Exception as e:
        logger.error(f"数据保存失败: {e}")


def force_save():
    """立即保存（关机前调用）。"""
    global _save_pending
    if _save_pending:
        _do_save()
        _save_pending = False


# 加载全局数据
data = load_data()
verified_users: set[int] = set(data["verified_users"])
banned_users: set[int] = set(data["banned_users"])
pending_users: dict[int, dict] = {}

# ──────────────────── 防刷屏 ────────────────────
_user_last_msg: dict[int, float] = {}


def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    if now - _user_last_msg.get(user_id, 0) < RATE_LIMIT_SECONDS:
        return True
    _user_last_msg[user_id] = now
    return False


# ──────────────────── 用户信息 ────────────────────
def record_user(user) -> str:
    """记录用户信息，返回显示名。"""
    uid = str(user.id)
    name = user.first_name or "未知"
    username = user.username or ""
    display = f"{name} (@{username})" if username else name

    info = data["user_info"].get(uid)
    if info is None:
        data["user_info"][uid] = {
            "name": name,
            "username": username,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "msg_count": 1,
        }
    else:
        info["name"] = name
        info["username"] = username
        info["msg_count"] = info.get("msg_count", 0) + 1

    save_data()
    return display


# ──────────────────── 验证码 ────────────────────
_CAPTCHA_EMOJIS = ["🐶", "🐱", "🐼", "🦊", "🐸", "🦁", "🐨", "🐯", "🐰"]


def generate_captcha():
    answer = random.choice(_CAPTCHA_EMOJIS)
    pool = [e for e in _CAPTCHA_EMOJIS if e != answer]
    random.shuffle(pool)
    options = pool[:5] + [answer]
    random.shuffle(options)
    buttons = [InlineKeyboardButton(e, callback_data=f"v:{e}") for e in options]
    keyboard = InlineKeyboardMarkup([buttons[:3], buttons[3:]])
    return f"请点击 {answer}", answer, keyboard


# ══════════════════════════════════════════════════
#                    命令处理
# ══════════════════════════════════════════════════

def _owner_only(func):
    """管理员权限装饰器。"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            return
        return await func(update, context)
    return wrapper


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
    if update.effective_user.id == OWNER_ID:
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
            "通过这个机器人，你可以联系主人。\n\n"
            "1️⃣ 发送 /start 开始验证\n"
            "2️⃣ 完成验证后直接发消息\n"
            "3️⃣ 支持文字、图片、视频、文件、语音等\n"
            "4️⃣ 主人回复后你会收到通知"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


@_owner_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    name = data["user_info"].get(str(target), {}).get("name", "未知")
    await update.message.reply_text(f"🚫 已封禁用户: {name} (ID: {target})")

    try:
        await context.bot.send_message(target, "🚫 你已被管理员禁止使用此机器人。")
    except Exception:
        pass


@_owner_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    name = data["user_info"].get(str(target), {}).get("name", "未知")
    await update.message.reply_text(f"✅ 已解封用户: {name} (ID: {target})")


@_owner_only
async def cmd_banlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


@_owner_only
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not data["user_info"]:
        await update.message.reply_text("📋 还没有用户联系过你")
        return

    sorted_users = sorted(
        data["user_info"].items(),
        key=lambda x: x[1].get("msg_count", 0),
        reverse=True,
    )

    lines = ["📋 *联系人列表*\n"]
    for uid, info in sorted_users[:20]:
        name = info.get("name", "未知")
        username = info.get("username", "")
        tag = f" @{username}" if username else ""
        count = info.get("msg_count", 0)
        first = info.get("first_seen", "?")
        status = "🚫" if int(uid) in banned_users else "✅"
        lines.append(f"{status} {name}{tag}\n    ID: `{uid}` | 消息: {count} | 首次: {first}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@_owner_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    away = "🟢 在线" if not data["away_mode"] else "🔴 离开"
    text = (
        f"📊 *运行统计 — v{VERSION}*\n\n"
        f"👥 总联系人数: {len(data['user_info'])}\n"
        f"✅ 已验证: {len(verified_users)}\n"
        f"🚫 已封禁: {len(banned_users)}\n"
        f"💬 总转发消息: {data['total_forwarded']}\n"
        f"📡 当前状态: {away}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@_owner_only
async def cmd_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data["away_mode"] = not data["away_mode"]
    save_data()

    if data["away_mode"]:
        await update.message.reply_text(
            f"🔴 已开启离开模式\n\n自动回复: {data['away_message']}\n\n"
            "用 /setaway 修改自动回复内容",
        )
    else:
        await update.message.reply_text("🟢 已关闭离开模式，你回来啦！")


@_owner_only
async def cmd_setaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(f"用法: /setaway 消息内容\n\n当前: {data['away_message']}")
        return
    data["away_message"] = " ".join(context.args)
    save_data()
    await update.message.reply_text(f"✅ 离开自动回复已更新:\n{data['away_message']}")


@_owner_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法: /broadcast 消息内容")
        return

    text = "📢 *来自管理员的通知*\n\n" + " ".join(context.args)
    success = fail = 0
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

    if not query.data or not query.data.startswith("v:"):
        return

    selected = query.data[2:]

    if user_id not in pending_users:
        await query.edit_message_text("⏰ 验证已过期，请重新发送 /start")
        return

    if selected == pending_users[user_id]["answer"]:
        verified_users.add(user_id)
        pending_users.pop(user_id, None)
        data["verified_users"] = list(verified_users)
        save_data()
        await query.edit_message_text("✅ 验证通过！你的消息将转达给主人。主人回复后你会收到通知。")

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

async def _forward_media(bot, chat_id, msg, header, caption_suffix):
    """统一处理不同类型消息的转发。"""
    if msg.text:
        await bot.send_message(chat_id, f"{header}\n{msg.text}", parse_mode="Markdown")
    elif msg.sticker:
        await bot.send_message(chat_id, header, parse_mode="Markdown")
        await bot.send_sticker(chat_id, msg.sticker.file_id)
    elif msg.photo:
        cap = (msg.caption or "") + caption_suffix
        await bot.send_photo(chat_id, msg.photo[-1].file_id, caption=cap)
    elif msg.video:
        cap = (msg.caption or "") + caption_suffix
        await bot.send_video(chat_id, msg.video.file_id, caption=cap)
    elif msg.video_note:
        await bot.send_message(chat_id, header, parse_mode="Markdown")
        await bot.send_video_note(chat_id, msg.video_note.file_id)
    elif msg.voice:
        await bot.send_message(chat_id, header, parse_mode="Markdown")
        await bot.send_voice(chat_id, msg.voice.file_id)
    elif msg.audio:
        cap = (msg.caption or "") + caption_suffix
        await bot.send_audio(chat_id, msg.audio.file_id, caption=cap)
    elif msg.document:
        cap = (msg.caption or "") + caption_suffix
        await bot.send_document(chat_id, msg.document.file_id, caption=cap)
    elif msg.animation:
        cap = (msg.caption or "") + caption_suffix
        await bot.send_animation(chat_id, msg.animation.file_id, caption=cap)
    elif msg.location:
        await bot.send_message(chat_id, header, parse_mode="Markdown")
        await bot.send_location(chat_id, msg.location.latitude, msg.location.longitude)
    elif msg.contact:
        await bot.send_message(chat_id, header, parse_mode="Markdown")
        await bot.send_contact(
            chat_id,
            phone_number=msg.contact.phone_number,
            first_name=msg.contact.first_name,
            last_name=msg.contact.last_name or "",
        )
    else:
        await bot.send_message(chat_id, header, parse_mode="Markdown")
        await msg.forward(chat_id)


async def forward_to_owner(context, user_id: int, display_name: str, message):
    """将用户消息转发给主人。"""
    header = f"💬 来自 *{display_name}* 的消息：\n用户 ID: `{user_id}`\n"
    suffix = f"\n\n💬 {display_name} | ID: {user_id}"

    try:
        await _forward_media(context.bot, OWNER_ID, message, header, suffix)
        data["total_forwarded"] += 1
        save_data()
    except Exception as e:
        logger.error(f"转发消息失败 (user={user_id}): {e}")


async def reply_to_user(context, target_id: int, message):
    """将主人的回复原样转发给用户。"""
    try:
        if message.text:
            await context.bot.send_message(target_id, f"💬 主人回复：\n{message.text}")
        elif message.sticker:
            await context.bot.send_sticker(target_id, message.sticker.file_id)
        else:
            await _forward_media(context.bot, target_id, message, "", "")
        return True
    except Exception as e:
        logger.error(f"回复用户失败 (target={target_id}): {e}")
        return False


def extract_user_id(text: str) -> int | None:
    """从转发消息文本中提取用户 ID。"""
    if not text:
        return None
    for marker in ("用户 ID:", "ID:"):
        if marker in text:
            try:
                segment = text.split(marker)[1].split("\n")[0].strip().strip("`")
                return int(segment)
            except (ValueError, IndexError):
                continue
    return None


# ══════════════════════════════════════════════════
#                 主消息处理
# ══════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user_id = update.effective_user.id

    # 忽略命令
    if msg.text and msg.text.startswith("/"):
        return

    # ── 管理员逻辑 ──
    if user_id == OWNER_ID:
        if msg.reply_to_message:
            source_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
            target_id = extract_user_id(source_text)
            if target_id:
                ok = await reply_to_user(context, target_id, msg)
                emoji = "✅" if ok else "❌"
                text = f"{emoji} {'已回复' if ok else '回复失败'} `{target_id}`"
                await msg.reply_text(text, parse_mode="Markdown")
                return
        await msg.reply_text("💡 请回复某条转发消息来回复对应用户。\n输入 /help 查看更多命令。")
        return

    # ── 封禁用户 ──
    if user_id in banned_users:
        return

    # ── 防刷屏 ──
    if is_rate_limited(user_id):
        await msg.reply_text("⏳ 发送太频繁了，请稍等几秒...")
        return

    # ── 未验证用户 ──
    if user_id not in verified_users:
        q, answer, keyboard = generate_captcha()
        pending_users[user_id] = {"answer": answer}
        await msg.reply_text(f"🤖 请先完成验证：\n\n{q}", reply_markup=keyboard)
        return

    # ── 已验证用户，转发给主人 ──
    display_name = record_user(update.effective_user)
    await forward_to_owner(context, user_id, display_name, msg)

    if data["away_mode"]:
        await msg.reply_text(f"✅ 已发送！\n\n🔴 {data['away_message']}")
    else:
        await msg.reply_text("✅ 已发送给主人，等待回复...")


# ══════════════════════════════════════════════════
#                   启动与初始化
# ══════════════════════════════════════════════════

async def post_init(application: Application):
    """启动时设置命令菜单并通知管理员。"""
    await application.bot.set_my_commands([
        BotCommand("start", "开始使用 / 验证"),
        BotCommand("help", "帮助信息"),
    ])

    away_status = "🔴 离开模式" if data["away_mode"] else "🟢 在线"
    await application.bot.send_message(
        OWNER_ID,
        f"🤖 *TeleRelay v{VERSION} 已启动！*\n\n"
        f"📡 状态: {away_status}\n"
        f"✅ 已验证用户: {len(verified_users)}\n"
        f"🚫 已封禁用户: {len(banned_users)}\n"
        f"💬 历史转发: {data['total_forwarded']}",
        parse_mode="Markdown",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"异常: {context.error}", exc_info=context.error)


def main():
    if not BOT_TOKEN or not OWNER_ID:
        print("❌ 请设置 BOT_TOKEN 和 OWNER_ID")
        print("   方式 1: 编辑 config.py")
        print("   方式 2: 设置环境变量 BOT_TOKEN 和 OWNER_ID")
        return

    # 读取运行模式
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    port = int(os.environ.get("PORT", "8443"))
    mode = os.environ.get("BOT_MODE", "polling")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(False)
        .build()
    )

    # 注册处理器
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
    app.add_handler(CallbackQueryHandler(handle_verify_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_error_handler(error_handler)

    # 关机保护
    atexit.register(force_save)

    if mode == "webhook" and webhook_url:
        logger.info(f"TeleRelay v{VERSION} — Webhook 模式 (port {port})")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=f"{webhook_url}/webhook",
            drop_pending_updates=True,
        )
    else:
        logger.info(f"TeleRelay v{VERSION} — Polling 模式 (低 CPU)")
        app.run_polling(
            drop_pending_updates=True,
            poll_interval=5.0,
            timeout=60,
            read_timeout=60,
            write_timeout=10,
            connect_timeout=10,
            pool_timeout=10,
        )


if __name__ == "__main__":
    main()
