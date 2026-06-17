"""
没丢 —— Flask 后端主程序
家庭物品语音登记查询 PWA，支持多用户注册登录。
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_sock import Sock
import os
import sys
import json as json_mod
import tempfile
from functools import wraps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_db, add_item, query_item, query_item_in_drawer, list_drawer
from db import delete_item, move_item, list_all, list_drawers, search_all
from db import rename_drawer, delete_drawer_items, log_query, get_query_logs, check_expiring
from db import register_user, login_user, logout_user, get_user_by_token

# ── 通义千问 API Key ──
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

app = Flask(__name__, static_folder="static", static_url_path="")
sock = Sock(app)
init_db()


# ══════════════════════════════════════════════════════
#  登录验证装饰器
# ══════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"ok": False, "error": "未登录"}), 401
        uid = get_user_by_token(token)
        if uid is None:
            return jsonify({"ok": False, "error": "登录已过期"}), 401
        request.user_id = uid
        return f(*a, **kw)
    return wrapper


# ══════════════════════════════════════════════════════
#  注册 / 登录 / 登出
# ══════════════════════════════════════════════════════

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"ok": False, "error": "用户名和密码不能为空"}), 400
    if len(username) < 2 or len(username) > 20:
        return jsonify({"ok": False, "error": "用户名需 2-20 个字符"}), 400
    if len(password) < 4:
        return jsonify({"ok": False, "error": "密码至少 4 位"}), 400
    user = register_user(username, password)
    if user is None:
        return jsonify({"ok": False, "error": "用户名已被占用"}), 409
    token = login_user(username, password)
    return jsonify({"ok": True, "user": user, "token": token})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"ok": False, "error": "用户名和密码不能为空"}), 400
    token = login_user(username, password)
    if token is None:
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
    return jsonify({"ok": True, "token": token})


@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    logout_user(token)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════
#  语音入口
# ══════════════════════════════════════════════════════

@app.route("/api/voice", methods=["POST"])
@login_required
def voice():
    data = request.get_json(force=True)
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text 不能为空"}), 400

    uid = request.user_id
    parsed = nlp_parse(text)
    intent = parsed.get("intent", "unknown")

    if intent == "record":
        drawer = parsed.get("drawer", "")
        item = parsed.get("item", "")
        expiry = parsed.get("expiry")
        if not drawer or not item:
            return jsonify({
                "ok": False, "error": "没听清抽屉或物品名，请再说一遍",
                "parsed": parsed
            }), 400
        record = add_item(uid, drawer, item, expiry)
        return jsonify({"ok": True, "action": "record", "record": record})

    elif intent == "query":
        qt = parsed.get("query_type", "search")
        drawer = parsed.get("drawer", "")
        item = parsed.get("item", "")

        if qt == "find_item" and item:
            results = query_item(uid, item)
            log_query(uid, text, "query", f"查找「{item}」找到 {len(results)} 条", len(results))
            return jsonify({
                "ok": True, "action": "query",
                "found": len(results) > 0, "results": results,
                "msg": _format_query_result(results, item)
            })
        elif qt == "check_in_drawer" and drawer and item:
            results = query_item_in_drawer(uid, drawer, item)
            log_query(uid, text, "query", f"查「{drawer}」里是否有「{item}」— {len(results)} 条", len(results))
            return jsonify({
                "ok": True, "action": "query",
                "found": len(results) > 0, "results": results,
                "msg": _format_check_result(results, drawer, item)
            })
        elif qt == "list_drawer" and drawer:
            results = list_drawer(uid, drawer)
            log_query(uid, text, "query", f"列出「{drawer}」— {len(results)} 件", len(results))
            return jsonify({
                "ok": True, "action": "query",
                "found": len(results) > 0, "drawer": drawer,
                "results": results, "msg": _format_drawer_list(results, drawer)
            })
        else:
            results = search_all(uid, item or text)
            log_query(uid, text, "query", f"全局搜索「{item or text}」— {len(results)} 条", len(results))
            return jsonify({
                "ok": True, "action": "query",
                "found": len(results) > 0, "results": results,
                "msg": _format_query_result(results, item or text)
            })

    elif intent == "delete":
        item = parsed.get("item", "")
        if not item:
            return jsonify({"ok": False, "error": "没听清要删除什么"}), 400
        candidates = query_item(uid, item)
        if not candidates:
            log_query(uid, text, "delete", f"未找到「{item}」", 0)
            return jsonify({"ok": False, "msg": f"没找到「{item}」"})
        deleted = delete_item(uid, candidates[0]["id"])
        log_query(uid, text, "delete", f"删除「{candidates[0]['item']}」", 1)
        return jsonify({
            "ok": True, "action": "delete",
            "deleted_item": candidates[0] if deleted else None,
            "msg": f"已删除「{candidates[0]['item']}」" if deleted else "删除失败"
        })

    elif intent == "move":
        item = parsed.get("item", "")
        new_drawer = parsed.get("new_drawer", "")
        if not item:
            return jsonify({"ok": False, "error": "没听清要移动什么"}), 400
        if not new_drawer:
            return jsonify({"ok": False, "error": "没听清移到哪里"}), 400
        candidates = query_item(uid, item)
        if not candidates:
            log_query(uid, text, "move", f"未找到「{item}」", 0)
            return jsonify({"ok": False, "msg": f"没找到「{item}」"})
        updated = move_item(uid, candidates[0]["id"], new_drawer)
        log_query(uid, text, "move", f"移动「{updated['item']}」到「{new_drawer}」", 1)
        return jsonify({
            "ok": True, "action": "move",
            "record": updated,
            "msg": f"「{updated['item']}」已移到「{new_drawer}」"
        })

    else:
        return jsonify({"ok": False, "error": "无法理解，请说「XX放了YY」或「XX在哪」"})


# ══════════════════════════════════════════════════════
#  手动登记/查询
# ══════════════════════════════════════════════════════

def nlp_parse(text: str) -> dict:
    """简单的规则引擎 NLP 解析，返回 intent 和提取的实体。
    优先级：查询 > 登记 > 删除 > 移动 > 兜底搜索"""
    import re
    result = {"intent": "unknown", "drawer": "", "item": "", "expiry": None,
              "query_type": "search", "new_drawer": ""}

    t = text.strip()

    # ══════════════════════════════════════════════════
    # 1. 查询意图（优先判断，避免被登记误匹配）
    # ══════════════════════════════════════════════════

    # 「XX在哪」「XX在哪儿」「XX在哪个抽屉」
    m = re.search(r"(.+?)\s*在\s*(?:哪|哪个|哪里|哪儿)", t)
    if m:
        result["intent"] = "query"
        result["query_type"] = "find_item"
        result["item"] = m.group(1).strip()
        return result

    # 「找XX」「查XX」「搜索XX」「找一下XX」
    m = re.search(r"(?:找|搜索|查)(?:一下|一找|一查)?\s*(.+)", t)
    if m:
        result["intent"] = "query"
        result["query_type"] = "find_item"
        result["item"] = m.group(1).strip()
        return result

    # 「药箱里有什么」「XX里面有啥」「XX里头有哪些」— 列出抽屉
    m = re.search(r"(\S+?)(?:里|里面|里边|里头)\s*(?:有|还有)\s*(?:什么|啥|哪些|多少|吗)", t)
    if m:
        result["intent"] = "query"
        result["query_type"] = "list_drawer"
        result["drawer"] = m.group(1).strip()
        return result

    # 「看看药箱」「列出药箱」「打开药箱」
    m = re.search(r"(?:看看|列[出举]|打开)\s*(\S+?)(?:里|里面|里头|有什么|有啥)?$", t)
    if m:
        drawer = m.group(1).strip()
        if drawer and drawer not in ("一下", "看看", "在哪"):
            result["intent"] = "query"
            result["query_type"] = "list_drawer"
            result["drawer"] = drawer
            return result

    # 「药箱里有没有YY」「药箱里有YY吗」— 检查抽屉内物品（需有明确疑问标记）
    m = re.search(r"(\S+?)\s*里(?:有没有|有没)\s*(.+?)\s*[吗呢吧？?]*$", t)
    if not m:
        m = re.search(r"(\S+?)\s*里有?\s*(.+?)\s*[吗呢吧？?]+$", t)
    if m:
        drawer_candidate = m.group(1).strip()
        item_candidate = m.group(2).strip()
        if item_candidate:
            result["intent"] = "query"
            result["query_type"] = "check_in_drawer"
            result["drawer"] = drawer_candidate
            result["item"] = item_candidate
            return result

    # ══════════════════════════════════════════════════
    # 2. 删除意图（放在登记前，避免"删除XX到YY"被误匹配）
    # ══════════════════════════════════════════════════
    m = re.search(r"(?:删除|删了|扔掉|扔了|去掉)\s*(.+)", t)
    if m:
        result["intent"] = "delete"
        result["item"] = m.group(1).strip()
        return result

    # ══════════════════════════════════════════════════
    # 3. 移动意图（放在登记前，避免"把XX移到YY"被当作登记）
    # ══════════════════════════════════════════════════
    m = re.search(r"(?:把|将)?(.*?)(?:移|挪|搬)[到至往]\s*(\S+)", t)
    if m:
        result["intent"] = "move"
        result["item"] = m.group(1).strip()
        result["new_drawer"] = m.group(2).strip()
        return result

    # ══════════════════════════════════════════════════
    # 4. 登记意图
    # ══════════════════════════════════════════════════

    # 「登记XX到药箱」「登记XX至药箱」
    m = re.search(r"登记\s*(.+?)\s*[到至]\s*(.+)", t)
    if m:
        name, expiry = _parse_item_with_date(m.group(1).strip())
        result["intent"] = "record"
        result["item"] = name
        result["drawer"] = m.group(2).strip()
        result["expiry"] = expiry
        return result

    # 「把创可贴放到药箱」「头孢放在药箱」「药箱里放了头孢」「药箱放了头孢」
    # 模式 A: (物品) + 放到/放在/放到/到 + (抽屉)
    m = re.search(r"(?:把|将)?(.*?)(?:放[到在入]|搬到|丢到|塞到|搁到|在)\s*(\S+)$", t)
    if m:
        item_raw = m.group(1).strip()
        drawer = m.group(2).strip()
        # 排除问句词被当抽屉：哪/什么/啥/吗
        if drawer not in ("哪", "哪里", "哪儿", "哪个", "什么", "啥", "吗"):
            name, expiry = _parse_item_with_date(item_raw)
            result["intent"] = "record"
            result["item"] = name
            result["drawer"] = drawer
            result["expiry"] = expiry
            return result

    # 模式 B: (抽屉)里 + 放了/有 + (物品)
    m = re.search(r"(\S+?)(?:里|里面|里边)?\s*(?:放[了入]|有)\s*(.+)", t)
    if m:
        drawer = m.group(1).strip()
        item_raw = m.group(2).strip()
        # 排除问句：物品位置不是问句词
        if not re.search(r"^(?:什么|啥|哪些|多少|吗|呢|吧)$", t.split()[-1] if t.split() else ""):
            name, expiry = _parse_item_with_date(item_raw)
            result["intent"] = "record"
            result["drawer"] = drawer
            result["item"] = name
            result["expiry"] = expiry
            return result

    # ══════════════════════════════════════════════════
    # 5. 兜底：全局搜索
    # ══════════════════════════════════════════════════
    if t:
        result["intent"] = "query"
        result["query_type"] = "search"
        result["item"] = t
        return result

    return result


def _parse_item_with_date(raw):
    import re
    m = re.search(r"(\d{8})$", raw)
    if m:
        d = m.group(1)
        name = raw[:m.start()]
        if name:
            return name, f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return raw, None


@app.route("/api/record", methods=["POST"])
@login_required
def record():
    data = request.get_json(force=True)
    uid = request.user_id
    drawer = data.get("drawer", "").strip()
    expiry = data.get("expiry", None)

    items_data = data.get("items")
    if items_data:
        # 兼容两种格式：字符串（逗号分隔）或对象数组 [{name, date}]
        if isinstance(items_data, list):
            # 数组格式
            records = []
            for obj in items_data:
                if isinstance(obj, dict):
                    item_name = obj.get("name", "").strip()
                    item_expiry = obj.get("date") or expiry
                else:
                    item_name = str(obj).strip()
                    item_expiry = expiry
                if item_name:
                    r = add_item(uid, drawer, item_name, item_expiry)
                    records.append(r)
        else:
            # 字符串格式
            items_text = str(items_data).strip()
            raw_items = [s.strip() for s in items_text.split(",") if s.strip()]
            records = []
            for raw in raw_items:
                item_name, item_expiry = _parse_item_with_date(raw)
                r = add_item(uid, drawer, item_name, item_expiry or expiry)
                records.append(r)
    else:
        item = data.get("item", "").strip()
        items = [item] if item else []
        if not drawer or not items:
            return jsonify({"ok": False, "error": "drawer 和 items/item 不能为空"}), 400
        records = [add_item(uid, drawer, it, expiry) for it in items]

    if not drawer or not records:
        return jsonify({"ok": False, "error": "drawer 和 items/item 不能为空"}), 400

    msg = f"已登记 {len(records)} 件物品到「{drawer}」"
    return jsonify({"ok": True, "records": records, "msg": msg})


@app.route("/api/query", methods=["POST"])
@login_required
def query():
    data = request.get_json(force=True)
    uid = request.user_id
    keyword = data.get("keyword", "").strip()
    drawer = data.get("drawer", "").strip() or None
    if not keyword:
        return jsonify({"ok": False, "error": "keyword 不能为空"}), 400
    if drawer:
        results = query_item_in_drawer(uid, drawer, keyword)
        summary = f"在「{drawer}」搜索「{keyword}」— {len(results)} 条"
    else:
        results = query_item(uid, keyword)
        summary = f"搜索「{keyword}」— {len(results)} 条"
    log_query(uid, keyword, "search", summary, len(results))
    return jsonify({
        "ok": True, "found": len(results) > 0, "results": results
    })


@app.route("/api/drawers", methods=["GET"])
@login_required
def drawers():
    return jsonify({"ok": True, "drawers": list_drawers(request.user_id)})


# ══════════════════════════════════════════════════════
#  箱子管理
# ══════════════════════════════════════════════════════

@app.route("/api/box", methods=["POST"])
@login_required
def add_box():
    uid = request.user_id
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name 不能为空"}), 400
    existing = list_drawers(uid)
    if name in existing:
        return jsonify({"ok": False, "error": f"箱子「{name}」已存在"}), 400
    add_item(uid, name, "（空箱子）", None)
    return jsonify({"ok": True, "name": name})


@app.route("/api/box/<name>", methods=["PUT"])
@login_required
def rename_box(name):
    uid = request.user_id
    data = request.get_json(force=True)
    new_name = data.get("name", "").strip()
    if not new_name:
        return jsonify({"ok": False, "error": "name 不能为空"}), 400
    count = rename_drawer(uid, name, new_name)
    return jsonify({"ok": True, "old_name": name, "new_name": new_name, "affected": count})


@app.route("/api/box/<name>", methods=["DELETE"])
@login_required
def delete_box(name):
    uid = request.user_id
    count = delete_drawer_items(uid, name)
    return jsonify({"ok": True, "name": name, "deleted": count})


@app.route("/api/recent", methods=["GET"])
@login_required
def recent():
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"ok": True, "items": list_all(request.user_id, limit)})


@app.route("/api/delete/<int:item_id>", methods=["DELETE"])
@login_required
def api_delete(item_id):
    ok = delete_item(request.user_id, item_id)
    return jsonify({"ok": ok})


@app.route("/api/expiring", methods=["GET"])
@login_required
def expiring():
    days = request.args.get("days", 90, type=int)
    items = check_expiring(request.user_id, days)
    return jsonify({"ok": True, "count": len(items), "items": items})


@app.route("/api/query_logs", methods=["GET"])
@login_required
def query_logs():
    limit = request.args.get("limit", 50, type=int)
    logs = get_query_logs(request.user_id, min(limit, 100))
    return jsonify({"ok": True, "count": len(logs), "logs": logs})


# ══════════════════════════════════════════════════════
#  前端静态文件
# ══════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.after_request
def add_no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ══════════════════════════════════════════════════════
#  回复格式化
# ══════════════════════════════════════════════════════

def _format_query_result(results: list, item: str) -> str:
    if not results:
        return f"没找到「{item}」"
    if len(results) == 1:
        r = results[0]
        exp = f"，保质期到{r['expiry']}" if r.get("expiry") else ""
        return f"「{r['item']}」在「{r['drawer']}」{exp}"
    lines = [f"找到 {len(results)} 个相关的："]
    for r in results[:5]:
        exp = f"，保质期到{r['expiry']}" if r.get("expiry") else ""
        lines.append(f"「{r['item']}」→「{r['drawer']}」{exp}")
    return "\n".join(lines)


def _format_check_result(results: list, drawer: str, item: str) -> str:
    if not results:
        return f"「{drawer}」里没有「{item}」"
    r = results[0]
    exp = f"，保质期到{r['expiry']}" if r.get("expiry") else ""
    return f"有的，「{r['item']}」在「{drawer}」{exp}"


def _format_drawer_list(results: list, drawer: str) -> str:
    if not results:
        return f"「{drawer}」里暂时没有登记物品"
    lines = [f"「{drawer}」里有 {len(results)} 件物品："]
    for r in results:
        exp = f"（保质期到{r['expiry']}）" if r.get("expiry") else ""
        lines.append(f"• {r['item']} {exp}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════
#  WebSocket 语音识别（通义千问）
# ══════════════════════════════════════════════════════

@sock.route("/ws/voice")
def ws_voice(ws):
    if not DASHSCOPE_API_KEY:
        ws.send(json_mod.dumps({"ok": False, "error": "未配置 API Key"}))
        return
    audio_chunks = []
    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            audio_chunks.append(data)
    except Exception:
        pass
    if not audio_chunks:
        ws.send(json_mod.dumps({"ok": False, "error": "未收到音频"}))
        return
    raw_audio = b"".join(audio_chunks)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(raw_audio)
        tmp_path = f.name
    wav_path = None
    try:
        from audio_convert import any_to_wav
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
            wav_path = wf.name
        any_to_wav(tmp_path, wav_path)

        import dashscope
        from dashscope.audio.asr import Recognition
        dashscope.api_key = DASHSCOPE_API_KEY
        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="wav",
            sample_rate=16000,
            language_hints=["zh"],
            callback=None,
        )
        result = recognition.call(wav_path)
        print(f"[ASR DEBUG] status={result.status_code}", flush=True)
        if result.status_code == 200:
            sentences = result.get_sentence()
            text = "".join(s.get("text", "") for s in (sentences or []))
            print(f"[ASR DEBUG] text={text}", flush=True)
            ws.send(json_mod.dumps({"ok": True, "text": text.strip()} if text.strip() else {"ok": False, "error": "识别为空"}))
        else:
            ws.send(json_mod.dumps({"ok": False, "error": f"识别失败: {result.message}"}))
    except Exception as e:
        ws.send(json_mod.dumps({"ok": False, "error": f"识别异常: {str(e)}"}))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        if wav_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass


@sock.route("/ws/voice_simple")
def ws_voice_simple(ws):
    if not DASHSCOPE_API_KEY:
        ws.send(json_mod.dumps({"ok": False, "error": "未配置 API Key"}))
        return
    audio_data = None
    mime_type = "audio/webm"
    try:
        # 消息1: JSON 元数据
        meta_msg = ws.receive()
        if isinstance(meta_msg, str) and meta_msg.startswith("{"):
            try:
                meta = json_mod.loads(meta_msg)
                mime_type = meta.get("mimeType", "audio/webm")
            except Exception:
                pass
        # 消息2: 二进制音频
        audio_msg = ws.receive()
        if audio_msg is not None:
            audio_data = audio_msg if isinstance(audio_msg, bytes) else audio_msg.encode()
    except Exception:
        pass
    if not audio_data:
        ws.send(json_mod.dumps({"ok": False, "error": "未收到音频"}))
        return
    raw_audio = audio_data
    suffix = ".wav" if "wav" in mime_type else (".mp3" if "mp3" in mime_type else ".webm")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(raw_audio)
        tmp_path = f.name
    wav_path = None
    try:
        # 浏览器录制的 WebM/MP4 需要转换为 WAV
        from audio_convert import any_to_wav
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
            wav_path = wf.name
        any_to_wav(tmp_path, wav_path)

        import dashscope
        from dashscope.audio.asr import Recognition
        dashscope.api_key = DASHSCOPE_API_KEY
        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="wav",
            sample_rate=16000,
            language_hints=["zh"],
            callback=None,
        )
        result = recognition.call(wav_path)
        print(f"[ASR DEBUG] status={result.status_code}", flush=True)
        if result.status_code == 200:
            sentences = result.get_sentence()
            text = "".join(s.get("text", "") for s in (sentences or []))
            print(f"[ASR DEBUG] text={text}", flush=True)
            ws.send(json_mod.dumps({"ok": True, "text": text.strip()} if text.strip() else {"ok": False, "error": "识别为空"}))
        else:
            ws.send(json_mod.dumps({"ok": False, "error": f"识别失败: {result.message}"}))
    except Exception as e:
        ws.send(json_mod.dumps({"ok": False, "error": f"识别异常: {str(e)}"}))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        if wav_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
