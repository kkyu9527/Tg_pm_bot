"""
用户业务逻辑层
处理用户相关的业务逻辑
"""

import os
from telegram import User
from database.db_operations import UserOperations
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_object

logger = setup_logger('user_srvc')


class UserService:
    """用户业务逻辑服务"""
    
    def __init__(self):
        self.user_ops = UserOperations()
    
    def register_or_update_user(self, user: User) -> bool:
        """注册或更新用户信息"""
        try:
            result = self.user_ops.save_user(
                user.id, user.first_name, user.last_name, user.username
            )
            if result:
                user_display = get_user_display_name_from_object(user)
                logger.info(f"用户信息已保存: {user_display}")
            return result
        except Exception as e:
            logger.error(f"保存用户信息失败: {e}")
            return False
    
    def is_owner(self, user_id: int) -> bool:
        """检查用户是否是机器人主人"""
        owner_id = os.getenv("USER_ID")
        return str(user_id) == owner_id
    
    def generate_welcome_message(self, user: User) -> str:
        """生成欢迎消息"""
        return (
            f"👋 您好，{user.first_name}！\n\n"
            f"🆔 ID: {user.id}\n"
            f"👤 姓名: {user.full_name}\n"
            f"🔰 用户名: @{user.username if user.username else '未设置'}\n"
            f"⭐ 是否是Premium用户: {'是' if user.is_premium else '否'}\n"
            f"您可以通过我向主人发送私信，我会将您的消息转发给主人。\n"
        )
    
    def generate_info_message(self) -> str:
        """生成信息消息"""
        return (
            "ℹ️ 关于私聊转发机器人\n\n"
            "这个机器人可以帮助您与用户进行交流，避免双向。\n\n"
            "项目已开源，地址：https://github.com/kkyu9527/Tg_pm_bot.git\n\n"
            "如有任何问题，请联系 @kkyu9527s_bot"
        )