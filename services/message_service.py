"""
消息业务逻辑层
处理消息转发、编辑、媒体组等业务逻辑
"""

import os
import asyncio
from datetime import datetime, timedelta, UTC
from telegram import Message, InputMediaPhoto, InputMediaVideo, Update, User
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from database.db_operations import MessageOperations
from database.db_operations import UserOperations, TopicOperations
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_db
from utils.callback_helpers import decode_callback, build_action_keyboard, \
    handle_delete_callback, handle_edit_callback, handle_cancel_edit_callback, handle_message_edit_execution

logger = setup_logger('msg_srvc')


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
        self.edit_states = {}
        self.media_group_cache = {}
        # 缓存环境变量
        self.owner_user_id = os.getenv("USER_ID")
        self.group_id = os.getenv("GROUP_ID")

    def _build_media_group(self, messages):
        """构建媒体组"""
        media_group = []
        for msg in sorted(messages, key=lambda x: x.message_id):
            if msg.photo:
                media_group.append(InputMediaPhoto(
                    media=msg.photo[-1].file_id,
                    caption=msg.caption
                ))
            elif msg.video:
                media_group.append(InputMediaVideo(
                    media=msg.video.file_id,
                    caption=msg.caption
                ))
        return media_group

    def _save_message_and_log(self, user_id: int, topic_id: int, original_id: int,
                              forwarded_id: int, direction: str, success_msg: str) -> bool:
        """保存消息记录并记录日志"""
        result = self.message_ops.save_message(user_id, topic_id, original_id, forwarded_id, direction)
        if result:
            logger.info(f"{success_msg}，消息ID: {original_id} -> {forwarded_id}")
        else:
            logger.error(f"{success_msg}但保存失败")
        return result

    async def forward_message(self, message: Message, bot, chat_id: int, thread_id: int = None) -> Message:
        """转发消息到指定聊天和话题"""
        kwargs = {"chat_id": chat_id, "from_chat_id": message.chat_id, "message_id": message.message_id}
        if thread_id:
            kwargs["message_thread_id"] = thread_id

        try:
            return await bot.copy_message(**kwargs)
        except Exception as e:
            logger.error(f"消息转发失败: {e}")
            raise

    async def handle_user_message_forward(self, message: Message, user: User, bot) -> bool:
        """处理用户消息转发"""
        # 保存用户信息并确保有话题
        from services.user_service import UserService
        from services.topic_service import TopicService
        user_service = UserService()
        topic_service = TopicService()

        user_service.register_or_update_user(user)
        topic_id = await topic_service.ensure_user_topic(bot, user)

        # 处理媒体组消息（简化逻辑）
        if message.media_group_id and (message.photo or message.video):
            return await self._handle_media_group_message(message, user, topic_id, bot, self.group_id)

        # 处理普通消息
        return await self._handle_regular_message_forward(message, user, topic_id, bot, self.group_id)

    async def _handle_media_group_message(self, message: Message, user: User, topic_id: int, bot,
                                          group_id: str) -> bool:
        """处理媒体组消息"""
        key = f"{user.id}:{message.media_group_id}"
        self.media_group_cache.setdefault(key, []).append(message)

        # 第一条消息时启动动态检测
        if len(self.media_group_cache[key]) == 1:
            asyncio.create_task(self._dynamic_process_media_group(
                key, user.id, topic_id, bot, group_id, "user_to_owner"))
        return True

    async def _dynamic_process_media_group(self, key: str, user_id: int, target_id: int,
                                           bot, target_chat: str, direction: str):
        """动态处理媒体组消息，根据消息ID连续性自动检测媒体组是否完整"""
        user_display = get_user_display_name_from_db(user_id)
        last_count = 0
        stable_count = 0
        uploading_message = None

        # 只在主人发送媒体组时显示上传中提示
        if direction == "owner_to_user":
            # 获取第一条消息用于回复
            if key in self.media_group_cache and self.media_group_cache[key]:
                first_message = self.media_group_cache[key][0]
                uploading_message = await first_message.reply_text("📁 媒体组上传中...")

        while True:
            await asyncio.sleep(0.5)  # 短间隔检测

            # 检查缓存是否还存在
            if key not in self.media_group_cache:
                return

            current_count = len(self.media_group_cache[key])

            # 如果数量没有变化，增加稳定计数
            if current_count == last_count:
                stable_count += 1
            else:
                stable_count = 0  # 重置稳定计数
                last_count = current_count

            # 如果数量稳定超过3次检测（1.5秒），认为媒体组完整
            if stable_count >= 3:
                messages = self.media_group_cache.pop(key, [])
                if messages:
                    # 删除上传中提示消息
                    if uploading_message:
                        try:
                            await uploading_message.delete()
                        except:
                            pass

                    logger.info(f"媒体组检测完成: {direction}, 用户{user_display}, 共{len(messages)}个媒体")
                    await self._send_media_group(messages, user_id, target_id, bot, target_chat, direction)
                return

    async def _send_media_group(self, messages, user_id: int, target_id: int,
                                bot, target_chat: str, direction: str):
        """发送媒体组"""
        media_group = self._build_media_group(messages)
        if not media_group:
            return

        user_display = get_user_display_name_from_db(user_id)

        try:
            # 根据方向发送媒体组
            if direction == "user_to_owner":
                sent_messages = await bot.send_media_group(
                    chat_id=target_chat, message_thread_id=target_id, media=media_group)
                if sent_messages:
                    self._save_message_and_log(user_id, target_id, messages[0].message_id,
                                               sent_messages[0].message_id, direction,
                                               f"用户{user_display}媒体组转发成功")
            else:  # owner_to_user
                sent_messages = await bot.send_media_group(chat_id=target_chat, media=media_group)
                if sent_messages:
                    self._save_message_and_log(user_id, target_id, sent_messages[0].message_id,
                                               messages[0].message_id, direction, f"主人媒体组转发给{user_display}成功")

                    # 主人发送媒体组后显示操作按钮（媒体组不支持编辑）
                    # 默认显示删除按钮，如果超过48小时会在删除时被移除
                    await messages[0].reply_text(f"✅ 媒体组已转发({len(media_group)}个媒体)",
                                                 reply_markup=build_action_keyboard(sent_messages[0].message_id,
                                                                                    user_id, show_edit=False,
                                                                                    show_delete=True))

        except Exception as e:
            logger.error(f"媒体组转发失败: {e}, 用户: {user_display}")
            if direction == "owner_to_user" and messages:
                await messages[0].reply_text(f"⚠️ 媒体组转发失败: {e}")

    async def _handle_regular_message_forward(self, message: Message, user: User, topic_id: int, bot,
                                              group_id: str) -> bool:
        """处理普通消息转发"""
        user_display = get_user_display_name_from_db(user.id)
        try:
            forwarded = await self.forward_message(message, bot, group_id, topic_id)
            self._save_message_and_log(user.id, topic_id, message.message_id,
                                       forwarded.message_id, "user_to_owner", f"用户{user_display}消息转发成功")
            return True
        except BadRequest as e:
            if "Message thread not found" in str(e):
                return await self._handle_topic_not_found(message, user, topic_id, bot, group_id)
            logger.error(f"转发失败: {e}, 用户: {user_display}")
            return False
        except Exception as e:
            logger.error(f"转发失败: {e}, 用户: {user_display}")
            return False

    async def _handle_topic_not_found(self, message: Message, user: User, topic_id: int, bot, group_id: str) -> bool:
        """处理话题不存在的情况"""
        user_display = get_user_display_name_from_db(user.id)
        logger.warning(f"话题{topic_id}未找到，正在为用户{user_display}重新创建")

        from services.topic_service import TopicService
        new_topic_id = await TopicService().ensure_user_topic(bot, user)

        try:
            forwarded = await self.forward_message(message, bot, group_id, new_topic_id)
            self._save_message_and_log(user.id, new_topic_id, message.message_id,
                                       forwarded.message_id, "user_to_owner", f"用户{user_display}消息转发到新话题成功")
            return True
        except Exception as e:
            logger.error(f"用户{user_display}消息在重新创建话题后转发失败: {e}")
            return False

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
        """处理消息删除操作（支持媒体组批量删除）"""
        user_display = get_user_display_name_from_db(user_id)

        try:
            # 先尝试删除目标消息
            await bot.delete_message(chat_id=user_id, message_id=message_id)
            deleted_count = 1

            # 尝试删除后续消息（媒体组最多10个，按钮在第一个上）
            for i in range(1, 10):
                try:
                    await bot.delete_message(chat_id=user_id, message_id=message_id + i)
                    deleted_count += 1
                except:
                    break  # 如果删除失败，停止尝试

            if deleted_count > 1:
                logger.info(f"已删除发送给用户 {user_display} 的媒体组({deleted_count}个消息)")
                return {'success': True, 'message': f'✅ 已删除媒体组({deleted_count}个消息)', 'show_edit': False}
            else:
                logger.info(f"已删除发送给用户 {user_display} 的消息 {message_id}")
                return {'success': True, 'message': '✅ 消息已删除', 'show_edit': False}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"删除消息失败: {error_msg}, 用户: {user_display}, 消息ID: {message_id}")

            # 针对常见错误提供友好的错误提示
            if "Message can't be deleted for everyone" in error_msg:
                return {'success': False, 'message': '⚠️ 消息超过48小时，无法删除', 'show_edit': True,
                        'remove_delete_button': True}
            elif "Message to delete not found" in error_msg:
                return {'success': False, 'message': '⚠️ 消息不存在或已被删除', 'show_edit': True,
                        'remove_delete_button': True}
            else:
                return {'success': False, 'message': f'⚠️ 删除失败: {error_msg}', 'show_edit': True}

    def start_message_edit(self, owner_user_id: int, message_id: int, user_id: int, original_message) -> str:
        """开始消息编辑操作"""
        self.edit_states[owner_user_id] = {
            "message_id": message_id, "user_id": user_id,
            "original_message": original_message, "timestamp": datetime.now(UTC)
        }
        user_display = get_user_display_name_from_db(user_id)
        logger.info(f"主人开始编辑发送给用户 {user_display} 的消息 {message_id}")
        return "✏️ 请发送新的消息内容，将替换之前的消息"

    def cancel_message_edit(self, owner_user_id: int) -> dict:
        """取消消息编辑操作"""
        state = self.edit_states.pop(owner_user_id, None)

        if state is not None:
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
        """执行消息编辑操作（仅支持文本消息）"""
        user_id, old_id = state["user_id"], state["message_id"]
        user_display = get_user_display_name_from_db(user_id)

        try:
            await bot.edit_message_text(chat_id=user_id, message_id=old_id, text=new_message.text)
            logger.info(f"文本消息编辑成功: 用户{user_display}, 消息ID{old_id}")
            # 编辑成功后，默认显示删除按钮（新编辑的消息不会超过48小时）
            return {'success': True, 'message': '✅ 已更新用户消息',
                    'message_id': old_id, 'show_delete': True, 'update_original': True}
        except Exception as e:
            error_msg = str(e)
            logger.error(f"文本消息编辑失败: {error_msg}, 用户: {user_display}, 消息ID: {old_id}")
            return {'success': False, 'message': f'⚠️ 编辑失败：{error_msg}',
                    'message_id': old_id, 'show_delete': True, 'update_original': True}

    # ============================= 完整流程方法 =============================

    async def handle_user_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户发送消息的完整流程"""
        # 只处理私聊消息且发送者不是主人
        if update.effective_chat.type != "private" or str(update.effective_user.id) == self.owner_user_id:
            return

        user, message, bot = update.effective_user, update.effective_message, context.bot
        user_display = get_user_display_name_from_db(user.id)
        logger.info(f"收到用户 {user_display} 的消息，消息ID: {message.message_id}")

    async def handle_owner_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理主人在群组中发送消息的完整流程"""
        self.cleanup_edit_states()

        # 只处理群组消息且发送者是主人
        if update.effective_chat.type == "private" or str(update.effective_user.id) != self.owner_user_id:
            return

        message = update.effective_message
        logger.info(f"收到主人的消息，消息ID: {message.message_id}")

        # 检查主人是否处于编辑状态
        if update.effective_user.id in self.edit_states:
            state = self.edit_states.pop(update.effective_user.id)
            logger.info(f"主人正在编辑发送给用户 {state['user_id']} 的消息 {state['message_id']}")
            await handle_message_edit_execution(context.bot, message, state, self)
            return

        # 只处理话题消息
        if not message.is_topic_message:
            return

        # 查找话题对应的用户
        topic = self.topic_ops.get_topic_by_id(message.message_thread_id)
        if not topic:
            logger.warning(f"无法找到话题 {message.message_thread_id} 对应的用户")
            await message.reply_text("⚠️ 无法找到此话题对应的用户")
            return

        user_id = topic["user_id"]

        # 处理媒体组消息
        if message.media_group_id and (message.photo or message.video):
            await self._handle_owner_media_group_message(message, user_id, context.bot)
        else:
            await self._handle_owner_message_forward(message, user_id, context.bot)

    async def _handle_owner_media_group_message(self, message: Message, user_id: int, bot):
        """处理主人发送的媒体组消息"""
        key = f"owner:{user_id}:{message.media_group_id}"
        self.media_group_cache.setdefault(key, []).append(message)

        # 第一条消息时启动动态检测
        if len(self.media_group_cache[key]) == 1:
            asyncio.create_task(self._dynamic_process_media_group(
                key, user_id, message.message_thread_id, bot, str(user_id), "owner_to_user"))

    async def _handle_owner_message_forward(self, message, user_id: int, bot):
        """处理主人消息转发"""
        user_display = get_user_display_name_from_db(user_id)
        try:
            forwarded = await self.forward_message(message, bot, user_id)
            self._save_message_and_log(user_id, message.message_thread_id, forwarded.message_id,
                                       message.message_id, "owner_to_user", f"主人消息转发给{user_display}成功")

            # 判断按钮显示逻辑
            show_edit = bool(message.text)  # 只有文本消息才显示编辑按钮
            show_delete = True  # 默认显示删除按钮，如果超过48小时会在删除时被移除

            await message.reply_text("✅ 已转发给用户",
                                     reply_markup=build_action_keyboard(forwarded.message_id, user_id,
                                                                        show_edit=show_edit, show_delete=show_delete))
        except Exception as e:
            logger.error(f"转发失败: {e}, 用户: {user_display}")
            await message.reply_text(f"⚠️ 转发失败: {e}")

    async def handle_button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调的完整流程"""
        self.cleanup_edit_states()
        query = update.callback_query
        await query.answer()

        try:
            data = decode_callback(query.data)
            logger.info(f"收到按钮回调: {data['action']}, 消息ID: {data['message_id']}, 用户ID: {data['user_id']}")
        except Exception as e:
            logger.error(f"回调数据解析失败: {e}")
            return

        action, message_id, user_id = data["action"], data["message_id"], data["user_id"]

        # 分发处理不同的按钮操作
        if action == self.ACTION_DELETE:
            await handle_delete_callback(query, context.bot, message_id, user_id, self)
        elif action == self.ACTION_EDIT:
            await handle_edit_callback(query, message_id, user_id, self)
        elif action == self.ACTION_CANCEL_EDIT:
            await handle_cancel_edit_callback(query, context.bot, self)
