"""
命令控制器
处理Telegram命令的路由和响应
"""

from telegram import Update, Chat
from telegram.ext import ContextTypes
from telegram.error import BadRequest
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
                            "• 管理消息\n\n"
                            "💡 提示：如果话题在Telegram中已被手动删除，请尝试重新添加机器人到群组或检查权限设置"
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
    
    async def handle_cleanup_topics_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /cleanup_topics 命令，用于清理孤立的话题记录"""
        # 只允许主人使用此命令
        effective_user = update.effective_user
        user_id = os.getenv("USER_ID")
        
        if not effective_user or not user_id or str(effective_user.id) != str(user_id):
            if update.message:
                await update.message.reply_text("⚠️ 此命令仅限主人使用")
            return
            
        # 只允许在群组中使用此命令
        chat = update.effective_chat
        if not chat or chat.type not in ["group", "supergroup"]:
            if update.message:
                await update.message.reply_text("⚠️ 此命令只能在群组中使用")
            return
            
        group_id = os.getenv("GROUP_ID")
        if not group_id:
            if update.message:
                await update.message.reply_text("⚠️ GROUP_ID 未配置")
            return
            
        processing_message = None
        if update.message:
            processing_message = await update.message.reply_text("🔍 正在检查并清理孤立话题记录...")
            
        try:
            # 获取所有话题记录
            all_topics = []
            connection = self.topic_service.topic_ops.db_connector.get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT topic_id, user_id, topic_name FROM topics")
                    all_topics = cursor.fetchall()
            finally:
                connection.close()
                
            if not all_topics:
                if processing_message:
                    await processing_message.edit_text("✅ 没有发现任何话题记录")
                return
                
            deleted_count = 0
            error_count = 0
            
            # 检查每个话题是否在Telegram中实际存在
            for topic_record in all_topics:
                topic_id, user_id, topic_name = topic_record
                try:
                    # 尝试编辑话题来验证话题是否存在
                    # 如果话题不存在，会抛出各种异常
                    await context.bot.edit_forum_topic(chat_id=int(group_id), message_thread_id=topic_id, name=topic_name)
                except BadRequest as e:
                    error_message = str(e).lower()
                    if "message thread not found" in error_message or "not enough rights" in error_message:
                        # 话题不存在或无权限，删除数据库记录
                        try:
                            self.topic_service.topic_ops.delete_topic(topic_id)
                            logger.info(f"已清理孤立话题记录: {topic_name} [话题ID:{topic_id}]")
                            deleted_count += 1
                        except Exception as delete_error:
                            logger.error(f"删除孤立话题记录时出错: {delete_error}")
                            error_count += 1
                    else:
                        # 其他错误，可能是权限问题但话题存在
                        logger.warning(f"检查话题 {topic_name} [话题ID:{topic_id}] 时发生其他错误，跳过清理: {e}")
                except Exception as e:
                    # 其他异常
                    logger.error(f"检查话题 {topic_name} [话题ID:{topic_id}] 存在性时出错: {e}")
                    error_count += 1
                    
            # 发送结果报告
            result_message = f"✅ 话题清理完成\n\n"
            result_message += f"🧹 清理记录数: {deleted_count}\n"
            if error_count > 0:
                result_message += f"⚠️ 错误数量: {error_count}\n"
            result_message += f"📊 总检查数: {len(all_topics)}"
            
            if processing_message:
                await processing_message.edit_text(result_message)
                
        except Exception as e:
            logger.error(f"清理话题记录时出错: {e}")
            if processing_message:
                await processing_message.edit_text(f"⚠️ 清理话题记录时出错: {e}")