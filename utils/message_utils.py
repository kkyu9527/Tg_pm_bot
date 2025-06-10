import os
import json
import asyncio
from datetime import datetime, timedelta, UTC
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, Message
from telegram.error import RetryAfter
from dotenv import load_dotenv
from database.db_operations import MessageOperations
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


class MessageUtils:
    ACTION_EDIT = "edit"
    ACTION_DELETE = "delete"
    ACTION_CANCEL_EDIT = "cancel_edit"

    TEXT_EDIT_PROMPT = "✏️ 请发送新的消息内容，将替换之前的消息"
    TEXT_EDIT_DONE = "✏️ 编辑完成"
    TEXT_EDIT_CANCELLED = "❎ 已取消编辑"
    TEXT_MSG_DELETED = "✅ 消息已删除"
    TEXT_MSG_UPDATED = "✅ 已更新用户消息"
    TEXT_MSG_RESENT = "✅ 已重新发送消息"

    datetime = datetime
    edit_states = {}
    media_group_cache = {}
    logger = logger
    GROUP_ID = GROUP_ID
    USER_ID = USER_ID

    @staticmethod
    def build_cancel_edit_keyboard(message_id, user_id):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("取消编辑", callback_data=encode_callback(
                MessageUtils.ACTION_CANCEL_EDIT, message_id, user_id, compact=True))
        ]])

    @staticmethod
    def build_action_keyboard(message_id, user_id):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("编辑", callback_data=encode_callback(MessageUtils.ACTION_EDIT, message_id, user_id)),
            InlineKeyboardButton("删除", callback_data=encode_callback(MessageUtils.ACTION_DELETE, message_id, user_id))
        ]])

    @staticmethod
    def build_edit_done_keyboard():
        return InlineKeyboardMarkup([])

    @staticmethod
    def cleanup_edit_states():
        now = datetime.now(UTC)
        timeout = timedelta(minutes=5)
        MessageUtils.edit_states = {
            uid: state for uid, state in MessageUtils.edit_states.items()
            if now - state['timestamp'] <= timeout
        }

    @staticmethod
    async def forward_content(message: Message, bot, chat_id: int, thread_id: int = None):
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
    async def flush_media_group_after_delay(key, user, topic_id, context):
        await asyncio.sleep(2.0)
        messages = MessageUtils.media_group_cache.pop(key, [])
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
            return await MessageUtils.flush_media_group_after_delay(key, user, topic_id, context)
        except Exception as e:
            logger.error(f"媒体组转发失败: {e}")

    @staticmethod
    async def ensure_topic(bot, user, topic_ops):
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
    async def edit_user_message(bot, new_message, state):
        user_id = state["user_id"]
        old_id = state["message_id"]
        original_msg = state["original_message"]
        try:
            if new_message.text:
                await bot.edit_message_text(chat_id=user_id, message_id=old_id, text=new_message.text)
                reply_text = MessageUtils.TEXT_MSG_UPDATED
                msg_id = old_id
            else:
                await bot.delete_message(chat_id=user_id, message_id=old_id)
                forwarded = await MessageUtils.forward_content(new_message, bot, user_id)
                reply_text = MessageUtils.TEXT_MSG_RESENT
                msg_id = forwarded.message_id

            if original_msg and original_msg.chat_id and original_msg.message_id:
                await bot.edit_message_text(
                    chat_id=original_msg.chat_id,
                    message_id=original_msg.message_id,
                    text=MessageUtils.TEXT_EDIT_DONE,
                    reply_markup=MessageUtils.build_edit_done_keyboard()
                )

            await new_message.reply_text(reply_text, reply_markup=MessageUtils.build_action_keyboard(msg_id, user_id))
            logger.info(f"已编辑用户 {user_id} 的消息")
        except Exception as e:
            logger.error(f"编辑失败: {e}")