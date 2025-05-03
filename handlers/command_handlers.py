from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import setup_logger

# 设置日志记录器
logger = setup_logger('commands', 'logs/commands.log')

class CommandHandlers:
    """处理机器人命令的类"""
    
    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        user = update.effective_user
        logger.info(f"用户 {user.id} ({user.first_name}) 发送了 /start 命令")
        
        welcome_message = (
            f"👋 您好，{user.first_name}！ID:{user.id} \n\n"
            f"欢迎使用私聊转发机器人。\n"
            f"您可以通过我向主人发送私信，我会将您的消息转发给主人。\n\n"
            f"请直接发送您想要传达的消息，可以是文字、图片、视频、语音等任何形式。\n\n"
            f"项目已开源，详情请使用 /info 命令查看。"
        )
        
        await update.message.reply_text(welcome_message)
    
    @staticmethod
    async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /info 命令"""
        user = update.effective_user
        logger.info(f"用户 {user.id} ({user.first_name}{user.last_name}) 发送了 /info 命令")
        
        info_message = (
            "ℹ️ 关于私聊转发机器人\n\n"
            "这个机器人可以帮助您向主人发送私信，并接收主人的回复。\n\n"
            "项目已开源，地址：https://github.com/kkyu9527/Tg_pm_bot.git\n\n"
            "如有任何问题，请联系 @kkyu9527s_bot"
        )
        
        await update.message.reply_text(info_message)