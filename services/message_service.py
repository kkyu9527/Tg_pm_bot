"""
消息业务逻辑层
处理消息转发、编辑、媒体组等业务逻辑
"""

import os
import asyncio
from datetime import datetime, timedelta, UTC
from telegram import Message, InputMediaPhoto, InputMediaVideo, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter
from database.db_operations import MessageOperations
from database.db_operations import UserOperations, TopicOperations
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db, get_topic_display_name, get_user_display_name_from_object
from utils.callback_helpers import decode_callback, build_action_keyboard, build_cancel_edit_keyboard, build_edit_done_keyboard, \
    handle_delete_callback, handle_edit_callback, handle_cancel_edit_callback, handle_message_edit_execution

logger = setup_logger('message_service')


class MessageService:
    """消息业务逻辑服务"""
    
    # 回调动作常量
    ACTION_EDIT = "edit"
    ACTION_DELETE = "delete"
    ACTION_CANCEL_EDIT = "cancel_edit"
    
    def __init__(self):
        self.message_ops = MessageOperations()
        self.user_ops = UserOperations()
        self.topic_ops = TopicOperations()
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

        user_display = get_user_display_name_from_db(user.id)
        topic_display = get_topic_display_name(topic_id, self.topic_ops)
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
            
            self.message_ops.save_message(
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
            self.message_ops.save_message(
                user.id, topic_id, message.message_id, forwarded.message_id, "user_to_owner"
            )
            
            user_display = get_user_display_name_from_db(user.id)
            topic_display = get_topic_display_name(topic_id, self.topic_ops)
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
        self.message_ops.save_message(
            user.id, new_topic_id, message.message_id, forwarded.message_id, "user_to_owner"
        )
        
        user_display = get_user_display_name_from_db(user.id)
        topic_display = get_topic_display_name(new_topic_id, self.topic_ops)
        logger.info(f"已将用户 {user_display} 的消息转发到新话题 {topic_display}")
        return True
    

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
    
    async def handle_message_deletion(self, bot, user_id: int, message_id: int) -> dict:
        """处理消息删除操作
        
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'show_edit': bool  # 是否显示编辑按钮
            }
        """
        try:
            await bot.delete_message(chat_id=user_id, message_id=message_id)
            user_display = get_user_display_name_from_db(user_id)
            logger.info(f"已删除发送给用户 {user_display} 的消息 {message_id}")
            return {
                'success': True,
                'message': '✅ 消息已删除',
                'show_edit': False
            }
        except Exception as e:
            error_message = str(e)
            user_display = get_user_display_name_from_db(user_id)
            logger.error(f"删除消息失败: {error_message}, 用户: {user_display}, 消息ID: {message_id}")
            
            if "Message can't be deleted for everyone" in error_message:
                return {
                    'success': False,
                    'message': '⚠️ 删除失败: 消息已超过48小时，无法删除，只能编辑',
                    'show_edit': True
                }
            else:
                return {
                    'success': False,
                    'message': f'⚠️ 删除失败: {error_message}',
                    'show_edit': True
                }
    
    def start_message_edit(self, owner_user_id: int, message_id: int, user_id: int, original_message) -> str:
        """开始消息编辑操作
        
        Returns:
            str: 给用户的提示消息
        """
        self.edit_states[owner_user_id] = {
            "message_id": message_id,
            "user_id": user_id,
            "original_message": original_message,
            "timestamp": datetime.now(UTC)
        }
        user_display = get_user_display_name_from_db(user_id)
        logger.info(f"主人开始编辑发送给用户 {user_display} 的消息 {message_id}")
        return "✏️ 请发送新的消息内容，将替换之前的消息"
    
    def cancel_message_edit(self, owner_user_id: int) -> dict:
        """取消消息编辑操作
        
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'message_id': int,
                'user_id': int
            }
        """
        if owner_user_id in self.edit_states:
            state = self.edit_states.pop(owner_user_id)
            user_display = get_user_display_name_from_db(state['user_id'])
            logger.info(f"主人取消编辑发送给用户 {user_display} 的消息 {state['message_id']}")
            return {
                'success': True,
                'message': '❎ 已取消编辑',
                'message_id': state['message_id'],
                'user_id': state['user_id']
            }
        return {
            'success': False,
            'message': '⚠️ 未找到编辑状态',
            'message_id': None,
            'user_id': None
        }
    
    async def execute_message_edit(self, bot, new_message, state) -> dict:
        """执行消息编辑操作
        
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'message_id': int,
                'show_edit': bool,
                'update_original': bool  # 是否更新原始编辑消息
            }
        """
        user_id = state["user_id"]
        old_id = state["message_id"]
        
        try:
            user_display = get_user_display_name_from_db(user_id)
            logger.info(f"开始编辑用户 {user_display} 的消息 {old_id}")
            
            # 处理文本消息编辑
            if new_message.text:
                try:
                    logger.info(f"编辑文本消息: 用户 {user_display}, 消息ID {old_id}")
                    await bot.edit_message_text(chat_id=user_id, message_id=old_id, text=new_message.text)
                    logger.info(f"文本消息编辑成功: 用户 {user_display}, 消息ID {old_id}")
                    return {
                        'success': True,
                        'message': '✅ 已更新用户消息',
                        'message_id': old_id,
                        'show_edit': True,
                        'update_original': True
                    }
                except Exception as edit_error:
                    edit_error_msg = str(edit_error)
                    logger.error(f"文本消息编辑失败: {edit_error_msg}, 用户: {user_display}, 消息ID: {old_id}")
                    
                    # 检查是否是因为超过48小时导致的编辑失败
                    if "Message can't be edited" in edit_error_msg or "too old" in edit_error_msg:
                        return {
                            'success': False,
                            'message': '⚠️ 编辑失败：消息已超过48小时，无法编辑，只能删除',
                            'message_id': old_id,
                            'show_edit': False,
                            'update_original': True
                        }
                    else:
                        return {
                            'success': False,
                            'message': f'⚠️ 编辑失败：{edit_error_msg}',
                            'message_id': old_id,
                            'show_edit': True,
                            'update_original': True
                        }
            
            # 处理非文本消息（需要删除旧消息并发送新消息）
            else:
                logger.info(f"删除旧消息并发送新消息: 用户 {user_display}, 旧消息ID {old_id}")
                await bot.delete_message(chat_id=user_id, message_id=old_id)
                forwarded = await self.forward_message(new_message, bot, user_id)
                logger.info(f"非文本消息替换成功: 用户 {user_display}, 新消息ID {forwarded.message_id}")
                return {
                    'success': True,
                    'message': '✅ 已重新发送消息',
                    'message_id': forwarded.message_id,
                    'show_edit': bool(new_message.text),
                    'update_original': True
                }
                
        except Exception as e:
            error_message = str(e)
            user_display = get_user_display_name_from_db(user_id)
            logger.error(f"编辑失败: {error_message}, 用户: {user_display}, 消息ID: {old_id}")
            return {
                'success': False,
                'message': f'⚠️ 编辑操作失败：{error_message}',
                'message_id': old_id,
                'show_edit': True,
                'update_original': False
            }
    
    # ============================= 完整流程方法 =============================
    
    async def handle_user_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户发送消息的完整流程"""
        USER_ID = os.getenv("USER_ID")
        
        # 只处理私聊消息且发送者不是主人
        if update.effective_chat.type != "private" or str(update.effective_user.id) == USER_ID:
            return

        user = update.effective_user
        message = update.effective_message
        bot = context.bot

        user_display = get_user_display_name_from_db(user.id)
        logger.info(f"收到用户 {user_display} 的消息")
        
        # 处理消息转发
        await self.handle_user_message_forward(message, user, bot)
    
    async def handle_owner_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人在群组中发送消息的完整流程"""
        USER_ID = os.getenv("USER_ID")
        
        # 清理过期的编辑状态
        self.cleanup_edit_states()
        
        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return

        logger.info("收到主人的消息")

        # 检查主人是否处于编辑状态
        if update.effective_user.id in self.edit_states:
            # 获取并移除编辑状态
            state = self.edit_states.pop(update.effective_user.id)
            logger.info(f"主人正在编辑发送给用户 {state['user_id']} 的消息 {state['message_id']}")
            
            # 执行编辑操作
            await handle_message_edit_execution(context.bot, update.effective_message, state, self)
            return

        # 获取消息对象
        message = update.effective_message
        
        # 只处理话题消息
        if not message.is_topic_message:
            return

        # 查找话题对应的用户
        topic = self.topic_ops.get_topic_by_id(message.message_thread_id)
        if not topic:
            logger.warning(f"无法找到话题 {message.message_thread_id} 对应的用户")
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return

        # 获取用户ID并转发消息
        user_id = topic["user_id"]
        await self._handle_owner_message_forward(message, user_id, context.bot)
    
    async def _handle_owner_message_forward(self, message, user_id: int, bot):
        """处理主人消息转发"""
        try:
            # 转发消息给用户
            forwarded = await self.forward_message(message, bot, user_id)
            if not forwarded:
                user_display = get_user_display_name_from_db(user_id)
                logger.warning(f"主人发送给用户 {user_display} 的消息转发失败，返回为空")
                return
                
            # 保存消息记录
            # 保存消息记录并记录日志
            result = self.message_ops.save_message(
                user_id, message.message_thread_id, forwarded.message_id, message.message_id, "owner_to_user"
            )
            if result:
                user_display = get_user_display_name_from_db(user_id)
                logger.info(f"已将主人的消息转发给用户 {user_display}")
            
            # 发送确认消息并添加操作按钮
            # 只有文本消息才显示编辑按钮，图片、视频等非文本消息不显示编辑按钮
            show_edit = bool(message.text)
            await message.reply_text(
                "✅ 已转发给用户",
                reply_markup=build_action_keyboard(forwarded.message_id, user_id, show_edit)
            )
        except Exception as e:
            # 处理转发失败的情况
            error_message = str(e)
            user_display = get_user_display_name_from_db(user_id)
            logger.error(f"转发失败: {error_message}, 用户: {user_display}")
            await message.reply_text(f"⚠️ 转发失败: {error_message}")
    
    async def handle_button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调的完整流程"""
        # 清理过期的编辑状态
        self.cleanup_edit_states()
        
        query = update.callback_query
        await query.answer()
        
        # 解析回调数据
        try:
            data = decode_callback(query.data)
            logger.info(f"收到按钮回调: {data['action']}, 消息ID: {data['message_id']}, 用户ID: {data['user_id']}")
        except Exception as e:
            logger.error(f"回调数据解析失败: {e}")
            return

        action = data["action"]
        message_id = data["message_id"]
        user_id = data["user_id"]

        # 分发处理不同的按钮操作
        if action == self.ACTION_DELETE:
            await handle_delete_callback(query, context.bot, message_id, user_id, self)
        elif action == self.ACTION_EDIT:
            await handle_edit_callback(query, message_id, user_id, self)
        elif action == self.ACTION_CANCEL_EDIT:
            await handle_cancel_edit_callback(query, context.bot, self)
