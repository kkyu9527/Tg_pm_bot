# Telegram 私聊转发机器人

⚠️ **注意**：由于本项目使用的是 Webhook 模式，**必须使用公网可访问的域名**，且建议使用 **HTTPS**。

项目默认端口为 **9527**，务必确保服务器开启该端口并正确配置反向代理（如 Nginx）。

---

这是一个基于 Python 的 Telegram 机器人，用于将用户私聊消息转发到群组话题中，并允许管理员回复用户消息。

## 功能特点

* 将用户私聊消息转发到指定群组的话题中
* 支持文本、图片、视频、语音、音频、文件、贴纸等多种消息类型
* 自动为每个用户创建独立话题
* 管理员可以直接在群组话题中回复用户
* 支持编辑和删除已发送的消息
* 消息映射关系保存到数据库中，不保存具体内容

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/kkyu9527/Tg_pm_bot.git
cd Tg_pm_bot
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 从 BotFather 获取 Bot Token

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 创建机器人
3. 复制生成的 API Token
4. 关闭隐私模式：发送 `/setprivacy`，选择机器人，选择 Disable

### 4. 获取用户 ID 和群组 ID

* 用户 ID：可通过 `@userinfobot` 获取
* 群组 ID：打开 Telegram Web 版，进入群组，查看 URL 中的数字部分，格式可能是 `-100xxxxxxxxxx`

### 5. 创建 `.env` 文件

在项目根目录创建 `.env` 文件，示例内容如下：

```dotenv
BOT_TOKEN=你的机器人Token
USER_ID=你的用户ID
GROUP_ID=你的群组ID
DB_HOST=127.0.0.1
DB_USER=你的数据库用户名
DB_PASSWORD=你的数据库密码
DB_NAME=Tg_pm_bot
WEBHOOK_URL=https://yourdomain.com/webhook
```

---

## 使用 Docker 运行（可选）

### 1. 安装 Docker 和 Docker Compose

确保安装并启动 Docker Desktop。

### 2. 配置 `.env` 文件（Docker 模式）

```dotenv
DB_HOST=mysql
DB_USER=botuser
DB_PASSWORD=botpass
DB_NAME=telegram_bot
```

### 3. 启动容器

```bash
docker-compose up --build -d
```

### 4. 停止容器

```bash
docker-compose down
```

---

## 不使用 Docker 运行

激活虚拟环境后运行：

```bash
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python main.py
```

---

## 使用说明

1. 用户私聊机器人发送消息
2. 机器人转发消息到群组话题
3. 管理员可在群组话题中回复和管理消息

---

## 常见问题

* 数据库连接失败：确认数据库服务运行，且 `.env` 配置正确
* 缺少 `cryptography` 包：运行 `pip install cryptography`
* 机器人消息不转发：确认 Bot Token、群组 ID 和机器人权限
* Webhook 无法访问：确认服务器公网可访问，且使用 HTTPS

---

## 许可证

[MIT License](https://github.com/kkyu9527/Tg_pm_bot?tab=MIT-1-ov-file)

---

## 项目地址

[https://github.com/kkyu9527/Tg\_pm\_bot.git](https://github.com/kkyu9527/Tg_pm_bot.git)
