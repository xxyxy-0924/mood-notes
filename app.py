"""
Daily mood notes - Flask backend.

Stores notes in JSONBin when configured, with in-memory storage as a local fallback.
"""

import os
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "").strip()
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "").strip()
ACCESS_PASSWORD = os.environ.get("MOOD_PASSWORD", "")

VALID_MOODS = [
    "开心",
    "难过",
    "生气",
    "委屈",
    "想你",
    "需要安慰",
    "想一个人静静",
]
MAX_TEXT_LENGTH = 500
MAX_SENDER_LENGTH = 20
MAX_TAGS = 10
MAX_TAG_LENGTH = 20

MEMORY_STORAGE = []
storage_lock = threading.Lock()


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_tags(value):
    if isinstance(value, list):
        raw_tags = value
    else:
        raw_tags = str(value or "").split(",")

    tags = []
    for tag in raw_tags:
        clean = str(tag).strip()[:MAX_TAG_LENGTH]
        if clean and clean not in tags:
            tags.append(clean)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def normalize_note(note):
    if not isinstance(note, dict):
        return None

    try:
        note_id = int(note.get("id") or datetime.now(timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError):
        note_id = int(datetime.now(timezone.utc).timestamp() * 1000)

    mood = str(note.get("mood", "")).strip()
    text = str(note.get("text", "")).strip()
    if not mood or not text:
        return None

    sender = str(note.get("sender") or "匿名").strip()[:MAX_SENDER_LENGTH] or "匿名"
    timestamp = str(note.get("time") or utc_now_iso()).strip()

    return {
        "id": note_id,
        "mood": mood,
        "text": text[:MAX_TEXT_LENGTH],
        "sender": sender,
        "tags": normalize_tags(note.get("tags", [])),
        "time": timestamp,
    }


def normalize_notes(notes):
    if not isinstance(notes, list):
        return []

    cleaned = []
    for note in notes:
        normalized = normalize_note(note)
        if normalized:
            cleaned.append(normalized)
    return cleaned


def extract_notes_from_jsonbin_record(record):
    if isinstance(record, list):
        return normalize_notes(record)
    if isinstance(record, dict):
        return normalize_notes(record.get("notes", []))
    return []


def jsonbin_headers():
    return {
        "Content-Type": "application/json",
        "X-Master-Key": JSONBIN_API_KEY,
        "X-BIN-VERSIONING": "false",
    }


def load_notes_from_jsonbin():
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        return load_notes_from_memory()

    try:
        response = requests.get(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
            headers=jsonbin_headers(),
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return extract_notes_from_jsonbin_record(data.get("record"))

        app.logger.warning("JSONBin load error: %s %s", response.status_code, response.text[:200])
        return load_notes_from_memory()
    except requests.RequestException as exc:
        app.logger.warning("Error loading from JSONBin: %s", exc)
        return load_notes_from_memory()


def save_notes_to_jsonbin(notes):
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        save_notes_to_memory(notes)
        return False

    payload = {
        "notes": normalize_notes(notes),
        "updated_at": utc_now_iso(),
    }

    try:
        response = requests.put(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
            json=payload,
            headers=jsonbin_headers(),
            timeout=10,
        )
        if response.status_code in (200, 201):
            return True

        app.logger.warning("JSONBin save error: %s %s", response.status_code, response.text[:200])
        save_notes_to_memory(notes)
        return False
    except requests.RequestException as exc:
        app.logger.warning("Error saving to JSONBin: %s", exc)
        save_notes_to_memory(notes)
        return False


def load_notes_from_memory():
    with storage_lock:
        return normalize_notes(MEMORY_STORAGE)


def save_notes_to_memory(notes):
    global MEMORY_STORAGE
    with storage_lock:
        MEMORY_STORAGE = normalize_notes(notes)


def load_notes():
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        return load_notes_from_jsonbin()
    return load_notes_from_memory()


def save_notes(notes):
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        return save_notes_to_jsonbin(notes)
    save_notes_to_memory(notes)
    return True


@app.route("/")
def index():
    return render_template("index.html", needs_password=bool(ACCESS_PASSWORD))


@app.route("/login", methods=["POST"])
def login():
    if not ACCESS_PASSWORD:
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    if data.get("password") == ACCESS_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码不正确"}), 403


def check_auth():
    if not ACCESS_PASSWORD:
        return True
    return request.headers.get("X-Mood-Password", "") == ACCESS_PASSWORD


def unauthorized_response():
    return jsonify({"error": "需要密码验证"}), 401


@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    if not check_auth():
        return unauthorized_response()
    return jsonify(load_notes())


@app.route("/api/notes", methods=["POST"])
def api_create_note():
    if not check_auth():
        return unauthorized_response()

    data = request.get_json(silent=True) or {}
    mood_input = str(data.get("mood", "")).strip()
    text = str(data.get("text", "")).strip()
    sender = str(data.get("sender", "")).strip()[:MAX_SENDER_LENGTH] or "匿名"

    if not mood_input:
        return jsonify({"error": "请选择一种心情"}), 400
    if not text:
        return jsonify({"error": "请写几句话"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": f"内容不能超过 {MAX_TEXT_LENGTH} 字"}), 400

    moods = []
    for mood in mood_input.split(","):
        clean = mood.strip()
        if clean and clean not in moods:
            moods.append(clean)

    if not moods:
        return jsonify({"error": "请选择一种心情"}), 400
    if len(moods) > 3:
        return jsonify({"error": "一次最多选择 3 种心情"}), 400

    invalid_moods = [mood for mood in moods if mood not in VALID_MOODS]
    if invalid_moods:
        return jsonify({"error": f"心情类型无效: {invalid_moods[0]}"}), 400

    note = {
        "id": int(datetime.now(timezone.utc).timestamp() * 1000),
        "mood": "+".join(moods),
        "text": text,
        "sender": sender,
        "tags": normalize_tags(data.get("tags", "")),
        "time": utc_now_iso(),
    }

    notes = load_notes()
    notes.insert(0, note)
    saved = save_notes(notes)

    return jsonify(note), 201 if saved else 202


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def api_delete_note(note_id):
    if not check_auth():
        return unauthorized_response()

    notes = load_notes()
    next_notes = [note for note in notes if note.get("id") != note_id]
    if len(next_notes) == len(notes):
        return jsonify({"error": "记录不存在"}), 404

    saved = save_notes(next_notes)
    return jsonify({"ok": True, "saved": saved})


@app.route("/api/stats", methods=["GET"])
def api_stats():
    if not check_auth():
        return unauthorized_response()

    notes = load_notes()
    mood_counts = {mood: 0 for mood in VALID_MOODS}
    for note in notes:
        for mood in str(note.get("mood", "")).split("+"):
            if mood in mood_counts:
                mood_counts[mood] += 1

    return jsonify({
        "total": len(notes),
        "moods": mood_counts,
        "latest_time": notes[0]["time"] if notes else None,
    })


@app.route("/health")
def health():
    storage_type = "jsonbin" if JSONBIN_API_KEY and JSONBIN_BIN_ID else "memory (temporary)"
    return jsonify({
        "status": "ok",
        "time": utc_now_iso(),
        "storage": storage_type,
        "password_enabled": bool(ACCESS_PASSWORD),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
