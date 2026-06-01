# WeCord 生产部署指南

## 架构概览

```
互联网用户                    远程服务器 (VPS)
    │                       ┌─────────────────────────┐
    │  HTTPS :443           │  Caddy / Nginx          │
    └──────────────────────▶│  ├─ / → Gist :8080      │
                            │  └─ 自动 Let's Encrypt  │
                            │                         │
                            │  we-mp-rss :8001        │  ← 不暴露公网
                            │  Gist :8080             │
                            │  Bridge :8081           │  ← 不暴露公网
                            └─────────────────────────┘
```

## 1. 服务器要求

| 项目 | 最低 | 推荐 |
|------|------|------|
| CPU | 2 核 | 4 核 |
| 内存 | 2 GB | 4 GB |
| 磁盘 | 20 GB | 40 GB |
| 系统 | Ubuntu 22.04 / Debian 12 | 同 |
| 带宽 | 3 Mbps | 5 Mbps+ |

国内云厂商参考（2C4G 年付 ~200-400 元）：
- 阿里云 ECS、腾讯云轻量、华为云 HECS

## 2. 服务器初始化

```bash
# SSH 登录后
apt update && apt install -y curl git

# 安装 Docker（官方脚本）
curl -fsSL https://get.docker.com | bash

# 普通用户免 sudo 运行 docker
sudo usermod -aG docker $USER
# 重新登录生效
```

## 3. 部署项目

```bash
git clone <你的仓库地址> /opt/wecord
cd /opt/wecord

# 配置环境变量
cp .env.example .env
nano .env   # 填入实际值
```

**.env 关键配置**（服务器环境）：

```bash
# Discord & AI（不变）
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx
DEEPSEEK_API_KEY=sk-xxx

# Gist — 注意 PUBLIC_URL 改为域名
GIST_BASE_URL=http://gist:8080
GIST_PUBLIC_URL=https://your-domain.com     # ← 改为实际域名
GIST_USERNAME=xxx
GIST_PASSWORD=xxx
GIST_FEED_ID=xxx
```

## 4. 配置反向代理（Caddy + HTTPS）

```bash
# 安装 Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

**`/etc/caddy/Caddyfile`**：

```caddy
your-domain.com {
    reverse_proxy localhost:8080
}
```

```bash
sudo systemctl reload caddy
```

Caddy 自动申请 Let's Encrypt 证书，无需额外配置。

## 5. 首次扫码授权

we-mp-rss 需要扫码获取公众号 RSS，但服务器没有浏览器。

**方案：SSH 端口转发**

在本地电脑执行：
```bash
ssh -L 8001:localhost:8001 user@your-server
```

然后本地浏览器打开 `http://localhost:8001`，扫码授权。

完成后关掉 SSH 隧道即可。Cookie 有效期较长，过期后才需要重新扫码。

## 6. 配置 we-mp-rss Webhook

1. 浏览器访问 `http://localhost:8001`（通过 SSH 隧道）
2. 消息任务 → 新建 → 配置：
   - `web_hook_url`: `http://bridge:8081/webhook`
   - `message_template`: 使用默认 JSON 模板
   - `cron_exp`: `*/10 * * * *`
   - `mps_id`: 你的公众号 ID

## 7. 配置 Gist 订阅源

Gist 中该 feed 的 RSS URL 需要改为容器内网地址：
- 原来可能是 `http://host.docker.internal:8001/rss/xxx`
- 改为 `http://we-mp-rss:8001/rss/xxx`

在 Gist Web UI（`https://your-domain.com`）中编辑 feed。

## 8. 启动

```bash
docker compose up -d --build
```

## 代码更新流程

```bash
# 本地开发完成后
git add . && git commit -m "fix: xxx"
git push

# 服务器上
ssh user@your-server
cd /opt/wecord
git pull
docker compose up -d --build   # 只重建有改动的服务
```

## 安全建议

- 用非 root 用户运行
- 防火墙只开放 22 (SSH) 和 443 (HTTPS)
- `.env` 权限设为 600
- 定期备份 `./data/` 目录
