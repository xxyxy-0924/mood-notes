# 每日心情笔记 - 部署指南

这个版本默认使用 Flask + Gunicorn 部署，推荐部署到 Render、Railway 或其他支持 Python Web Service 的平台。

## 必填配置

安装依赖：

```bash
pip install -r requirements.txt
```

启动命令：

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

`Procfile` 可以保持：

```text
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

## 推荐环境变量

```text
JSONBIN_API_KEY=你的 JSONBin API Key
JSONBIN_BIN_ID=你的 Bin ID
MOOD_PASSWORD=访问密码，可选但推荐
FLASK_DEBUG=0
```

如果没有配置 `JSONBIN_API_KEY` 和 `JSONBIN_BIN_ID`，应用会回退到内存存储。内存存储只适合测试，Render 免费实例重启后记录会丢失。

## JSONBin 数据格式

新版后端会保存为：

```json
{
  "notes": [],
  "updated_at": "2026-05-23T00:00:00Z"
}
```

同时兼容旧版直接保存数组的格式，所以已有数据不需要手动迁移。

## API

- `GET /api/notes`：获取所有心情记录
- `POST /api/notes`：新增记录
- `DELETE /api/notes/<id>`：删除记录
- `GET /api/stats`：获取统计数据
- `GET /health`：健康检查

如果设置了 `MOOD_PASSWORD`，前端会先要求输入密码，API 请求需要携带：

```text
X-Mood-Password: 你的访问密码
```

## 本次改进点

- 修复 JSONBin 保存和读取格式不一致导致线上新增记录失败的问题。
- 读取旧数据时自动清洗字段，避免坏数据拖垮页面。
- JSONBin 请求增加超时和错误日志。
- 新增 `/api/stats` 和更完整的 `/health`。
- 前端支持多选心情、昵称、标签、字数提示、完整筛选和更稳的异常提示。
