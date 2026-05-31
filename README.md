# WeCord

微信公众号中文文章 → AI 英译摘要卡片 → Discord 频道。

## 架构

```
we-mp-rss (:8001)          Gist (:8080)
   │ 扫码获取公众号 RSS         │ 订阅 RSS · AI 翻译
   │                           │
   │  webhook (新文章通知)      │  GET 公开只读 (免登录)
   ▼                           ▼
 Bridge (:8081)  ───────── Discord Webhook
   │  DeepSeek 英译 + 摘要       │  Embed 卡片
   └─────────────────────────────┘
```

| 服务 | 端口 | 说明 |
|------|------|------|
| we-mp-rss | 8001 | 扫码获取微信公众号 RSS 源 |
| Gist | 8080 | RSS 阅读器 · AI 翻译 · 公开只读 |
| Bridge | 8081 | 桥接服务 · webhook → 摘要 → Discord |

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入实际的 API key 和凭据
```

### 2. 初始化 Gist 账号

```bash
# 首次启动后会进入注册页面
docker compose up -d gist

# 浏览器访问 http://localhost:8080
# 注册账号 → 把 username/password 填入 .env 的 GIST_USERNAME / GIST_PASSWORD
```

### 3. 订阅公众号 RSS

1. 访问 `http://localhost:8001` 进入 we-mp-rss Web UI
2. 扫码授权获取公众号 RSS 源（会生成 FEED_ID）
3. 在 Gist (`http://localhost:8080`) 中添加订阅：
   - 添加 RSS 源 URL：`http://host.docker.internal:8001/rss/{FEED_ID}`
4. 在 Gist 中找到该 feed 的 ID（地址栏 `/#/feeds/{feedId}`），填入 `.env` 的 `GIST_FEED_ID`

### 4. 配置 we-mp-rss Webhook

1. 访问 `http://localhost:8001` → 消息任务
2. 新建消息任务，配置：
   - **web_hook_url**: `http://bridge:8081/webhook`
   - **message_template**: 使用默认 JSON 模板
   - **cron_exp**: `*/10 * * * *`（每 10 分钟检查）
   - **mps_id**: 你的公众号 ID

### 5. 启动全部服务

```bash
docker compose up -d
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `DISCORD_WEBHOOK_URL` | ✅ | Discord 频道 Webhook URL |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | — | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | — | 默认 `deepseek-chat` |
| `GIST_USERNAME` | ✅ | Gist 登录用户名 |
| `GIST_PASSWORD` | ✅ | Gist 登录密码 |
| `GIST_BASE_URL` | — | 默认 `http://gist:8080` |
| `GIST_FEED_ID` | ✅ | 目标公众号在 Gist 中的 Feed ID |
| `MAX_SUMMARY_CHARS` | — | 摘要最大字符数，默认 300 |
