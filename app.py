"""
Daily mood notes - Flask backend.

Notes are stored in JSONBin when configured. If JSONBin is unavailable, writes
fail closed instead of falling back to memory, so old cloud data cannot be
accidentally overwritten by an empty temporary list.
"""

import json
import os
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

app = Flask(__name__)

JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "").strip()
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "").strip()
ACCESS_PASSWORD = os.environ.get("MOOD_PASSWORD", "").strip()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
DEFAULT_WEATHER_CITY = os.environ.get("DEFAULT_WEATHER_CITY", "厦门海沧").strip() or "厦门海沧"

TEXT_MOODS = [
    "开心",
    "难过",
    "生气",
    "委屈",
    "想你",
    "需要安慰",
    "想一个人静静",
]
EMOJI_MOODS = ["😋", "🥲", "🥹", "🧐", "🤓", "😜", "😝", "😞", "😟", "😣", "😖", "☹️", "😓", "😱", "😨", "😰"]
VALID_MOODS = TEXT_MOODS + EMOJI_MOODS
REACTIONS = ["抱抱你", "收到啦", "想你了"]
NEGATIVE_MOODS = {"难过", "生气", "委屈", "需要安慰", "想一个人静静", "🥲", "🥹", "😞", "😟", "😣", "😖", "☹️", "😓", "😱", "😨", "😰"}

MAX_TEXT_LENGTH = 500
MAX_SENDER_LENGTH = 20
MAX_TAGS = 10
MAX_TAG_LENGTH = 20

MEMORY_STORAGE = []
storage_lock = threading.Lock()

WEATHER_CODES = {
    0: "晴",
    1: "多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾",
    51: "小雨",
    53: "小雨",
    55: "小雨",
    56: "冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "阵雪",
    95: "雷雨",
    96: "雷雨",
    99: "雷雨",
}
WEATHER_EMOJIS = {
    "晴": "☀️",
    "多云": "⛅",
    "阴": "☁️",
    "雾": "🌫️",
    "小雨": "🌧️",
    "中雨": "🌧️",
    "大雨": "🌧️",
    "阵雨": "🌦️",
    "强阵雨": "⛈️",
    "雷雨": "⛈️",
    "小雪": "🌨️",
    "中雪": "🌨️",
    "大雪": "❄️",
    "雪": "❄️",
    "冻雨": "🌧️",
}


class StorageUnavailable(RuntimeError):
    """Raised when JSONBin cannot be reached or rejects a request."""


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_reactions():
    return {reaction: 0 for reaction in REACTIONS}


def normalize_reactions(value):
    reactions = default_reactions()
    if not isinstance(value, dict):
        return reactions
    for reaction in REACTIONS:
        try:
            reactions[reaction] = max(0, int(value.get(reaction, 0)))
        except (TypeError, ValueError):
            reactions[reaction] = 0
    return reactions


def normalize_tags(value):
    raw_tags = value if isinstance(value, list) else str(value or "").split(",")
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
        "reactions": normalize_reactions(note.get("reactions", {})),
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


def jsonbin_configured():
    return bool(JSONBIN_API_KEY and JSONBIN_BIN_ID)


def load_notes_from_jsonbin():
    try:
        response = requests.get(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
            headers=jsonbin_headers(),
            timeout=10,
        )
    except requests.RequestException as exc:
        raise StorageUnavailable(f"JSONBin 读取失败: {exc}") from exc

    if response.status_code != 200:
        raise StorageUnavailable(f"JSONBin 读取失败: {response.status_code} {response.text[:160]}")

    data = response.json()
    return extract_notes_from_jsonbin_record(data.get("record"))


def save_notes_to_jsonbin(notes):
    payload = {"notes": normalize_notes(notes), "updated_at": utc_now_iso()}
    try:
        response = requests.put(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
            json=payload,
            headers=jsonbin_headers(),
            timeout=10,
        )
    except requests.RequestException as exc:
        raise StorageUnavailable(f"JSONBin 保存失败: {exc}") from exc

    if response.status_code not in (200, 201):
        raise StorageUnavailable(f"JSONBin 保存失败: {response.status_code} {response.text[:160]}")
    return True


def load_notes_from_memory():
    with storage_lock:
        return normalize_notes(MEMORY_STORAGE)


def save_notes_to_memory(notes):
    global MEMORY_STORAGE
    with storage_lock:
        MEMORY_STORAGE = normalize_notes(notes)
    return True


def load_notes():
    if jsonbin_configured():
        return load_notes_from_jsonbin()
    return load_notes_from_memory()


def save_notes(notes):
    if jsonbin_configured():
        return save_notes_to_jsonbin(notes)
    return save_notes_to_memory(notes)


def storage_error_response(exc):
    app.logger.warning("Storage unavailable: %s", exc)
    return jsonify({
        "error": "云端存储暂时不可用，已停止保存以保护旧数据。请稍后刷新或检查 JSONBin 配置。",
        "detail": str(exc),
    }), 503


def weather_text(code):
    return WEATHER_CODES.get(int(code or 0), "多云")


def weather_emoji(text):
    return WEATHER_EMOJIS.get(text, "🌤️")


def wind_level(speed_kmh):
    try:
        speed = float(speed_kmh or 0)
    except (TypeError, ValueError):
        speed = 0
    levels = [1, 5, 11, 19, 28, 38, 49, 61, 74, 88, 102, 117]
    for index, limit in enumerate(levels):
        if speed < limit:
            return index
    return 12


def weather_reminder(today, tomorrow, precip_probability):
    if tomorrow in {"中雨", "大雨", "阵雨", "强阵雨", "雷雨"} or precip_probability >= 55:
        return "明天可能有雨，出门记得带伞。"
    if today in {"大雨", "强阵雨", "雷雨"}:
        return "今天雨势明显，尽量慢一点出门。"
    if today in {"晴", "多云"}:
        return "天气还不错，也别忘了照顾好自己。"
    if today in {"小雪", "中雪", "大雪", "雪"}:
        return "天气偏冷，记得穿暖一点。"
    return "今天也要把自己照顾好。"


def geocode_city(city):
    if city == "厦门海沧":
        return {"name": "厦门海沧", "latitude": 24.4845, "longitude": 118.0329}
    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "zh", "format": "json"},
        timeout=8,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        raise ValueError("city not found")
    result = results[0]
    return {
        "name": result.get("name") or city,
        "latitude": result["latitude"],
        "longitude": result["longitude"],
    }


def fetch_weather(city=None, lat=None, lon=None):
    if lat is not None and lon is not None:
        location = {"name": "当前位置", "latitude": float(lat), "longitude": float(lon)}
    else:
        location = geocode_city(city or DEFAULT_WEATHER_CITY)

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 2,
        },
        timeout=8,
    )
    response.raise_for_status()
    data = response.json()
    current = data.get("current", {})
    daily = data.get("daily", {})
    today_code = current.get("weather_code", 3)
    tomorrow_codes = daily.get("weather_code") or [today_code, today_code]
    tomorrow_code = tomorrow_codes[1] if len(tomorrow_codes) > 1 else today_code
    today_text = weather_text(today_code)
    tomorrow_text = weather_text(tomorrow_code)
    precip = daily.get("precipitation_probability_max") or [0, 0]
    tomorrow_precip = int(precip[1] if len(precip) > 1 and precip[1] is not None else 0)

    return {
        "ok": True,
        "city": location["name"],
        "temperature": round(float(current.get("temperature_2m", 0))),
        "weather": today_text,
        "emoji": weather_emoji(today_text),
        "humidity": int(current.get("relative_humidity_2m") or 0),
        "wind_level": wind_level(current.get("wind_speed_10m")),
        "today_high": round(float((daily.get("temperature_2m_max") or [0])[0] or 0)),
        "today_low": round(float((daily.get("temperature_2m_min") or [0])[0] or 0)),
        "tomorrow": tomorrow_text,
        "tomorrow_precipitation": tomorrow_precip,
        "reminder": weather_reminder(today_text, tomorrow_text, tomorrow_precip),
        "source": "open-meteo",
    }


def split_note_moods(note):
    return [mood for mood in str(note.get("mood", "")).split("+") if mood]


def local_analysis(notes):
    recent = notes[:10]
    total = len(notes)
    if not total:
        return {
            "summary": "还没有记录，今天可以先写下一句话。",
            "suggestion": "不用写得很完整，几个字也算认真照顾自己。",
            "tone": "empty",
            "source": "local",
        }
    recent_moods = [mood for note in recent for mood in split_note_moods(note)]
    negative_count = sum(1 for mood in recent_moods if mood in NEGATIVE_MOODS)
    positive_count = sum(1 for mood in recent_moods if mood in {"开心", "😋", "😜", "😝", "🤓"})
    unique_days = []
    for note in notes:
        day = str(note.get("time", ""))[:10]
        if day and day not in unique_days:
            unique_days.append(day)
    streak_hint = f"你已经留下 {total} 条心情记录，" if total >= 2 else "你已经开始记录自己，"
    if negative_count >= max(2, positive_count + 1):
        return {
            "summary": f"{streak_hint}最近低落和紧张的信号偏多。",
            "suggestion": "今晚适合早点休息，或者给自己安排一件很小但舒服的事。",
            "tone": "care",
            "source": "local",
        }
    if positive_count >= 2:
        return {
            "summary": f"{streak_hint}最近出现了不少轻松的情绪。",
            "suggestion": "可以把让你开心的小细节记下来，之后会很有用。",
            "tone": "bright",
            "source": "local",
        }
    if len(unique_days) >= 3:
        return {
            "summary": f"{streak_hint}连续关注自己的节奏正在变稳定。",
            "suggestion": "继续这样慢慢写，小蜥蜴会帮你把变化收起来。",
            "tone": "steady",
            "source": "local",
        }
    return {
        "summary": f"{streak_hint}情绪还在慢慢展开。",
        "suggestion": "今天可以多写一点原因，小蜥蜴会更懂你。",
        "tone": "gentle",
        "source": "local",
    }


def deepseek_analysis(notes):
    if not DEEPSEEK_API_KEY or not notes:
        return None
    recent = [
        {"mood": note.get("mood"), "text": note.get("text"), "time": note.get("time"), "tags": note.get("tags", [])}
        for note in notes[:8]
    ]
    prompt = (
        "你是一个温柔克制的心情日记助手，名字叫小蜥蜴。"
        "根据最近记录输出紧凑 JSON，字段只有 summary、suggestion、tone。"
        "summary 不超过 32 字，suggestion 不超过 42 字，tone 从 care/bright/steady/gentle 选择。"
        "不要诊断疾病，不要夸张，不要说教。记录如下："
        f"{recent}"
    )
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": "你只输出紧凑 JSON，不要 Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 220,
            },
            timeout=12,
        )
        response.raise_for_status()
        parsed = json.loads(response.json()["choices"][0]["message"]["content"].strip())
        return {
            "summary": str(parsed.get("summary") or "小蜥蜴看见了你最近的心情。")[:60],
            "suggestion": str(parsed.get("suggestion") or "先照顾好今天的自己。")[:80],
            "tone": str(parsed.get("tone") or "gentle")[:20],
            "source": "deepseek",
        }
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("DeepSeek analysis fallback: %s", exc)
        return None


def check_auth():
    if not ACCESS_PASSWORD:
        return True
    return request.headers.get("X-Mood-Password", "").strip() == ACCESS_PASSWORD


def unauthorized_response():
    return jsonify({"error": "需要密码验证，请重新输入密码。"}), 401


@app.route("/")
def index():
    return render_template("index.html", needs_password=bool(ACCESS_PASSWORD))


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/login", methods=["POST"])
def login():
    if not ACCESS_PASSWORD:
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    if str(data.get("password", "")).strip() == ACCESS_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码不正确"}), 403


@app.route("/api/weather", methods=["GET"])
def api_weather():
    city = request.args.get("city", DEFAULT_WEATHER_CITY).strip() or DEFAULT_WEATHER_CITY
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    try:
        weather = fetch_weather(city=city, lat=lat, lon=lon) if lat and lon else fetch_weather(city=city)
        return jsonify(weather)
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Weather fallback: %s", exc)
        return jsonify({
            "ok": False,
            "city": city,
            "temperature": None,
            "weather": "暂不可用",
            "emoji": "🌤️",
            "humidity": None,
            "wind_level": None,
            "today_high": None,
            "today_low": None,
            "tomorrow": "未知",
            "tomorrow_precipitation": None,
            "reminder": "天气暂时没有取到，出门前再看一眼窗外。",
            "source": "fallback",
        }), 200


@app.route("/api/analysis", methods=["GET"])
def api_analysis():
    if not check_auth():
        return unauthorized_response()
    try:
        notes = load_notes()
    except StorageUnavailable as exc:
        return storage_error_response(exc)
    return jsonify(deepseek_analysis(notes) or local_analysis(notes))


@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    if not check_auth():
        return unauthorized_response()
    try:
        return jsonify(load_notes())
    except StorageUnavailable as exc:
        return storage_error_response(exc)


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
        "reactions": default_reactions(),
        "time": utc_now_iso(),
    }
    try:
        notes = load_notes()
        notes.insert(0, note)
        save_notes(notes)
    except StorageUnavailable as exc:
        return storage_error_response(exc)
    return jsonify(note), 201


@app.route("/api/notes/<int:note_id>/reactions", methods=["POST"])
def api_add_reaction(note_id):
    if not check_auth():
        return unauthorized_response()
    data = request.get_json(silent=True) or {}
    reaction = str(data.get("reaction", "")).strip()
    if reaction not in REACTIONS:
        return jsonify({"error": "回应类型无效"}), 400
    try:
        notes = load_notes()
        for note in notes:
            if note.get("id") == note_id:
                reactions = normalize_reactions(note.get("reactions", {}))
                reactions[reaction] += 1
                note["reactions"] = reactions
                save_notes(notes)
                return jsonify({"ok": True, "saved": True, "note": note})
    except StorageUnavailable as exc:
        return storage_error_response(exc)
    return jsonify({"error": "记录不存在"}), 404


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def api_delete_note(note_id):
    if not check_auth():
        return unauthorized_response()
    try:
        notes = load_notes()
        next_notes = [note for note in notes if note.get("id") != note_id]
        if len(next_notes) == len(notes):
            return jsonify({"error": "记录不存在"}), 404
        save_notes(next_notes)
    except StorageUnavailable as exc:
        return storage_error_response(exc)
    return jsonify({"ok": True, "saved": True})


@app.route("/api/stats", methods=["GET"])
def api_stats():
    if not check_auth():
        return unauthorized_response()
    try:
        notes = load_notes()
    except StorageUnavailable as exc:
        return storage_error_response(exc)
    mood_counts = {mood: 0 for mood in VALID_MOODS}
    for note in notes:
        for mood in split_note_moods(note):
            if mood in mood_counts:
                mood_counts[mood] += 1
    return jsonify({"total": len(notes), "moods": mood_counts, "latest_time": notes[0]["time"] if notes else None})


@app.route("/health")
def health():
    storage_type = "jsonbin" if jsonbin_configured() else "memory (temporary)"
    storage_ok = True
    storage_detail = "ok"
    if jsonbin_configured():
        try:
            load_notes_from_jsonbin()
        except StorageUnavailable as exc:
            storage_ok = False
            storage_detail = str(exc)
    return jsonify({
        "status": "ok" if storage_ok else "degraded",
        "time": utc_now_iso(),
        "storage": storage_type,
        "storage_ok": storage_ok,
        "storage_detail": storage_detail,
        "password_enabled": bool(ACCESS_PASSWORD),
        "default_weather_city": DEFAULT_WEATHER_CITY,
        "deepseek_enabled": bool(DEEPSEEK_API_KEY),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
