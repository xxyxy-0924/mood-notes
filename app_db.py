"""
每日心情笔记 - Flask 后端 (数据库版)
使用免费的数据库服务存储数据，避免容器重启导致的数据丢失
"""
import os
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# ===== 配置 =====
# 使用环境变量配置数据库连接
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # 用于 PostgreSQL
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")  # 用于 Supabase
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # Supabase 密钥

# 如果没有配置外部数据库，则使用内存存储（适用于短期测试）
MEMORY_STORAGE = []
storage_lock = threading.Lock()

# 访问密码
ACCESS_PASSWORD = os.environ.get("MOOD_PASSWORD", "")


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
    """从数据库加载心情记录"""
    # 如果配置了 Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        return load_notes_supabase()
    # 如果配置了 PostgreSQL
    elif DATABASE_URL:
        return load_notes_postgres()
    # 否则使用内存存储（临时）
    else:
        return load_notes_from_memory()


def save_notes(notes):
    """保存心情记录到数据库"""
    # 如果配置了 Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        return save_notes_supabase(notes)
    # 如果配置了 PostgreSQL
    elif DATABASE_URL:
        return save_notes_postgres(notes)
    # 否则使用内存存储（临时）
    else:
        return save_notes_to_memory(notes)


def load_notes_supabase():
    """从 Supabase 加载记录"""
    # 这里需要安装 supabase 库: pip install supabase
    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        response = client.table("mood_notes").select("*").order("id", desc=True).execute()
        return response.data
    except ImportError:
        print("Supabase client not installed. Install with: pip install supabase")
        return load_notes_from_memory()
    except Exception as e:
        print(f"Error loading from Supabase: {e}")
        return load_notes_from_memory()


def save_notes_supabase(notes):
    """保存记录到 Supabase"""
    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # 清空现有数据并插入新数据
        client.table("mood_notes").delete().neq("id", 0).execute()
        
        # 插入所有记录
        for note in notes:
            client.table("mood_notes").insert(note).execute()
    except ImportError:
        print("Supabase client not installed. Install with: pip install supabase")
        save_notes_to_memory(notes)
    except Exception as e:
        print(f"Error saving to Supabase: {e}")
        save_notes_to_memory(notes)


def load_notes_postgres():
    """从 PostgreSQL 加载记录"""
    # 这里需要安装 psycopg2 或 sqlalchemy
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM mood_notes ORDER BY created_at DESC")
        records = cur.fetchall()
        cur.close()
        conn.close()
        
        # 转换为字典列表
        notes = []
        for record in records:
            note = dict(record)
            # 确保时间格式正确
            if isinstance(note['time'], datetime):
                note['time'] = note['time'].isoformat() + "Z"
            notes.append(note)
        
        return notes
    except ImportError:
        print("PostgreSQL client not installed. Install with: pip install psycopg2-binary")
        return load_notes_from_memory()
    except Exception as e:
        print(f"Error loading from PostgreSQL: {e}")
        return load_notes_from_memory()


def save_notes_postgres(notes):
    """保存记录到 PostgreSQL"""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # 清空现有数据
        cur.execute("DELETE FROM mood_notes")
        
        # 插入新数据
        for note in notes:
            cur.execute("""
                INSERT INTO mood_notes (id, mood, text, sender, time, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                note.get('id'),
                note.get('mood'),
                note.get('text'),
                note.get('sender', '匿名'),
                note.get('time'),
                datetime.utcnow()
            ))
        
        conn.commit()
        cur.close()
        conn.close()
    except ImportError:
        print("PostgreSQL client not installed. Install with: pip install psycopg2-binary")
        save_notes_to_memory(notes)
    except Exception as e:
        print(f"Error saving to PostgreSQL: {e}")
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

    note = {
        "id": int(datetime.utcnow().timestamp() * 1000),
        "mood": mood,
        "text": text,
        "sender": sender,
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
    return jsonify({
        "status": "ok", 
        "time": datetime.utcnow().isoformat() + "Z",
        "storage": "supabase" if SUPABASE_URL and SUPABASE_KEY else 
                   "postgres" if DATABASE_URL else 
                   "memory (temporary)"
    })


# ===== 启动 =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
