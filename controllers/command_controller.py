"""
命令控制器
处理Telegram命令的路由和响应
"""

from telegram import Update, Chat
from telegram.ext import ContextTypes
from services.user_service import UserService
from services.topic_service import TopicService
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_object
import os

logger = setup_logger('cmd_ctrl')


class CommandController:
    """命令控制器"""
    
    def __init__(self):
        self.user_service = UserService()
        self.topic_service = TopicService()
    
    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        user = update.effective_user
        if not user:
            return
            
        user_display = get_user_display_name_from_object(user)
        logger.info(f"用户 {user_display} 发送了 /start 命令")

        # 注册或更新用户信息
        self.user_service.register_or_update_user(user)

        # 生成并发送欢迎消息
        welcome_message = self.user_service.generate_welcome_message(user)
        if update.message:
            await update.message.reply_text(welcome_message)

        # 创建话题 & 发送欢迎卡片到群组
        try:
            topic_id = await self.topic_service.ensure_user_topic(context.bot, user)
            
            # 获取话题信息用于日志
            topic_info = self.topic_service.topic_ops.get_topic_by_id(topic_id)
            topic_display = f"{topic_info['topic_name']} [话题ID:{topic_id}]" if topic_info else f"[话题ID:{topic_id}]"
            logger.info(f"用户 {user_display} 的话题 {topic_display} 已创建或已存在")
        except Exception as e:
            error_message = str(e)
            logger.error(f"为用户 {user_display} 创建话题时出错: {error_message}")
            if update.message:
                # 向用户发送简短的错误提示
                await update.message.reply_text("⚠️ 创建话题时出错，正在联系主人")
                
            # 向主人发送详细的错误信息
            try:
                import os
                GROUP_ID = os.getenv("GROUP_ID")
                USER_ID = os.getenv("USER_ID")
                if GROUP_ID and USER_ID:
                    admin_message = (
                        f"🚨 为用户 {user_display} 创建话题时出错\n"
                        f"错误详情: {error_message}\n"
                        f"用户ID: {user.id}\n"
                        f"群组ID: {GROUP_ID}"
                    )
                    
                    # 如果是权限错误，提供具体的解决建议
                    if "Not enough rights" in error_message:
                        admin_message += (
                            "\n\n🔧 解决方案:\n"
                            "请确保机器人具有以下权限：\n"
                            "• 创建话题\n"
                            "• 发送消息\n"
                            "• 管理消息"
                        )
                    
                    await context.bot.send_message(chat_id=GROUP_ID, text=admin_message)
            except Exception as admin_error:
                logger.error(f"向主人发送错误信息时出错: {admin_error}")
            return

    async def handle_info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /info 命令"""
        user = update.effective_user
        if not user:
            return
            
        user_display = get_user_display_name_from_object(user)
        logger.info(f"用户 {user_display} 发送了 /info 命令")
        
        # 生成并发送信息消息
        info_message = self.user_service.generate_info_message()
        if update.message:
            await update.message.reply_text(info_message)

    async def handle_get_group_id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /get_group_id 命令，用于获取当前群组的ID"""
        # 只允许在群组中使用此命令
        chat = update.effective_chat
        if not chat or chat.type not in ["group", "supergroup"]:
            if update.message:
                await update.message.reply_text("⚠️ 此命令只能在群组中使用")
            return

        # 获取群组信息
        group_id = chat.id
        group_title = chat.title or "未命名群组"
        
        # 获取环境变量中的配置信息
        configured_group_id = os.getenv("GROUP_ID")
        user_id = os.getenv("USER_ID")
        
        # 检查是否是配置的群组
        is_configured_group = str(group_id) == str(configured_group_id) if configured_group_id else False
        
        # 构建响应消息
        response_message = (
            f"📋 群组信息\n"
            f"╭ 群组名称: {group_title}\n"
            f"├ 群组ID: <code>{group_id}</code>\n"
            f"╰ 配置状态: {'✅ 已配置' if is_configured_group else '❌ 未配置'}\n\n"
        )
        
        # 如果是主人用户，提供更多配置信息
        effective_user = update.effective_user
        if effective_user and user_id and str(effective_user.id) == str(user_id):
            response_message += (
                f"🔧 配置信息\n"
                f"╭ 配置的群组ID: <code>{configured_group_id or '未设置'}</code>\n"
                f"╰ 你的用户ID: <code>{user_id}</code>\n\n"
            )
        
        response_message += "📌 提示：将此群组ID配置到环境变量 GROUP_ID 中即可使用"
        
        # 记录日志
        if effective_user:
            user_display = get_user_display_name_from_object(effective_user)
            logger.info(f"用户 {user_display} 在群组 '{group_title}' [{group_id}] 中请求获取群组ID")
        
        # 发送响应
        if update.message:
            await update.message.reply_text(response_message, parse_mode="HTML")
