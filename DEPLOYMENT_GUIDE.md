# 每日心情笔记 - 部署指南

## 解决数据丢失问题

由于 Render 免费版容器重启会导致数据丢失，我们需要使用外部存储服务。

## 方案1: 使用 JSONBin.io (推荐 - 简单易用)

### 1. 注册 JSONBin.io
- 访问 https://jsonbin.io/
- 注册免费账户

### 2. 创建新的 JSON Bin
- 登录后点击 "Create new"
- 将你的数据结构粘贴进去（或留空）
- 记下生成的 "Bin ID"

### 3. 获取 API 密钥
- 在 "Account" 页面找到 "API Key"

### 4. 部署到 Render
在 Render 的环境变量中设置：
```
JSONBIN_API_KEY = 你的API密钥
JSONBIN_BIN_ID = 你的BinID
MOOD_PASSWORD = 你们的共同密码（可选）
```

## 方案2: 使用 Supabase (功能更强)

### 1. 注册 Supabase
- 访问 https://supabase.io/
- 创建免费项目

### 2. 创建表
```sql
CREATE TABLE mood_notes (
  id BIGINT PRIMARY KEY,
  mood TEXT NOT NULL,
  text TEXT NOT NULL,
  sender TEXT DEFAULT '匿名',
  time TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 3. 部署到 Render
在 Render 的环境变量中设置：
```
SUPABASE_URL = 你的项目URL
SUPABASE_KEY = 你的 anon key
MOOD_PASSWORD = 你们的共同密码（可选）
```

## 方案3: 使用默认（临时）
如果不设置任何外部存储，数据会保存在内存中，容器重启后会丢失。

---

## 部署步骤

1. 将代码推送到 GitHub 仓库
2. 在 Render 创建 Web Service，连接你的仓库
3. 在环境变量中配置上述参数
4. 部署完成后即可使用

## 环境变量说明

- `JSONBIN_API_KEY` / `JSONBIN_BIN_ID`: JSONBin 配置
- `SUPABASE_URL` / `SUPABASE_KEY`: Supabase 配置  
- `DATABASE_URL`: PostgreSQL 数据库连接字符串
- `MOOD_PASSWORD`: 访问密码（可选）
- `FLASK_DEBUG`: 调试模式（默认 0）

## 文件结构

```
mood-notes/
├── app_persistent.py    ← 使用外部存储的主程序
├── app.py              ← 原始版本（本地存储）
├── requirements.txt
├── Procfile
├── .gitignore
└── templates/
    └── index.html
```

要使用持久化版本，请将 `app_persistent.py` 重命名为 `app.py` 再部署。