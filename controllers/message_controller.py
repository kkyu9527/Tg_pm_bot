"""
消息控制器
处理Telegram消息的路由和响应
"""

from telegram import Update
from telegram.ext import ContextTypes
from services.message_service import MessageService
from services.topic_service import TopicService
from utils.logger import setup_logger

logger = setup_logger('message_controller')


class MessageController:
    """消息控制器 - 只负责路由和响应"""
    
    def __init__(self):
        self.message_service = MessageService()
        self.topic_service = TopicService()
    
    async def handle_user_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户发送的消息"""
        await self.message_service.handle_user_message(update, context)
    
    async def handle_owner_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人在群组中发送的消息"""
        await self.message_service.handle_owner_message(update, context)
    
    async def handle_button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调"""
        await self.message_service.handle_button_callback(update, context)
    
    async def handle_owner_delete_topic(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人删除话题的请求"""
        await self.topic_service.handle_topic_deletion_flow(update, context)
