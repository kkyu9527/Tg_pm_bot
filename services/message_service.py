"""
消息业务逻辑层
处理消息转发、编辑、媒体组等业务逻辑
"""

import os
import asyncio
from datetime import datetime, timedelta, UTC
from telegram import Message, InputMediaPhoto, InputMediaVideo
from telegram.error import BadRequest, RetryAfter
from repositories.message_repository import MessageRepository
from repositories.user_repository import UserRepository
from repositories.topic_repository import TopicRepository
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db, get_topic_display_name, \
    get_user_display_name_from_object

logger = setup_logger('message_service')


class MessageService:
    """消息业务逻辑服务"""
    
    def __init__(self):
        self.message_repo = MessageRepository()
        self.user_repo = UserRepository()
        self.topic_repo = TopicRepository()
        # 状态存储
        self.edit_states = {}           # 编辑状态缓存
        self.media_group_cache = {}     # 媒体组缓存
    
    async def forward_message(self, message: Message, bot, chat_id: int, thread_id: int = None) -> Message:
        """转发消息到指定聊天和话题"""
        kwargs = {"chat_id": chat_id, "from_chat_id": message.chat_id, "message_id": message.message_id}
        if thread_id:
            kwargs["message_thread_id"] = thread_id

        # 获取用户显示名称用于日志
        from_chat_display = str(message.chat_id)
        to_chat_display = str(chat_id)
        if hasattr(message, 'from_user') and message.from_user:
            from_chat_display = get_user_display_name_from_object(message.from_user)
        
        logger.info(
            f"尝试转发消息: 从 {from_chat_display} 到 {to_chat_display}" + (f", 话题ID: {thread_id}" if thread_id else ""))

        # 尝试最多两次转发
        for attempt in range(2):
            try:
                result = await bot.copy_message(**kwargs)
                logger.info(f"消息转发成功: 消息ID {message.message_id} -> {result.message_id}")
                return result
            except Exception as e:
                error_message = str(e)
                logger.error(f"消息转发失败 (尝试 {attempt + 1}/2): {error_message}")
                if attempt == 0:
                    logger.info("等待1秒后重试")
                    await asyncio.sleep(1)

        logger.warning(f"消息转发最终失败: 消息ID {message.message_id}")
        return None
    
    async def handle_user_message_forward(self, message: Message, user, bot) -> bool:
        """处理用户消息转发"""
        GROUP_ID = os.getenv("GROUP_ID")
        
        # 保存用户信息并确保有话题（避免循环导入）
        from services.user_service import UserService
        from services.topic_service import TopicService
        user_service = UserService()
        topic_service = TopicService()
        
        user_service.register_or_update_user(user)
        topic_id = await topic_service.ensure_user_topic(bot, user)

        # 处理媒体组消息
        if message.media_group_id and (message.photo or message.video):
            return await self._handle_media_group_message(message, user, topic_id, bot)

        # 处理普通消息
        return await self._handle_regular_message_forward(message, user, topic_id, bot, GROUP_ID)
    
    async def _handle_media_group_message(self, message: Message, user, topic_id: int, context) -> bool:
        """处理媒体组消息"""
        key = f"{user.id}:{message.media_group_id}"
        self.media_group_cache.setdefault(key, []).append(message)
        
        # 如果是媒体组的第一条消息，创建延迟处理任务
        if len(self.media_group_cache[key]) == 1:
            asyncio.create_task(self._flush_media_group_after_delay(key, user, topic_id, context))
        return True
    
    async def _flush_media_group_after_delay(self, key: str, user, topic_id: int, context):
        """延迟处理并发送媒体组消息"""
        GROUP_ID = os.getenv("GROUP_ID")
        await asyncio.sleep(2.0)
        
        messages = self.media_group_cache.pop(key, [])
        if not messages:
            logger.warning(f"媒体组缓存为空: {key}")
            return

        user_display = get_user_display_name_from_db(user.id, self.user_repo.user_ops)
        topic_display = get_topic_display_name(topic_id, self.topic_repo.topic_ops)
        logger.info(f"处理媒体组: 用户 {user_display}, 话题 {topic_display}, 消息数量 {len(messages)}")
        
        bot = context.bot
        media_group = []
        for m in sorted(messages, key=lambda x: x.message_id):
            if m.photo:
                media_group.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=m.caption or None))
                logger.debug(f"添加照片到媒体组: 消息ID {m.message_id}")
            elif m.video:
                media_group.append(InputMediaVideo(media=m.video.file_id, caption=m.caption or None))
                logger.debug(f"添加视频到媒体组: 消息ID {m.message_id}")
        
        try:
            logger.info(f"发送媒体组: 用户 {user_display}, 话题 {topic_display}, 媒体数量 {len(media_group)}")
            sent_group = await bot.send_media_group(chat_id=GROUP_ID, message_thread_id=topic_id, media=media_group)
            
            self.message_repo.save_message(
                user.id, topic_id, messages[0].message_id, sent_group[0].message_id, "user_to_owner"
            )
            logger.info(f"媒体组发送成功: 用户 {user_display}, 话题 {topic_display}, 消息ID {sent_group[0].message_id}")
            
        except RetryAfter as e:
            retry_after = e.retry_after
            logger.warning(f"限流：等待 {retry_after} 秒")
            await asyncio.sleep(retry_after + 1)
            logger.info(f"重试发送媒体组: 用户 {user_display}, 话题 {topic_display}")
            return await self._flush_media_group_after_delay(key, user, topic_id, context)
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"媒体组转发失败: {error_message}, 用户: {user_display}, 话题: {topic_display}")
    
    async def _handle_regular_message_forward(self, message: Message, user, topic_id: int, bot, group_id: str) -> bool:
        """处理普通消息转发"""
        try:
            forwarded = await self.forward_message(message, bot, group_id, topic_id)
            if not forwarded:
                user_display = get_user_display_name_from_db(user.id)
                logger.warning(f"用户 {user_display} 的消息转发失败，返回为空")
                return False
                
            # 保存消息记录
            self.message_repo.save_message(
                user.id, topic_id, message.message_id, forwarded.message_id, "user_to_owner"
            )
            
            user_display = get_user_display_name_from_db(user.id, self.user_repo.user_ops)
            topic_display = get_topic_display_name(topic_id, self.topic_repo.topic_ops)
            logger.info(f"已将用户 {user_display} 的消息转发到话题 {topic_display}")
            return True
            
        except BadRequest as e:
            error_message = str(e)
            if "Message thread not found" in error_message:
                return await self._handle_topic_not_found(message, user, topic_id, bot, group_id)
            else:
                user_display = get_user_display_name_from_db(user.id)
                topic_display = get_topic_display_name(topic_id)
                logger.error(f"转发失败: {error_message}, 用户: {user_display}, 话题: {topic_display}")
                return False
    
    async def _handle_topic_not_found(self, message: Message, user, topic_id: int, bot, group_id: str) -> bool:
        """处理话题不存在的情况"""
        topic_display = get_topic_display_name(topic_id)
        logger.warning(f"话题 {topic_display} 未找到，正在重新创建")
        
        # 避免循环导入
        from services.topic_service import TopicService
        topic_service = TopicService()
        
        topic_service.recreate_topic_if_not_found(topic_id)
        new_topic_id = await topic_service.ensure_user_topic(bot, user)
        
        # 重新尝试转发
        forwarded = await self.forward_message(message, bot, group_id, new_topic_id)
        if not forwarded:
            user_display = get_user_display_name_from_db(user.id)
            logger.warning(f"用户 {user_display} 的消息在重新创建话题后转发失败")
            return False
            
        # 保存消息记录
        self.message_repo.save_message(
            user.id, new_topic_id, message.message_id, forwarded.message_id, "user_to_owner"
        )
        
        user_display = get_user_display_name_from_db(user.id, self.user_repo.user_ops)
        topic_display = get_topic_display_name(new_topic_id, self.topic_repo.topic_ops)
        logger.info(f"已将用户 {user_display} 的消息转发到新话题 {topic_display}")
        return True
    
    def save_message_record(self, user_id: int, topic_id: int, user_message_id: int, 
                          group_message_id: int, direction: str) -> bool:
        """保存消息记录"""
        return self.message_repo.save_message(user_id, topic_id, user_message_id, group_message_id, direction)
    
    def cleanup_edit_states(self):
        """清理过期的编辑状态"""
        now = datetime.now(UTC)
        timeout = timedelta(minutes=5)
        old_count = len(self.edit_states)
        
        self.edit_states = {
            uid: state for uid, state in self.edit_states.items()
            if now - state['timestamp'] <= timeout
        }
        
        new_count = len(self.edit_states)
        if old_count > new_count:
            logger.info(f"清理了 {old_count - new_count} 个过期的编辑状态")