"""
Webhook控制器
处理FastAPI的路由和响应
"""

import time
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from telegram import Update
from utils.logger import setup_logger

logger = setup_logger('web_ctrl')


class WebhookController:
    """Webhook控制器"""
    
    def __init__(self, app_version: str):
        self.app_version = app_version
    
    async def handle_webhook(self, request: Request, application):
        """处理Telegram webhook请求"""
        data = await request.json()
        logger.info("📩 收到 Webhook 更新")
        update = Update.de_json(data, bot=application.bot)
        await application.update_queue.put(update)
        return Response(content="OK", status_code=200)
    
    async def handle_index(self):
        """处理首页请求"""
        return JSONResponse(content={
            "status": "✅ running",
            "service": "Telegram Forward Bot",
            "version": self.app_version,
            "uptime": time.strftime("%Y-%m-%d %H:%M:%S")
        })