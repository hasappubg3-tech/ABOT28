from .shared import *
import time as _time

# ── مساعد: تحويل وثيقة MongoDB إلى dict مشابه لـ sqlite3.Row ──────
def _d(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc

def _col(name: str):
    return get_mongo_db()[name]

# ── عداد تلقائي (بديل AUTOINCREMENT) ─────────────────────────────
def _next_id(col_name: str) -> int:
    result = get_mongo_db()["_counters"].find_one_and_update(
        {"_id": col_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return result["seq"]

# ── تهيئة قاعدة البيانات (فهارس) ─────────────────────────────────
def init_db():
    mdb = get_mongo_db()
    mdb["buttons"].create_index([("parent_id", ASCENDING), ("ord", ASCENDING), ("id", ASCENDING)])
    mdb["buttons"].create_index([("id", ASCENDING)], unique=True)
    mdb["content_items"].create_index([("button_id", ASCENDING), ("ord", ASCENDING), ("id", ASCENDING)])
    mdb["content_items"].create_index([("id", ASCENDING)], unique=True)
    mdb["admins"].create_index([("id", ASCENDING)], unique=True)
    mdb["settings"].create_index([("key", ASCENDING)], unique=True)
    mdb["user_stats"].create_index([("user_id", ASCENDING)], unique=True)
    mdb["quiz_questions"].create_index([("button_id", ASCENDING), ("ord", ASCENDING)])
    mdb["quiz_questions"].create_index([("id", ASCENDING)], unique=True)
    mdb["quiz_options"].create_index([("question_id", ASCENDING)])
    mdb["quiz_options"].create_index([("id", ASCENDING)], unique=True)
    mdb["exam_questions"].create_index([("button_id", ASCENDING), ("ord", ASCENDING)])
    mdb["exam_questions"].create_index([("id", ASCENDING)], unique=True)
    mdb["exam_progress"].create_index([("user_id", ASCENDING), ("exam_button_id", ASCENDING)], unique=True)
    mdb["item_ratings"].create_index([("item_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    mdb["button_ratings"].create_index([("button_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    mdb["daily_stats"].create_index([("date", ASCENDING)], unique=True)
    mdb["user_button_clicks"].create_index([("user_id", ASCENDING), ("button_id", ASCENDING)], unique=True)
    mdb["caption_buttons"].create_index([("id", ASCENDING)], unique=True)
    mdb["motivational_phrases"].create_index([("id", ASCENDING)], unique=True)
    mdb["pomodoro_settings"].create_index([("user_id", ASCENDING)], unique=True)
    mdb["file_request_admins"].create_index([("user_id", ASCENDING)], unique=True)
    mdb["file_reply_sessions"].create_index([("admin_id", ASCENDING), ("message_id", ASCENDING)], unique=True)
    mdb["user_reply_sessions"].create_index([("user_id", ASCENDING), ("message_id", ASCENDING)], unique=True)
    mdb["active_file_convos"].create_index([("user_id", ASCENDING)], unique=True)
    mdb["quiz_sent_log"].create_index([("user_id", ASCENDING), ("question_id", ASCENDING)], unique=True)
    logging.info("MongoDB: تم تهيئة الفهارس.")

# ── المشرفون ──────────────────────────────────────────────────────
def is_admin(uid):
    return _col("admins").find_one({"id": uid}) is not None

def add_admin(uid, name=None):
    _col("admins").update_one({"id": uid}, {"$set": {"id": uid, "username": name}}, upsert=True)

def update_admin_username(uid, username=None):
    if not username:
        return
    _col("admins").update_one({"id": uid}, {"$set": {"username": username.lstrip("@")}})

def get_admin_by_username(username):
    username = (username or "").strip().lstrip("@").lower()
    if not username:
        return None
    doc = _col("admins").find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
    return _d(doc)

def del_admin(uid):
    _col("admins").delete_one({"id": uid})

def all_admins():
    return [_d(r) for r in _col("admins").find()]

# ── الإعدادات ─────────────────────────────────────────────────────
def get_setting(key, default=None):
    doc = _col("settings").find_one({"key": key})
    return doc["value"] if doc else default

def set_setting(key, value):
    _col("settings").update_one({"key": key}, {"$set": {"key": key, "value": value}}, upsert=True)

def get_start_message():
    return get_setting("start_message", "👋 أهلاً!")

def set_start_message(value):
    set_setting("start_message", value)

def get_global_caption():
    return get_setting("global_caption", "")

def get_storage_channel_id():
    ch = (STORAGE_CHANNEL_ID or "").strip()
    if not ch:
        return None
    if ch.lstrip("-").isdigit():
        return int(ch)
    return ch

# ── الأزرار ───────────────────────────────────────────────────────
def get_buttons(pid=None):
    if pid is None:
        docs = _col("buttons").find({"parent_id": None, "deleted": {"$ne": 1}}).sort([("ord", 1), ("id", 1)])
    else:
        docs = _col("buttons").find({"parent_id": pid, "deleted": {"$ne": 1}}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def get_btn(bid):
    return _d(_col("buttons").find_one({"id": bid, "deleted": {"$ne": 1}}))

def get_btn_any(bid):
    """يجلب الزر حتى لو كان محذوفاً ناعماً."""
    return _d(_col("buttons").find_one({"id": bid}))

def _siblings_ids(pid):
    docs = _col("buttons").find(
        {"parent_id": pid, "deleted": {"$ne": 1}} if pid is not None else {"parent_id": None, "deleted": {"$ne": 1}}
    ).sort([("ord", 1), ("id", 1)])
    return [d["id"] for d in docs]

def _renumber(ids):
    for i, bid in enumerate(ids):
        _col("buttons").update_one({"id": bid}, {"$set": {"ord": i + 1}})

def add_btn(pid, t, label):
    ids = _siblings_ids(pid)
    ur = 1 if t == "content" else 0
    new_id = _next_id("buttons")
    _col("buttons").insert_one({
        "id": new_id, "parent_id": pid, "type": t, "label": label,
        "ord": len(ids) + 1, "new_row": 1, "click_count": 0,
        "unified_rating": ur, "no_caption": 0, "no_btn_caption": 0,
        "hidden": 0, "special_action": None, "compound_text": None,
        "random_quiz": 0, "random_exam": 0,
    })
    return new_id

def add_btn_before(before_bid, pid, t, label):
    ids = _siblings_ids(pid)
    pos = ids.index(before_bid) if before_bid in ids else 0
    ur = 1 if t == "content" else 0
    new_id = _next_id("buttons")
    _col("buttons").insert_one({
        "id": new_id, "parent_id": pid, "type": t, "label": label,
        "ord": 0, "new_row": 1, "click_count": 0,
        "unified_rating": ur, "no_caption": 0, "no_btn_caption": 0,
        "hidden": 0, "special_action": None, "compound_text": None,
        "random_quiz": 0, "random_exam": 0,
    })
    ids.insert(pos, new_id)
    _renumber(ids)
    return new_id

def add_btn_after(after_bid, pid, t, label, new_row=1):
    ids = _siblings_ids(pid)
    if after_bid is None:
        pos = 0
    else:
        pos = (ids.index(after_bid) + 1) if after_bid in ids else len(ids)
    ur = 1 if t == "content" else 0
    new_id = _next_id("buttons")
    _col("buttons").insert_one({
        "id": new_id, "parent_id": pid, "type": t, "label": label,
        "ord": 0, "new_row": new_row, "click_count": 0,
        "unified_rating": ur, "no_caption": 0, "no_btn_caption": 0,
        "hidden": 0, "special_action": None, "compound_text": None,
        "random_quiz": 0, "random_exam": 0,
    })
    ids.insert(pos, new_id)
    _renumber(ids)
    return new_id

def upd_btn_label(bid, label):
    _col("buttons").update_one({"id": bid}, {"$set": {"label": label}})

def del_btn(bid):
    _soft_delete_btn_recursive(bid)

def _soft_delete_btn_recursive(bid):
    """حذف ناعم — يخفي الزر وأبناءه ويحتفظ بالبيانات للاستعادة أو النسخ."""
    children = _col("buttons").find({"parent_id": bid, "deleted": {"$ne": 1}})
    for child in children:
        _soft_delete_btn_recursive(child["id"])
    _col("buttons").update_one({"id": bid}, {"$set": {"deleted": 1}})

def clone_btn(source_bid, pid, add_after="END", add_before=None, new_row=1):
    """ينشئ نسخة كاملة من زر (حتى لو محذوف) في الموضع المحدد.
    يشمل النسخ: المحتوى، الكويز (أسئلة+خيارات)، الامتحان، الأزرار الداخلية للزر المدمج."""
    src = get_btn_any(source_bid)
    if not src:
        return None
    label = src["label"]
    t = src["type"]

    if add_before is not None:
        new_bid = add_btn_before(add_before, pid, t, label)
    elif add_after != "END":
        new_bid = add_btn_after(add_after, pid, t, label, new_row=new_row)
    else:
        new_bid = add_btn(pid, t, label)

    updates = {}
    for field in ["special_action", "compound_text", "random_quiz", "random_exam",
                  "unified_rating", "no_caption", "no_btn_caption"]:
        v = src.get(field)
        if v is not None:
            updates[field] = v
    if updates:
        _col("buttons").update_one({"id": new_bid}, {"$set": updates})

    if t == "content":
        items = list(_col("content_items").find({"button_id": source_bid}).sort([("ord", 1), ("id", 1)]))
        for item in items:
            n_id = _next_id("content_items")
            _col("content_items").insert_one({
                "id": n_id, "button_id": new_bid,
                "type": item.get("type"), "content": item.get("content"),
                "file_id": item.get("file_id"), "local_path": item.get("local_path"),
                "channel_msg_id": item.get("channel_msg_id"), "ord": item.get("ord", 1)
            })

    elif t == "quiz":
        questions = list(_col("quiz_questions").find({"button_id": source_bid}).sort([("ord", 1), ("id", 1)]))
        for q in questions:
            new_qid = _next_id("quiz_questions")
            _col("quiz_questions").insert_one({
                "id": new_qid, "button_id": new_bid,
                "question": q.get("question"), "correct_option": q.get("correct_option", 0),
                "explanation": q.get("explanation", ""), "ord": q.get("ord", 1)
            })
            opts = list(_col("quiz_options").find({"question_id": q["id"]}).sort([("ord", 1)]))
            for opt in opts:
                new_oid = _next_id("quiz_options")
                _col("quiz_options").insert_one({
                    "id": new_oid, "question_id": new_qid,
                    "text": opt.get("text"), "ord": opt.get("ord", 1)
                })

    elif t == "exam":
        questions = list(_col("exam_questions").find({"button_id": source_bid}).sort([("ord", 1), ("id", 1)]))
        for eq in questions:
            new_eqid = _next_id("exam_questions")
            _col("exam_questions").insert_one({
                "id": new_eqid, "button_id": new_bid,
                "q_type": eq.get("q_type", "text"), "q_text": eq.get("q_text"),
                "q_file_id": eq.get("q_file_id"), "q_channel_msg_id": eq.get("q_channel_msg_id"),
                "a_type": eq.get("a_type", "text"), "a_text": eq.get("a_text"),
                "a_file_id": eq.get("a_file_id"), "a_channel_msg_id": eq.get("a_channel_msg_id"),
                "ord": eq.get("ord", 1)
            })

    elif t == "compound":
        # إذا كان الزر الأصل محذوفاً، أبناؤه محذوفون معه — نُضمّنهم للاستعادة الكاملة
        child_filter = {"parent_id": source_bid} if src.get("deleted") else {"parent_id": source_bid, "deleted": {"$ne": 1}}
        internal = list(_col("buttons").find(child_filter).sort([("ord", 1), ("id", 1)]))
        for child in internal:
            child_new_id = _next_id("buttons")
            _col("buttons").insert_one({
                "id": child_new_id, "parent_id": new_bid,
                "type": child.get("type", "content"), "label": child.get("label", ""),
                "ord": child.get("ord", 1), "new_row": child.get("new_row", 1),
                "click_count": 0, "unified_rating": child.get("unified_rating", 1),
                "no_caption": child.get("no_caption", 0), "no_btn_caption": child.get("no_btn_caption", 0),
                "hidden": 0, "special_action": None, "compound_text": None,
                "random_quiz": 0, "random_exam": 0, "deleted": 0,
            })
            child_items = list(_col("content_items").find({"button_id": child["id"]}).sort([("ord", 1)]))
            for item in child_items:
                n_id = _next_id("content_items")
                _col("content_items").insert_one({
                    "id": n_id, "button_id": child_new_id,
                    "type": item.get("type"), "content": item.get("content"),
                    "file_id": item.get("file_id"), "local_path": item.get("local_path"),
                    "channel_msg_id": item.get("channel_msg_id"), "ord": item.get("ord", 1)
                })

    elif t in ("menu", "exam_group"):
        # استنساخ عميق — يكرر نفسه لكل زر داخلي بأي عمق
        # إذا كان الزر الأصل محذوفاً، أبناؤه محذوفون معه — نُضمّنهم للاستعادة الكاملة
        child_filter = {"parent_id": source_bid} if src.get("deleted") else {"parent_id": source_bid, "deleted": {"$ne": 1}}
        children = list(_col("buttons").find(child_filter).sort([("ord", 1), ("id", 1)]))
        last_cloned_child = None
        for child in children:
            if last_cloned_child is None:
                child_new_id = clone_btn(child["id"], new_bid)
            else:
                child_new_id = clone_btn(
                    child["id"], new_bid,
                    add_after=last_cloned_child,
                    new_row=child.get("new_row", 1)
                )
            if child_new_id:
                last_cloned_child = child_new_id

    return new_bid

def get_compound_text(bid):
    doc = _col("buttons").find_one({"id": bid}, {"compound_text": 1})
    txt = doc.get("compound_text") if doc else None
    return txt if (txt is not None and str(txt).strip() != "") else "اختر:"

def set_compound_text(bid, text):
    _col("buttons").update_one({"id": bid}, {"$set": {"compound_text": text}})

def set_btn_unified_rating(bid, val=1):
    _col("buttons").update_one({"id": bid}, {"$set": {"unified_rating": 1 if val else 0}})

def set_btn_hidden(bid, val=1):
    _col("buttons").update_one({"id": bid}, {"$set": {"hidden": 1 if val else 0}})

def set_btn_no_caption(bid, val=1):
    _col("buttons").update_one({"id": bid}, {"$set": {"no_caption": 1 if val else 0}})

def set_btn_no_btn_caption(bid, val=1):
    _col("buttons").update_one({"id": bid}, {"$set": {"no_btn_caption": 1 if val else 0}})

def propagate_compound_settings(parent_bid):
    parent = get_btn(parent_bid)
    if not parent or parent.get("type") != "compound":
        return
    _col("buttons").update_many({"parent_id": parent_bid}, {"$set": {
        "unified_rating": parent.get("unified_rating", 0) or 0,
        "no_caption": parent.get("no_caption", 0) or 0,
        "no_btn_caption": parent.get("no_btn_caption", 0) or 0,
    }})

def inc_click_count(bid, uid=None):
    if uid is not None:
        try:
            _col("user_button_clicks").insert_one({"user_id": uid, "button_id": bid})
            _col("buttons").update_one({"id": bid}, {"$inc": {"click_count": 1}})
        except Exception:
            pass
    else:
        _col("buttons").update_one({"id": bid}, {"$inc": {"click_count": 1}})

def get_btn_path(bid) -> str:
    parts = []
    current = get_btn(bid)
    while current:
        parts.append(current["label"])
        pid = current.get("parent_id")
        current = get_btn(pid) if pid else None
    parts.reverse()
    return " › ".join(parts)

def _create_nested_buttons(parent_id, buttons_list, anchor_id=None, use_after=False):
    added = []
    last_id = anchor_id
    for btn in buttons_list:
        label = btn.get("label", "").strip()
        btype = btn.get("type", "menu")
        new_row = btn.get("new_row", True)
        children = btn.get("children", [])
        if not label:
            continue
        if btype not in ("menu", "content"):
            btype = "menu"
        nr = 0 if not new_row else 1
        if last_id is None and not use_after:
            new_id = add_btn(parent_id, btype, label)
        else:
            new_id = add_btn_after(last_id, parent_id, btype, label, new_row=nr)
        last_id = new_id
        use_after = True
        depth = "📂" if btype == "menu" else "📄"
        added.append(f"{depth} {label}")
        if children and btype == "menu":
            child_added = _create_nested_buttons(new_id, children)
            added.extend(f"  └ {a}" for a in child_added)
    return added

def swap_btns(bid1, bid2):
    b1 = get_btn(bid1)
    b2 = get_btn(bid2)
    if not b1 or not b2:
        return
    _col("buttons").update_one({"id": bid1}, {"$set": {"ord": b2["ord"], "new_row": b2["new_row"]}})
    _col("buttons").update_one({"id": bid2}, {"$set": {"ord": b1["ord"], "new_row": b1["new_row"]}})

# ── الزر الخاص ───────────────────────────────────────────────────
def get_special_btn():
    return _d(_col("buttons").find_one({"type": "special", "deleted": {"$ne": 1}}))

def create_special_btn(label: str, pid=None) -> int:
    return add_btn(pid, "special", label)

def move_special_btn(bid: int, new_pid):
    ids = _siblings_ids(new_pid)
    new_ord = len(ids) + 1
    _col("buttons").update_one({"id": bid}, {"$set": {"parent_id": new_pid, "ord": new_ord, "new_row": 1}})

def all_menu_levels() -> list:
    docs = _col("buttons").find({"type": "menu", "deleted": {"$ne": 1}}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def get_all_special_btns() -> list:
    docs = _col("buttons").find({"type": "special", "deleted": {"$ne": 1}}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def set_btn_special_action(bid, action):
    _col("buttons").update_one({"id": bid}, {"$set": {"special_action": action}})

# ── مشرفو الملفات ─────────────────────────────────────────────────
def get_file_request_admins():
    return [_d(r) for r in _col("file_request_admins").find().sort("user_id", 1)]

def is_file_supervisor(uid):
    if is_admin(uid):
        return True
    return _col("file_request_admins").find_one({"user_id": uid}) is not None

def add_file_request_admin(uid, username=None):
    _col("file_request_admins").update_one(
        {"user_id": uid}, {"$set": {"user_id": uid, "username": username}}, upsert=True
    )

def del_file_request_admin(uid):
    _col("file_request_admins").delete_one({"user_id": uid})

# ── جلسات الردود ──────────────────────────────────────────────────
def save_file_reply_session(admin_id, message_id, user_id):
    _col("file_reply_sessions").update_one(
        {"admin_id": admin_id, "message_id": message_id},
        {"$set": {"admin_id": admin_id, "message_id": message_id, "user_id": user_id}},
        upsert=True
    )

def get_file_reply_user(admin_id, message_id):
    doc = _col("file_reply_sessions").find_one({"admin_id": admin_id, "message_id": message_id})
    return doc["user_id"] if doc else None

def del_file_reply_session(admin_id, message_id):
    _col("file_reply_sessions").delete_one({"admin_id": admin_id, "message_id": message_id})

def save_user_reply_session(user_id, message_id):
    _col("user_reply_sessions").update_one(
        {"user_id": user_id, "message_id": message_id},
        {"$set": {"user_id": user_id, "message_id": message_id}},
        upsert=True
    )

def is_user_reply_msg(user_id, message_id):
    return _col("user_reply_sessions").find_one({"user_id": user_id, "message_id": message_id}) is not None

def set_file_convo_active(user_id):
    _col("active_file_convos").update_one(
        {"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True
    )

def is_file_convo_active(user_id):
    return _col("active_file_convos").find_one({"user_id": user_id}) is not None

def clear_file_convo(user_id):
    _col("active_file_convos").delete_one({"user_id": user_id})

# ── عناصر المحتوى ────────────────────────────────────────────────
def get_items(bid):
    docs = _col("content_items").find({"button_id": bid}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def get_storage_summary():
    pipeline = [
        {"$match": {"type": {"$ne": "text"}}},
        {"$group": {
            "_id": None,
            "total_files": {"$sum": 1},
            "in_channel": {"$sum": {"$cond": [{"$and": [{"$ne": ["$channel_msg_id", None]}, {"$ne": ["$channel_msg_id", 0]}]}, 1, 0]}},
            "missing_channel": {"$sum": {"$cond": [{"$or": [{"$eq": ["$channel_msg_id", None]}, {"$eq": ["$channel_msg_id", 0]}]}, 1, 0]}},
            "repairable_local": {"$sum": {"$cond": [{"$and": [
                {"$or": [{"$eq": ["$channel_msg_id", None]}, {"$eq": ["$channel_msg_id", 0]}]},
                {"$and": [{"$ne": ["$local_path", None]}, {"$ne": ["$local_path", ""]}]}
            ]}, 1, 0]}},
            "repairable_file_id": {"$sum": {"$cond": [{"$and": [
                {"$or": [{"$eq": ["$channel_msg_id", None]}, {"$eq": ["$channel_msg_id", 0]}]},
                {"$or": [{"$eq": ["$local_path", None]}, {"$eq": ["$local_path", ""]}]},
                {"$and": [{"$ne": ["$file_id", None]}, {"$ne": ["$file_id", ""]}]}
            ]}, 1, 0]}},
        }}
    ]
    result = list(_col("content_items").aggregate(pipeline))
    if not result:
        return {"total_files": 0, "in_channel": 0, "missing_channel": 0, "repairable_local": 0, "repairable_file_id": 0}
    r = result[0]
    r.pop("_id", None)
    return r

def get_items_missing_channel():
    docs = _col("content_items").find({
        "type": {"$ne": "text"},
        "$or": [{"channel_msg_id": None}, {"channel_msg_id": 0}]
    }).sort("id", 1)
    return [_d(r) for r in docs]

def add_item(bid, t, content=None, file_id=None, local_path=None, channel_msg_id=None):
    last = _col("content_items").find_one({"button_id": bid}, sort=[("ord", -1)])
    n = (last["ord"] if last else 0) + 1
    new_id = _next_id("content_items")
    _col("content_items").insert_one({
        "id": new_id, "button_id": bid, "type": t,
        "content": content, "file_id": file_id,
        "local_path": local_path, "channel_msg_id": channel_msg_id, "ord": n
    })

def upd_item_file_id(iid, file_id):
    _col("content_items").update_one({"id": iid}, {"$set": {"file_id": file_id}})

def upd_item_channel_msg_id(iid, channel_msg_id):
    _col("content_items").update_one({"id": iid}, {"$set": {"channel_msg_id": channel_msg_id}})

def del_item(iid):
    _col("content_items").delete_one({"id": iid})

def upd_item_content(iid, content):
    _col("content_items").update_one({"id": iid}, {"$set": {"content": content}})

def get_item(iid):
    return _d(_col("content_items").find_one({"id": iid}))

# ── تقييم العناصر ────────────────────────────────────────────────
def get_item_rating_summary(iid: int) -> dict:
    pipeline = [
        {"$match": {"item_id": iid}},
        {"$group": {"_id": None, "cnt": {"$sum": 1}, "avg_rating": {"$avg": "$rating"}}}
    ]
    result = list(_col("item_ratings").aggregate(pipeline))
    if not result:
        return {"count": 0, "avg": 0.0}
    r = result[0]
    return {"count": r["cnt"], "avg": float(r.get("avg_rating") or 0)}

def get_user_item_rating(iid: int, uid: int):
    doc = _col("item_ratings").find_one({"item_id": iid, "user_id": uid})
    return doc["rating"] if doc else None

def save_item_rating(iid: int, uid: int, rating: int):
    _col("item_ratings").update_one(
        {"item_id": iid, "user_id": uid},
        {"$set": {"item_id": iid, "user_id": uid, "rating": rating, "rated_at": int(_time.time())}},
        upsert=True
    )

def rating_stars(avg: float) -> str:
    filled = int(round(avg))
    filled = max(0, min(5, filled))
    return "★" * filled + "☆" * (5 - filled)

def item_rating_text(iid: int, uid: int | None = None) -> str:
    s = get_item_rating_summary(iid)
    if s["count"] == 0:
        rating_line = "⭐ تقييم الملف: لا يوجد تقييم بعد"
    else:
        rating_line = f"⭐ تقييم الملف: {rating_stars(s['avg'])} {s['avg']:.1f}/5"
    count_line = f"👥 عدد التقييمات: {s['count']}"
    user_line = ""
    if uid:
        user_rating = get_user_item_rating(iid, uid)
        if user_rating:
            user_line = f"\n✅ تقييمك: {user_rating}/5"
    return f"{rating_line}\n{count_line}{user_line}"

def kb_item_rating(iid: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ قيّم الملف", callback_data=f"rate_open_{iid}")
    ]])

def kb_item_rating_choices(iid: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐" * i, callback_data=f"rate_set_{iid}_{i}") for i in range(1, 4)],
        [InlineKeyboardButton("⭐" * i, callback_data=f"rate_set_{iid}_{i}") for i in range(4, 6)],
        [InlineKeyboardButton("رجوع", callback_data=f"rate_back_{iid}")],
    ])

async def send_item_rating_message(target, item, uid=None):
    if item.get("type") == "text":
        return
    iid = item.get("id")
    if not iid:
        return
    await target.reply_text(item_rating_text(iid, uid), reply_markup=kb_item_rating(iid))

# ── تقييم موحد على مستوى الزر ────────────────────────────────────
def get_btn_rating_summary(bid: int) -> dict:
    pipeline = [
        {"$match": {"button_id": bid}},
        {"$group": {"_id": None, "cnt": {"$sum": 1}, "avg_rating": {"$avg": "$rating"}}}
    ]
    result = list(_col("button_ratings").aggregate(pipeline))
    if not result:
        return {"count": 0, "avg": 0.0}
    r = result[0]
    return {"count": r["cnt"], "avg": float(r.get("avg_rating") or 0)}

def get_user_btn_rating(bid: int, uid: int):
    doc = _col("button_ratings").find_one({"button_id": bid, "user_id": uid})
    return doc["rating"] if doc else None

def save_btn_rating(bid: int, uid: int, rating: int):
    _col("button_ratings").update_one(
        {"button_id": bid, "user_id": uid},
        {"$set": {"button_id": bid, "user_id": uid, "rating": rating, "rated_at": int(_time.time())}},
        upsert=True
    )

def btn_rating_text(bid: int, uid: int | None = None) -> str:
    s = get_btn_rating_summary(bid)
    if s["count"] == 0:
        rating_line = "⭐ تقييم المحتوى: لا يوجد تقييم بعد"
    else:
        rating_line = f"⭐ تقييم المحتوى: {rating_stars(s['avg'])} {s['avg']:.1f}/5"
    count_line = f"👥 عدد التقييمات: {s['count']}"
    user_line = ""
    if uid:
        user_rating = get_user_btn_rating(bid, uid)
        if user_rating:
            user_line = f"\n✅ تقييمك: {user_rating}/5"
    return f"{rating_line}\n{count_line}{user_line}"

def kb_btn_rating(bid: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ قيّم المحتوى", callback_data=f"brate_open_{bid}")
    ]])

def kb_btn_rating_choices(bid: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐" * i, callback_data=f"brate_set_{bid}_{i}") for i in range(1, 4)],
        [InlineKeyboardButton("⭐" * i, callback_data=f"brate_set_{bid}_{i}") for i in range(4, 6)],
        [InlineKeyboardButton("رجوع", callback_data=f"brate_back_{bid}")],
    ])

async def send_btn_unified_rating_message(target, bid: int, uid=None):
    await target.reply_text(btn_rating_text(bid, uid), reply_markup=kb_btn_rating(bid))

# ── الإحصائيات ───────────────────────────────────────────────────
def _today_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def get_stats() -> str:
    now = int(_time.time())
    today = _today_str()
    yesterday = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    day30_ago  = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    ts_7d  = now - 7  * 86400
    ts_14d = now - 14 * 86400
    ts_30d = now - 30 * 86400
    mdb = get_mongo_db()

    total_users   = mdb["user_stats"].count_documents({})
    today_doc     = mdb["daily_stats"].find_one({"date": today})
    yest_doc      = mdb["daily_stats"].find_one({"date": yesterday})
    new_today     = today_doc["new_users"] if today_doc else 0
    new_yesterday = yest_doc["new_users"] if yest_doc else 0
    new_month     = sum(d.get("new_users", 0) for d in mdb["daily_stats"].find({"date": {"$gte": day30_ago}}))
    msg_today     = today_doc["msg_count"] if today_doc else 0
    msg_yesterday = yest_doc["msg_count"] if yest_doc else 0
    msg_month     = sum(d.get("msg_count", 0) for d in mdb["daily_stats"].find({"date": {"$gte": day30_ago}}))

    eligible_7d  = mdb["user_stats"].count_documents({"first_seen": {"$gt": 0, "$lte": ts_14d}})
    retained_7d  = mdb["user_stats"].count_documents({"first_seen": {"$gt": 0, "$lte": ts_14d}, "last_active": {"$gte": ts_7d}})
    eligible_30d = mdb["user_stats"].count_documents({"first_seen": {"$gt": 0, "$lte": ts_30d}})
    retained_30d = mdb["user_stats"].count_documents({"first_seen": {"$gt": 0, "$lte": ts_30d}, "last_active": {"$gte": ts_30d}})

    ts_today_start = int(datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    ts_yest_start  = ts_today_start - 86400
    ts_month_start = now - 30 * 86400
    subscribed_via_notif = mdb["user_stats"].count_documents({"subscribed_via_notif": 1})
    sub_today    = mdb["user_stats"].count_documents({"subscribed_at": {"$gte": ts_today_start}})
    sub_yesterday= mdb["user_stats"].count_documents({"subscribed_at": {"$gte": ts_yest_start, "$lt": ts_today_start}})
    sub_month    = mdb["user_stats"].count_documents({"subscribed_at": {"$gte": ts_month_start}})

    total_btns = mdb["buttons"].count_documents({"deleted": {"$ne": 1}})
    menus      = mdb["buttons"].count_documents({"type": "menu", "deleted": {"$ne": 1}})
    content    = mdb["buttons"].count_documents({"type": "content", "deleted": {"$ne": 1}})
    admins     = mdb["admins"].count_documents({})

    retention_7d  = f"{round(retained_7d/eligible_7d*100)}%" if eligible_7d > 0 else "—"
    retention_30d = f"{round(retained_30d/eligible_30d*100)}%" if eligible_30d > 0 else "—"
    sub_rate      = f"{round(subscribed_via_notif/total_users*100)}%" if total_users > 0 else "—"
    db_size_kb    = round(os.path.getsize(DB) / 1024, 1) if os.path.exists(DB) else 0

    return (
        "📊 *إحصائيات البوت*\n\n"
        "👥 *المستخدمون*\n"
        f"  ├ إجمالي المستخدمين: `{total_users}`\n"
        f"  ├ جدد اليوم: `{new_today}`\n"
        f"  ├ جدد الأمس: `{new_yesterday}`\n"
        f"  └ جدد آخر 30 يوم: `{new_month}`\n\n"
        "📢 *الاشتراك بالقناة*\n"
        f"  ├ إجمالي المشتركين عبر الرسالة: `{subscribed_via_notif}` ({sub_rate})\n"
        f"  ├ اليوم: `{sub_today}`\n"
        f"  ├ الأمس: `{sub_yesterday}`\n"
        f"  └ آخر 30 يوم: `{sub_month}`\n\n"
        "💬 *الرسائل*\n"
        f"  ├ اليوم: `{msg_today}`\n"
        f"  ├ الأمس: `{msg_yesterday}`\n"
        f"  └ آخر 30 يوم: `{msg_month}`\n\n"
        "📈 *معدل الاحتفاظ بالمستخدمين*\n"
        f"  ├ خلال 7 أيام: `{retention_7d}`\n"
        f"  └ خلال 30 يوم: `{retention_30d}`\n\n"
        "🤖 *البوت*\n"
        f"  ├ قوائم: `{menus}` | محتوى: `{content}` | إجمالي: `{total_btns}`\n"
        f"  ├ المشرفون: `{admins}`\n"
        f"  └ حجم قاعدة بيانات SQLite المحلية: `{db_size_kb} KB`"
    )

def get_trending_page(page: int, page_size: int = 10):
    offset = page * page_size
    docs = list(_col("buttons").find(
        {"type": "content", "click_count": {"$gt": 0}, "deleted": {"$ne": 1}}
    ).sort("click_count", -1).skip(offset).limit(page_size))
    total = _col("buttons").count_documents({"type": "content", "click_count": {"$gt": 0}, "deleted": {"$ne": 1}})
    return [_d(r) for r in docs], total

_TYPE_ICON = {"text": "📝", "photo": "🖼", "video": "🎬", "file": "📁", "audio": "🎵"}

def _content_summary(bid) -> str:
    pipeline = [
        {"$match": {"button_id": bid}},
        {"$group": {"_id": "$type", "cnt": {"$sum": 1}}}
    ]
    rows = list(_col("content_items").aggregate(pipeline))
    if not rows:
        return "📭"
    parts = []
    for r in rows:
        icon = _TYPE_ICON.get(r["_id"], "📄")
        cnt = r["cnt"]
        parts.append(f"{icon}×{cnt}" if cnt > 1 else icon)
    return " ".join(parts)

def build_trending_text(page: int, page_size: int = 10) -> tuple:
    btns, total = get_trending_page(page, page_size)
    total_pages = max(1, (total + page_size - 1) // page_size)
    if not btns:
        text = "🔥 *الملفات الترند*\n\nلا توجد بيانات بعد.\nستظهر الأرقام بعد أن يبدأ المستخدمون بالضغط على الأزرار."
    else:
        start = page * page_size + 1
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, b in enumerate(btns, start=start):
            rank = i
            icon = medals.get(rank, f"{rank}\\.")
            path = get_btn_path(b["id"])
            content_sum = _content_summary(b["id"])
            lines.append(f"{icon} {content_sum} `{b['click_count']}` طلب\n_📍 {path}_")
        text = f"🔥 *الملفات الترند* — صفحة {page+1}/{total_pages}\n\n" + "\n\n".join(lines)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"st_trending_{page-1}"))
    if (page + 1) * page_size < total:
        nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"st_trending_{page+1}"))
    rows_kb = []
    if nav:
        rows_kb.append(nav)
    rows_kb.append([InlineKeyboardButton("رجوع", callback_data="st_back")])
    return text, InlineKeyboardMarkup(rows_kb)

def kb_cancel_inline():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]])

# ── الامتحانات ───────────────────────────────────────────────────
def add_exam_question(bid, q_type, q_text, q_file_id, q_channel_msg_id=None):
    count = _col("exam_questions").count_documents({"button_id": bid})
    new_id = _next_id("exam_questions")
    _col("exam_questions").insert_one({
        "id": new_id, "button_id": bid,
        "q_type": q_type, "q_text": q_text, "q_file_id": q_file_id,
        "q_channel_msg_id": q_channel_msg_id,
        "a_type": "text", "a_text": None, "a_file_id": None, "a_channel_msg_id": None,
        "ord": count + 1
    })
    return new_id

def set_exam_answer(qid, a_type, a_text, a_file_id, a_channel_msg_id=None):
    _col("exam_questions").update_one({"id": qid}, {"$set": {
        "a_type": a_type, "a_text": a_text,
        "a_file_id": a_file_id, "a_channel_msg_id": a_channel_msg_id
    }})

def get_exam_questions(bid):
    docs = _col("exam_questions").find({"button_id": bid}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def get_exam_question(qid):
    return _d(_col("exam_questions").find_one({"id": qid}))

def del_exam_question(qid):
    _col("exam_questions").delete_one({"id": qid})

def toggle_random_exam(bid):
    b = get_btn(bid)
    if not b:
        return False
    new_val = 0 if (b.get("random_exam", 0) or 0) else 1
    _col("buttons").update_one({"id": bid}, {"$set": {"random_exam": new_val}})
    return bool(new_val)

def reset_exam_progress(uid, bid, total):
    _col("exam_progress").update_one(
        {"user_id": uid, "exam_button_id": bid},
        {"$set": {"user_id": uid, "exam_button_id": bid, "total": total,
                  "answered": 0, "correct": 0, "wrong": 0, "completed": 0,
                  "updated_at": int(_time.time())}},
        upsert=True
    )

def mark_exam_answer(uid, bid, total, correct):
    doc = _col("exam_progress").find_one({"user_id": uid, "exam_button_id": bid})
    answered = (doc["answered"] if doc else 0) + 1
    good = (doc["correct"] if doc else 0) + (1 if correct else 0)
    bad  = (doc["wrong"]   if doc else 0) + (0 if correct else 1)
    completed = 1 if total and answered >= total else 0
    _col("exam_progress").update_one(
        {"user_id": uid, "exam_button_id": bid},
        {"$set": {"user_id": uid, "exam_button_id": bid, "total": total,
                  "answered": answered, "correct": good, "wrong": bad,
                  "completed": completed, "updated_at": int(_time.time())}},
        upsert=True
    )
    return {"total": total, "answered": answered, "correct": good, "wrong": bad, "completed": completed}

def finish_exam_progress(uid, bid, total):
    doc = _col("exam_progress").find_one({"user_id": uid, "exam_button_id": bid})
    answered = doc["answered"] if doc else 0
    good     = doc["correct"]  if doc else 0
    bad      = doc["wrong"]    if doc else 0
    completed = 1 if total and answered >= total else 0
    _col("exam_progress").update_one(
        {"user_id": uid, "exam_button_id": bid},
        {"$set": {"user_id": uid, "exam_button_id": bid, "total": total,
                  "answered": answered, "correct": good, "wrong": bad,
                  "completed": completed, "updated_at": int(_time.time())}},
        upsert=True
    )
    return {"total": total, "answered": answered, "correct": good, "wrong": bad, "completed": completed}

def get_exam_progress(uid, bid):
    doc = _col("exam_progress").find_one({"user_id": uid, "exam_button_id": bid})
    if doc:
        return _d(doc)
    return {"total": len(get_exam_questions(bid)), "answered": 0, "correct": 0, "wrong": 0, "completed": 0}

def get_exam_topics(parent_bid):
    return [b for b in get_buttons(parent_bid) if b.get("type") == "exam"]

def is_exam_topic_unlocked(uid, parent_bid, topic_bid):
    for topic in get_exam_topics(parent_bid):
        if topic["id"] == topic_bid:
            return True
        if not get_exam_progress(uid, topic["id"]).get("completed"):
            return False
    return True

def exam_group_summary(uid, parent_bid):
    topics = get_exam_topics(parent_bid)
    total_topics = len(topics)
    completed_topics = 0
    total_q = answered = correct = wrong = 0
    for topic in topics:
        progress = get_exam_progress(uid, topic["id"])
        if progress.get("completed"):
            completed_topics += 1
        qs = len(get_exam_questions(topic["id"]))
        total_q  += qs
        answered += progress.get("answered") or 0
        correct  += progress.get("correct") or 0
        wrong    += progress.get("wrong") or 0
    percent = round((completed_topics / total_topics) * 100) if total_topics else 0
    return {
        "topics": topics, "total_topics": total_topics,
        "completed_topics": completed_topics, "total_questions": total_q,
        "answered": answered, "correct": correct, "wrong": wrong, "percent": percent,
    }

def kb_add_content_active(bid: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ انتهاء الإضافة", callback_data=f"ci_add_done_{bid}")
    ]])

# ── إحصائيات المستخدمين ──────────────────────────────────────────
def update_user_info(uid, username=None, first_name=None):
    upd = {}
    if username is not None:
        upd["username"] = username.lstrip("@") if username else None
    if first_name is not None:
        upd["first_name"] = first_name
    if upd:
        _col("user_stats").update_one({"user_id": uid}, {"$set": upd})
