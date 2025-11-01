import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from telegram import BotCommandScopeAllGroupChats, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from database.db_connector import DatabaseConnector
from database.db_init import DatabaseInitializer
from controllers.command_controller import CommandController
from controllers.message_controller import MessageController
from controllers.webhook_controller import WebhookController
from utils.logger import setup_logger

# 全局版本号
APP_VERSION = "1.1.6-beta"

logger = setup_logger('app_init')

def initialize_database_with_retry(db_connector: DatabaseConnector,
                                   max_retries: int = 10,
                                   delay: int = 3) -> None:
    """
    重试机制：尝试连接并初始化数据库，直到成功或达到最大重试次数。

    Args:
        db_connector: 数据库连接器实例
        max_retries: 最大重试次数
        delay: 重试间隔（秒）

    Raises:
        RuntimeError: 超过最大重试次数仍未成功
    """
    db_initializer = DatabaseInitializer(db_connector)
    for attempt in range(1, max_retries + 1):
        try:
            db_initializer.initialize_database()
            logger.info("✅ 数据库初始化完成")
            return
        except Exception as e:
            logger.warning(
                f"数据库初始化失败 (第 {attempt}/{max_retries} 次)：{e}，"
                f"{delay}s 后重试…"
            )
            time.sleep(delay)
    raise RuntimeError("❌ 超过最大重试次数，数据库初始化失败")

async def setup_bot_commands(application: Application):
    """
    设置机器人命令列表
    
    Args:
        application: Telegram应用实例
    """
    from telegram import BotCommandScopeAllPrivateChats
    
    # 为群组聊天设置命令（包括get_group_id命令）
    await application.bot.set_my_commands(
        commands=[
            BotCommand("delete_topic", "删除当前话题（仅限主人）"),
            BotCommand("get_group_id", "获取当前群组ID（用于配置）")
        ],
        scope=BotCommandScopeAllGroupChats()
    )
    
    # 为私聊设置命令（不包括get_group_id和delete_topic命令）
    await application.bot.set_my_commands(
        commands=[
            BotCommand("start", "开始使用机器人"),
            BotCommand("info", "查看机器人信息")
        ],
        scope=BotCommandScopeAllPrivateChats()
    )

def register_handlers(application: Application, 
                     command_controller: CommandController,
                     message_controller: MessageController):
    """
    注册所有消息和命令处理器
    
    Args:
        application: Telegram应用实例
        command_controller: 命令控制器实例
        message_controller: 消息控制器实例
    """
    # 注册命令处理器
    application.add_handler(CommandHandler("start", command_controller.handle_start_command))
    application.add_handler(CommandHandler("info", command_controller.handle_info_command))
    application.add_handler(CommandHandler("get_group_id", command_controller.handle_get_group_id_command))
    application.add_handler(
        CommandHandler("delete_topic", message_controller.handle_owner_delete_topic)
    )
    
    # 注册消息处理器
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND,
                       message_controller.handle_user_message)
    )
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.IS_TOPIC_MESSAGE,
                       message_controller.handle_owner_message)
    )
    
    # 注册回调查询处理器
    application.add_handler(CallbackQueryHandler(message_controller.handle_button_callback))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI应用的生命周期管理器
    
    Args:
        app: FastAPI应用实例
    """
    application = None
    try:
        logger.info(f"🔧 初始化 Telegram 私聊转发机器人 V{APP_VERSION}")

        # 用重试机制初始化数据库
        db_connector = DatabaseConnector()
        initialize_database_with_retry(db_connector)

        # 环境变量检查
        bot_token = os.getenv('BOT_TOKEN')
        webhook_url = os.getenv('WEBHOOK_URL')
        if not bot_token or not webhook_url:
            raise RuntimeError("❌ BOT_TOKEN 或 WEBHOOK_URL 未设置")

        # 初始化 Telegram Bot 应用
        application = (
            Application.builder()
            .token(bot_token)
            .connect_timeout(60.0)
            .pool_timeout(60.0)
            .read_timeout(60.0)
            .build()
        )

        # 初始化控制器
        command_controller = CommandController()
        message_controller = MessageController()
        webhook_controller = WebhookController(APP_VERSION)

        # 注册处理器
        register_handlers(application, command_controller, message_controller)

        # 初始化应用
        await application.initialize()
        
        # 设置命令
        await setup_bot_commands(application)

        # 启动应用并设置webhook
        await application.start()
        await application.bot.set_webhook(url=webhook_url)
        
        # 将应用实例和webhook控制器存储在FastAPI状态中
        app.state.application = application
        app.state.webhook_controller = webhook_controller
        
        logger.info(f"🚀 Webhook 已设置: {webhook_url}")

        yield

    except Exception as e:
        logger.exception(f"❌ 启动失败：{e}")
        raise

    finally:
        if application:
            await application.bot.delete_webhook()
            await application.stop()
            await application.shutdown()
            logger.info("🔻 Telegram 应用已关闭")