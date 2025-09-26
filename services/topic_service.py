"""
话题业务逻辑层
处理话题相关的业务逻辑
"""

import os
from typing import Dict, Optional, Any
from telegram import User
from repositories.topic_repository import TopicRepository
from repositories.user_repository import UserRepository
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db, get_topic_display_name

logger = setup_logger('topic_service')


class TopicService:
    """话题业务逻辑服务"""
    
    def __init__(self):
        self.topic_repo = TopicRepository()
        self.user_repo = UserRepository()
    
    async def ensure_user_topic(self, bot, user: User) -> int:
        """确保用户有对应的话题，如果没有则创建新话题"""
        # 检查用户是否已有话题
        topic = self.topic_repo.get_user_topic(user.id)
        if topic:
            user_display = get_user_display_name_from_db(user.id, self.user_repo.user_ops)
            topic_display = get_topic_display_name(topic['topic_id'], self.topic_repo.topic_ops)
            logger.info(f"找到用户 {user_display} 的现有话题: {topic_display}")
            return topic["topic_id"]

        # 创建新话题
        GROUP_ID = os.getenv("GROUP_ID")
        topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
        username = f"@{user.username}" if user.username else "无用户名"
        user_display = get_user_display_name_from_db(user.id)
        logger.info(f"为用户 {user_display} 创建新话题: {topic_name}")
        
        # 通过Telegram API创建话题
        topic_id = (await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name)).message_thread_id
        
        # 保存话题信息
        self.topic_repo.save_topic(user.id, topic_id, topic_name)
        
        user_display = get_user_display_name_from_db(user.id, self.user_repo.user_ops)
        topic_display = get_topic_display_name(topic_id, self.topic_repo.topic_ops)
        logger.info(f"话题创建成功: 用户 {user_display}, 话题 {topic_display}")

        # 发送用户信息卡片
        await self._send_user_info_card(bot, user, topic_id, username, GROUP_ID)
        
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
            topic_display = get_topic_display_name(topic_id, self.topic_repo.topic_ops)
            logger.info(f"尝试置顶用户信息: 话题 {topic_display}, 消息ID {sent_msg.message_id}")
            await bot.pin_chat_message(chat_id=group_id, message_id=sent_msg.message_id)
            logger.info(f"消息置顶成功: 话题 {topic_display}, 消息ID {sent_msg.message_id}")
        except Exception as e:
            error_message = str(e)
            topic_display = get_topic_display_name(topic_id)
            logger.warning(f"置顶失败: {error_message}, 话题: {topic_display}, 消息ID: {sent_msg.message_id}")
    
    def get_topic_by_id(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """根据话题ID获取话题信息"""
        return self.topic_repo.get_topic_by_id(topic_id)
    
    def delete_topic(self, topic_id: int) -> bool:
        """删除话题"""
        return self.topic_repo.delete_topic(topic_id)
    
    def recreate_topic_if_not_found(self, topic_id: int):
        """如果话题未找到则删除数据库记录"""
        self.topic_repo.delete_topic(topic_id)