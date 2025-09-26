"""
消息控制器
处理Telegram消息的路由和响应
"""

import os
import json
from datetime import datetime, UTC
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from services.user_service import UserService
from services.message_service import MessageService
from services.topic_service import TopicService
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db

logger = setup_logger('message_controller')


def encode_callback(action, message_id, user_id, compact=False):
    """编码回调数据"""
    data = {
        ("a" if compact else "action"): action,
        ("m" if compact else "message_id"): message_id,
        ("u" if compact else "user_id"): user_id
    }
    return json.dumps(data, separators=(',', ':') if compact else None)


def decode_callback(data):
    """解码回调数据"""
    obj = json.loads(data)
    return {
        "action": obj.get("action") or obj.get("a"),
        "message_id": obj.get("message_id") or obj.get("m"),
        "user_id": obj.get("user_id") or obj.get("u")
    }


class MessageController:
    """消息控制器"""
    
    # 回调动作常量
    ACTION_EDIT = "edit"
    ACTION_DELETE = "delete"
    ACTION_CANCEL_EDIT = "cancel_edit"
    
    def __init__(self):
        self.user_service = UserService()
        self.message_service = MessageService()
        self.topic_service = TopicService()
    
    def build_action_keyboard(self, message_id, user_id):
        """构建消息操作键盘"""
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "编辑",
                callback_data=encode_callback(self.ACTION_EDIT, message_id, user_id)
            ),
            InlineKeyboardButton(
                "删除",
                callback_data=encode_callback(self.ACTION_DELETE, message_id, user_id)
            )
        ]])
    
    def build_cancel_edit_keyboard(self, message_id, user_id):
        """构建取消编辑键盘"""
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "取消编辑", 
                callback_data=encode_callback(self.ACTION_CANCEL_EDIT, message_id, user_id, compact=True)
            )
        ]])
    
    def build_edit_done_keyboard(self):
        """构建编辑完成键盘"""
        return InlineKeyboardMarkup([])
    
    async def handle_user_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户发送的消息"""
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
        await self.message_service.handle_user_message_forward(message, user, bot)
    
    async def handle_owner_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人在群组中发送的消息"""
        USER_ID = os.getenv("USER_ID")
        
        # 清理过期的编辑状态
        self.message_service.cleanup_edit_states()
        
        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return

        logger.info("收到主人的消息")

        # 检查主人是否处于编辑状态
        if update.effective_user.id in self.message_service.edit_states:
            # 获取并移除编辑状态
            state = self.message_service.edit_states.pop(update.effective_user.id)
            logger.info(f"主人正在编辑发送给用户 {state['user_id']} 的消息 {state['message_id']}")
            
            # 执行编辑操作
            await self._edit_user_message(context.bot, update.effective_message, state)
            return

        # 获取消息对象
        message = update.effective_message
        
        # 只处理话题消息
        if not message.is_topic_message:
            return

        # 查找话题对应的用户
        topic = self.topic_service.get_topic_by_id(message.message_thread_id)
        if not topic:
            logger.warning(f"无法找到话题 {message.message_thread_id} 对应的用户")
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return

        # 获取用户ID并转发消息
        user_id = topic["user_id"]
        try:
            # 转发消息给用户
            forwarded = await self.message_service.forward_message(message, context.bot, user_id)
            if not forwarded:
                user_display = get_user_display_name_from_db(user_id)
                logger.warning(f"主人发送给用户 {user_display} 的消息转发失败，返回为空")
                return
                
            # 保存消息记录
            self.message_service.save_message_record(
                user_id, message.message_thread_id, forwarded.message_id, message.message_id, "owner_to_user"
            )
            
            # 获取用户显示名称并记录日志
            try:
                user_display = get_user_display_name_from_db(user_id, self.message_service.user_repo.user_ops)
                logger.info(f"已将主人的消息转发给用户 {user_display}")
            except Exception as e:
                logger.error(f"获取用户显示名称失败: {e}, 用户ID: {user_id}")
                logger.info(f"已将主人的消息转发给用户 [ID:{user_id}]")
            
            # 发送确认消息并添加操作按钮
            await message.reply_text(
                "✅ 已转发给用户",
                reply_markup=self.build_action_keyboard(forwarded.message_id, user_id)
            )
        except Exception as e:
            # 处理转发失败的情况
            error_message = str(e)
            user_display = get_user_display_name_from_db(user_id)
            logger.error(f"转发失败: {error_message}, 用户: {user_display}")
            await message.reply_text(f"⚠️ 转发失败: {error_message}")
    
    async def handle_button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调"""
        # 清理过期的编辑状态
        self.message_service.cleanup_edit_states()
        
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

        # 处理删除消息操作
        if action == self.ACTION_DELETE:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
                await query.edit_message_text("✅ 消息已删除")
                user_display = get_user_display_name_from_db(user_id, self.message_service.user_repo.user_ops)
                logger.info(f"已删除发送给用户 {user_display} 的消息 {message_id}")
            except Exception as e:
                error_message = str(e)
                user_display = get_user_display_name_from_db(user_id)
                logger.error(f"删除消息失败: {error_message}, 用户: {user_display}, 消息ID: {message_id}")
                
                if "Message can't be deleted for everyone" in error_message:
                    await query.edit_message_text(
                        "⚠️ 删除失败: 消息已超过48小时，无法删除，只能编辑",
                        reply_markup=self.build_action_keyboard(message_id, user_id)
                    )
                else:
                    await query.edit_message_text(
                        f"⚠️ 删除失败: {error_message}",
                        reply_markup=self.build_action_keyboard(message_id, user_id)
                    )
        
        # 处理编辑消息操作
        elif action == self.ACTION_EDIT:
            self.message_service.edit_states[query.from_user.id] = {
                "message_id": message_id,
                "user_id": user_id,
                "original_message": query.message,
                "timestamp": datetime.now(UTC)
            }
            user_display = get_user_display_name_from_db(user_id)
            logger.info(f"主人开始编辑发送给用户 {user_display} 的消息 {message_id}")
            await query.edit_message_text(
                "✏️ 请发送新的消息内容，将替换之前的消息",
                reply_markup=self.build_cancel_edit_keyboard(message_id, user_id)
            )
        
        elif action == self.ACTION_CANCEL_EDIT:
            if query.from_user.id in self.message_service.edit_states:
                state = self.message_service.edit_states.pop(query.from_user.id)
                user_display = get_user_display_name_from_db(state['user_id'])
                logger.info(f"主人取消编辑发送给用户 {user_display} 的消息 {state['message_id']}")
                await query.edit_message_text(
                    "❎ 已取消编辑",
                    reply_markup=self.build_action_keyboard(state["message_id"], state["user_id"])
                )
    
    async def _edit_user_message(self, bot, new_message, state):
        """编辑发送给用户的消息"""
        user_id = state["user_id"]
        old_id = state["message_id"]
        original_msg = state["original_message"]
        
        try:
            user_display = get_user_display_name_from_db(user_id, self.message_service.user_repo.user_ops)
            logger.info(f"开始编辑用户 {user_display} 的消息 {old_id}")
            
            # 处理文本消息编辑
            if new_message.text:
                logger.info(f"编辑文本消息: 用户 {user_display}, 消息ID {old_id}")
                await bot.edit_message_text(chat_id=user_id, message_id=old_id, text=new_message.text)
                reply_text = "✅ 已更新用户消息"
                msg_id = old_id
                logger.info(f"文本消息编辑成功: 用户 {user_display}, 消息ID {old_id}")
            
            # 处理非文本消息（需要删除旧消息并发送新消息）
            else:
                logger.info(f"删除旧消息并发送新消息: 用户 {user_display}, 旧消息ID {old_id}")
                await bot.delete_message(chat_id=user_id, message_id=old_id)
                forwarded = await self.message_service.forward_message(new_message, bot, user_id)
                reply_text = "✅ 已重新发送消息"
                msg_id = forwarded.message_id
                logger.info(f"非文本消息替换成功: 用户 {user_display}, 新消息ID {msg_id}")

            # 更新原始编辑消息状态
            if original_msg and original_msg.chat_id and original_msg.message_id:
                logger.info(f"更新原始编辑消息: 聊天ID {original_msg.chat_id}, 消息ID {original_msg.message_id}")
                await bot.edit_message_text(
                    chat_id=original_msg.chat_id,
                    message_id=original_msg.message_id,
                    text="✏️ 编辑完成",
                    reply_markup=self.build_edit_done_keyboard()
                )

            # 发送编辑完成的确认消息
            await new_message.reply_text(
                reply_text,
                reply_markup=self.build_action_keyboard(msg_id, user_id)
            )
            logger.info(f"已完成编辑用户 {user_display} 的消息, 最终消息ID: {msg_id}")
            
        except Exception as e:
            error_message = str(e)
            user_display = get_user_display_name_from_db(user_id)
            logger.error(f"编辑失败: {error_message}, 用户: {user_display}, 消息ID: {old_id}")
    
    async def handle_owner_delete_topic(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人删除话题的请求"""
        USER_ID = os.getenv("USER_ID")
        GROUP_ID = os.getenv("GROUP_ID")
        
        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != USER_ID:
            return
            
        # 只处理话题消息
        if not update.message.is_topic_message:
            return

        logger.info("主人尝试删除话题")

        # 获取话题ID并验证其存在性
        topic_id = update.effective_message.message_thread_id
        if not self.topic_service.get_topic_by_id(topic_id):
            logger.warning(f"话题 {topic_id} 在数据库中不存在")
            await update.effective_message.reply_text("⚠️ 此话题在数据库中不存在")
            return

        # 尝试从Telegram删除话题
        try:
            await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic_id)
        except Exception as e:
            logger.warning(f"Telegram 话题删除失败: {e}")
            
        # 尝试从数据库删除话题
        try:
            # 再次检查话题是否存在
            topic = self.topic_service.get_topic_by_id(topic_id)
            if not topic:
                await update.effective_message.reply_text("⚠️ 数据库中未找到话题，跳过清理")
                return

            # 从数据库中删除话题
            self.topic_service.delete_topic(topic_id)
            logger.info(f"主人删除了话题 {topic_id} 以及相关数据库记录")
            await update.effective_message.reply_text("✅ 话题已删除")
        except Exception as e:
            # 处理数据库删除失败的情况
            logger.error(f"从数据库中删除话题失败: {e}")
            await update.effective_message.reply_text(f"⚠️ 从数据库中删除话题失败: {e}")