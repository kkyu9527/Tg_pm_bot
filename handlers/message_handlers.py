import os
import json
import asyncio
from datetime import datetime, timedelta, UTC
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, Message
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter
from dotenv import load_dotenv
from database.db_operations import UserOperations, TopicOperations, MessageOperations
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db, get_topic_display_name

load_dotenv()

# 全局常量
GROUP_ID = os.getenv("GROUP_ID")
USER_ID = os.getenv("USER_ID")
logger = setup_logger('messages')


def encode_callback(action, message_id, user_id, compact=False):
    """将回调数据编码为JSON字符串
    
    Args:
        action: 操作类型
        message_id: 消息ID
        user_id: 用户ID
        compact: 是否使用紧凑格式
        
    Returns:
        编码后的JSON字符串
    """
    data = {
        ("a" if compact else "action"): action,
        ("m" if compact else "message_id"): message_id,
        ("u" if compact else "user_id"): user_id
    }
    return json.dumps(data, separators=(',', ':') if compact else None)


def decode_callback(data):
    """将JSON字符串解码为回调数据
    
    Args:
        data: 编码的JSON字符串
        
    Returns:
        包含action、message_id和user_id的字典
    """
    obj = json.loads(data)
    return {
        "action": obj.get("action") or obj.get("a"),
        "message_id": obj.get("message_id") or obj.get("m"),
        "user_id": obj.get("user_id") or obj.get("u")
    }

class MessageHandlers:
    """消息处理器类，负责处理用户和主人之间的消息交互"""
    
    # 回调动作常量
    ACTION_EDIT = "edit"              # 编辑消息
    ACTION_DELETE = "delete"          # 删除消息
    ACTION_CANCEL_EDIT = "cancel_edit"  # 取消编辑

    # 状态存储
    edit_states = {}                 # 编辑状态缓存 {user_id: {message_id, original_text, timestamp}}
    media_group_cache = {}           # 媒体组缓存
    logger = logger                  # 日志记录器

    @staticmethod
    def build_cancel_edit_keyboard(message_id, user_id):
        """构建取消编辑的内联键盘
        
        Args:
            message_id: 消息ID
            user_id: 用户ID
            
        Returns:
            包含取消编辑按钮的内联键盘
        """
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "取消编辑", 
                callback_data=encode_callback(MessageHandlers.ACTION_CANCEL_EDIT, message_id, user_id, compact=True)
            )
        ]])

    @staticmethod
    def build_action_keyboard(message_id, user_id):
        """构建消息操作的内联键盘
        
        Args:
            message_id: 消息ID
            user_id: 用户ID
            
        Returns:
            包含编辑和删除按钮的内联键盘
        """
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "编辑",
                callback_data=encode_callback(MessageHandlers.ACTION_EDIT, message_id, user_id)
            ),
            InlineKeyboardButton(
                "删除",
                callback_data=encode_callback(MessageHandlers.ACTION_DELETE, message_id, user_id)
            )
        ]])

    @staticmethod
    def build_edit_done_keyboard():
        """构建编辑完成的空内联键盘
        
        Returns:
            空的内联键盘（移除编辑按钮）
        """
        return InlineKeyboardMarkup([])

    @staticmethod
    def cleanup_edit_states():
        """清理过期的编辑状态（超过5分钟未完成的编辑）"""
        now = datetime.now(UTC)
        timeout = timedelta(minutes=5)
        old_count = len(MessageHandlers.edit_states)
        
        # 过滤保留未超时的编辑状态
        MessageHandlers.edit_states = {
            uid: state for uid, state in MessageHandlers.edit_states.items()
            if now - state['timestamp'] <= timeout
        }
        
        # 记录清理结果
        new_count = len(MessageHandlers.edit_states)
        if old_count > new_count:
            MessageHandlers.logger.info(f"清理了 {old_count - new_count} 个过期的编辑状态")

    @staticmethod
    async def forward_content(message: Message, bot, chat_id: int, thread_id: int = None):
        """转发消息内容到指定聊天和话题
        
        Args:
            message: 要转发的消息对象
            bot: 机器人实例
            chat_id: 目标聊天ID
            thread_id: 目标话题ID（可选）
            
        Returns:
            成功时返回转发的消息对象，失败时返回None
        """
        # 准备转发参数
        kwargs = {"chat_id": chat_id, "from_chat_id": message.chat_id, "message_id": message.message_id}
        if thread_id:
            kwargs["message_thread_id"] = thread_id

        logger.info(
            f"尝试转发消息: 从 {message.chat_id} 到 {chat_id}" + (f", 话题ID: {thread_id}" if thread_id else ""))

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

    @staticmethod
    async def flush_media_group_after_delay(key, user, topic_id, context):
        """延迟处理并发送媒体组消息
        
        Args:
            key: 媒体组缓存键
            user: 用户对象
            topic_id: 话题ID
            context: 上下文对象
        """
        # 等待2秒，确保媒体组中的所有消息都已收集完毕
        await asyncio.sleep(2.0)
        
        # 从缓存中获取并移除媒体组消息
        messages = MessageHandlers.media_group_cache.pop(key, [])
        if not messages:
            logger.warning(f"媒体组缓存为空: {key}")
            return

        user_display = get_user_display_name_from_db(user.id, UserOperations())
        topic_display = get_topic_display_name(topic_id, TopicOperations())
        logger.info(f"处理媒体组: 用户 {user_display}, 话题 {topic_display}, 消息数量 {len(messages)}")
        bot = context.bot
        
        # 构建媒体组
        media_group = []
        for m in sorted(messages, key=lambda x: x.message_id):  # 按消息ID排序确保顺序一致
            if m.photo:
                media_group.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=m.caption or None))
                logger.debug(f"添加照片到媒体组: 消息ID {m.message_id}")
            elif m.video:
                media_group.append(InputMediaVideo(media=m.video.file_id, caption=m.caption or None))
                logger.debug(f"添加视频到媒体组: 消息ID {m.message_id}")
                
        # 尝试发送媒体组
        try:
            logger.info(f"发送媒体组: 用户 {user_display}, 话题 {topic_display}, 媒体数量 {len(media_group)}")
            sent_group = await bot.send_media_group(chat_id=GROUP_ID, message_thread_id=topic_id, media=media_group)
            
            # 保存消息记录
            MessageOperations().save_message(
                user.id, topic_id, messages[0].message_id, sent_group[0].message_id, "user_to_owner"
            )
            logger.info(f"媒体组发送成功: 用户 {user_display}, 话题 {topic_display}, 消息ID {sent_group[0].message_id}")
            
        except RetryAfter as e:
            # 处理限流情况
            retry_after = e.retry_after
            logger.warning(f"限流：等待 {retry_after} 秒")
            await asyncio.sleep(retry_after + 1)
            logger.info(f"重试发送媒体组: 用户 {user_display}, 话题 {topic_display}")
            return await MessageHandlers.flush_media_group_after_delay(key, user, topic_id, context)
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"媒体组转发失败: {error_message}, 用户: {user_display}, 话题: {topic_display}")

    @staticmethod
    async def ensure_topic(bot, user, topic_ops):
        """确保用户有对应的话题，如果没有则创建新话题
        
        Args:
            bot: 机器人实例
            user: 用户对象
            topic_ops: 话题操作对象
            
        Returns:
            话题ID
        """
        # 检查用户是否已有话题
        topic = topic_ops.get_user_topic(user.id)
        if topic:
            user_display = get_user_display_name_from_db(user.id, UserOperations())
            topic_display = get_topic_display_name(topic['topic_id'], topic_ops)
            logger.info(f"找到用户 {user_display} 的现有话题: {topic_display}")
            return topic["topic_id"]

        # 创建新话题
        topic_name = f"{user.first_name} {(user.last_name or '')}".strip() + f" (ID: {user.id})"
        username = f"@{user.username}" if user.username else "无用户名"
        user_display = get_user_display_name_from_db(user.id)
        logger.info(f"为用户 {user_display} 创建新话题: {topic_name}")
        topic_id = (await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name)).message_thread_id
        topic_ops.save_topic(user.id, topic_id, topic_name)
        user_display = get_user_display_name_from_db(user.id, UserOperations())
        topic_display = get_topic_display_name(topic_id, topic_ops)
        logger.info(f"话题创建成功: 用户 {user_display}, 话题 {topic_display}")

        # 准备用户信息文本
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
                sent_msg = await bot.send_photo(GROUP_ID, photo=photos.photos[0][-1].file_id,
                                                message_thread_id=topic_id, caption=info_text, parse_mode="HTML")
            else:
                logger.info(f"用户 {user.id} 无头像")
                raise Exception("无头像")
        except Exception as e:
            logger.warning(f"获取用户头像失败: {e}，发送纯文本信息")
            sent_msg = await bot.send_message(GROUP_ID, text=info_text, message_thread_id=topic_id, parse_mode="HTML")

        # 尝试置顶用户信息
        try:
            logger.info(f"尝试置顶用户信息: 话题 {topic_id}, 消息ID {sent_msg.message_id}")
            await bot.pin_chat_message(chat_id=GROUP_ID, message_id=sent_msg.message_id)
            logger.info(f"消息置顶成功: 话题 {topic_id}, 消息ID {sent_msg.message_id}")
        except Exception as e:
            error_message = str(e)
            logger.warning(f"置顶失败: {error_message}, 话题ID: {topic_id}, 消息ID: {sent_msg.message_id}")

        return topic_id

    @staticmethod
    async def edit_user_message(bot, new_message, state, user):
        """编辑发送给用户的消息
        
        Args:
            bot: 机器人实例
            new_message: 新消息对象
            state: 编辑状态信息
            user: 用户对象
        """
        user_id = state["user_id"]
        old_id = state["message_id"]
        original_msg = state["original_message"]
        
        try:
            logger.info(f"开始编辑用户 {user_id} {user.first_name}{user.last_name}的消息 {old_id}")
            
            # 处理文本消息编辑
            if new_message.text:
                logger.info(f"编辑文本消息: 用户 {user_id} {user.first_name}{user.last_name}, 消息ID {old_id}")
                await bot.edit_message_text(chat_id=user_id, message_id=old_id, text=new_message.text)
                reply_text = "✅ 已更新用户消息"
                msg_id = old_id
                logger.info(f"文本消息编辑成功: 用户 {user_id} {user.first_name}{user.last_name}, 消息ID {old_id}")
            
            # 处理非文本消息（需要删除旧消息并发送新消息）
            else:
                logger.info(f"删除旧消息并发送新消息: 用户 {user_id}, 旧消息ID {old_id}")
                await bot.delete_message(chat_id=user_id, message_id=old_id)
                forwarded = await MessageHandlers.forward_content(new_message, bot, user_id)
                reply_text = "✅ 已重新发送消息"
                msg_id = forwarded.message_id
                logger.info(f"非文本消息替换成功: 用户 {user_id} {user.first_name}{user.last_name}, 新消息ID {msg_id}")

            # 更新原始编辑消息状态
            if original_msg and original_msg.chat_id and original_msg.message_id:
                logger.info(f"更新原始编辑消息: 聊天ID {original_msg.chat_id}, 消息ID {original_msg.message_id}")
                await bot.edit_message_text(
                    chat_id=original_msg.chat_id,
                    message_id=original_msg.message_id,
                    text="✏️ 编辑完成",
                    reply_markup=MessageHandlers.build_edit_done_keyboard()
                )

            # 发送编辑完成的确认消息
            await new_message.reply_text(
                reply_text,
                reply_markup=MessageHandlers.build_action_keyboard(msg_id, user_id)
            )
            logger.info(f"已完成编辑用户 {user_id} 的消息, 最终消息ID: {msg_id}")
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"编辑失败: {error_message}, 用户ID: {user_id}, 消息ID: {old_id}")

    @staticmethod
    async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户发送的消息
        
        Args:
            update: 更新对象
            context: 上下文对象
        """
        # 只处理私聊消息且发送者不是主人
        if update.effective_chat.type != "private" or str(update.effective_user.id) == USER_ID:
            return

        user = update.effective_user
        message = update.effective_message
        bot = context.bot

        user_display = get_user_display_name_from_db(user.id)
        logger.info(f"收到用户 {user_display} 的消息")
        
        # 保存用户信息并确保用户有对应的话题
        UserOperations().save_user(user.id, user.first_name, user.last_name, user.username)
        topic_id = await MessageHandlers.ensure_topic(bot, user, TopicOperations())

        # 处理媒体组消息（照片或视频）
        if message.media_group_id and (message.photo or message.video):
            key = f"{user.id}:{message.media_group_id}"
            MessageHandlers.media_group_cache.setdefault(key, []).append(message)
            
            # 如果是媒体组的第一条消息，创建延迟处理任务
            if len(MessageHandlers.media_group_cache[key]) == 1:
                import asyncio
                asyncio.create_task(MessageHandlers.flush_media_group_after_delay(key, user, topic_id, context))
            return

        # 处理普通消息
        try:
            # 转发消息到群组话题
            forwarded = await MessageHandlers.forward_content(message, bot, GROUP_ID, topic_id)
            if not forwarded:
                logger.warning(f"用户 {user.id} 的消息转发失败，返回为空")
                return
                
            # 保存消息记录
            MessageOperations().save_message(
                user.id, 
                topic_id, 
                message.message_id, 
                forwarded.message_id,
                "user_to_owner"
            )
            user_display = get_user_display_name_from_db(user.id, UserOperations())
            topic_display = get_topic_display_name(topic_id, TopicOperations())
            logger.info(f"已将用户 {user_display} 的消息转发到话题 {topic_display}")
            
        except BadRequest as e:
            error_message = str(e)
            
            # 处理话题不存在的情况
            if "Message thread not found" in error_message:
                logger.warning(f"话题 {topic_id} 未找到，正在重新创建")
                TopicOperations().delete_topic(topic_id)
                topic_id = await MessageHandlers.ensure_topic(bot, user, TopicOperations())
                
                # 重新尝试转发
                forwarded = await MessageHandlers.forward_content(message, bot, GROUP_ID, topic_id)
                if not forwarded:
                    logger.warning(f"用户 {user.id} 的消息在重新创建话题后转发失败")
                    return
                    
                # 保存消息记录
                MessageOperations().save_message(
                    user.id, 
                    topic_id, 
                    message.message_id, 
                    forwarded.message_id,
                    "user_to_owner"
                )
                logger.info(f"已将用户 {user.id} 的消息转发到新话题 {topic_id}")
            else:
                logger.error(f"转发失败: {error_message}, 用户ID: {user.id}, 话题ID: {topic_id}")

    @staticmethod
    async def handle_owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人在群组中发送的消息
        
        处理主人在群组话题中的消息，包括编辑状态下的消息处理和普通消息的转发。
        只处理群组中的消息，且发送者必须是主人。
        
        Args:
            update: 更新对象，包含消息和用户信息
            context: 上下文对象，包含机器人实例
        """
        # 清理过期的编辑状态
        MessageHandlers.cleanup_edit_states()
        
        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return

        logger.info(f"收到主人的消息")

        # 检查主人是否处于编辑状态
        if update.effective_user.id in MessageHandlers.edit_states:
            # 获取并移除编辑状态
            state = MessageHandlers.edit_states.pop(update.effective_user.id)
            logger.info(f"主人正在编辑发送给用户 {state['user_id']} 的消息 {state['message_id']}")
            
            # 执行编辑操作
            await MessageHandlers.edit_user_message(context.bot, update.effective_message, state)
            return

        # 获取消息对象
        message = update.effective_message
        
        # 只处理话题消息
        if not message.is_topic_message:
            return

        # 查找话题对应的用户
        topic = TopicOperations().get_topic_by_id(message.message_thread_id)
        if not topic:
            logger.warning(f"无法找到话题 {message.message_thread_id} 对应的用户")
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return

        # 获取用户ID并转发消息
        user_id = topic["user_id"]
        try:
            # 转发消息给用户
            forwarded = await MessageHandlers.forward_content(message, context.bot, user_id)
            if not forwarded:
                logger.warning(f"主人发送给用户 {user_id} 的消息转发失败，返回为空")
                return
                
            # 保存消息记录
            MessageOperations().save_message(
                user_id, 
                message.message_thread_id, 
                forwarded.message_id,
                message.message_id, 
                "owner_to_user"
            )
            
            logger.info(f"已将主人的消息转发给用户 {user_id}")
            
            # 发送确认消息并添加操作按钮
            await message.reply_text(
                "✅ 已转发给用户",
                reply_markup=MessageHandlers.build_action_keyboard(forwarded.message_id, user_id)
            )
        except Exception as e:
            # 处理转发失败的情况
            error_message = str(e)
            logger.error(f"转发失败: {error_message}, 用户ID: {user_id}")
            await message.reply_text(f"⚠️ 转发失败: {error_message}")

    @staticmethod
    async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调
        
        处理主人点击消息操作按钮（删除或编辑）的回调请求。
        
        Args:
            update: 更新对象，包含回调查询信息
            context: 上下文对象，包含机器人实例
        """
        # 清理过期的编辑状态
        MessageHandlers.cleanup_edit_states()
        
        # 获取回调查询对象并应答
        query = update.callback_query
        await query.answer()
        
        # 解析回调数据
        try:
            data = decode_callback(query.data)
            logger.info(f"收到按钮回调: {data['action']}, 消息ID: {data['message_id']}, 用户ID: {data['user_id']}")
        except Exception as e:
            logger.error(f"回调数据解析失败: {e}")
            return

        # 提取回调数据
        action = data["action"]
        message_id = data["message_id"]
        user_id = data["user_id"]

        # 处理删除消息操作
        if action == MessageHandlers.ACTION_DELETE:
            try:
                # 尝试删除发送给用户的消息
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
                await query.edit_message_text("✅ 消息已删除")
                logger.info(f"已删除发送给用户 {user_id} 的消息 {message_id}")
            except Exception as e:
                # 处理删除失败的情况
                error_message = str(e)
                logger.error(f"删除消息失败: {error_message}, 用户ID: {user_id}, 消息ID: {message_id}")
                
                # 特殊处理48小时后无法删除的情况
                if "Message can't be deleted for everyone" in error_message:
                    await query.edit_message_text(
                        f"⚠️ 删除失败: 消息已超过48小时，无法删除，只能编辑",
                        reply_markup=MessageHandlers.build_action_keyboard(message_id, user_id)
                    )
                else:
                    # 处理其他删除失败的情况
                    await query.edit_message_text(
                        f"⚠️ 删除失败: {error_message}",
                        reply_markup=MessageHandlers.build_action_keyboard(message_id, user_id)
                    )
        
        # 处理编辑消息操作
        elif action == MessageHandlers.ACTION_EDIT:
            # 创建编辑状态
            MessageHandlers.edit_states[query.from_user.id] = {
                "message_id": message_id,
                "user_id": user_id,
                "original_message": query.message,
                "timestamp": datetime.now(UTC)
            }
            logger.info(f"主人开始编辑发送给用户 {user_id} 的消息 {message_id}")
            await query.edit_message_text(
                "✏️ 请发送新的消息内容，将替换之前的消息",
                reply_markup=MessageHandlers.build_cancel_edit_keyboard(message_id, user_id)
            )
        elif action == MessageHandlers.ACTION_CANCEL_EDIT:
            if query.from_user.id in MessageHandlers.edit_states:
                state = MessageHandlers.edit_states.pop(query.from_user.id)
                logger.info(f"主人取消编辑发送给用户 {state['user_id']} 的消息 {state['message_id']}")
                await query.edit_message_text(
                    "❎ 已取消编辑",
                    reply_markup=MessageHandlers.build_action_keyboard(state["message_id"], state["user_id"])
                )

    @staticmethod
    async def handle_owner_delete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人删除话题的请求
        
        处理主人在群组中删除用户话题的请求，包括从Telegram和数据库中删除话题。
        只处理群组中的话题消息，且发送者必须是主人。
        
        Args:
            update: 更新对象，包含消息和用户信息
            context: 上下文对象，包含机器人实例
        """
        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return
            
        # 只处理话题消息
        if not update.message.is_topic_message:
            return

        logger.info(f"主人尝试删除话题")

        # 获取话题ID并验证其存在性
        topic_id = update.effective_message.message_thread_id
        if not TopicOperations().get_topic_by_id(topic_id):
            logger.warning(f"话题 {topic_id} 在数据库中不存在")
            await update.effective_message.reply_text("⚠️ 此话题在数据库中不存在")
            return

        # 尝试从Telegram删除话题
        try:
            await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception as e:
            logger.warning(f"Telegram 话题删除失败: {e}")
            
        # 尝试从数据库获取话题信息
        try:
            # 再次检查话题是否存在
            topic = TopicOperations().get_topic_by_id(topic_id)
            if not topic:
                await update.effective_message.reply_text("⚠️ 数据库中未找到话题，跳过清理")
                return

            # 从数据库中删除话题
            TopicOperations().delete_topic(topic_id)
            logger.info(f"主人删除了话题 {topic_id} 以及相关数据库记录")
            await update.effective_message.reply_text("✅ 话题已删除")
        except Exception as e:
            # 处理数据库删除失败的情况
            logger.error(f"从数据库中删除话题失败: {e}")
            await update.effective_message.reply_text(f"⚠️ 从数据库中删除话题失败: {e}")
