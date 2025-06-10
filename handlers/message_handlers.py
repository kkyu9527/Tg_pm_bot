from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from database.db_operations import UserOperations, TopicOperations, MessageOperations
from utils.message_utils import (
    MessageUtils,
    decode_callback
)

from datetime import datetime, UTC

USER_ID = MessageUtils.USER_ID
GROUP_ID = MessageUtils.GROUP_ID

class MessageHandlers:

    @staticmethod
    async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private" or str(update.effective_user.id) == USER_ID:
            return

        user = update.effective_user
        message = update.effective_message
        bot = context.bot

        UserOperations().save_user(user.id, user.first_name, user.last_name, user.username)
        topic_id = await MessageUtils.ensure_topic(bot, user, TopicOperations())

        if message.media_group_id and (message.photo or message.video):
            key = f"{user.id}:{message.media_group_id}"
            MessageUtils.media_group_cache.setdefault(key, []).append(message)
            if len(MessageUtils.media_group_cache[key]) == 1:
                import asyncio
                asyncio.create_task(MessageUtils.flush_media_group_after_delay(key, user, topic_id, context))
            return

        try:
            forwarded = await MessageUtils.forward_content(message, bot, GROUP_ID, topic_id)
            if not forwarded:
                return
            MessageOperations().save_message(user.id, topic_id, message.message_id, forwarded.message_id, "user_to_owner")
        except BadRequest as e:
            if "Message thread not found" in str(e):
                TopicOperations().delete_topic(topic_id)
                topic_id = await MessageUtils.ensure_topic(bot, user, TopicOperations())
                forwarded = await MessageUtils.forward_content(message, bot, GROUP_ID, topic_id)
                if not forwarded:
                    return
                MessageOperations().save_message(user.id, topic_id, message.message_id, forwarded.message_id, "user_to_owner")
            else:
                MessageUtils.logger.error(f"转发失败: {e}")

    @staticmethod
    async def handle_owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        MessageUtils.cleanup_edit_states()
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return

        if update.effective_user.id in MessageUtils.edit_states:
            state = MessageUtils.edit_states.pop(update.effective_user.id)
            await MessageUtils.edit_user_message(context.bot, update.effective_message, state)
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
            forwarded = await MessageUtils.forward_content(message, context.bot, user_id)
            if not forwarded:
                return
            MessageOperations().save_message(user_id, message.message_thread_id, forwarded.message_id,
                                             message.message_id, "owner_to_user")
            await message.reply_text("✅ 已转发给用户",
                                     reply_markup=MessageUtils.build_action_keyboard(forwarded.message_id, user_id))
        except Exception as e:
            MessageUtils.logger.error(f"转发失败: {e}")
            await message.reply_text(f"⚠️ 转发失败: {e}")

    @staticmethod
    async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        MessageUtils.cleanup_edit_states()
        query = update.callback_query
        await query.answer()
        try:
            data = decode_callback(query.data)
        except Exception as e:
            MessageUtils.logger.error(f"回调数据解析失败: {e}")
            return

        action = data["action"]
        message_id = data["message_id"]
        user_id = data["user_id"]

        if action == MessageUtils.ACTION_DELETE:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
                await query.edit_message_text(MessageUtils.TEXT_MSG_DELETED)
            except Exception as e:
                await query.edit_message_text(f"⚠️ 删除失败: {e}")
        elif action == MessageUtils.ACTION_EDIT:
            MessageUtils.edit_states[query.from_user.id] = {
                "message_id": message_id,
                "user_id": user_id,
                "original_message": query.message,
                "timestamp": datetime.now(UTC)
            }
            await query.edit_message_text(
                MessageUtils.TEXT_EDIT_PROMPT,
                reply_markup=MessageUtils.build_cancel_edit_keyboard(message_id, user_id)
            )
        elif action == MessageUtils.ACTION_CANCEL_EDIT:
            if query.from_user.id in MessageUtils.edit_states:
                state = MessageUtils.edit_states.pop(query.from_user.id)
                await query.edit_message_text(
                    MessageUtils.TEXT_EDIT_CANCELLED,
                    reply_markup=MessageUtils.build_action_keyboard(state["message_id"], state["user_id"])
                )

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
            MessageUtils.logger.warning(f"Telegram 话题删除失败: {e}")
        try:
            topic = TopicOperations().get_topic_by_id(topic_id)
            if not topic:
                await update.effective_message.reply_text("⚠️ 数据库中未找到话题，跳过清理")
                return

            TopicOperations().delete_topic(topic_id)
            MessageUtils.logger.info(f"主人删除了话题 {topic_id} 以及相关数据库记录")
        except Exception as e:
            MessageUtils.logger.error(f"从数据库中删除话题失败: {e}")