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

# 加载环境变量
load_dotenv()
GROUP_ID = os.getenv("GROUP_ID")
USER_ID = os.getenv("USER_ID")
logger = setup_logger('messages', 'logs/messages.log')


class MessageHandlers:
    edit_states = {}
    media_group_cache = {}

    @staticmethod
    def _cleanup_edit_states():
        now = datetime.utcnow()
        timeout = timedelta(minutes=5)
        to_remove = [uid for uid, state in MessageHandlers.edit_states.items()
                     if now - state['timestamp'] > timeout]
        for uid in to_remove:
            del MessageHandlers.edit_states[uid]

    @staticmethod
    async def _forward_content(message: Message, bot, chat_id: int, thread_id: int = None):
        try:
            kwargs = {"chat_id": chat_id}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            if message.text:
                return await bot.send_message(**kwargs, text=message.text)
            elif message.photo:
                return await bot.send_photo(**kwargs, photo=message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                return await bot.send_video(**kwargs, video=message.video.file_id, caption=message.caption)
            elif message.voice:
                return await bot.send_voice(**kwargs, voice=message.voice.file_id, caption=message.caption)
            elif message.audio:
                return await bot.send_audio(**kwargs, audio=message.audio.file_id, caption=message.caption)
            elif message.document:
                return await bot.send_document(**kwargs, document=message.document.file_id, caption=message.caption)
            elif message.sticker:
                return await bot.send_sticker(**kwargs, sticker=message.sticker.file_id)
        except Exception as e:
            logger.error(f"消息转发失败: {e}")

    @staticmethod
    async def _flush_media_group_after_delay(key: str, user, topic_id: int, context):
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
                user_id=user.id,
                topic_id=topic_id,
                user_message_id=messages[0].message_id,
                group_message_id=sent_group[0].message_id,
                direction="user_to_owner"
            )
        except RetryAfter as e:
            logger.warning(f"限流：等待 {e.retry_after} 秒重试发送媒体组")
            await asyncio.sleep(e.retry_after + 1)
            return await MessageHandlers._flush_media_group_after_delay(key, user, topic_id, context)
        except Exception as e:
            logger.error(f"媒体组转发失败: {e}")

    @staticmethod
    async def _ensure_topic(bot, user, topic_ops):
        topic = topic_ops.get_user_topic(user.id)
        if topic:
            return topic["topic_id"]

        username = f"@{user.username}" if user.username else "无用户名"
        topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
        forum_topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name)
        topic_id = forum_topic.message_thread_id
        topic_ops.save_topic(user.id, topic_id, topic_name)

        sent_msg = await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=f"用户 {topic_name}\n用户名: {username}\n开始了新的对话。"
        )

        try:
            await bot.pin_chat_message(
                chat_id=GROUP_ID,
                message_id=sent_msg.message_id,
                message_thread_id=topic_id
            )
        except Exception as e:
            logger.warning(f"置顶消息失败: {e}")

        return topic_id

    @staticmethod
    async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private" or str(update.effective_user.id) == USER_ID:
            return

        user = update.effective_user
        message = update.effective_message
        bot = context.bot
        logger.info(f"收到用户 {user.id} ({user.first_name}) 的消息")

        UserOperations().save_user(user.id, user.first_name, user.last_name, user.username)
        topic_ops = TopicOperations()
        topic_id = await MessageHandlers._ensure_topic(bot, user, topic_ops)

        if message.media_group_id and (message.photo or message.video):
            key = f"{user.id}:{message.media_group_id}"
            if key not in MessageHandlers.media_group_cache:
                MessageHandlers.media_group_cache[key] = []
                asyncio.create_task(
                    MessageHandlers._flush_media_group_after_delay(key, user, topic_id, context)
                )
            MessageHandlers.media_group_cache[key].append(message)
            return

        try:
            forwarded_msg = await MessageHandlers._forward_content(message, bot, GROUP_ID, topic_id)
            MessageOperations().save_message(user.id, topic_id, message.message_id,
                                             forwarded_msg.message_id, "user_to_owner")
        except BadRequest as e:
            if "Message thread not found" in str(e):
                logger.warning(f"话题 {topic_id} 不存在，重新创建")
                topic_ops.delete_topic(topic_id)
                new_topic_id = await MessageHandlers._ensure_topic(bot, user, topic_ops)
                forwarded_msg = await MessageHandlers._forward_content(message, bot, GROUP_ID, new_topic_id)
                MessageOperations().save_message(user.id, new_topic_id, message.message_id,
                                                 forwarded_msg.message_id, "user_to_owner")
            else:
                logger.error(f"转发失败: {e}")

    @staticmethod
    async def handle_owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        MessageHandlers._cleanup_edit_states()
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return
        if update.effective_user.id in MessageHandlers.edit_states:
            edit_state = MessageHandlers.edit_states.pop(update.effective_user.id)
            await MessageHandlers._edit_user_message(context.bot, update.effective_message, edit_state)
            return
        if not update.message.is_topic_message:
            return

        message = update.effective_message
        topic_id = message.message_thread_id
        logger.info(f"收到主人在话题 {topic_id} 中的消息")
        topic = TopicOperations().get_topic_by_id(topic_id)
        if not topic:
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return
        user_id = topic["user_id"]
        bot = context.bot
        try:
            forwarded_msg = await MessageHandlers._forward_content(message, bot, user_id)
            MessageOperations().save_message(user_id, topic_id, forwarded_msg.message_id,
                                             message.message_id, "owner_to_user")
            keyboard = [[
                InlineKeyboardButton("编辑", callback_data=json.dumps({
                    "action": "edit", "message_id": forwarded_msg.message_id, "user_id": user_id
                })),
                InlineKeyboardButton("删除", callback_data=json.dumps({
                    "action": "delete", "message_id": forwarded_msg.message_id, "user_id": user_id
                }))
            ]]
            await message.reply_text("✅ 已转发给用户", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"转发失败: {e}")
            await message.reply_text(f"⚠️ 转发失败: {str(e)}")

    @staticmethod
    async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        MessageHandlers._cleanup_edit_states()
        query = update.callback_query
        await query.answer()
        try:
            data = json.loads(query.data)
            action = data["action"]
            message_id = data["message_id"]
            user_id = data["user_id"]
        except Exception as e:
            logger.error(f"回调数据解析失败: {e}")
            return

        if action == "delete":
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
                await query.edit_message_text("✅ 消息已删除")
                logger.info(f"删除用户 {user_id} 的消息 {message_id}")
            except Exception as e:
                logger.error(f"删除失败: {e}")
                await query.edit_message_text(f"⚠️ 删除失败: {str(e)}")
        elif action == "edit":
            MessageHandlers.edit_states[query.from_user.id] = {
                "message_id": message_id,
                "user_id": user_id,
                "original_message": query.message,
                "timestamp": datetime.utcnow()
            }
            await query.edit_message_text("✏️ 请发送新的消息内容，将替换之前的消息")

    @staticmethod
    async def _edit_user_message(bot, new_message, state):
        try:
            user_id = state["user_id"]
            message_id = state["message_id"]
            if new_message.text:
                await bot.edit_message_text(chat_id=user_id, message_id=message_id, text=new_message.text)
            else:
                await bot.delete_message(chat_id=user_id, message_id=message_id)
                await MessageHandlers._forward_content(new_message, bot, user_id)
            logger.info(f"已编辑用户 {user_id} 的消息")
        except Exception as e:
            logger.error(f"编辑失败: {e}")
    @staticmethod
    async def handle_owner_delete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return
        if not update.message.is_topic_message:
            return

        message = update.effective_message
        topic_id = message.message_thread_id
        bot = context.bot

        topic_ops = TopicOperations()
        topic = topic_ops.get_topic_by_id(topic_id)
        if not topic:
            await message.reply_text("⚠️ 此话题在数据库中不存在")
            return

        try:
            await bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception as e:
            logger.warning(f"尝试删除 Telegram 话题失败: {e}")

        try:
            topic_ops.delete_topic(topic_id)
            logger.info(f"主人删除了话题 {topic_id}，已从数据库中移除")
        except Exception as e:
            logger.error(f"从数据库中删除话题失败: {e}")