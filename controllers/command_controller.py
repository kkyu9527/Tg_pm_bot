"""
命令控制器
处理Telegram命令的路由和响应
"""

from telegram import Update
from telegram.ext import ContextTypes
from services.user_service import UserService
from services.topic_service import TopicService
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_object

logger = setup_logger('cmd_ctrl')


class CommandController:
    """命令控制器"""
    
    def __init__(self):
        self.user_service = UserService()
        self.topic_service = TopicService()
    
    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        user = update.effective_user
        user_display = get_user_display_name_from_object(user)
        logger.info(f"用户 {user_display} 发送了 /start 命令")

        # 注册或更新用户信息
        self.user_service.register_or_update_user(user)

        # 生成并发送欢迎消息
        welcome_message = self.user_service.generate_welcome_message(user)
        await update.message.reply_text(welcome_message)

        # 创建话题 & 发送欢迎卡片到群组
        topic_id = await self.topic_service.ensure_user_topic(context.bot, user)
        
        # 获取话题信息用于日志
        topic_info = self.topic_service.topic_ops.get_topic_by_id(topic_id)
        topic_display = f"{topic_info['topic_name']} [话题ID:{topic_id}]" if topic_info else f"[话题ID:{topic_id}]"
        logger.info(f"用户 {user_display} 的话题 {topic_display} 已创建或已存在")

    async def handle_info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /info 命令"""
        user = update.effective_user
        user_display = get_user_display_name_from_object(user)
        logger.info(f"用户 {user_display} 发送了 /info 命令")
        
        # 生成并发送信息消息
        info_message = self.user_service.generate_info_message()
        await update.message.reply_text(info_message)