import os
import time
import uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request
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
APP_VERSION = "1.1.1-beta"

# 加载环境变量
load_dotenv()
logger = setup_logger('main')

def initialize_database_with_retry(db_connector: DatabaseConnector,
                                   max_retries: int = 10,
                                   delay: int = 3) -> None:
    """
    重试机制：尝试连接并初始化数据库，直到成功或达到最大重试次数。
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    application = None
    try:
        logger.info(f"🔧 初始化 Telegram 私聊转发机器人 V{APP_VERSION}")

        # 用重试机制初始化数据库，替代简单的 sleep
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
        application.add_handler(CommandHandler("start", command_controller.handle_start_command))
        application.add_handler(CommandHandler("info", command_controller.handle_info_command))
        application.add_handler(
            CommandHandler("delete_topic", message_controller.handle_owner_delete_topic)
        )
        application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND,
                           message_controller.handle_user_message)
        )
        application.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.IS_TOPIC_MESSAGE,
                           message_controller.handle_owner_message)
        )
        application.add_handler(CallbackQueryHandler(message_controller.handle_button_callback))

        await application.initialize()

        await application.bot.set_my_commands(
            commands=[
                BotCommand("delete_topic", "删除当前话题（仅限主人）")
            ],
            scope=BotCommandScopeAllGroupChats()
        )

        await application.start()
        await application.bot.set_webhook(url=webhook_url)
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

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    return await app.state.webhook_controller.handle_webhook(request, app.state.application)

@app.get("/")
async def index():
    return await app.state.webhook_controller.handle_index()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9527)