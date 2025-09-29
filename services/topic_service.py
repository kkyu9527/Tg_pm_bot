"""
话题业务逻辑层
处理话题相关的业务逻辑
"""

import os
from telegram import User, Update
from telegram.ext import ContextTypes
from database.db_operations import TopicOperations, UserOperations
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db, get_topic_display_name

logger = setup_logger('top_srvc')


class TopicService:
    """话题业务逻辑服务"""
    
    def __init__(self):
        self.topic_ops = TopicOperations()
        self.user_ops = UserOperations()
        self.USER_ID = os.getenv("USER_ID")
        self.GROUP_ID = os.getenv("GROUP_ID")
    

    async def ensure_user_topic(self, bot, user: User) -> int:
        """确保用户有对应的话题，如果没有则创建新话题"""
        # 检查用户是否已有话题
        topic = self.topic_ops.get_user_topic(user.id)
        if topic:
            user_display = get_user_display_name_from_db(user.id, self.user_ops)
            topic_display = get_topic_display_name(topic['topic_id'], self.topic_ops)
            logger.info(f"找到用户 {user_display} 的现有话题: {topic_display}")
            return topic["topic_id"]

        # 创建新话题
        topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
        username = f"@{user.username}" if user.username else "无用户名"
        user_display = get_user_display_name_from_db(user.id,self.user_ops)
        logger.info(f"为用户 {user_display} 创建新话题: {topic_name}")
        
        # 通过Telegram API创建话题
        topic_id = (await bot.create_forum_topic(chat_id=self.GROUP_ID, name=topic_name)).message_thread_id
        
        # 保存话题信息
        self.topic_ops.save_topic(user.id, topic_id, topic_name)
        
        user_display = get_user_display_name_from_db(user.id, self.user_ops)
        topic_display = get_topic_display_name(topic_id, self.topic_ops)
        logger.info(f"话题创建成功: 用户 {user_display}, 话题 {topic_display}")

        # 发送用户信息卡片
        await self._send_user_info_card(bot, user, topic_id, username, self.GROUP_ID)
        
        return topic_id
    
    async def _send_user_info_card(self, bot, user: User, topic_id: int, username: str, group_id: str):
        """发送用户信息卡片到话题"""
        info_text = (
            f"👤 <b>新用户开始对话</b>\n"
            f"╭ 姓名: {user.first_name} {user.last_name or ''}\n"
            f"├ 用户名: {username}\n"
            f"├ 用户ID: <code>{user.id}</code>\n"
            f"├ 语言代码: {user.language_code or '未知'}\n"
            f"╰ Premium 用户: {'✅' if getattr(user, 'is_premium', False) else '❌'}\n"
        )

        # 尝试发送带头像的用户信息
        try:
            logger.info(f"尝试获取用户 {user.id} 的头像")
            photos = await bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                logger.info(f"用户 {user.id} 有头像，发送带头像的信息")
                sent_msg = await bot.send_photo(group_id, photo=photos.photos[0][-1].file_id,
                                                message_thread_id=topic_id, caption=info_text, parse_mode="HTML")
            else:
                logger.info(f"用户 {user.id} 无头像")
                raise Exception("无头像")
        except Exception as e:
            logger.warning(f"获取用户头像失败: {e}，发送纯文本信息")
            sent_msg = await bot.send_message(group_id, text=info_text, message_thread_id=topic_id, parse_mode="HTML")

        # 尝试置顶用户信息
        try:
            topic_display = get_topic_display_name(topic_id, self.topic_ops)
            logger.info(f"尝试置顶用户信息: 话题 {topic_display}, 消息ID {sent_msg.message_id}")
            await bot.pin_chat_message(chat_id=group_id, message_id=sent_msg.message_id)
            logger.info(f"消息置顶成功: 话题 {topic_display}, 消息ID {sent_msg.message_id}")
        except Exception as e:
            error_message = str(e)
            topic_display = get_topic_display_name(topic_id, self.topic_ops)
            logger.warning(f"置顶失败: {error_message}, 话题: {topic_display}, 消息ID: {sent_msg.message_id}")
    
    async def handle_topic_deletion(self, bot, topic_id: int, group_id: str) -> dict:
        """处理话题删除操作
        
        Returns:
            dict: {
                'success': bool,
                'message': str
            }
        """
        # 验证话题存在性
        topic = self.topic_ops.get_topic_by_id(topic_id)
        if not topic:
            logger.warning(f"话题 {topic_id} 在数据库中不存在")
            return {
                'success': False,
                'message': '⚠️ 此话题在数据库中不存在'
            }
        
        # 尝试从 Telegram 删除话题
        try:
            await bot.delete_forum_topic(chat_id=group_id, message_thread_id=topic_id)
        except Exception as e:
            logger.warning(f"Telegram 话题删除失败: {e}")
        
        # 尝试从数据库删除话题
        try:
            # 再次检查话题是否存在
            topic = self.topic_ops.get_topic_by_id(topic_id)
            if not topic:
                return {
                    'success': False,
                    'message': '⚠️ 数据库中未找到话题，跳过清理'
                }
            
            # 从数据库中删除话题
            self.topic_ops.delete_topic(topic_id)
            logger.info(f"主人删除了话题 {topic_id} 以及相关数据库记录")
            return {
                'success': True,
                'message': '✅ 话题已删除'
            }
        except Exception as e:
            logger.error(f"从数据库中删除话题失败: {e}")
            return {
                'success': False,
                'message': f'⚠️ 从数据库中删除话题失败: {e}'
            }
    
    async def handle_topic_deletion_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人删除话题请求的完整流程"""
        
        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != self.USER_ID:
            return
            
        # 只处理话题消息
        if not update.message.is_topic_message:
            return

        logger.info("主人尝试删除话题")

        topic_id = update.effective_message.message_thread_id
        result = await self.handle_topic_deletion(context.bot, topic_id, self.GROUP_ID)
        logger.info(f"话题删除操作完成: {result['message']}")
