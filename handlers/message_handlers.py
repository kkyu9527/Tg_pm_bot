import os
import json
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import (
    Update, Message, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter
from database.db_operations import UserOperations, TopicOperations, MessageOperations
from utils.logger import setup_logger

load_dotenv()
GROUP_ID = os.getenv("GROUP_ID")
USER_ID = os.getenv("USER_ID")
logger = setup_logger('messages', 'logs/messages.log')


def encode_callback(action, message_id, user_id, compact=False):
    data = {
        ("a" if compact else "action"): action,
        ("m" if compact else "message_id"): message_id,
        ("u" if compact else "user_id"): user_id
    }
    return json.dumps(data, separators=(',', ':') if compact else None)


def decode_callback(data):
    obj = json.loads(data)
    return {
        "action": obj.get("action") or obj.get("a"),
        "message_id": obj.get("message_id") or obj.get("m"),
        "user_id": obj.get("user_id") or obj.get("u")
    }


class MessageHandlers:
    ACTION_EDIT = "edit"
    ACTION_DELETE = "delete"
    ACTION_CANCEL_EDIT = "cancel_edit"

    TEXT_EDIT_PROMPT = "✏️ 请发送新的消息内容，将替换之前的消息"
    TEXT_EDIT_DONE = "✏️ 编辑完成"
    TEXT_EDIT_CANCELLED = "❎ 已取消编辑"
    TEXT_MSG_DELETED = "✅ 消息已删除"
    TEXT_MSG_UPDATED = "✅ 已更新用户消息"
    TEXT_MSG_RESENT = "✅ 已重新发送消息"

    edit_states = {}
    media_group_cache = {}

    @staticmethod
    def build_cancel_edit_keyboard(message_id, user_id):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("取消编辑", callback_data=encode_callback(
                MessageHandlers.ACTION_CANCEL_EDIT, message_id, user_id, compact=True))
        ]])

    @staticmethod
    def build_action_keyboard(message_id, user_id):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("编辑", callback_data=encode_callback(MessageHandlers.ACTION_EDIT, message_id, user_id)),
            InlineKeyboardButton("删除", callback_data=encode_callback(MessageHandlers.ACTION_DELETE, message_id, user_id))
        ]])

    @staticmethod
    def build_edit_done_keyboard():
        return InlineKeyboardMarkup([])

    @staticmethod
    def _cleanup_edit_states():
        now = datetime.utcnow()
        timeout = timedelta(minutes=5)
        MessageHandlers.edit_states = {
            uid: state for uid, state in MessageHandlers.edit_states.items()
            if now - state['timestamp'] <= timeout
        }

    @staticmethod
    async def _forward_content(message: Message, bot, chat_id: int, thread_id: int = None):
        kwargs = {"chat_id": chat_id, "from_chat_id": message.chat_id, "message_id": message.message_id}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        for attempt in range(2):
            try:
                return await bot.copy_message(**kwargs)
            except Exception as e:
                logger.error(f"消息转发失败: {e}")
                if attempt == 0:
                    await asyncio.sleep(1)
        return None

    @staticmethod
    async def _flush_media_group_after_delay(key, user, topic_id, context):
        await asyncio.sleep(2.0)
        messages = MessageHandlers.media_group_cache.pop(key, [])
        if not messages:
            return
        bot = context.bot
        media_group = []
        for m in sorted(messages, key=lambda x: x.message_id):
            if m.photo:
                media_group.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=m.caption or None))
            elif m.video:
                media_group.append(InputMediaVideo(media=m.video.file_id, caption=m.caption or None))

        try:
            sent_group = await bot.send_media_group(chat_id=GROUP_ID, message_thread_id=topic_id, media=media_group)
            MessageOperations().save_message(
                user.id, topic_id, messages[0].message_id, sent_group[0].message_id, "user_to_owner"
            )
        except RetryAfter as e:
            logger.warning(f"限流：等待 {e.retry_after} 秒")
            await asyncio.sleep(e.retry_after + 1)
            return await MessageHandlers._flush_media_group_after_delay(key, user, topic_id, context)
        except Exception as e:
            logger.error(f"媒体组转发失败: {e}")

    @staticmethod
    async def _ensure_topic(bot, user, topic_ops):
        topic = topic_ops.get_user_topic(user.id)
        if topic:
            return topic["topic_id"]

        topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
        username = f"@{user.username}" if user.username else "无用户名"
        topic_id = (await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name)).message_thread_id
        topic_ops.save_topic(user.id, topic_id, topic_name)

        info_text = (
            f"👤 <b>新用户开始对话</b>\n"
            f"╭ 姓名: {user.first_name} {user.last_name or ''}\n"
            f"├ 用户名: {username}\n"
            f"├ 用户ID: <code>{user.id}</code>\n"
            f"├ 语言代码: {user.language_code or '未知'}\n"
            f"╰ Premium 用户: {'✅' if getattr(user, 'is_premium', False) else '❌'}\n"
        )

        try:
            photos = await bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                sent_msg = await bot.send_photo(GROUP_ID, photo=photos.photos[0][-1].file_id,
                                                message_thread_id=topic_id, caption=info_text, parse_mode="HTML")
            else:
                raise Exception("无头像")
        except Exception:
            sent_msg = await bot.send_message(GROUP_ID, text=info_text, message_thread_id=topic_id, parse_mode="HTML")

        try:
            await bot.pin_chat_message(chat_id=GROUP_ID, message_id=sent_msg.message_id)
        except Exception as e:
            logger.warning(f"置顶失败: {e}")

        return topic_id

    @staticmethod
    async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private" or str(update.effective_user.id) == USER_ID:
            return

        user = update.effective_user
        message = update.effective_message
        bot = context.bot

        UserOperations().save_user(user.id, user.first_name, user.last_name, user.username)
        topic_id = await MessageHandlers._ensure_topic(bot, user, TopicOperations())

        if message.media_group_id and (message.photo or message.video):
            key = f"{user.id}:{message.media_group_id}"
            MessageHandlers.media_group_cache.setdefault(key, []).append(message)
            if len(MessageHandlers.media_group_cache[key]) == 1:
                asyncio.create_task(MessageHandlers._flush_media_group_after_delay(key, user, topic_id, context))
            return

        try:
            forwarded = await MessageHandlers._forward_content(message, bot, GROUP_ID, topic_id)
            if not forwarded:
                return
            MessageOperations().save_message(user.id, topic_id, message.message_id,
                                             forwarded.message_id, "user_to_owner")
        except BadRequest as e:
            if "Message thread not found" in str(e):
                TopicOperations().delete_topic(topic_id)
                topic_id = await MessageHandlers._ensure_topic(bot, user, TopicOperations())
                forwarded = await MessageHandlers._forward_content(message, bot, GROUP_ID, topic_id)
                if not forwarded:
                    return
                MessageOperations().save_message(user.id, topic_id, message.message_id,
                                                 forwarded.message_id, "user_to_owner")
            else:
                logger.error(f"转发失败: {e}")

    @staticmethod
    async def handle_owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        MessageHandlers._cleanup_edit_states()
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return

        if update.effective_user.id in MessageHandlers.edit_states:
            state = MessageHandlers.edit_states.pop(update.effective_user.id)
            await MessageHandlers._edit_user_message(context.bot, update.effective_message, state)
            return

        message = update.effective_message
        if not message.is_topic_message:
            return

        topic = TopicOperations().get_topic_by_id(message.message_thread_id)
        if not topic:
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return

        user_id = topic["user_id"]
        try:
            forwarded = await MessageHandlers._forward_content(message, context.bot, user_id)
            if not forwarded:
                return
            MessageOperations().save_message(user_id, message.message_thread_id, forwarded.message_id,
                                             message.message_id, "owner_to_user")
            await message.reply_text("✅ 已转发给用户",
                                     reply_markup=MessageHandlers.build_action_keyboard(forwarded.message_id, user_id))
        except Exception as e:
            logger.error(f"转发失败: {e}")
            await message.reply_text(f"⚠️ 转发失败: {e}")

    @staticmethod
    async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        MessageHandlers._cleanup_edit_states()
        query = update.callback_query
        await query.answer()
        try:
            data = decode_callback(query.data)
        except Exception as e:
            logger.error(f"回调数据解析失败: {e}")
            return

        action = data["action"]
        message_id = data["message_id"]
        user_id = data["user_id"]

        if action == MessageHandlers.ACTION_DELETE:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
                await query.edit_message_text(MessageHandlers.TEXT_MSG_DELETED)
            except Exception as e:
                await query.edit_message_text(f"⚠️ 删除失败: {e}")
        elif action == MessageHandlers.ACTION_EDIT:
            MessageHandlers.edit_states[query.from_user.id] = {
                "message_id": message_id,
                "user_id": user_id,
                "original_message": query.message,
                "timestamp": datetime.utcnow()
            }
            await query.edit_message_text(
                MessageHandlers.TEXT_EDIT_PROMPT,
                reply_markup=MessageHandlers.build_cancel_edit_keyboard(message_id, user_id)
            )
        elif action == MessageHandlers.ACTION_CANCEL_EDIT:
            if query.from_user.id in MessageHandlers.edit_states:
                state = MessageHandlers.edit_states.pop(query.from_user.id)
                await query.edit_message_text(
                    MessageHandlers.TEXT_EDIT_CANCELLED,
                    reply_markup=MessageHandlers.build_action_keyboard(state["message_id"], state["user_id"])
                )

    @staticmethod
    async def _edit_user_message(bot, new_message, state):
        user_id = state["user_id"]
        old_id = state["message_id"]
        original_msg = state["original_message"]
        try:
            if new_message.text:
                await bot.edit_message_text(chat_id=user_id, message_id=old_id, text=new_message.text)
                reply_text = MessageHandlers.TEXT_MSG_UPDATED
                msg_id = old_id
            else:
                await bot.delete_message(chat_id=user_id, message_id=old_id)
                forwarded = await MessageHandlers._forward_content(new_message, bot, user_id)
                reply_text = MessageHandlers.TEXT_MSG_RESENT
                msg_id = forwarded.message_id

            # 编辑原来的“✏️ 请发送新的消息内容”提示，清除键盘
            try:
                if original_msg and original_msg.chat_id and original_msg.message_id:
                    await bot.edit_message_text(
                        chat_id=original_msg.chat_id,
                        message_id=original_msg.message_id,
                        text=MessageHandlers.TEXT_EDIT_DONE,
                        reply_markup=MessageHandlers.build_edit_done_keyboard()
                    )
            except Exception as e:
                logger.warning(f"无法清除原消息的键盘: {e}")

            await new_message.reply_text(reply_text, reply_markup=MessageHandlers.build_action_keyboard(msg_id, user_id))
            logger.info(f"已编辑用户 {user_id} 的消息")
        except Exception as e:
            logger.error(f"编辑失败: {e}")

    @staticmethod
    async def handle_owner_delete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return
        if not update.message.is_topic_message:
            return

        topic_id = update.effective_message.message_thread_id
        if not TopicOperations().get_topic_by_id(topic_id):
            await update.effective_message.reply_text("⚠️ 此话题在数据库中不存在")
            return

        try:
            await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception as e:
            logger.warning(f"Telegram 话题删除失败: {e}")
        try:
            topic = TopicOperations().get_topic_by_id(topic_id)
            if not topic:
                await update.effective_message.reply_text("⚠️ 数据库中未找到话题，跳过清理")
                return

            user_id = topic["user_id"]

            # 删除数据库中的话题和消息记录及用户记录
            TopicOperations().delete_topic(topic_id)
            logger.info(f"主人删除了话题 {topic_id} 以及相关数据库记录")
        except Exception as e:
            logger.error(f"从数据库中删除话题失败: {e}")