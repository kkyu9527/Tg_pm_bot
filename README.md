# Telegram 私聊转发机器人

这是一个基于 Python 的 Telegram 机器人，用于将用户私聊消息转发到群组话题中，并允许管理员回复用户消息。

## 功能特点

- 将用户私聊消息转发到指定群组的话题中
- 支持文本、图片、视频、语音、音频、文件、贴纸等多种消息类型
- 自动为每个用户创建独立的话题
- 管理员可以直接在群组话题中回复用户
- 支持编辑和删除已发送的消息
- 消息记录保存到数据库中，方便查询和管理

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/kkyu9527/Tg_pm_bot.git
cd Tg_pm_bot
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate  # 在 Windows 上使用 .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 从 BotFather 获取 Bot Token

1. 在 Telegram 中搜索 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 命令创建一个新机器人
3. 按照提示设置机器人名称和用户名
4. 创建成功后，BotFather 会发送一个 API Token，格式类似于：`123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`
5. 保存这个 Token，后续需要用到
6. **关闭隐私模式**：发送 `/setprivacy` 命令，选择你的机器人，然后选择 `Disable`。这样机器人才能看到群组中的所有消息

### 4. 获取自己的用户 ID

有几种方法可以获取自己的 Telegram 用户 ID：

**方法一：使用 @userinfobot**
1. 在 Telegram 中搜索 [@userinfobot](https://t.me/userinfobot)
2. 向机器人发送任意消息
3. 机器人会回复你的用户信息，包括用户 ID

**方法二：使用 @RawDataBot**
1. 在 Telegram 中搜索 [@RawDataBot](https://t.me/RawDataBot)
2. 向机器人发送任意消息
3. 机器人会回复详细的用户数据，其中包含你的用户 ID

### 5. 创建群组并获取群组 ID

1. 在 Telegram 中创建一个新的群组（建议创建超级群组）
2. 确保启用了话题功能（在群组设置中开启）
3. 将你创建的机器人添加到群组中，并授予管理员权限
4. 获取群组 ID 的方法：
   - 在浏览器中打开 Telegram Web 版
   - 进入你创建的群组
   - 查看浏览器地址栏，URL 中的数字部分就是群组 ID，格式可能是 `-100xxxxxxxxxx`

### 6. 创建 .env 文件

在项目根目录创建一个 `.env` 文件，填入以下内容：

```
BOT_TOKEN=你的机器人Token
USER_ID=你的用户ID
GROUP_ID=你的群组ID
DB_HOST=localhost
DB_USER=你的数据库用户名
DB_PASSWORD=你的数据库密码
DB_NAME=Tg_pm_bot
```

注意：
- `BOT_TOKEN` 是从 BotFather 获取的 Token
- `USER_ID` 是你的 Telegram 用户 ID
- `GROUP_ID` 是你创建的群组 ID，包括前面的负号（如果有）

### 7. 配置 MySQL 数据库

确保你的系统已安装 MySQL 数据库，并创建一个用户用于访问数据库。

注意：程序会自动创建名为 `Tg_pm_bot` 的数据库和所需的表，无需手动创建。

### 8. 运行机器人

首先激活虚拟环境：

```bash
source .venv/bin/activate  # 在 macOS/Linux 上
# 或
.venv\Scripts\activate     # 在 Windows 上
```

```bash
python main.py
```

如果一切配置正确，你应该会看到类似以下的日志输出：

```
INFO - 开始初始化 Telegram 私聊转发机器人
INFO - 初始化数据库连接
INFO - 初始化数据库表
INFO - 成功连接到MySQL服务器
INFO - 数据库 'Tg_pm_bot' 已创建或已存在
INFO - 所有数据库表已成功创建
INFO - 数据库初始化成功
INFO - 启动机器人
INFO - 机器人启动成功
```

## 使用方法

1. 用户向你的机器人发送私聊消息
2. 机器人会自动将消息转发到指定群组的话题中
3. 你可以在群组话题中查看和回复用户消息
4. 回复时可以使用编辑和删除按钮管理已发送的消息

## 项目结构

```
Tg_pm_bot/
├── database/               # 数据库相关代码
│   ├── db_connector.py     # 数据库连接器
│   ├── db_init.py          # 数据库初始化
│   └── db_operations.py    # 数据库操作
├── handlers/               # 消息处理程序
│   ├── command_handlers.py # 命令处理
│   └── message_handlers.py # 消息处理
├── logs/                   # 日志文件目录
├── utils/                  # 工具函数
│   └── logger.py           # 日志配置
├── .env                    # 环境变量配置
├── main.py                 # 主程序
└── requirements.txt        # 依赖列表
```

## 依赖项

主要依赖项包括：

- python-telegram-bot：Telegram 机器人 API 的 Python 封装
- python-dotenv：用于加载环境变量
- mysql-connector-python：MySQL 数据库连接器

完整依赖列表请参见 `requirements.txt` 文件。

## 故障排除

1. **连接超时错误**：
   - 检查网络连接
   - 如果在中国大陆使用，可能需要配置代理

2. **数据库连接错误**：
   - 确认 MySQL 服务正在运行
   - 检查 .env 文件中的数据库凭据是否正确

3. **机器人无法接收消息**：
   - 确认 BOT_TOKEN 是否正确
   - 检查机器人是否已启动

4. **无法转发消息到群组**：
   - 确认 GROUP_ID 是否正确
   - 检查机器人是否已添加到群组并具有管理员权限
   - 确认群组已启用话题功能

## 许可证

[MIT License](https://github.com/kkyu9527/Tg_pm_bot/blob/main/LICENSE)

## 项目地址

https://github.com/kkyu9527/Tg_pm_bot.git
