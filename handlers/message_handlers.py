import os
import json
from datetime import datetime, timedelta
from telegram import Update, Message, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from database.db_operations import UserOperations, TopicOperations, MessageOperations
from utils.logger import setup_logger
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
GROUP_ID = os.getenv("GROUP_ID")
USER_ID = os.getenv("USER_ID")
logger = setup_logger('messages', 'logs/messages.log')

class MessageHandlers:
    """处理用户消息的类"""

    edit_states = {}

    message_type_map = {
        "text": lambda bot, kwargs, msg: bot.send_message(**kwargs, text=msg.text),
        "photo": lambda bot, kwargs, msg: bot.send_photo(**kwargs, photo=msg.photo[-1].file_id, caption=msg.caption),
        "video": lambda bot, kwargs, msg: bot.send_video(**kwargs, video=msg.video.file_id, caption=msg.caption),
        "voice": lambda bot, kwargs, msg: bot.send_voice(**kwargs, voice=msg.voice.file_id, caption=msg.caption),
        "audio": lambda bot, kwargs, msg: bot.send_audio(**kwargs, audio=msg.audio.file_id, caption=msg.caption),
        "document": lambda bot, kwargs, msg: bot.send_document(**kwargs, document=msg.document.file_id, caption=msg.caption),
        "sticker": lambda bot, kwargs, msg: bot.send_sticker(**kwargs, sticker=msg.sticker.file_id),
    }

    @staticmethod
    def _determine_message_type(message: Message) -> str:
        if message.text:
            return "text"
        elif message.photo:
            return "photo"
        elif message.video:
            return "video"
        elif message.voice:
            return "voice"
        elif message.audio:
            return "audio"
        elif message.document:
            return "document"
        elif message.sticker:
            return "sticker"
        return "unsupported"

    @staticmethod
    async def _forward_content(message: Message, bot, chat_id: int, thread_id: int = None):
        message_type = MessageHandlers._determine_message_type(message)
        if message_type not in MessageHandlers.message_type_map:
            raise ValueError("暂不支持的消息类型")
        kwargs = {"chat_id": chat_id}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        return await MessageHandlers.message_type_map[message_type](bot, kwargs, message)

    @staticmethod
    def _cleanup_edit_states():
        now = datetime.utcnow()
        timeout = timedelta(minutes=5)
        to_remove = [uid for uid, state in MessageHandlers.edit_states.items()
                     if now - state['timestamp'] > timeout]
        for uid in to_remove:
            del MessageHandlers.edit_states[uid]

    @staticmethod
    async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private" or str(update.effective_user.id) == USER_ID:
            return

        user = update.effective_user
        message = update.effective_message
        logger.info(f"收到用户 {user.id} ({user.first_name}) 的消息")

        user_ops = UserOperations()
        user_ops.save_user(user.id, user.first_name, user.last_name, user.username)

        topic_ops = TopicOperations()
        topic = topic_ops.get_user_topic(user.id)
        need_create_topic = not topic
        bot = context.bot

        if topic:
            topic_id = topic["topic_id"]
            try:
                test_msg = await bot.send_message(chat_id=GROUP_ID, message_thread_id=topic_id, text="验证话题存在性")
                await bot.delete_message(chat_id=GROUP_ID, message_id=test_msg.message_id)
            except BadRequest as e:
                if "Message thread not found" in str(e):
                    logger.warning(f"话题 {topic_id} 不存在，将创建新话题")
                    need_create_topic = True
                else:
                    raise

        if need_create_topic:
            topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
            forum_topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name)
            topic_id = forum_topic.message_thread_id
            topic_ops.save_topic(user.id, topic_id, topic_name)
            await bot.send_message(chat_id=GROUP_ID, message_thread_id=topic_id,
                                   text=f"用户 {topic_name} 开始了新的对话。")
            logger.info(f"为用户 {user.id} 创建了新话题 {topic_id}")

        message_type = MessageHandlers._determine_message_type(message)
        user_display = f"@{user.username}" if user.username else f"{user.first_name} {(user.last_name or '')}".strip()

        try:
            forwarded_msg = await bot.send_message(chat_id=GROUP_ID, message_thread_id=topic_id,
                                                   text=f"{user_display} 发来了一条 {message_type} 消息。")
            await MessageHandlers._forward_content(message, bot, GROUP_ID, topic_id)

            msg_ops = MessageOperations()
            msg_ops.save_message(user.id, topic_id, message_type, message.message_id,
                                 forwarded_msg.message_id, "user_to_owner")
        except BadRequest as e:
            logger.error(f"转发失败: {e}")
            if "Message thread not found" in str(e):
                logger.error(f"话题 {topic_id} 不存在")
            else:
                raise

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

        topic_ops = TopicOperations()
        topic = topic_ops.get_topic_by_id(topic_id)
        if not topic:
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return

        user_id = topic["user_id"]
        message_type = MessageHandlers._determine_message_type(message)
        bot = context.bot

        try:
            forwarded_msg = await MessageHandlers._forward_content(message, bot, user_id)
            msg_ops = MessageOperations()
            msg_ops.save_message(user_id, topic_id, message_type, forwarded_msg.message_id,
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