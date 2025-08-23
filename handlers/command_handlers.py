from database.db_operations import UserOperations
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from utils.logger import setup_logger
from handlers.message_handlers import MessageHandlers
from database.db_operations import TopicOperations
import os

# 设置日志记录器
logger = setup_logger('commands', 'logs/commands.log')

class CommandHandlers:
    """处理机器人命令的类"""

    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        user = update.effective_user
        logger.info(f"用户 {user.id} ({user.first_name}) 发送了 /start 命令")

        UserOperations().save_user(user.id, user.first_name, user.last_name, user.username)

        welcome_message = (
            f"👋 您好，{user.first_name}！\n\n"
            f"🆔 ID: {user.id}\n"
            f"👤 姓名: {user.full_name}\n"
            f"🔰 用户名: @{user.username if user.username else '未设置'}\n"
            f"⭐ 是否是Premium用户: {'是' if user.is_premium else '否'}\n"
            f"您可以通过我向主人发送私信，我会将您的消息转发给主人。\n"
        )

        await update.message.reply_text(welcome_message)

        # ✅ 创建话题 & 发送欢迎卡片到群组
        topic_id = await MessageHandlers.ensure_topic(context.bot, user, TopicOperations())
        logger.info(f"用户 {user.id} 的话题 {topic_id} 已创建或已存在")

    @staticmethod
    async def info_command(update: Update, _: ContextTypes.DEFAULT_TYPE):
        """处理 /info 命令"""
        user = update.effective_user
        logger.info(f"用户 {user.id} ({user.first_name}) 发送了 /info 命令")
        
        info_message = (
            "ℹ️ 关于私聊转发机器人\n\n"
            "这个机器人可以帮助您与用户进行交流，避免双向。\n\n"
            "项目已开源，地址：https://github.com/kkyu9527/Tg_pm_bot.git\n\n"
            "如有任何问题，请联系 @kkyu9527s_bot"
        )
        
        await update.message.reply_text(info_message)
        
    @staticmethod
    async def show_commands(update: Update, _: ContextTypes.DEFAULT_TYPE):
        """显示所有可用命令的按钮（仅限群组中的主人使用）"""
        user = update.effective_user
        
        # 检查是否是群组消息且是主人
        if update.effective_chat.type != "group" and update.effective_chat.type != "supergroup":
            logger.info(f"用户 {user.id} ({user.first_name}) 在非群组中请求显示命令按钮，已拒绝")
            await update.message.reply_text("⚠️ 此命令只能在群组中使用")
            return
            
        if str(user.id) != os.getenv("USER_ID"):
            logger.info(f"非主人用户 {user.id} ({user.first_name}) 请求显示命令按钮，已拒绝")
            await update.message.reply_text("⚠️ 只有主人可以使用此命令")
            return
        
        logger.info(f"主人 {user.id} ({user.first_name}) 在群组中请求显示命令按钮")
        
        # 创建包含所有命令的键盘
        keyboard = [
            [KeyboardButton("/delete_topic")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "📋 以下是可用的命令：", 
            reply_markup=reply_markup
        )
        logger.info(f"已为主人 {user.id} 显示命令按钮")