from telegram import Update, Message, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from database.db_operations import UserOperations, TopicOperations, MessageOperations
from utils.logger import setup_logger
import os
from dotenv import load_dotenv
from telegram.error import BadRequest

# 加载环境变量
load_dotenv()

# 获取群组ID
GROUP_ID = os.getenv('GROUP_ID')
USER_ID = os.getenv('USER_ID')

# 设置日志记录器
logger = setup_logger('messages', 'logs/messages.log')

class MessageHandlers:
    """处理用户消息的类"""
    
    @staticmethod
    async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户发送给机器人的消息"""
        # 忽略来自群组的消息
        if update.effective_chat.type != "private":
            return
            
        # 忽略主人的消息（主人的消息在群组中处理）
        if str(update.effective_user.id) == USER_ID:
            return
            
        user = update.effective_user
        message = update.effective_message
        
        logger.info(f"收到用户 {user.id} ({user.first_name}) 的消息")
        
        # 保存用户信息到数据库
        user_ops = UserOperations()
        user_ops.save_user(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username
        )
        
        # 检查用户是否已有话题，如果没有则创建
        topic_ops = TopicOperations()
        topic = topic_ops.get_user_topic(user.id)
        
        # 标记是否需要创建新话题
        need_create_topic = False
        
        if not topic:
            need_create_topic = True
        else:
            topic_id = topic['topic_id']
            # 尝试验证话题是否存在
            try:
                # 发送一个测试消息来验证话题是否存在
                bot = context.bot
                test_msg = await bot.send_message(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    text="验证话题存在性"
                )
                # 如果成功发送，则立即删除测试消息
                await bot.delete_message(
                    chat_id=GROUP_ID,
                    message_id=test_msg.message_id
                )
            except BadRequest as e:
                if "Message thread not found" in str(e):
                    logger.warning(f"话题 {topic_id} 不存在，将创建新话题")
                    need_create_topic = True
                else:
                    # 其他错误，直接抛出
                    raise
            
        # 确定消息类型
        message_type = MessageHandlers._determine_message_type(message)
        
        # 转发消息到群组话题
        bot = context.bot
        
        # 构建用户显示名称
        if user.username:
            user_display = f"@{user.username}"
        else:
            user_display = user.first_name
            if user.last_name:
                user_display += f" {user.last_name}"
        
        # 如果需要创建新话题
        if need_create_topic:
            # 创建话题名称
            topic_name = f"{user.first_name}"
            if user.last_name:
                topic_name += f" {user.last_name}"
            topic_name += f" (ID: {user.id})"
            
            # 在群组中创建话题
            forum_topic = await bot.create_forum_topic(
                chat_id=GROUP_ID,
                name=topic_name
            )
            
            # 保存话题信息到数据库
            topic_id = forum_topic.message_thread_id
            topic_ops.save_topic(
                user_id=user.id,
                topic_id=topic_id,
                topic_name=topic_name
            )
            
            # 发送初始消息到话题
            await bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                text=f"用户 {topic_name} 开始了新的对话。"
            )
            
            logger.info(f"为用户 {user.id} 创建了新话题 {topic_id}")
            
        # 发送通知消息
        try:
            forwarded_msg = await bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                text=f"{user_display} 发来了一条 {message_type} 消息。"
            )
            
            # 根据消息类型转发实际内容
            if message.text:
                await bot.send_message(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    text=message.text
                )
            elif message.photo:
                await bot.send_photo(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption
                )
            elif message.video:
                await bot.send_video(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    video=message.video.file_id,
                    caption=message.caption
                )
            elif message.voice:
                await bot.send_voice(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    voice=message.voice.file_id,
                    caption=message.caption
                )
            elif message.audio:
                await bot.send_audio(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    audio=message.audio.file_id,
                    caption=message.caption
                )
            elif message.document:
                await bot.send_document(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    document=message.document.file_id,
                    caption=message.caption
                )
            elif message.sticker:
                await bot.send_sticker(
                    chat_id=GROUP_ID,
                    message_thread_id=topic_id,
                    sticker=message.sticker.file_id
                )
            # 可以根据需要添加更多类型的处理
            
            # 保存消息记录到数据库
            msg_ops = MessageOperations()
            msg_ops.save_message(
                user_id=user.id,
                topic_id=topic_id,
                message_type=message_type,
                user_message_id=message.message_id,
                group_message_id=forwarded_msg.message_id,
                direction="user_to_owner"
            )
            
            logger.info(f"已将用户 {user.id} 的 {message_type} 消息转发到话题 {topic_id}")
        except BadRequest as e:
            if "Message thread not found" in str(e):
                logger.error(f"话题 {topic_id} 不存在，尝试重新创建话题失败")
                # 这里可以添加重试逻辑或通知管理员
            else:
                # 其他错误，直接抛出
                raise
    
    @staticmethod
    async def handle_owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人在群组话题中发送的消息"""
        # 忽略来自私聊的消息
        if update.effective_chat.type == "private":
            return
            
        # 忽略非主人的消息
        if str(update.effective_user.id) != USER_ID:
            return
            
        # 忽略非话题消息
        if not update.message.is_topic_message:
            return
            
        message = update.effective_message
        topic_id = message.message_thread_id
        
        logger.info(f"收到主人在话题 {topic_id} 中的消息")
        
        # 查找话题对应的用户
        topic_ops = TopicOperations()
        topic = topic_ops.get_topic_by_id(topic_id)
        
        if not topic:
            logger.warning(f"找不到话题 {topic_id} 对应的用户")
            await message.reply_text("⚠️ 无法找到此话题对应的用户，可能是数据库记录丢失。")
            return
            
        user_id = topic['user_id']
        
        # 确定消息类型
        message_type = MessageHandlers._determine_message_type(message)
        
        # 转发消息给用户
        bot = context.bot
        
        try:
            # 根据消息类型转发实际内容
            if message.text:
                forwarded_msg = await bot.send_message(
                    chat_id=user_id,
                    text=message.text
                )
            elif message.photo:
                forwarded_msg = await bot.send_photo(
                    chat_id=user_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption
                )
            elif message.video:
                forwarded_msg = await bot.send_video(
                    chat_id=user_id,
                    video=message.video.file_id,
                    caption=message.caption
                )
            elif message.voice:
                forwarded_msg = await bot.send_voice(
                    chat_id=user_id,
                    voice=message.voice.file_id,
                    caption=message.caption
                )
            elif message.audio:
                forwarded_msg = await bot.send_audio(
                    chat_id=user_id,
                    audio=message.audio.file_id,
                    caption=message.caption
                )
            elif message.document:
                forwarded_msg = await bot.send_document(
                    chat_id=user_id,
                    document=message.document.file_id,
                    caption=message.caption
                )
            elif message.sticker:
                forwarded_msg = await bot.send_sticker(
                    chat_id=user_id,
                    sticker=message.sticker.file_id
                )
            else:
                await message.reply_text("⚠️ 不支持的消息类型，无法转发给用户。")
                return
                
            # 保存消息记录到数据库
            msg_ops = MessageOperations()
            msg_ops.save_message(
                user_id=user_id,
                topic_id=topic_id,
                message_type=message_type,
                user_message_id=forwarded_msg.message_id,
                group_message_id=message.message_id,
                direction="owner_to_user"
            )
            
            # 创建内联键盘按钮
            keyboard = [
                [
                    InlineKeyboardButton("编辑", callback_data=f"edit_{forwarded_msg.message_id}_{user_id}"),
                    InlineKeyboardButton("删除", callback_data=f"delete_{forwarded_msg.message_id}_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 在消息下方添加一个小小的回复标记，并带有按钮
            await message.reply_text(
                "✅ 已转发给用户",
                reply_markup=reply_markup
            )
            
            logger.info(f"已将主人的 {message_type} 消息转发给用户 {user_id}")
            
        except Exception as e:
            logger.error(f"转发消息给用户 {user_id} 时出错: {e}")
            await message.reply_text(f"⚠️ 转发消息失败: {str(e)}")
    
    @staticmethod
    async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调"""
        query = update.callback_query
        await query.answer()  # 回应回调查询
        
        # 解析回调数据
        data = query.data.split("_")
        action = data[0]
        message_id = int(data[1])
        user_id = int(data[2])
        
        if action == "delete":
            try:
                # 删除发送给用户的消息
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=message_id
                )
                
                # 更新按钮文本，表示已删除
                await query.edit_message_text(
                    "✅ 消息已删除",
                    reply_markup=None
                )
                
                logger.info(f"已删除发送给用户 {user_id} 的消息 {message_id}")
            except Exception as e:
                logger.error(f"删除消息时出错: {e}")
                await query.edit_message_text(
                    f"⚠️ 删除消息失败: {str(e)}",
                    reply_markup=None
                )
        
        elif action == "edit":
            # 编辑功能暂不实现
            await query.edit_message_text(
                "⚠️ 编辑功能暂未实现",
                reply_markup=query.message.reply_markup
            )
    
    @staticmethod
    def _determine_message_type(message: Message) -> str:
        """确定消息类型"""
        if message.text:
            return "文本"
        elif message.photo:
            return "图片"
        elif message.video:
            return "视频"
        elif message.voice:
            return "语音"
        elif message.audio:
            return "音频"
        elif message.document:
            return "文件"
        elif message.location:
            return "定位"
        elif message.poll:
            return "投票"
        elif message.sticker:
            return "贴纸"
        elif message.animation:
            return "动画"
        elif message.contact:
            return "联系人"
        elif message.dice:
            return "骰子"
        elif message.game:
            return "游戏"
        elif message.venue:
            return "场所"
        elif message.video_note:
            return "视频留言"
        else:
            return "未知类型"