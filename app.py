"""
每日心情笔记 - 数据持久化解决方案

由于 Render 免费版容器重启会导致数据丢失，
这里提供几种解决方案：

方案1: 使用 GitHub Gist 作为外部存储
方案2: 使用 JSONBin.io 在线 JSON 存储
方案3: 使用免费数据库 (Supabase/PostgreSQL)

当前实现使用方案2: JSONBin.io (免费且简单)
"""

import os
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# ===== 配置 =====
# JSONBin.io 配置 (需要预先创建一个免费的 JSONBin)
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "")  # 你的 JSONBin API 密钥
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "")    # 你的 JSONBin ID

# 如果没有配置 JSONBin，则使用内存存储（临时方案）
MEMORY_STORAGE = []
storage_lock = threading.Lock()

# 访问密码
ACCESS_PASSWORD = os.environ.get("MOOD_PASSWORD", "")


def load_notes_from_jsonbin():
    """从 JSONBin 加载心情记录"""
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        return load_notes_from_memory()
    
    try:
        import requests
        headers = {
            'Content-Type': 'application/json',
            'X-Master-Key': JSONBIN_API_KEY
        }
        response = requests.get(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}", headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get('record', [])
        else:
            print(f"JSONBin load error: {response.status_code}")
            return load_notes_from_memory()
    except Exception as e:
        print(f"Error loading from JSONBin: {e}")
        return load_notes_from_memory()


def save_notes_to_jsonbin(notes):
    """保存心情记录到 JSONBin"""
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        save_notes_to_memory(notes)
        return
    
    try:
        import requests
        headers = {
            'Content-Type': 'application/json',
            'X-Master-Key': JSONBIN_API_KEY,
            'X-BIN-VERSIONING': 'false'  # 不启用版本控制，覆盖现有数据
        }
        response = requests.put(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}", 
                               json={"notes": notes}, headers=headers)
        if response.status_code != 200:
            print(f"JSONBin save error: {response.status_code}")
            save_notes_to_memory(notes)
    except Exception as e:
        print(f"Error saving to JSONBin: {e}")
        save_notes_to_memory(notes)


def load_notes_from_memory():
    """从内存加载心情记录（临时方案）"""
    global MEMORY_STORAGE
    with storage_lock:
        return MEMORY_STORAGE.copy()


def save_notes_to_memory(notes):
    """保存心情记录到内存（临时方案）"""
    global MEMORY_STORAGE
    with storage_lock:
        MEMORY_STORAGE = notes


def load_notes():
    """从持久化存储加载心情记录"""
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        return load_notes_from_jsonbin()
    else:
        return load_notes_from_memory()


def save_notes(notes):
    """保存心情记录到持久化存储"""
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        save_notes_to_jsonbin(notes)
    else:
        save_notes_to_memory(notes)


# ===== 页面路由 =====

@app.route("/")
def index():
    """首页 — 心情笔记页面"""
    needs_password = bool(ACCESS_PASSWORD)
    return render_template("index.html", needs_password=needs_password)


@app.route("/login", methods=["POST"])
def login():
    """密码验证接口"""
    if not ACCESS_PASSWORD:
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    if data.get("password") == ACCESS_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码不正确"}), 403


# ===== API 接口 =====

def check_auth():
    """检查密码验证（从 Header 中读取）"""
    if not ACCESS_PASSWORD:
        return True
    auth = request.headers.get("X-Mood-Password", "")
    return auth == ACCESS_PASSWORD


@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    """获取所有心情记录"""
    if not check_auth():
        return jsonify({"error": "需要密码验证"}), 401

    notes = load_notes()
    return jsonify(notes)


@app.route("/api/notes", methods=["POST"])
def api_create_note():
    """创建一条心情记录"""
    if not check_auth():
        return jsonify({"error": "需要密码验证"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求数据格式错误"}), 400

    mood_input = data.get("mood", "").strip()
    text = data.get("text", "").strip()
    sender = data.get("sender", "").strip()[:20]  # 限制发送者名称长度

    if not mood_input:
        return jsonify({"error": "请选择一种心情"}), 400
    if not text:
        return jsonify({"error": "请写几句话"}), 400
    if len(text) > 500:
        return jsonify({"error": "内容不能超过 500 字"}), 400

    # Split multiple moods by comma and validate each
    moods = [m.strip() for m in mood_input.split(',')]
    valid_moods = ["开心", "难过", "生气", "委屈", "想你", "需要安慰", "想一个人静静"]
    
    for m in moods:
        if m not in valid_moods:
            return jsonify({"error": f"心情类型无效: {m}"}), 400
    
    # Join multiple moods with '+' for display
    mood = '+'.join(moods)
    
    if not sender:
        sender = "匿名"

    # 获取并处理标签
    tags_input = data.get("tags", "").strip()
    tags = []
    if tags_input:
        # 分割标签并去除空白
        tags = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
        # 限制每个标签长度和总数
        tags = [tag[:20] for tag in tags[:10]]  # 最多10个标签，每个最多20字符

    note = {
        "id": int(datetime.utcnow().timestamp() * 1000),
        "mood": mood,
        "text": text,
        "sender": sender,
        "tags": tags,
        "time": datetime.utcnow().isoformat() + "Z",
    }

    notes = load_notes()
    notes.insert(0, note)
    save_notes(notes)

    return jsonify(note), 201


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def api_delete_note(note_id):
    """删除一条心情记录"""
    if not check_auth():
        return jsonify({"error": "需要密码验证"}), 401

    notes = load_notes()
    original_len = len(notes)
    notes = [n for n in notes if n["id"] != note_id]
    if len(notes) == original_len:
        return jsonify({"error": "记录不存在"}), 404
    
    save_notes(notes)
    return jsonify({"ok": True})


# ===== 健康检查 =====
@app.route("/health")
def health():
    storage_type = "jsonbin" if JSONBIN_API_KEY and JSONBIN_BIN_ID else "memory (temporary)"
    return jsonify({
        "status": "ok", 
        "time": datetime.utcnow().isoformat() + "Z",
        "storage": storage_type
    })


# ===== 启动 =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
