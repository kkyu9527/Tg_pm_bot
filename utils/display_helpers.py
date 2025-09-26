"""
显示名称辅助函数模块
提供统一的用户和话题显示名称格式化功能
"""

def get_user_display_name_from_object(user):
    """从 Telegram 用户对象获取格式化显示名称
    
    Args:
        user: Telegram 用户对象
        
    Returns:
        格式化的用户显示名称: 名称(@用户名) [ID:xxx] 或 名称 [ID:xxx]
    """
    first_name = user.first_name or ''
    last_name = user.last_name or ''
    username = user.username or ''
    display_name = f"{first_name} {last_name}".strip()
    return f"{display_name}(@{username}) [ID:{user.id}]" if username else f"{display_name} [ID:{user.id}]"


def get_user_display_name_from_db(user_id, user_ops=None):
    """从数据库获取用户的格式化显示名称
    
    Args:
        user_id: 用户ID
        user_ops: 用户操作对象（可选，用于数据库查询）
        
    Returns:
        格式化的用户显示名称: 名称(@用户名) [ID:xxx] 或 名称 [ID:xxx]
    """
    if user_ops:
        user_info = user_ops.get_user(user_id)
        if user_info:
            first_name = user_info.get('first_name', '')
            last_name = user_info.get('last_name', '') or ''
            username = user_info.get('username', '')
            name_parts = [first_name, last_name]
            display_name = ' '.join(filter(None, name_parts)).strip()
            if username:
                return f"{display_name}(@{username}) [ID:{user_id}]"
            else:
                return f"{display_name} [ID:{user_id}]"
    return f"[ID:{user_id}]"


def get_topic_display_name(topic_id, topic_ops=None):
    """获取话题的格式化显示名称
    
    Args:
        topic_id: 话题ID
        topic_ops: 话题操作对象（可选，用于数据库查询）
        
    Returns:
        格式化的话题显示名称: 话题名称 [话题ID:xxx]
    """
    if topic_ops:
        topic_info = topic_ops.get_topic_by_id(topic_id)
        if topic_info:
            topic_name = topic_info.get('topic_name', '')
            return f"{topic_name} [话题ID:{topic_id}]"
    return f"[话题ID:{topic_id}]"