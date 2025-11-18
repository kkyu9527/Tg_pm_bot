"""
话题业务逻辑层
处理话题相关的业务逻辑
"""

import os
from telegram import User, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
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
            
            # 检查现有话题是否在当前配置的群组中
            current_group_id = self.GROUP_ID
            existing_group_id = topic.get('group_id')
            
            # 如果群组ID不匹配或者没有群组ID记录，则需要更新话题
            if existing_group_id != current_group_id:
                if existing_group_id is None and current_group_id is not None:
                    # 旧话题没有group_id，更新它而不是删除重建
                    logger.info(f"更新用户 {user_display} 的旧话题，添加群组ID: {current_group_id}")
                    self.topic_ops.save_topic(user.id, topic['topic_id'], topic['topic_name'], current_group_id)
                    logger.info(f"用户 {user_display} 的话题已更新群组ID")
                    return topic["topic_id"]
                else:
                    logger.info(f"检测到群组切换: 旧群组 {existing_group_id} -> 新群组 {current_group_id}，为用户 {user_display} 重新创建话题")
                    
                    # 删除旧话题相关的所有记录
                    try:
                        self.topic_ops.delete_topic(topic['topic_id'])
                        logger.info(f"已删除用户 {user_display} 的旧话题记录")
                    except Exception as e:
                        logger.warning(f"删除旧话题记录时出错: {e}")
                    
                    # 清除topic变量，以便后续创建新话题
                    topic = None
            else:
                # 群组ID匹配，检查话题是否在Telegram中实际存在
                try:
                    # 尝试编辑话题来验证话题是否存在
                    # 如果话题不存在，会抛出 BadRequest 异常
                    await bot.edit_forum_topic(chat_id=self.GROUP_ID, message_thread_id=topic["topic_id"], name=topic["topic_name"])
                    logger.info(f"用户 {user_display} 的话题已在当前群组中，直接使用")
                    return topic["topic_id"]
                except BadRequest as e:
                    error_message = str(e).lower()
                    if "message thread not found" in error_message or "not enough rights" in error_message:
                        logger.warning(f"用户 {user_display} 的话题在Telegram中不存在或无权限访问，将重新创建")
                        # 删除数据库中的旧话题记录
                        try:
                            self.topic_ops.delete_topic(topic['topic_id'])
                            logger.info(f"已删除用户 {user_display} 的旧话题记录")
                        except Exception as delete_error:
                            logger.warning(f"删除旧话题记录时出错: {delete_error}")
                        # 清除topic变量，以便后续创建新话题
                        topic = None
                    else:
                        # 其他错误，重新抛出
                        raise
                except Exception as e:
                    logger.error(f"检查话题存在性时出错: {e}")
                    # 如果检查失败，仍然尝试使用现有话题，避免不必要的重新创建
                    logger.info(f"用户 {user_display} 的话题将直接使用（检查失败时的保守策略）")
                    return topic["topic_id"]

        # 确保GROUP_ID不为None
        if not self.GROUP_ID:
            logger.error("GROUP_ID未配置")
            raise ValueError("GROUP_ID未配置")

        # 创建新话题
        topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
        username = f"@{user.username}" if user.username else "无用户名"
        user_display = get_user_display_name_from_db(user.id, self.user_ops)
        logger.info(f"为用户 {user_display} 创建新话题: {topic_name}")
        
        # 通过Telegram API创建话题
        try:
            topic_id = (await bot.create_forum_topic(chat_id=self.GROUP_ID, name=topic_name)).message_thread_id
        except Exception as e:
            logger.error(f"创建话题失败: {e}")
            # 如果创建话题失败，尝试使用默认话题或返回错误
            raise Exception(f"无法为用户 {user_display} 创建话题: {e}")
        
        # 保存话题信息，包含当前群组ID
        try:
            self.topic_ops.save_topic(user.id, topic_id, topic_name, self.GROUP_ID)
        except Exception as e:
            logger.error(f"保存话题信息失败: {e}")
            # 如果保存失败，尝试删除刚创建的话题
            try:
                await bot.delete_forum_topic(chat_id=self.GROUP_ID, message_thread_id=topic_id)
            except:
                pass
            raise Exception(f"无法保存话题信息: {e}")
        
        user_display = get_user_display_name_from_db(user.id, self.user_ops)
        topic_display = get_topic_display_name(topic_id, self.topic_ops)
        logger.info(f"话题创建成功: 用户 {user_display}, 话题 {topic_display}")

        # 发送用户信息卡片
        try:
            await self._send_user_info_card(bot, user, topic_id, username, self.GROUP_ID)
        except Exception as e:
            logger.warning(f"发送用户信息卡片失败: {e}")
            # 不要因为发送信息卡片失败而影响整个流程
        
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
        if not update.effective_chat or not update.effective_user:
            return
            
        if update.effective_chat.type == "private" or str(update.effective_user.id) != self.USER_ID:
            return
            
        # 只处理话题消息
        if not update.message or not update.message.is_topic_message:
            return

        logger.info("主人尝试删除话题")

        if not update.effective_message or not self.GROUP_ID:
            return
            
        topic_id = update.effective_message.message_thread_id
        if topic_id is not None:
            result = await self.handle_topic_deletion(context.bot, topic_id, self.GROUP_ID or "")
            logger.info(f"话题删除操作完成: {result['message']}")