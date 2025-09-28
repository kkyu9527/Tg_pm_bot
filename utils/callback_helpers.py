"""
回调数据处理工具
处理Telegram按钮回调数据的编码和解码，以及回调处理逻辑
"""

import json
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from utils.logger import setup_logger

logger = setup_logger('cb_hlp')


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


def build_action_keyboard(message_id, user_id, show_edit=False, show_delete=False, actions=None):
    """构建消息操作键盘
    
    Args:
        message_id: 消息ID
        user_id: 用户ID
        show_edit: 是否显示编辑按钮
        show_delete: 是否显示删除按钮
        actions: 动作常量字典，默认使用标准动作
    """
    if actions is None:
        actions = {
            'edit': 'edit',
            'delete': 'delete'
        }
    
    buttons = []
    
    # 如果显示编辑按钮，先添加编辑按钮
    if show_edit:
        buttons.append(InlineKeyboardButton(
            "✏️ 编辑",
            callback_data=encode_callback(actions['edit'], message_id, user_id)
        ))
    
    # 如果显示删除按钮，添加删除按钮
    if show_delete:
        buttons.append(InlineKeyboardButton(
            "🗑️ 删除",
            callback_data=encode_callback(actions['delete'], message_id, user_id)
        ))
    
    if not buttons:
        return None
    
    return InlineKeyboardMarkup([buttons])


def build_cancel_edit_keyboard(message_id, user_id, cancel_action="cancel_edit"):
    """构建取消编辑键盘"""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "取消编辑", 
            callback_data=encode_callback(cancel_action, message_id, user_id, compact=True)
        )
    ]])


def build_edit_done_keyboard():
    """构建编辑完成键盘"""
    return InlineKeyboardMarkup([])


# =========================== 回调处理逻辑 ===========================

async def handle_delete_callback(query, bot, message_id: int, user_id: int, message_service):
    """处理删除按钮回调"""
    result = await message_service.handle_message_deletion(bot, user_id, message_id)
    
    if result['success']:
        # 删除成功，移除所有按钮
        await query.edit_message_text(result['message'])
    else:
        # 删除失败，根据错误类型决定后续操作
        if result.get('remove_delete_button', False):
            # 消息超过48小时或不存在，移除删除按钮
            keyboard = None
            if result.get('show_edit', False):
                # 如果是文本消息，只显示编辑按钮
                keyboard = build_action_keyboard(message_id, user_id, show_edit=True, show_delete=False)
            
            await query.edit_message_text(result['message'], reply_markup=keyboard)
        else:
            # 其他错误，只更新文本内容
            try:
                await query.edit_message_text(result['message'])
            except Exception as e:
                logger.warning(f"无法更新失败消息: {e}")


async def handle_edit_callback(query, message_id: int, user_id: int, message_service):
    """处理编辑按钮回调"""
    prompt_message = message_service.start_message_edit(
        query.from_user.id, message_id, user_id, query.message
    )
    await query.edit_message_text(
        prompt_message,
        reply_markup=build_cancel_edit_keyboard(message_id, user_id)
    )


async def handle_cancel_edit_callback(query, bot, message_service):
    """处理取消编辑按钮回调"""
    result = message_service.cancel_message_edit(query.from_user.id)
    
    if result['success']:
        # 只有文本消息才会进入编辑状态，所以取消时显示文本消息按钮
        # 这里默认显示删除按钮，如果超过48小时会在删除时被移除
        await query.edit_message_text(
            result['message'],
            reply_markup=build_action_keyboard(result['message_id'], result['user_id'], show_edit=True, show_delete=True)
        )
    else:
        await query.edit_message_text(result['message'])


async def handle_message_edit_execution(bot, new_message, state, message_service):
    """处理消息编辑执行"""
    # 调用Service层处理业务逻辑
    result = await message_service.execute_message_edit(bot, new_message, state)
    
    # 更新原始编辑消息状态
    if result['update_original'] and state.get('original_message'):
        original_msg = state['original_message']
        if original_msg and original_msg.chat_id and original_msg.message_id:
            logger.info(f"更新原始编辑消息: 聊天ID {original_msg.chat_id}, 消息ID {original_msg.message_id}")
            await bot.edit_message_text(
                chat_id=original_msg.chat_id,
                message_id=original_msg.message_id,
                text="✏️ 编辑完成",
                reply_markup=build_edit_done_keyboard()
            )
    
    # 发送编辑结果的确认消息，文本消息显示编辑和删除按钮
    await new_message.reply_text(
        result['message'],
        reply_markup=build_action_keyboard(result['message_id'], state['user_id'], show_edit=True, show_delete=result.get('show_delete', True))
    )