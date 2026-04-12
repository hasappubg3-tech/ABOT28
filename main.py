import logging
import os
import sqlite3
import json
import httpx
import zipfile
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DB = "data.db"
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

GEMINI_MODEL = "gemini-2.5-flash"

def _load_gemini_keys():
    keys = []
    for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        *[os.environ.get(f"GEMINI_API_KEY_{i}", "") for i in range(1, 11)],
    ]:
        if k and k not in keys:
            keys.append(k)
    return keys

GEMINI_KEYS = _load_gemini_keys()

BTN_BACK     = "رجوع"
BTN_ADD      = "➕ إضافة"
BTN_MANAGE   = "⚙️ إدارة"
BTN_ADMINS   = "👥 مشرفون"
BTN_CANCEL   = "❌ إلغاء"
BTN_SETTINGS = "⚙️ الاعدادات"

BTN_SWAP = "🔀 تغيير"

ADMIN_BTNS   = {BTN_ADMINS}
BTN_PLUS = "➕"
SPECIAL_BTNS = {BTN_BACK, BTN_ADD, BTN_MANAGE, BTN_ADMINS, BTN_CANCEL, BTN_SWAP, BTN_PLUS,
                BTN_SETTINGS, "📂 قائمة", "📄 محتوى"}

_SUP_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUP_MAP    = {c: str(i) for i, c in enumerate(_SUP_DIGITS)}

def _plus_label(bid: int) -> str:
    """يُنشئ نص زر ➕ + رقم الزر بأرقام فوقية مثل ➕⁵."""
    return BTN_PLUS + ''.join(_SUP_DIGITS[int(d)] for d in str(bid))

def _parse_plus(text: str):
    """يُعيد bid إذا كان النص زر ➕ مع أرقام فوقية، وإلا None."""
    if not text.startswith(BTN_PLUS):
        return None
    rest = text[len(BTN_PLUS):]
    if not rest:
        return None
    digits = ''.join(_SUP_MAP.get(c, '') for c in rest)
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None

# ── قاعدة البيانات ────────────────────────────────────────────────
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY, username TEXT);
            CREATE TABLE IF NOT EXISTS buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER REFERENCES buttons(id) ON DELETE CASCADE,
                type TEXT NOT NULL, label TEXT NOT NULL,
                ord INTEGER DEFAULT 0,
                new_row INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS content_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                button_id INTEGER NOT NULL REFERENCES buttons(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                content TEXT,
                file_id TEXT,
                local_path TEXT,
                ord INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS caption_buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                ord INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id   INTEGER PRIMARY KEY,
                opens     INTEGER DEFAULT 0,
                sessions  INTEGER DEFAULT 0,
                last_notif_opens    INTEGER DEFAULT 0,
                last_notif_sessions INTEGER DEFAULT 0
            );
        """)
        try:
            c.execute("ALTER TABLE buttons ADD COLUMN new_row INTEGER DEFAULT 1")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE buttons ADD COLUMN click_count INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE content_items ADD COLUMN local_path TEXT")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE buttons ADD COLUMN no_caption INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE buttons ADD COLUMN no_btn_caption INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE user_stats ADD COLUMN pending_notif_bid INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE user_stats ADD COLUMN subscribed_via_notif INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE user_stats ADD COLUMN subscribed_at INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE user_stats ADD COLUMN first_seen INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE user_stats ADD COLUMN last_active INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date      TEXT PRIMARY KEY,
                msg_count INTEGER DEFAULT 0,
                new_users INTEGER DEFAULT 0
            );
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_button_clicks (
                user_id   INTEGER NOT NULL,
                button_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, button_id)
            );
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS motivational_phrases (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT NOT NULL
            );
        """)
        c.commit()

def is_admin(uid):
    return db().execute("SELECT 1 FROM admins WHERE id=?", (uid,)).fetchone() is not None

def add_admin(uid, name=None):
    c = db(); c.execute("INSERT OR IGNORE INTO admins VALUES(?,?)", (uid, name)); c.commit(); c.close()

def del_admin(uid):
    c = db(); c.execute("DELETE FROM admins WHERE id=?", (uid,)); c.commit(); c.close()

def all_admins():
    return [dict(r) for r in db().execute("SELECT * FROM admins").fetchall()]

def get_setting(key, default=None):
    r = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default

def set_setting(key, value):
    c = db()
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
    c.commit(); c.close()

def get_global_caption():
    return get_setting("global_caption", "")

# ── العبارات التحفيزية ────────────────────────────────────────────
def get_phrases():
    return [dict(r) for r in db().execute(
        "SELECT id, phrase FROM motivational_phrases ORDER BY id"
    ).fetchall()]

def add_phrase(text: str):
    c = db()
    c.execute("INSERT INTO motivational_phrases(phrase) VALUES(?)", (text,))
    c.commit(); c.close()

def del_phrase(pid: int):
    c = db()
    c.execute("DELETE FROM motivational_phrases WHERE id=?", (pid,))
    c.commit(); c.close()

def get_phrases_chance() -> int:
    """يُرجع نسبة إرسال العبارة (0-100)."""
    return int(get_setting("phrases_chance", "30"))

def get_random_phrase() -> str | None:
    """يُرجع عبارة عشوائية أو None إذا لم توجد عبارات / لم تتحقق النسبة."""
    import random
    chance = get_phrases_chance()
    if chance <= 0 or random.randint(1, 100) > chance:
        return None
    rows = db().execute("SELECT phrase FROM motivational_phrases ORDER BY RANDOM() LIMIT 1").fetchall()
    return rows[0][0] if rows else None

def toggle_btn_no_caption(bid):
    b = get_btn(bid)
    if not b: return False
    current = b.get("no_caption", 0) or 0
    new_val = 0 if current else 1
    c = db()
    c.execute("UPDATE buttons SET no_caption=? WHERE id=?", (new_val, bid))
    c.commit(); c.close()
    return bool(new_val)

def toggle_btn_no_btn_caption(bid):
    b = get_btn(bid)
    if not b: return False
    current = b.get("no_btn_caption", 0) or 0
    new_val = 0 if current else 1
    c = db()
    c.execute("UPDATE buttons SET no_btn_caption=? WHERE id=?", (new_val, bid))
    c.commit(); c.close()
    return bool(new_val)

def get_caption_buttons():
    return [dict(r) for r in db().execute(
        "SELECT * FROM caption_buttons ORDER BY ord,id").fetchall()]

def add_caption_button(label, url):
    c = db(); cur = c.cursor()
    n = cur.execute("SELECT COALESCE(MAX(ord),0)+1 FROM caption_buttons").fetchone()[0]
    cur.execute("INSERT INTO caption_buttons(label,url,ord) VALUES(?,?,?)", (label, url, n))
    c.commit(); c.close()

def del_caption_button(cbid):
    c = db(); c.execute("DELETE FROM caption_buttons WHERE id=?", (cbid,)); c.commit(); c.close()

def build_caption_btn_markup(buttons):
    if not buttons:
        return None
    rows = [[InlineKeyboardButton(b["label"], url=b["url"])] for b in buttons]
    return InlineKeyboardMarkup(rows)

# ── نظام التنبيهات ────────────────────────────────────────────────
def _today_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def _ensure_user_stats(uid):
    import time as _time
    c = db()
    now = int(_time.time())
    today = _today_str()
    existing = c.execute("SELECT user_id, first_seen FROM user_stats WHERE user_id=?", (uid,)).fetchone()
    if existing is None:
        c.execute("INSERT OR IGNORE INTO user_stats(user_id, first_seen, last_active) VALUES(?,?,?)", (uid, now, now))
        c.execute("INSERT INTO daily_stats(date, new_users) VALUES(?,1) ON CONFLICT(date) DO UPDATE SET new_users=new_users+1", (today,))
    elif existing["first_seen"] == 0:
        c.execute("UPDATE user_stats SET first_seen=? WHERE user_id=?", (now, uid))
    c.commit(); c.close()

def track_message(uid):
    import time as _time
    _ensure_user_stats(uid)
    c = db()
    today = _today_str()
    now = int(_time.time())
    c.execute("UPDATE user_stats SET last_active=? WHERE user_id=?", (now, uid))
    c.execute("INSERT INTO daily_stats(date, msg_count) VALUES(?,1) ON CONFLICT(date) DO UPDATE SET msg_count=msg_count+1", (today,))
    c.commit(); c.close()

def get_user_stats(uid):
    _ensure_user_stats(uid)
    r = db().execute("SELECT * FROM user_stats WHERE user_id=?", (uid,)).fetchone()
    return dict(r) if r else {}

def inc_user_opens(uid):
    _ensure_user_stats(uid)
    c = db()
    c.execute("UPDATE user_stats SET opens=opens+1 WHERE user_id=?", (uid,))
    c.commit(); c.close()
    return db().execute("SELECT opens FROM user_stats WHERE user_id=?", (uid,)).fetchone()[0]

def inc_user_sessions(uid):
    _ensure_user_stats(uid)
    c = db()
    c.execute("UPDATE user_stats SET sessions=sessions+1 WHERE user_id=?", (uid,))
    c.commit(); c.close()
    return db().execute("SELECT sessions FROM user_stats WHERE user_id=?", (uid,)).fetchone()[0]

def mark_notif_sent(uid):
    s = get_user_stats(uid)
    c = db()
    c.execute("UPDATE user_stats SET last_notif_opens=?, last_notif_sessions=? WHERE user_id=?",
              (s.get("opens", 0), s.get("sessions", 0), uid))
    c.commit(); c.close()

def set_pending_notif(uid, bid):
    _ensure_user_stats(uid)
    c = db()
    c.execute("UPDATE user_stats SET pending_notif_bid=? WHERE user_id=?", (bid, uid))
    c.commit(); c.close()

def clear_pending_notif(uid):
    _ensure_user_stats(uid)
    c = db()
    c.execute("UPDATE user_stats SET pending_notif_bid=0 WHERE user_id=?", (uid,))
    c.commit(); c.close()

def record_channel_subscription(uid):
    import time as _time
    _ensure_user_stats(uid)
    c = db()
    already = c.execute("SELECT subscribed_via_notif FROM user_stats WHERE user_id=?", (uid,)).fetchone()
    if already and already[0] == 0:
        c.execute("UPDATE user_stats SET subscribed_via_notif=1, subscribed_at=? WHERE user_id=?", (int(_time.time()), uid))
        c.commit()
    c.close()

def get_pending_notif(uid):
    s = get_user_stats(uid)
    return s.get("pending_notif_bid", 0) or 0

async def is_subscribed(bot, uid: int):
    """
    يتحقق من اشتراك المستخدم في القناة.
    يُرجع: True إذا مشترك، False إذا غير مشترك، None إذا تعذّر الفحص.
    """
    chan = get_setting("notif_channel", "").strip()
    if not chan:
        return None
    try:
        if chan.startswith("http"):
            parts = chan.rstrip("/").split("/")
            channel_id = f"@{parts[-1]}"
        elif chan.startswith("-"):
            channel_id = int(chan)
        else:
            channel_id = f"@{chan.lstrip('@')}"
        member = await bot.get_chat_member(channel_id, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return None

def should_notify(uid) -> bool:
    """النظام 1: هل يجب إظهار التنبيه المنبثق؟"""
    chan = get_setting("notif_channel", "").strip()
    if not chan:
        return False
    msg = get_setting("notif_message", "")
    if not msg:
        return False
    enabled = get_setting("notif_enabled", "1")
    if enabled != "1":
        return False
    s = get_user_stats(uid)
    opens   = s.get("opens", 0)
    last_op = s.get("last_notif_opens", 0)
    try:
        every_opens = int(get_setting("notif_every_opens", "5"))
    except Exception:
        every_opens = 5
    if every_opens > 0 and opens > 0 and (opens - last_op) >= every_opens:
        return True
    return False


async def send_notif_gate(target, uid, bid):
    """يُرسل نافذة التنبيه المنبثقة — المستخدم لا يستطيع تجاوزها."""
    msg         = get_setting("notif_message", "🔔 يرجى الاشتراك في قناتنا!")
    chan        = get_setting("notif_channel", "").strip()
    ok_text     = get_setting("notif_ok_text",    "✅ نعم، اشتركت")
    cancel_text = get_setting("notif_cancel_text", "❌ لا، لاحقاً")

    rows = []
    if chan:
        url = chan if chan.startswith("http") else f"https://t.me/{chan.lstrip('@')}"
        rows.append([InlineKeyboardButton("📢 انضم للقناة الآن", url=url)])
    rows.append([
        InlineKeyboardButton(ok_text,     callback_data=f"notif_ok_{bid}"),
        InlineKeyboardButton(cancel_text, callback_data=f"notif_skip_{bid}"),
    ])
    markup = InlineKeyboardMarkup(rows)
    try:
        try:
            await target.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            await target.reply_text(msg, reply_markup=markup)
        mark_notif_sent(uid)
        set_pending_notif(uid, bid)
    except Exception:
        pass

def get_buttons(pid=None):
    if pid is None:
        q = "SELECT * FROM buttons WHERE parent_id IS NULL ORDER BY ord,id"
        return [dict(r) for r in db().execute(q).fetchall()]
    return [dict(r) for r in db().execute(
        "SELECT * FROM buttons WHERE parent_id=? ORDER BY ord,id", (pid,)).fetchall()]

def get_btn(bid):
    r = db().execute("SELECT * FROM buttons WHERE id=?", (bid,)).fetchone()
    return dict(r) if r else None

def _siblings(cur, pid):
    if pid is None:
        return [r[0] for r in cur.execute(
            "SELECT id FROM buttons WHERE parent_id IS NULL ORDER BY ord,id").fetchall()]
    return [r[0] for r in cur.execute(
        "SELECT id FROM buttons WHERE parent_id=? ORDER BY ord,id", (pid,)).fetchall()]

def _renumber(cur, ids):
    for i, bid in enumerate(ids):
        cur.execute("UPDATE buttons SET ord=? WHERE id=?", (i + 1, bid))

def add_btn(pid, t, label):
    """يضيف زراً في نهاية القائمة."""
    c = db(); cur = c.cursor()
    ids = _siblings(cur, pid)
    cur.execute("INSERT INTO buttons(parent_id,type,label,ord) VALUES(?,?,?,?)",
                (pid, t, label, len(ids) + 1))
    lid = cur.lastrowid; c.commit(); c.close(); return lid

def add_btn_before(before_bid, pid, t, label):
    """يضيف زراً في صف جديد قبل before_bid مباشرة."""
    c = db(); cur = c.cursor()
    ids = _siblings(cur, pid)
    pos = ids.index(before_bid) if before_bid in ids else 0
    cur.execute("INSERT INTO buttons(parent_id,type,label,ord,new_row) VALUES(?,?,?,?,?)",
                (pid, t, label, 0, 1))
    new_id = cur.lastrowid
    ids.insert(pos, new_id)
    _renumber(cur, ids)
    c.commit(); c.close(); return new_id

def add_btn_after(after_bid, pid, t, label, new_row=1):
    """يضيف زراً بعد after_bid، أو في البداية إذا كان after_bid=None."""
    c = db(); cur = c.cursor()
    ids = _siblings(cur, pid)
    if after_bid is None:
        pos = 0
    else:
        pos = (ids.index(after_bid) + 1) if after_bid in ids else len(ids)
    cur.execute("INSERT INTO buttons(parent_id,type,label,ord,new_row) VALUES(?,?,?,?,?)",
                (pid, t, label, 0, new_row))
    new_id = cur.lastrowid
    ids.insert(pos, new_id)
    _renumber(cur, ids)
    c.commit(); c.close(); return new_id

def upd_btn_label(bid, label):
    c = db(); c.execute("UPDATE buttons SET label=? WHERE id=?", (label, bid)); c.commit(); c.close()

def inc_click_count(bid, uid=None):
    c = db()
    if uid is not None:
        try:
            c.execute("INSERT INTO user_button_clicks(user_id, button_id) VALUES(?,?)", (uid, bid))
            c.execute("UPDATE buttons SET click_count=COALESCE(click_count,0)+1 WHERE id=?", (bid,))
        except Exception:
            pass  # المستخدم ضغط من قبل، لا نعدّ مرة ثانية
    else:
        c.execute("UPDATE buttons SET click_count=COALESCE(click_count,0)+1 WHERE id=?", (bid,))
    c.commit(); c.close()

def get_btn_path(bid) -> str:
    """يُرجع المسار الكامل للزر: قسم1 ‹ قسم2 ‹ اسم الزر"""
    parts = []
    current = get_btn(bid)
    while current:
        parts.append(current["label"])
        pid = current.get("parent_id")
        current = get_btn(pid) if pid else None
    parts.reverse()
    return " › ".join(parts)

def _create_nested_buttons(parent_id, buttons_list, anchor_id=None, use_after=False):
    """ينشئ قائمة أزرار داخل parent_id بشكل متداخل (يدعم children)."""
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

def del_btn(bid):
    c = db(); c.execute("DELETE FROM buttons WHERE id=?", (bid,)); c.commit(); c.close()

# ── الزر الخاص (singleton type='special') ─────────────────────────
def get_special_btn():
    r = db().execute("SELECT * FROM buttons WHERE type='special' LIMIT 1").fetchone()
    return dict(r) if r else None

def create_special_btn(label: str, pid=None) -> int:
    """ينشئ الزر الخاص في نهاية المستوى المحدد ويُرجع id."""
    return add_btn(pid, "special", label)

def move_special_btn(bid: int, new_pid):
    """ينقل الزر الخاص إلى مستوى جديد (new_pid=None يعني الجذر)."""
    c = db()
    ids = _siblings(c.cursor(), new_pid)
    new_ord = len(ids) + 1
    if new_pid is None:
        c.execute("UPDATE buttons SET parent_id=NULL, ord=?, new_row=1 WHERE id=?", (new_ord, bid))
    else:
        c.execute("UPDATE buttons SET parent_id=?, ord=?, new_row=1 WHERE id=?", (new_pid, new_ord, bid))
    c.commit(); c.close()

def all_menu_levels() -> list:
    """يُرجع قائمة بجميع أزرار النوع menu مرتبة (للاختيار من بينها كوجهة نقل)."""
    return [dict(r) for r in db().execute(
        "SELECT id, label, parent_id FROM buttons WHERE type='menu' ORDER BY ord, id"
    ).fetchall()]


def swap_btns(bid1, bid2):
    """يبدّل موضع زرين (ord + new_row)."""
    c = db(); cur = c.cursor()
    b1 = dict(cur.execute("SELECT ord, new_row FROM buttons WHERE id=?", (bid1,)).fetchone())
    b2 = dict(cur.execute("SELECT ord, new_row FROM buttons WHERE id=?", (bid2,)).fetchone())
    cur.execute("UPDATE buttons SET ord=?, new_row=? WHERE id=?", (b2['ord'], b2['new_row'], bid1))
    cur.execute("UPDATE buttons SET ord=?, new_row=? WHERE id=?", (b1['ord'], b1['new_row'], bid2))
    c.commit(); c.close()

# ── content_items ─────────────────────────────────────────────────
def get_items(bid):
    return [dict(r) for r in db().execute(
        "SELECT * FROM content_items WHERE button_id=? ORDER BY ord,id", (bid,)).fetchall()]

def add_item(bid, t, content=None, file_id=None, local_path=None):
    c = db(); cur = c.cursor()
    n = cur.execute("SELECT COALESCE(MAX(ord),0)+1 FROM content_items WHERE button_id=?", (bid,)).fetchone()[0]
    cur.execute("INSERT INTO content_items(button_id,type,content,file_id,local_path,ord) VALUES(?,?,?,?,?,?)",
                (bid, t, content, file_id, local_path, n))
    c.commit(); c.close()

def upd_item_file_id(iid, file_id):
    c = db(); c.execute("UPDATE content_items SET file_id=? WHERE id=?", (file_id, iid)); c.commit(); c.close()

def del_item(iid):
    c = db(); c.execute("DELETE FROM content_items WHERE id=?", (iid,)); c.commit(); c.close()

def upd_item_content(iid, content):
    c = db(); c.execute("UPDATE content_items SET content=? WHERE id=?", (content, iid)); c.commit(); c.close()

def get_item(iid):
    r = db().execute("SELECT * FROM content_items WHERE id=?", (iid,)).fetchone()
    return dict(r) if r else None

# ── اكتشاف نوع المحتوى تلقائياً ─────────────────────────────────
def detect_content(m):
    if m.photo:
        return "photo", m.caption, m.photo[-1].file_id
    if m.document:
        return "file", m.caption, m.document.file_id
    if m.video:
        return "video", m.caption, m.video.file_id
    if m.audio:
        return "audio", m.caption, m.audio.file_id
    if m.voice:
        return "audio", m.caption, m.voice.file_id
    if m.text:
        return "text", m.text, None
    return None, None, None

async def download_and_save(bot, file_id: str, file_type: str) -> str | None:
    try:
        import uuid
        ext_map = {"photo": "jpg", "video": "mp4", "audio": "mp3", "file": "bin"}
        ext = ext_map.get(file_type, "bin")
        filename = f"{MEDIA_DIR}/{file_type}_{uuid.uuid4().hex}.{ext}"
        tg_file = await bot.get_file(file_id)
        await tg_file.download_to_drive(filename)
        return filename
    except Exception as e:
        logging.warning(f"فشل تحميل الملف محلياً: {e}")
        return None

async def send_file_item(target, item, reply_markup=None, extra_caption=""):
    t = item["type"]
    fid = item.get("file_id")
    cap = item.get("content") or ""
    if extra_caption:
        cap = f"{cap}\n{extra_caption}" if cap else extra_caption
    lpath = item.get("local_path")
    iid = item.get("id")
    kwargs = {"caption": cap}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup

    async def _send_from_fid():
        if t == "photo":
            return await target.reply_photo(fid, **kwargs)
        elif t == "file":
            return await target.reply_document(fid, **kwargs)
        elif t == "video":
            return await target.reply_video(fid, **kwargs)
        elif t == "audio":
            return await target.reply_audio(fid, **kwargs)

    async def _send_from_local():
        if not lpath or not os.path.exists(lpath):
            return None
        with open(lpath, "rb") as f:
            if t == "photo":
                msg = await target.reply_photo(f, **kwargs)
            elif t == "file":
                msg = await target.reply_document(f, **kwargs)
            elif t == "video":
                msg = await target.reply_video(f, **kwargs)
            elif t == "audio":
                msg = await target.reply_audio(f, **kwargs)
            else:
                return None
        new_fid = None
        if msg:
            if t == "photo" and msg.photo:
                new_fid = msg.photo[-1].file_id
            elif t == "file" and msg.document:
                new_fid = msg.document.file_id
            elif t == "video" and msg.video:
                new_fid = msg.video.file_id
            elif t == "audio" and msg.audio:
                new_fid = msg.audio.file_id
            if new_fid and iid:
                upd_item_file_id(iid, new_fid)
        return msg

    if t == "text":
        await target.reply_text(cap, **({"reply_markup": reply_markup} if reply_markup else {}))
        return

    if fid:
        try:
            await _send_from_fid()
            return
        except Exception:
            pass
    await _send_from_local()

# ── بناء لوحة مفاتيح الرد ────────────────────────────────────────
ICON = {"menu": "📂", "content": "📄"}

def build_kb(uid, pid=None):
    btns = get_buttons(pid)
    admin = is_admin(uid)
    rows = []
    current_row = []
    last_bid_in_row = None
    for i, b in enumerate(btns):
        if i > 0 and b.get('new_row', 1):
            if current_row:
                if admin and last_bid_in_row is not None:
                    current_row.append(KeyboardButton(_plus_label(last_bid_in_row)))
                rows.append(current_row)
            current_row = []
        current_row.append(KeyboardButton(b['label']))
        last_bid_in_row = b['id']
    if current_row:
        if admin and last_bid_in_row is not None:
            current_row.append(KeyboardButton(_plus_label(last_bid_in_row)))
        rows.append(current_row)
    if admin and not btns:
        rows.append([KeyboardButton(BTN_PLUS)])
    if admin:
        rows.append([KeyboardButton(BTN_ADD)])
    if pid is not None:
        rows.append([KeyboardButton(BTN_BACK)])
    if admin:
        rows.append([KeyboardButton(BTN_SETTINGS)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True) if (rows or admin) else None

# ── لوحات Inline ─────────────────────────────────────────────────
def kb_manage(pid=None):
    ctx = "r" if pid is None else str(pid)
    rows = []
    btns = get_buttons(pid)
    for b in btns:
        rows.append([
            InlineKeyboardButton(b['label'], callback_data=f"e_{b['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"confirm_x_{b['id']}"),
            InlineKeyboardButton("➕", callback_data=f"plus_{b['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة", callback_data=f"plus_e_{ctx}")])
    if len(btns) >= 2:
        rows.append([InlineKeyboardButton("🔀 تبديل موضع زرين", callback_data=f"swp_start_{ctx}")])
    if pid is not None:
        b = get_btn(pid); back = b["parent_id"] if b else None
        rows.append([InlineKeyboardButton("رجوع", callback_data="m_r" if back is None else f"m_{back}")])
    return InlineKeyboardMarkup(rows)

def kb_add_position(after_bid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆️ فوقه (صف جديد)",      callback_data=f"pladd_above_{after_bid}")],
        [InlineKeyboardButton("➡️ بجانبه (نفس السطر)",  callback_data=f"pladd_same_{after_bid}")],
        [InlineKeyboardButton("⬇️ تحته (سطر جديد)",     callback_data=f"pladd_new_{after_bid}")],
        [InlineKeyboardButton("❌ إلغاء",                callback_data="pt_cancel")],
    ])

def kb_add_where(pid):
    """يُعرض عند BTN_ADD ليختار المشرف الموضع أولاً."""
    btns = get_buttons(pid)
    if not btns:
        return None  # لا حاجة للسؤال إذا لم تكن هناك أزرار
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆️ في أعلى القائمة (صف جديد أول)", callback_data="pt_addtop")],
        [InlineKeyboardButton("⬇️ في أسفل القائمة (نهاية القائمة)", callback_data="pt_addbottom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="pt_cancel")],
    ])

def kb_add_type():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📂 قائمة", callback_data="pt_m"),
        InlineKeyboardButton("📄 محتوى", callback_data="pt_c"),
        InlineKeyboardButton("❌ إلغاء", callback_data="pt_cancel"),
    ]])

def kb_swap_select(pid=None, first_bid=None):
    """لوحة اختيار الزر للتبديل — بنفس تخطيط الأزرار الأصلي."""
    btns = get_buttons(pid)
    rows = []
    current_row = []
    for i, b in enumerate(btns):
        if i > 0 and b.get('new_row', 1) and current_row:
            rows.append(current_row)
            current_row = []
        if first_bid is None:
            current_row.append(InlineKeyboardButton(b['label'], callback_data=f"swp1_{b['id']}"))
        elif b['id'] == first_bid:
            current_row.append(InlineKeyboardButton(f"✅ {b['label']}", callback_data="noop"))
        else:
            current_row.append(InlineKeyboardButton(b['label'], callback_data=f"swp2_{first_bid}_{b['id']}"))
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="m_r" if pid is None else f"m_{pid}")])
    return InlineKeyboardMarkup(rows)

def kb_edit_menu_btn(bid):
    b = get_btn(bid)
    rows = [
        [InlineKeyboardButton("📂 فتح القائمة", callback_data=f"m_{bid}")],
        [InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"el_{bid}")],
        [InlineKeyboardButton("🗑 حذف",          callback_data=f"confirm_x_{bid}")],
    ]
    pid = b["parent_id"] if b else None
    rows.append([InlineKeyboardButton("رجوع", callback_data="m_r" if pid is None else f"m_{pid}")])
    return InlineKeyboardMarkup(rows)

def kb_content_panel(bid):
    """لوحة إدارة محتوى الزر (كاملة)."""
    items = get_items(bid)
    b = get_btn(bid)
    rows = []
    if items:
        rows.append([InlineKeyboardButton("👁 عرض المحتوى", callback_data=f"ci_view_{bid}")])
    rows.append([InlineKeyboardButton("➕ إضافة محتوى", callback_data=f"ci_add_{bid}")])
    global_cap = get_global_caption()
    if global_cap:
        no_cap = (b.get("no_caption", 0) or 0) if b else 0
        cap_label = "✅ تفعيل كليشة الكلام" if no_cap else "🚫 إلغاء كليشة الكلام"
        rows.append([InlineKeyboardButton(cap_label, callback_data=f"ci_toggle_cap_{bid}")])
    cap_btns = get_caption_buttons()
    if cap_btns:
        no_btn_cap = (b.get("no_btn_caption", 0) or 0) if b else 0
        btn_cap_label = "✅ تفعيل كليشة الأزرار" if no_btn_cap else "🚫 إلغاء كليشة الأزرار"
        rows.append([InlineKeyboardButton(btn_cap_label, callback_data=f"ci_toggle_btn_cap_{bid}")])
    rows.append([InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"el_{bid}")])
    rows.append([InlineKeyboardButton("🗑 حذف الزر",    callback_data=f"confirm_x_{bid}")])
    pid = b["parent_id"] if b else None
    rows.append([InlineKeyboardButton("رجوع", callback_data="m_r" if pid is None else f"m_{pid}")])
    return InlineKeyboardMarkup(rows)

def kb_menu_quick(bid):
    """خيارات سريعة لزر قائمة عند الضغط من الكيبورد — بدون إضافة أو رجوع."""
    b = get_btn(bid)
    pid = b["parent_id"] if b else None
    siblings = get_buttons(pid)
    rows = [
        [InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"el_{bid}")],
        [InlineKeyboardButton("🗑 حذف",          callback_data=f"confirm_x_{bid}")],
    ]
    if len(siblings) >= 2:
        rows.append([InlineKeyboardButton("🔀 تبديل الموضع", callback_data=f"swp_start_{'r' if pid is None else str(pid)}")])
    return InlineKeyboardMarkup(rows)

def kb_content_quick(bid):
    """خيارات سريعة لزر محتوى عند الضغط من الكيبورد — بدون رجوع."""
    items = get_items(bid)
    b = get_btn(bid)
    rows = []
    if items:
        rows.append([InlineKeyboardButton("👁 عرض المحتوى", callback_data=f"ci_view_{bid}")])
    rows.append([InlineKeyboardButton("➕ إضافة محتوى", callback_data=f"ci_add_{bid}")])
    global_cap = get_global_caption()
    if global_cap:
        no_cap = (b.get("no_caption", 0) or 0) if b else 0
        cap_label = "✅ تفعيل كليشة الكلام" if no_cap else "🚫 إلغاء كليشة الكلام"
        rows.append([InlineKeyboardButton(cap_label, callback_data=f"ci_toggle_cap_{bid}")])
    cap_btns = get_caption_buttons()
    if cap_btns:
        no_btn_cap = (b.get("no_btn_caption", 0) or 0) if b else 0
        btn_cap_label = "✅ تفعيل كليشة الأزرار" if no_btn_cap else "🚫 إلغاء كليشة الأزرار"
        rows.append([InlineKeyboardButton(btn_cap_label, callback_data=f"ci_toggle_btn_cap_{bid}")])
    rows.append([InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"el_{bid}")])
    rows.append([InlineKeyboardButton("🗑 حذف",          callback_data=f"confirm_x_{bid}")])
    return InlineKeyboardMarkup(rows)

def kb_item_actions(iid):
    """أزرار تحت كل عنصر محتوى عند العرض."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ تغيير الوصف", callback_data=f"ci_edit_{iid}"),
        InlineKeyboardButton("🗑 حذف",          callback_data=f"ci_del_{iid}"),
    ]])

def kb_admins_inline():
    rows = []
    for a in all_admins():
        name = a.get("username") or str(a["id"])
        rows.append([
            InlineKeyboardButton(f"👤 {name}", callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"da_{a['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة مشرف", callback_data="aa")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="st_back")])
    return InlineKeyboardMarkup(rows)

def kb_settings():
    global_cap = get_global_caption()
    cap_btns = get_caption_buttons()
    notif1_on  = get_setting("notif_enabled", "1") == "1"
    notif1_msg = get_setting("notif_message", "")
    cap_label    = "✏️ تغيير كليشة الكلام" if global_cap else "📌 كليشة الكلام"
    capbtn_label = f"🔗 كليشة الأزرار ({len(cap_btns)} زر)" if cap_btns else "🔗 كليشة الأزرار"
    notif1_icon  = "✅" if (notif1_on and notif1_msg) else "⭕"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المشرفون",                     callback_data="st_admins")],
        [InlineKeyboardButton("💾 النسخ الاحتياطي",              callback_data="st_backup_menu")],
        [InlineKeyboardButton(cap_label,                         callback_data="st_caption")],
        [InlineKeyboardButton(capbtn_label,                      callback_data="st_capbtn")],
        [InlineKeyboardButton(f"📢 رسالة الاشتراك {notif1_icon}", callback_data="st_notif1")],
        [InlineKeyboardButton("📊 الإحصائيات",                   callback_data="st_stats")],
        [InlineKeyboardButton("🔥 الملفات الترند",                callback_data="st_trending_0")],
        [InlineKeyboardButton("📡 الإذاعة",                       callback_data="st_broadcast")],
        [InlineKeyboardButton("💬 العبارات التحفيزية",             callback_data="st_phrases")],
        [InlineKeyboardButton("⭐ الزر الخاص",                     callback_data="st_special")],
    ])

def kb_notif1_settings():
    notif_on     = get_setting("notif_enabled", "1") == "1"
    msg          = get_setting("notif_message", "")
    chan         = get_setting("notif_channel", "")
    every_op     = get_setting("notif_every_opens", "5")
    ok_text      = get_setting("notif_ok_text",    "✅ نعم، اشتركت")
    cancel_text  = get_setting("notif_cancel_text", "❌ لا، لاحقاً")
    toggle_label = "🔕 إيقاف رسالة الاشتراك" if notif_on else "📢 تفعيل رسالة الاشتراك"
    rows = []
    rows.append([InlineKeyboardButton(toggle_label, callback_data="st_notif_toggle")])
    rows.append([InlineKeyboardButton(
        "✏️ تغيير نص التنبيه" if msg else "✏️ كتابة نص التنبيه",
        callback_data="st_notif_msg"
    )])
    rows.append([InlineKeyboardButton(
        f"📢 القناة: {chan}" if chan else "📢 تحديد رابط القناة",
        callback_data="st_notif_chan"
    )])
    rows.append([InlineKeyboardButton(
        f"📂 يظهر كل {every_op} ضغطة",
        callback_data="st_notif_opens"
    )])
    rows.append([
        InlineKeyboardButton(f'زر "نعم": {ok_text}',    callback_data="st_notif_ok_text"),
        InlineKeyboardButton(f'زر "لا": {cancel_text}', callback_data="st_notif_cancel_text"),
    ])
    rows.append([InlineKeyboardButton("رجوع", callback_data="st_back")])
    return InlineKeyboardMarkup(rows)

def kb_broadcast():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 إرسال رسالة جديدة", callback_data="st_broadcast_send")],
        [InlineKeyboardButton("رجوع",                  callback_data="st_back")],
    ])

def kb_broadcast_confirm():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ إرسال للجميع",  callback_data="st_broadcast_confirm"),
            InlineKeyboardButton("❌ إلغاء",          callback_data="st_broadcast"),
        ],
    ])

def kb_phrases():
    phrases = get_phrases()
    chance  = get_phrases_chance()
    rows = []
    for p in phrases:
        short = p["phrase"][:30] + ("…" if len(p["phrase"]) > 30 else "")
        rows.append([
            InlineKeyboardButton(f"🗑 {short}", callback_data=f"st_phrase_del_{p['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة عبارة",            callback_data="st_phrase_add")])
    rows.append([InlineKeyboardButton(f"🎲 نسبة الظهور: {chance}%", callback_data="st_phrase_chance")])
    rows.append([InlineKeyboardButton("رجوع",                       callback_data="st_back")])
    return InlineKeyboardMarkup(rows)

def kb_special_settings():
    sp = get_special_btn()
    rows = []
    if sp:
        rows.append([InlineKeyboardButton(f"✏️ تغيير الاسم: «{sp['label']}»", callback_data="st_special_rename")])
        rows.append([InlineKeyboardButton("🔀 تغيير الموضع",                  callback_data="st_special_move")])
        rows.append([InlineKeyboardButton("🗑 حذف الزر الخاص",               callback_data="st_special_del")])
    else:
        rows.append([InlineKeyboardButton("➕ إنشاء الزر الخاص",             callback_data="st_special_create")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="st_back")])
    return InlineKeyboardMarkup(rows)

def kb_special_move_picker():
    """لوحة اختيار وجهة نقل الزر الخاص (مستوى جديد)."""
    rows = [[InlineKeyboardButton("📌 القائمة الرئيسية", callback_data="st_special_moveto_root")]]
    for m in all_menu_levels():
        rows.append([InlineKeyboardButton(f"📂 {m['label']}", callback_data=f"st_special_moveto_{m['id']}")])
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="st_special")])
    return InlineKeyboardMarkup(rows)

def kb_caption_settings():
    global_cap = get_global_caption()
    rows = []
    if global_cap:
        rows.append([InlineKeyboardButton("✏️ تغيير الكليشة", callback_data="st_caption_set")])
        rows.append([InlineKeyboardButton("🗑 حذف الكليشة",   callback_data="st_caption_clear")])
    else:
        rows.append([InlineKeyboardButton("➕ كتابة الكليشة", callback_data="st_caption_set")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="st_back")])
    return InlineKeyboardMarkup(rows)

def kb_caption_btn_settings():
    btns = get_caption_buttons()
    rows = []
    for b in btns:
        rows.append([
            InlineKeyboardButton(f"🔗 {b['label']}", url=b["url"]),
            InlineKeyboardButton("🗑", callback_data=f"st_capbtn_del_{b['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة زر رابط", callback_data="st_capbtn_add")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="st_back")])
    return InlineKeyboardMarkup(rows)

def kb_backup_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 تحميل نسخة احتياطية", callback_data="st_backup_dl")],
        [InlineKeyboardButton("📤 رفع نسخة احتياطية",   callback_data="st_restore")],
        [InlineKeyboardButton("رجوع",                 callback_data="st_back")],
    ])

def get_stats() -> str:
    import time as _time
    now = int(_time.time())
    today = _today_str()
    yesterday = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    day30_ago  = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    ts_7d  = now - 7  * 86400
    ts_14d = now - 14 * 86400
    ts_30d = now - 30 * 86400

    with db() as c:
        # ── المستخدمون ──────────────────────────────────
        total_users   = c.execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
        new_today     = c.execute("SELECT COALESCE(SUM(new_users),0) FROM daily_stats WHERE date=?", (today,)).fetchone()[0]
        new_yesterday = c.execute("SELECT COALESCE(SUM(new_users),0) FROM daily_stats WHERE date=?", (yesterday,)).fetchone()[0]
        new_month     = c.execute("SELECT COALESCE(SUM(new_users),0) FROM daily_stats WHERE date>=?", (day30_ago,)).fetchone()[0]

        # ── الرسائل ──────────────────────────────────────
        msg_today     = c.execute("SELECT COALESCE(SUM(msg_count),0) FROM daily_stats WHERE date=?", (today,)).fetchone()[0]
        msg_yesterday = c.execute("SELECT COALESCE(SUM(msg_count),0) FROM daily_stats WHERE date=?", (yesterday,)).fetchone()[0]
        msg_month     = c.execute("SELECT COALESCE(SUM(msg_count),0) FROM daily_stats WHERE date>=?", (day30_ago,)).fetchone()[0]

        # ── الاحتفاظ بالمستخدمين ─────────────────────────
        # مستخدمون انضموا قبل 14 يوم أو أكثر (يمكن تقييمهم)
        eligible_7d  = c.execute("SELECT COUNT(*) FROM user_stats WHERE first_seen>0 AND first_seen<=?", (ts_14d,)).fetchone()[0]
        retained_7d  = c.execute("SELECT COUNT(*) FROM user_stats WHERE first_seen>0 AND first_seen<=? AND last_active>=?", (ts_14d, ts_7d)).fetchone()[0]
        eligible_30d = c.execute("SELECT COUNT(*) FROM user_stats WHERE first_seen>0 AND first_seen<=?", (ts_30d,)).fetchone()[0]
        retained_30d = c.execute("SELECT COUNT(*) FROM user_stats WHERE first_seen>0 AND first_seen<=? AND last_active>=?", (ts_30d, ts_30d)).fetchone()[0]

        # ── القناة ───────────────────────────────────────
        import time as _time2
        ts_today_start    = int(datetime.datetime.utcnow().replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
        ts_yest_start     = ts_today_start - 86400
        ts_month_start    = int((_time2.time()) - 30 * 86400)
        subscribed_via_notif  = c.execute("SELECT COUNT(*) FROM user_stats WHERE subscribed_via_notif=1").fetchone()[0]
        sub_today             = c.execute("SELECT COUNT(*) FROM user_stats WHERE subscribed_at>=?", (ts_today_start,)).fetchone()[0]
        sub_yesterday         = c.execute("SELECT COUNT(*) FROM user_stats WHERE subscribed_at>=? AND subscribed_at<?", (ts_yest_start, ts_today_start)).fetchone()[0]
        sub_month             = c.execute("SELECT COUNT(*) FROM user_stats WHERE subscribed_at>=?", (ts_month_start,)).fetchone()[0]

        # ── البوت ────────────────────────────────────────
        total_btns = c.execute("SELECT COUNT(*) FROM buttons").fetchone()[0]
        menus      = c.execute("SELECT COUNT(*) FROM buttons WHERE type='menu'").fetchone()[0]
        content    = c.execute("SELECT COUNT(*) FROM buttons WHERE type='content'").fetchone()[0]
        admins     = c.execute("SELECT COUNT(*) FROM admins").fetchone()[0]

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
        f"  └ حجم قاعدة البيانات: `{db_size_kb} KB`"
    )

def get_trending_page(page: int, page_size: int = 10):
    """يُرجع (قائمة الأزرار, إجمالي العدد) لصفحة معينة مرتّبة بالأكثر طلباً."""
    offset = page * page_size
    rows = db().execute(
        "SELECT id, label, click_count FROM buttons WHERE type='content' AND COALESCE(click_count,0)>0 "
        "ORDER BY click_count DESC LIMIT ? OFFSET ?",
        (page_size, offset)
    ).fetchall()
    total = db().execute(
        "SELECT COUNT(*) FROM buttons WHERE type='content' AND COALESCE(click_count,0)>0"
    ).fetchone()[0]
    return [dict(r) for r in rows], total

_TYPE_ICON = {"text": "📝", "photo": "🖼", "video": "🎬", "file": "📁", "audio": "🎵"}

def _content_summary(bid) -> str:
    """يُرجع ملخص أنواع المحتوى داخل الزر مثل: 🖼×2 🎬×1"""
    rows = db().execute(
        "SELECT type, COUNT(*) as cnt FROM content_items WHERE button_id=? GROUP BY type", (bid,)
    ).fetchall()
    if not rows:
        return "📭"
    parts = []
    for r in rows:
        icon = _TYPE_ICON.get(r["type"], "📄")
        cnt = r["cnt"]
        parts.append(f"{icon}×{cnt}" if cnt > 1 else icon)
    return " ".join(parts)

def build_trending_text(page: int, page_size: int = 10) -> tuple:
    """يبني النص ولوحة التنقل للترند. يُرجع (text, markup)."""
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

def kb_confirm_delete(bid):
    b = get_btn(bid)
    pid = b["parent_id"] if b else None
    back_cb = "m_r" if pid is None else f"m_{pid}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ موافق", callback_data=f"x_{bid}"),
        InlineKeyboardButton("❌ إلغاء", callback_data=back_cb),
    ]])


# ── مساعد اللوحة الثابتة ─────────────────────────────────────────
async def set_panel(ctx, chat_id, text, markup=None):
    msg = await ctx.bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")
    ctx.user_data["panel_id"] = msg.message_id

# ── إذاعة رسالة لجميع المستخدمين ────────────────────────────────
async def do_broadcast(bot, from_chat_id: int, msg_id: int) -> tuple:
    """ينسخ الرسالة msg_id من from_chat_id إلى جميع المستخدمين. يُرجع (نجح, فشل)."""
    import asyncio
    user_ids = [r[0] for r in db().execute("SELECT user_id FROM user_stats").fetchall()]
    success = 0
    failed  = 0
    for uid in user_ids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=msg_id)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # تجنب flood limits
    return success, failed

# ── إعادة إرسال نافذة التنبيه المعلقة (دون تحديث العداد) ─────────
async def resend_notif_gate(target, uid, bid):
    msg         = get_setting("notif_message", "🔔 يرجى الاشتراك في قناتنا!")
    chan        = get_setting("notif_channel", "").strip()
    ok_text     = get_setting("notif_ok_text",    "✅ نعم، اشتركت")
    cancel_text = get_setting("notif_cancel_text", "❌ لا، لاحقاً")

    rows = []
    if chan:
        url = chan if chan.startswith("http") else f"https://t.me/{chan.lstrip('@')}"
        rows.append([InlineKeyboardButton("📢 انضم للقناة الآن", url=url)])
    rows.append([
        InlineKeyboardButton(ok_text,     callback_data=f"notif_ok_{bid}"),
        InlineKeyboardButton(cancel_text, callback_data=f"notif_skip_{bid}"),
    ])
    markup = InlineKeyboardMarkup(rows)
    try:
        try:
            await target.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            await target.reply_text(msg, reply_markup=markup)
    except Exception:
        pass

# ── عرض عناصر المحتوى للمستخدم ───────────────────────────────────
async def send_items(m, bid, uid=None, bot=None):
    if uid and not is_admin(uid):
        # النظام 1: هل هناك تنبيه منبثق معلق؟
        pending_bid = get_pending_notif(uid)
        if pending_bid:
            await resend_notif_gate(m, uid, pending_bid)
            return

        # فحص الاشتراك في القناة (مرة واحدة فقط)
        # True = مشترك | False = غير مشترك | None = تعذّر الفحص
        subscribed = await is_subscribed(bot, uid) if bot else None

        # النظام 1: تحديث العداد وفحص قبل إرسال المحتوى (فقط إذا تأكدنا أنه غير مشترك)
        if subscribed is False:
            inc_user_opens(uid)
            if should_notify(uid):
                await send_notif_gate(m, uid, bid)
                return  # حجب المحتوى عند ظهور التنبيه المنبثق

    items = get_items(bid)
    if not items:
        await m.reply_text("📭 لا يوجد محتوى بعد.")
        return
    if uid and not is_admin(uid):
        inc_click_count(bid, uid)
    b = get_btn(bid)
    no_cap = (b.get("no_caption", 0) or 0) if b else 0
    extra_cap = get_global_caption() if not no_cap else ""
    no_btn_cap = (b.get("no_btn_caption", 0) or 0) if b else 0
    cap_btns = get_caption_buttons() if not no_btn_cap else []
    link_markup = build_caption_btn_markup(cap_btns)
    for item in items:
        await send_file_item(m, item, extra_caption=extra_cap, reply_markup=link_markup)

    # إرسال عبارة تحفيزية عشوائية بعد المحتوى (للمستخدمين فقط)
    if uid and not is_admin(uid):
        phrase = get_random_phrase()
        if phrase:
            try:
                await m.reply_text(phrase, message_effect_id="5046509860389126442")
            except Exception:
                await m.reply_text(phrase)

# ── /start ────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx):
    uid = update.effective_user.id
    ctx.user_data.clear()
    kb = build_kb(uid)
    if not kb:
        await update.message.reply_text("👋 أهلاً! لا توجد أزرار متاحة حالياً.")
        return
    await update.message.reply_text("👋 أهلاً!", reply_markup=kb)
    if not is_admin(uid):
        inc_user_sessions(uid)

async def cmd_myid(update: Update, ctx):
    await update.message.reply_text(f"🆔 `{update.effective_user.id}`", parse_mode="Markdown")

# ── معالج الرسائل الرئيسي ─────────────────────────────────────────
async def on_message(update: Update, ctx):
    m = update.message
    uid = update.effective_user.id
    text = (m.text or "").strip()
    state = ctx.user_data.get("state")
    pid = ctx.user_data.get("pid")
    chat_id = m.chat_id

    track_message(uid)

    # ── انتظار اسم الزر ───────────────────────────────────────────
    if state == "wait_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للاسم."); return
        t = ctx.user_data.get("new_type"); add_pid = ctx.user_data.get("add_pid")
        add_after   = ctx.user_data.get("add_after", "END")
        add_new_row = ctx.user_data.get("add_new_row", 0)
        add_before  = ctx.user_data.get("add_before")
        if add_before is not None:
            bid = add_btn_before(add_before, add_pid, t, text)
        elif add_after != "END":
            bid = add_btn_after(add_after, add_pid, t, text, new_row=add_new_row)
        else:
            bid = add_btn(add_pid, t, text)
        ctx.user_data.pop("state", None); ctx.user_data.pop("new_type", None)
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_pid", None)
        ctx.user_data.pop("add_new_row", None); ctx.user_data.pop("add_before", None)
        ctx.user_data["pid"] = add_pid
        await m.reply_text(f"✅ تم إنشاء *{text}*", parse_mode="Markdown",
                           reply_markup=build_kb(uid, add_pid))
        if t == "content":
            await set_panel(ctx, chat_id,
                            f"📄 *{text}*\n\nلا يوجد محتوى بعد. اضغط ➕ لإضافة محتوى.",
                            kb_content_panel(bid))
        return

    # ── انتظار محتوى جديد لزر موجود ──────────────────────────────
    if state == "wait_item_content":
        bid = ctx.user_data.get("item_bid")
        t, content, fid = detect_content(m)
        if t is None:
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً أو فيديو أو صوتاً."); return
        if t == "text" and text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        lpath = None
        if fid:
            lpath = await download_and_save(ctx.bot, fid, t)
        add_item(bid, t, content, fid, lpath)
        ctx.user_data.pop("state", None); ctx.user_data.pop("item_bid", None)
        b = get_btn(bid)
        items = get_items(bid)
        await set_panel(ctx, chat_id,
                        f"📄 *{b['label']}*\n_{len(items)} عنصر_",
                        kb_content_panel(bid))
        await m.reply_text("✅ تمت الإضافة.", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار وصف جديد لعنصر محتوى ─────────────────────────────
    if state == "wait_item_desc":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً للوصف."); return
        iid = ctx.user_data.get("item_iid")
        msg_id = ctx.user_data.get("item_msg_id")
        upd_item_content(iid, m.text)
        ctx.user_data.pop("state", None)
        ctx.user_data.pop("item_iid", None)
        ctx.user_data.pop("item_msg_id", None)
        if msg_id:
            try:
                await ctx.bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id,
                                                        reply_markup=kb_item_actions(iid))
            except Exception:
                pass
        await m.reply_text("✅ تم تحديث الوصف.", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار نص الكليشة الثابتة ────────────────────────────────
    if state == "wait_caption_text":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للكليشة."); return
        set_setting("global_caption", m.text)
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id,
                        f"✅ تم حفظ الكليشة الثابتة:\n\n{m.text}\n\n⚙️ *الاعدادات*",
                        kb_settings())
        await m.reply_text("✅ تم حفظ الكليشة.", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار اسم زر الرابط ────────────────────────────────────
    if state == "wait_capbtn_label":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً لاسم الزر."); return
        ctx.user_data["capbtn_label"] = m.text
        ctx.user_data["state"] = "wait_capbtn_url"
        await m.reply_text(
            f"✅ الاسم: *{m.text}*\n\nالآن أرسل *رابط* الزر (يبدأ بـ https://):",
            parse_mode="Markdown"
        )
        return

    # ── انتظار رابط زر الكليشة ──────────────────────────────────
    if state == "wait_capbtn_url":
        if not m.text or not (m.text.startswith("http://") or m.text.startswith("https://")):
            await m.reply_text("⚠️ أرسل رابطاً صحيحاً يبدأ بـ https://"); return
        label = ctx.user_data.pop("capbtn_label", "زر")
        add_caption_button(label, m.text)
        ctx.user_data.pop("state", None)
        btns = get_caption_buttons()
        await set_panel(ctx, chat_id,
                        f"🔗 *كليشة الأزرار* — {len(btns)} زر",
                        kb_caption_btn_settings())
        await m.reply_text(f"✅ تمت إضافة الزر: *{label}*", parse_mode="Markdown",
                           reply_markup=build_kb(uid, pid))
        return

    # ── انتظار نص رسالة الاشتراك (النظام 1) ─────────────────────
    if state == "wait_notif_msg":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للرسالة."); return
        set_setting("notif_message", m.text)
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "📢 *رسالة الاشتراك*", kb_notif1_settings())
        await m.reply_text("✅ تم حفظ نص رسالة الاشتراك.", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار رابط قناة التنبيه ─────────────────────────────────
    if state == "wait_notif_chan":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل يوزرنيم القناة أو رابطها."); return
        chan = m.text.strip()
        set_setting("notif_channel", chan)
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "📢 *رسالة الاشتراك*", kb_notif1_settings())
        await m.reply_text(f"✅ تم حفظ القناة: `{chan}`", parse_mode="Markdown",
                           reply_markup=build_kb(uid, pid))
        return

    # ── انتظار عدد الضغطات قبل رسالة الاشتراك (النظام 1) ────────────────
    if state == "wait_notif_opens":
        try:
            val = int(m.text.strip())
            if val < 0: raise ValueError
        except (ValueError, AttributeError):
            await m.reply_text("⚠️ أرسل رقماً صحيحاً (0 أو أكثر)."); return
        set_setting("notif_every_opens", str(val))
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "📢 *رسالة الاشتراك*", kb_notif1_settings())
        lbl = f"كل {val} ضغطة" if val > 0 else "مُعطَّل"
        await m.reply_text(f"✅ تم الضبط: {lbl}", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار فترية الجلسات ─────────────────────────────────────
    if state == "wait_notif_sessions":
        try:
            val = int(m.text.strip())
            if val < 0: raise ValueError
        except (ValueError, AttributeError):
            await m.reply_text("⚠️ أرسل رقماً صحيحاً (0 أو أكثر)."); return
        set_setting("notif_every_sessions", str(val))
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "🔔 *التنبيه المنبثق*", kb_notif1_settings())
        lbl = f"كل {val} جلسات" if val > 0 else "مُعطَّل"
        await m.reply_text(f"✅ تم الضبط: {lbl}", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار نص زر "نعم" ───────────────────────────────────────
    if state == "wait_notif_ok_text":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        set_setting("notif_ok_text", m.text.strip())
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "📢 *رسالة الاشتراك*", kb_notif1_settings())
        await m.reply_text(f"✅ تم حفظ نص زر \"نعم\": {m.text.strip()}", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار نص زر "لا" ────────────────────────────────────────
    if state == "wait_notif_cancel_text":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        set_setting("notif_cancel_text", m.text.strip())
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "📢 *رسالة الاشتراك*", kb_notif1_settings())
        await m.reply_text(f"✅ تم حفظ نص زر \"لا\": {m.text.strip()}", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار ملف الاستعادة ─────────────────────────────────────
    if state == "wait_restore_zip":
        if not m.document:
            await m.reply_text("⚠️ أرسل ملف ZIP فقط.")
            return
        ctx.user_data.pop("state", None)
        wait_msg = await m.reply_text("⏳ جاري تحميل الملف وتطبيق الاستعادة...")
        zip_tmp = f"/tmp/restore_{m.document.file_unique_id}.zip"
        try:
            tg_file = await ctx.bot.get_file(m.document.file_id)
            await tg_file.download_to_drive(zip_tmp)
            ok, msg = await restore_backup(zip_tmp)
            await wait_msg.edit_text(msg)
        except Exception as e:
            await wait_msg.edit_text(f"❌ فشل التحميل أو الاستعادة: {e}")
        finally:
            if os.path.exists(zip_tmp):
                os.remove(zip_tmp)
        return

    # ── انتظار رسالة الإذاعة ─────────────────────────────────────
    if state == "wait_broadcast_msg":
        ctx.user_data.pop("state", None)
        ctx.user_data["broadcast_from"] = chat_id
        ctx.user_data["broadcast_mid"]  = m.message_id
        total = db().execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
        await m.reply_text(
            f"📡 *معاينة الإذاعة*\n\nسيتم إرسال هذه الرسالة إلى *{total}* مستخدم.\n\n"
            "هل تريد المتابعة؟",
            parse_mode="Markdown",
            reply_markup=kb_broadcast_confirm()
        )
        return

    # ── انتظار نص عبارة تحفيزية جديدة ──────────────────────────────
    if state == "wait_phrase_text":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً للعبارة."); return
        add_phrase(m.text.strip())
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id,
                        f"✅ تمت إضافة العبارة.\n\n💬 *العبارات التحفيزية* ({len(get_phrases())})",
                        kb_phrases())
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار اسم الزر الخاص (إنشاء أو تغيير) ──────────────────────
    if state == "wait_special_name":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للاسم."); return
        sp = get_special_btn()
        if sp:
            upd_btn_label(sp["id"], m.text.strip())
            msg = f"✅ تم تغيير اسم الزر الخاص إلى «{m.text.strip()}»"
        else:
            create_special_btn(m.text.strip())
            msg = f"✅ تم إنشاء الزر الخاص «{m.text.strip()}» في القائمة الرئيسية"
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, f"{msg}\n\n⭐ *الزر الخاص*", kb_special_settings())
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار نسبة العبارات التحفيزية ──────────────────────────────
    if state == "wait_phrases_chance":
        try:
            val = int((m.text or "").strip())
            if not 0 <= val <= 100:
                raise ValueError
        except ValueError:
            await m.reply_text("⚠️ أرسل رقماً بين 0 و 100."); return
        set_setting("phrases_chance", str(val))
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id,
                        f"✅ تم ضبط النسبة على *{val}%*\n\n💬 *العبارات التحفيزية*",
                        kb_phrases())
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار اسم جديد للتعديل ───────────────────────────────────
    if state == "wait_edit_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        bid = ctx.user_data.get("edit_bid"); upd_btn_label(bid, text)
        b = get_btn(bid); ctx.user_data.pop("state", None)
        if b and b["type"] == "content":
            await set_panel(ctx, chat_id, f"📄 *{text}*", kb_content_panel(bid))
        await m.reply_text("✅ تم تغيير الاسم.", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار رقم المشرف ─────────────────────────────────────────
    if state == "wait_admin_id":
        try: tid = int(text)
        except ValueError: await m.reply_text("⚠️ أرسل رقم ID صحيح."); return
        add_admin(tid); ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, f"👥 *المشرفون* ({len(all_admins())}):", kb_admins_inline())
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── تحليل صورة بالذكاء الاصطناعي (للمشرفين فقط) ─────────────
    if not state and m.photo and is_admin(uid):
        import re
        caption = (m.caption or "").strip()
        if caption.startswith("."):
            caption_body = caption[1:].strip()
            if "قائمة" in caption_body:
                btn_type = "menu"
            elif "محتوى" in caption_body:
                btn_type = "content"
            else:
                btn_type = None
            if btn_type:
                page_match = re.search(
                    r'صورة\s*(\d+|واحد[ة]?|اثنت?ين|ثلاث[ة]?|اربع[ة]?|خمس[ة]?|ست[ة]?|سبع[ة]?|ثمان[ي]?[ة]?|تسع[ة]?|عشر[ة]?)',
                    caption_body
                )
                page_words = {"واحد":1,"واحدة":1,"اثنين":2,"اثنتين":2,"ثلاثة":3,"ثلاث":3,
                              "اربعة":4,"اربع":4,"خمسة":5,"خمس":5,"ستة":6,"ست":6,
                              "سبعة":7,"سبع":7,"ثمانية":8,"ثماني":8,"تسعة":9,"تسع":9,"عشرة":10,"عشر":10}
                wait_msg = await m.reply_text("⏳ جاري تحميل الصورة...")
                try:
                    img_data, mime = await _download_image_base64(ctx.bot, m.photo[-1].file_id)
                except Exception as e:
                    await wait_msg.edit_text(f"❌ فشل تحميل الصورة: {e}"); return
                if page_match:
                    pg_str = page_match.group(1)
                    page_num = int(pg_str) if pg_str.isdigit() else page_words.get(pg_str, 1)
                    batch = ctx.user_data.get("img_batch", [])
                    batch = [b for b in batch if b["page"] != page_num]
                    batch.append({"data": img_data, "mime": mime, "page": page_num, "type": btn_type})
                    batch.sort(key=lambda x: x["page"])
                    ctx.user_data["img_batch"] = batch
                    await wait_msg.edit_text(
                        f"✅ تم حفظ صورة {page_num} ({len(batch)} صورة مخزنة).\n"
                        f"أرسل بقية الصور أو اكتب: *. تطبيق* لإضافة الأزرار.",
                        parse_mode="Markdown"
                    )
                else:
                    batch = ctx.user_data.pop("img_batch", [])
                    batch.append({"data": img_data, "mime": mime, "page": len(batch)+1, "type": btn_type})
                    batch.sort(key=lambda x: x["page"])
                    await wait_msg.edit_text("⏳ جاري تحليل الصورة...")
                    await _process_image_batch(wait_msg, m, ctx, uid, pid, batch, btn_type)
                return

    # ── إشارة النقطة للذكاء الاصطناعي (للمشرفين فقط) ────────────
    if not state and text.startswith(".") and is_admin(uid):
        request_text = text[1:].strip()
        if not request_text:
            await m.reply_text("💡 اكتب طلبك بعد النقطة. مثال:\n. أضف أزرار: خدماتنا، من نحن، تواصل معنا")
            return
        if not GEMINI_KEYS:
            await m.reply_text("❌ لم يُعَيَّن أي مفتاح Gemini API.")
            return
        # ── تطبيق الصور المخزنة ───────────────────────────────────
        if request_text in ("تطبيق", "تطبيق الصور"):
            batch = ctx.user_data.pop("img_batch", [])
            if not batch:
                await m.reply_text("⚠️ لا توجد صور مخزنة. أرسل صوراً مرقّمة أولاً."); return
            wait_msg = await m.reply_text(f"⏳ جاري تحليل {len(batch)} صورة...")
            btn_type = batch[0].get("type", "menu")
            await _process_image_batch(wait_msg, m, ctx, uid, pid, batch, btn_type); return
        # ── إلغاء الصور المخزنة ───────────────────────────────────
        if request_text in ("إلغاء الصور", "الغاء الصور", "حذف الصور"):
            ctx.user_data.pop("img_batch", None)
            await m.reply_text("✅ تم مسح الصور المخزنة."); return
        wait_msg = await m.reply_text("⏳ جاري التواصل مع الذكاء الاصطناعي...")
        current_btns = get_buttons(pid)
        action, operations, del_idx, error = await process_ai_request(request_text, current_btns)
        if error:
            await wait_msg.edit_text(error)
            return

        result_lines = []

        # ── تنفيذ الحذف ───────────────────────────────────────────
        if action in ("delete_all", "delete_some", "delete_then_add"):
            if action == "delete_all":
                to_delete = [b["id"] for b in current_btns]
            else:
                to_delete = [current_btns[i]["id"] for i in del_idx
                             if isinstance(i, int) and 0 <= i < len(current_btns)]
            for bid in to_delete:
                del_btn(bid)
            if to_delete:
                result_lines.append(f"🗑 تم حذف {len(to_delete)} زر")
            current_btns = get_buttons(pid)   # تحديث القائمة بعد الحذف

        # ── تنفيذ الإضافة (عمليات متعددة) ────────────────────────
        if action in ("add", "delete_then_add") and operations:
            # نحفظ نسخة من الأزرار قبل أي تعديل لضمان صحة الفهارس
            original_btns = list(current_btns)
            all_added = []
            for op in operations:
                insert  = op.get("insert", -1)
                buttons = op.get("buttons", [])
                if not buttons:
                    continue
                if insert == "start":
                    anchor_id = None
                    use_after = True
                elif isinstance(insert, int) and 0 <= insert < len(original_btns):
                    anchor_id = original_btns[insert]["id"]
                    use_after = True
                else:
                    anchor_id = None
                    use_after = False
                created = _create_nested_buttons(pid, buttons, anchor_id=anchor_id, use_after=use_after)
                all_added.extend(created)
            if all_added:
                result_lines.append(f"✅ تمت إضافة {len(all_added)} زر:\n" +
                                    "\n".join(f"  • {a}" for a in all_added))

        if not result_lines:
            await wait_msg.edit_text("⚠️ لم يتم تنفيذ أي عملية.")
            return
        await wait_msg.edit_text("\n\n".join(result_lines), parse_mode="Markdown")
        await m.reply_text("🔄", reply_markup=build_kb(uid, pid))
        return


    # ── كليشة "اضف" لإضافة أزرار بتنسيق سريع ────────────────────
    if not state and text.startswith("اضف") and is_admin(uid):
        body = text[len("اضف"):].strip()
        if not body:
            await m.reply_text(
                "💡 اكتب الأزرار بعد كلمة *اضف*، مثال:\n"
                "```\n"
                "اضف\n"
                "زر 1 | زر 2\n"
                "زر 3\n"
                "```\n"
                "الفاصلة | تضع الأزرار جنب بعض في نفس السطر.",
                parse_mode="Markdown"
            )
            return
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        if not lines:
            await m.reply_text("⚠️ لم يتم العثور على أزرار.")
            return
        ctx.user_data["quick_add_lines"] = lines
        ctx.user_data["quick_add_pid"] = pid
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📂 قائمة", callback_data="qa_menu"),
            InlineKeyboardButton("📄 محتوى", callback_data="qa_content"),
        ]])
        preview = "\n".join(
            " | ".join(p.strip() for p in l.split("|") if p.strip()) for l in lines
        )
        await m.reply_text(
            f"📋 *الأزرار المراد إضافتها:*\n`{preview}`\n\nما نوع الأزرار؟",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    # ── إلغاء ─────────────────────────────────────────────────────
    if text == BTN_CANCEL:
        ctx.user_data.pop("state", None)
        await m.reply_text("✅ تم الإلغاء.", reply_markup=build_kb(uid, pid))
        return

    # ── رجوع ──────────────────────────────────────────────────────
    if text == BTN_BACK:
        if pid is not None:
            b = get_btn(pid); new_pid = b["parent_id"] if b else None
            ctx.user_data["pid"] = new_pid
            await m.reply_text(".", reply_markup=build_kb(uid, new_pid))
        else:
            ctx.user_data["pid"] = None
            await m.reply_text(".", reply_markup=build_kb(uid, None))
        return

    # ── نسخة احتياطية يدوية ───────────────────────────────────────
    if not state and text == "نسخة احتياطية" and is_admin(uid):
        await m.reply_text("⏳ جاري إنشاء النسخة الاحتياطية...")
        await send_backup(ctx.bot, uid)
        return

    # ── حذف الكل ──────────────────────────────────────────────────
    if not state and text == "حذف الكل" and is_admin(uid):
        btns = get_buttons(pid)
        if not btns:
            await m.reply_text("⚠️ لا توجد أزرار في هذه القائمة.")
            return
        level_name = "القائمة الرئيسية" if pid is None else (get_btn(pid) or {}).get("label", "القائمة الحالية")
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=f"delall_{pid if pid is not None else 'r'}"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel"),
        ]])
        await m.reply_text(
            f"⚠️ هل تريد حذف جميع الأزرار ({len(btns)}) في *{level_name}*؟",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    # ── أزرار المشرف ──────────────────────────────────────────────
    if is_admin(uid):
        if text == BTN_ADD:
            ctx.user_data["add_pid"] = pid
            ctx.user_data.pop("add_after", None)
            ctx.user_data.pop("add_new_row", None)
            ctx.user_data.pop("add_before", None)
            where_kb = kb_add_where(pid)
            if where_kb:
                await set_panel(ctx, chat_id, "⬆️⬇️ أين تريد إضافة الزر الجديد؟", where_kb)
            else:
                await set_panel(ctx, chat_id, "اختر نوع الزر الجديد:", kb_add_type())
            return
        if text.startswith(BTN_PLUS):
            after_bid = _parse_plus(text)
            if after_bid is not None:
                b = get_btn(after_bid)
                ctx.user_data["add_pid"] = b["parent_id"] if b else pid
                await set_panel(ctx, chat_id, "أين تريد إضافة الزر الجديد؟", kb_add_position(after_bid))
            else:
                ctx.user_data["add_pid"] = pid
                ctx.user_data.pop("add_after", None)
                await set_panel(ctx, chat_id, "اختر نوع الزر الجديد:", kb_add_type())
            return
        if text == BTN_SWAP:
            btns = get_buttons(pid)
            if len(btns) < 2:
                await m.reply_text("⚠️ يجب أن يكون هناك زران على الأقل للتبديل.")
            else:
                await set_panel(ctx, chat_id, "🔀 *اختر الزر الأول:*", kb_swap_select(pid))
            return
        if text == BTN_SETTINGS:
            await set_panel(ctx, chat_id, "⚙️ *الاعدادات*", kb_settings())
            return

    # ── ضغط زر من القائمة ─────────────────────────────────────────
    btns = get_buttons(pid)
    matched = next((b for b in btns if b['label'] == text), None)
    if not matched:
        # البوت أُعيد تشغيله وضاع الموقع، نبحث في كل الأزرار
        all_btns = [dict(r) for r in db().execute(
            "SELECT * FROM buttons WHERE label=?", (text,)).fetchall()]
        if all_btns:
            matched = all_btns[0]
            ctx.user_data["pid"] = matched.get("parent_id")
        else:
            return

    b = matched
    if b["type"] == "menu":
        ctx.user_data["pid"] = b["id"]
        await m.reply_text(".", reply_markup=build_kb(uid, b["id"]))
        if is_admin(uid):
            await set_panel(ctx, chat_id, f"📂 *{b['label']}*", kb_menu_quick(b["id"]))

    elif b["type"] == "content":
        if is_admin(uid):
            items = get_items(b["id"])
            await set_panel(ctx, chat_id,
                            f"📄 *{b['label']}*\n_{len(items)} عنصر_",
                            kb_content_quick(b["id"]))
        else:
            await send_items(m, b["id"], uid=uid, bot=ctx.bot)

    elif b["type"] == "special":
        if is_admin(uid):
            await set_panel(ctx, chat_id, f"⭐ *الزر الخاص — {b['label']}*", kb_special_settings())
        # سلوك المستخدم سيُحدَّد لاحقاً

# ── معالج أزرار Inline ────────────────────────────────────────────
async def cb_manage(update: Update, ctx):
    q = update.callback_query
    uid = q.from_user.id
    d = q.data

    # ── معالجة تنبيهات الاشتراك (لجميع المستخدمين) ───────────────
    if d.startswith("notif_ok_") or d.startswith("notif_skip_"):
        if d.startswith("notif_ok_"):
            # التحقق الفعلي من الاشتراك قبل السماح بالمتابعة
            # True=مشترك | False=غير مشترك | None=تعذّر الفحص (نعطي صلاحية المرور)
            sub_status = await is_subscribed(ctx.bot, uid)
            if sub_status is False:
                chan = get_setting("notif_channel", "").strip()
                ok_text     = get_setting("notif_ok_text",    "✅ نعم، اشتركت")
                cancel_text = get_setting("notif_cancel_text", "❌ لا، لاحقاً")
                bid_str = d[len("notif_ok_"):]
                rows = []
                if chan:
                    url = chan if chan.startswith("http") else f"https://t.me/{chan.lstrip('@')}"
                    rows.append([InlineKeyboardButton("📢 انضم للقناة الآن", url=url)])
                rows.append([
                    InlineKeyboardButton(ok_text,     callback_data=f"notif_ok_{bid_str}"),
                    InlineKeyboardButton(cancel_text, callback_data=f"notif_skip_{bid_str}"),
                ])
                try:
                    await q.answer("❌ لم يتم التحقق من اشتراكك، يرجى الانضمام للقناة أولاً!", show_alert=True)
                    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
                except Exception:
                    pass
                return
            # إما مشترك فعلاً أو تعذّر الفحص → نسمح بالمتابعة
            await q.answer()
            if sub_status is True:
                record_channel_subscription(uid)
            clear_pending_notif(uid)
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            try:
                await ctx.bot.send_message(
                    chat_id=q.message.chat_id,
                    text="✅ *شكراً لك!*\n\nيمكنك الآن الاستمرار في التصفح.",
                    parse_mode="Markdown",
                    api_kwargs={"message_effect_id": "5046509860389126442"}
                )
            except Exception:
                try:
                    await ctx.bot.send_message(
                        chat_id=q.message.chat_id,
                        text="✅ *شكراً لك!*\n\nيمكنك الآن الاستمرار في التصفح.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        else:
            await q.answer()
            clear_pending_notif(uid)
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            try:
                await ctx.bot.send_message(
                    chat_id=q.message.chat_id,
                    text="👌 *حسناً!*\n\nيمكنك الاستمرار في التصفح.",
                    parse_mode="Markdown",
                    api_kwargs={"message_effect_id": "5107584321108051014"}
                )
            except Exception:
                try:
                    await ctx.bot.send_message(
                        chat_id=q.message.chat_id,
                        text="👌 *حسناً!*\n\nيمكنك الاستمرار في التصفح.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        return

    await q.answer()
    if not is_admin(uid): return
    chat_id = q.message.chat_id
    ctx.user_data["panel_id"] = q.message.message_id
    pid = ctx.user_data.get("pid")

    if d == "noop": return

    if d == "cancel":
        ctx.user_data.pop("state", None)
        await q.edit_message_text("✅ تم الإلغاء."); return

    # ── لوحة الاعدادات ────────────────────────────────────────────
    if d == "st_admins":
        await q.edit_message_text(
            f"👥 *المشرفون* ({len(all_admins())}):",
            parse_mode="Markdown",
            reply_markup=kb_admins_inline()
        )
        return

    if d == "st_backup_menu":
        await q.edit_message_text("💾 *النسخ الاحتياطي*\n\nاختر العملية:", parse_mode="Markdown",
                                  reply_markup=kb_backup_menu())
        return

    if d == "st_backup_dl":
        await q.edit_message_text("⏳ جاري إنشاء النسخة الاحتياطية، يرجى الانتظار...")
        await send_backup(ctx.bot, q.from_user.id)
        try:
            await q.edit_message_text("💾 *النسخ الاحتياطي*\n\nاختر العملية:", parse_mode="Markdown",
                                      reply_markup=kb_backup_menu())
        except Exception:
            pass
        return

    if d == "st_restore":
        ctx.user_data["state"] = "wait_restore_zip"
        await q.edit_message_text(
            "📤 *رفع نسخة احتياطية*\n\nأرسل ملف ZIP الخاص بالنسخة الاحتياطية الآن.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
            ]])
        )
        return

    if d == "st_stats":
        await q.edit_message_text(get_stats(), parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("رجوع", callback_data="st_back")
                                  ]]))
        return

    if d.startswith("st_trending_"):
        page = int(d[len("st_trending_"):])
        text, markup = build_trending_text(page)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return

    if d == "st_back":
        await q.edit_message_text("⚙️ *الاعدادات*", parse_mode="Markdown",
                                  reply_markup=kb_settings())
        return

    if d == "st_broadcast":
        total = db().execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
        await q.edit_message_text(
            f"📡 *الإذاعة*\n\nعدد المستخدمين: *{total}*\n\n"
            "اضغط الزر أدناه وأرسل الرسالة التي تريد بثها (نص، صورة، فيديو، ملف…).",
            parse_mode="Markdown",
            reply_markup=kb_broadcast()
        )
        return

    if d == "st_broadcast_send":
        ctx.user_data["state"] = "wait_broadcast_msg"
        await q.edit_message_text(
            "📩 أرسل الرسالة التي تريد إذاعتها الآن:\n_(نص أو صورة أو فيديو أو ملف)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="st_broadcast")
            ]])
        )
        return

    if d == "st_broadcast_confirm":
        from_chat = ctx.user_data.pop("broadcast_from", None)
        mid       = ctx.user_data.pop("broadcast_mid",  None)
        if not from_chat or not mid:
            await q.edit_message_text("⚠️ انتهت صلاحية الإذاعة، أعد المحاولة.",
                                      reply_markup=kb_broadcast())
            return
        await q.edit_message_text("⏳ جاري الإرسال…")
        success, failed = await do_broadcast(ctx.bot, from_chat, mid)
        await q.edit_message_text(
            f"📡 *انتهت الإذاعة*\n\n"
            f"✅ نجح: *{success}*\n"
            f"❌ فشل: *{failed}*\n"
            f"📊 المجموع: *{success + failed}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("رجوع للإعدادات", callback_data="st_back")
            ]])
        )
        return

    # ── العبارات التحفيزية ────────────────────────────────────────
    if d == "st_phrases":
        phrases = get_phrases()
        count   = len(phrases)
        chance  = get_phrases_chance()
        header  = (
            f"💬 *العبارات التحفيزية* — {count} عبارة\n"
            f"🎲 نسبة الظهور: *{chance}%*\n\n"
            "اضغط على عبارة لحذفها، أو أضف عبارة جديدة."
        ) if count else (
            f"💬 *العبارات التحفيزية*\n🎲 نسبة الظهور: *{chance}%*\n\nلا توجد عبارات بعد."
        )
        await q.edit_message_text(header, parse_mode="Markdown", reply_markup=kb_phrases())
        return

    if d == "st_phrase_add":
        ctx.user_data["state"] = "wait_phrase_text"
        await q.edit_message_text(
            "✏️ أرسل نص العبارة التحفيزية الجديدة:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="st_phrases")
            ]])
        )
        return

    if d.startswith("st_phrase_del_"):
        pid_del = int(d[len("st_phrase_del_"):])
        del_phrase(pid_del)
        phrases = get_phrases()
        count   = len(phrases)
        chance  = get_phrases_chance()
        header  = (
            f"💬 *العبارات التحفيزية* — {count} عبارة\n"
            f"🎲 نسبة الظهور: *{chance}%*\n\n"
            "✅ تم حذف العبارة."
        )
        await q.edit_message_text(header, parse_mode="Markdown", reply_markup=kb_phrases())
        return

    if d == "st_phrase_chance":
        chance = get_phrases_chance()
        ctx.user_data["state"] = "wait_phrases_chance"
        await q.edit_message_text(
            f"🎲 *نسبة ظهور العبارة التحفيزية*\n\nالنسبة الحالية: *{chance}%*\n\n"
            "أرسل رقماً بين 0 و 100:\n"
            "_0 = معطّلة، 100 = تظهر مع كل محتوى_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="st_phrases")
            ]])
        )
        return

    # ── الزر الخاص ───────────────────────────────────────────────────
    if d == "st_special":
        sp = get_special_btn()
        if sp:
            pid_info = "القائمة الرئيسية" if sp.get("parent_id") is None else (
                (get_btn(sp["parent_id"]) or {}).get("label", "—"))
            header = f"⭐ *الزر الخاص*\n\nالاسم الحالي: *{sp['label']}*\nالموضع: _{pid_info}_"
        else:
            header = "⭐ *الزر الخاص*\n\nلا يوجد زر خاص بعد."
        await q.edit_message_text(header, parse_mode="Markdown", reply_markup=kb_special_settings())
        return

    if d == "st_special_create":
        if get_special_btn():
            await q.answer("⚠️ يوجد زر خاص بالفعل.", show_alert=True); return
        ctx.user_data["state"] = "wait_special_name"
        await q.edit_message_text(
            "⭐ أرسل اسم الزر الخاص الجديد:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="st_special")]])
        )
        return

    if d == "st_special_rename":
        sp = get_special_btn()
        if not sp:
            await q.answer("⚠️ لا يوجد زر خاص.", show_alert=True); return
        ctx.user_data["state"] = "wait_special_name"
        await q.edit_message_text(
            f"✏️ الاسم الحالي: *{sp['label']}*\n\nأرسل الاسم الجديد للزر الخاص:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="st_special")]])
        )
        return

    if d == "st_special_move":
        sp = get_special_btn()
        if not sp:
            await q.answer("⚠️ لا يوجد زر خاص.", show_alert=True); return
        await q.edit_message_text(
            "🔀 *اختر المستوى الذي تريد نقل الزر الخاص إليه:*\n_(سيُضاف في نهاية المستوى المختار)_",
            parse_mode="Markdown",
            reply_markup=kb_special_move_picker()
        )
        return

    if d.startswith("st_special_moveto_"):
        sp = get_special_btn()
        if not sp:
            await q.answer("⚠️ لا يوجد زر خاص.", show_alert=True); return
        dest = d[len("st_special_moveto_"):]
        new_pid = None if dest == "root" else int(dest)
        if new_pid == sp["id"]:
            await q.answer("⚠️ لا يمكن نقل الزر داخل نفسه.", show_alert=True); return
        move_special_btn(sp["id"], new_pid)
        dest_name = "القائمة الرئيسية" if new_pid is None else (
            (get_btn(new_pid) or {}).get("label", "—"))
        await q.edit_message_text(
            f"✅ تم نقل الزر الخاص *{sp['label']}* إلى: _{dest_name}_",
            parse_mode="Markdown",
            reply_markup=kb_special_settings()
        )
        # نُحدِّث الكيبورد ليعكس الوضع الجديد عند المستوى الحالي
        cur_pid = ctx.user_data.get("pid")
        await q.message.reply_text("🔄", reply_markup=build_kb(uid, cur_pid))
        return

    if d == "st_special_del":
        sp = get_special_btn()
        if not sp:
            await q.answer("⚠️ لا يوجد زر خاص.", show_alert=True); return
        await q.edit_message_text(
            f"⚠️ هل تريد حذف الزر الخاص *{sp['label']}* نهائياً؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 نعم، احذفه", callback_data="st_special_del_confirm"),
                InlineKeyboardButton("❌ إلغاء",       callback_data="st_special"),
            ]])
        )
        return

    if d == "st_special_del_confirm":
        sp = get_special_btn()
        if sp:
            del_btn(sp["id"])
        await q.edit_message_text("✅ تم حذف الزر الخاص.", reply_markup=kb_special_settings())
        return

    if d == "st_caption":
        global_cap = get_global_caption()
        if global_cap:
            cap_display = f"📌 *الكليشة الثابتة الحالية:*\n\n{global_cap}"
        else:
            cap_display = "📌 لا توجد كليشة ثابتة حالياً."
        await q.edit_message_text(cap_display, parse_mode="Markdown",
                                  reply_markup=kb_caption_settings())
        return

    if d == "st_caption_set":
        ctx.user_data["state"] = "wait_caption_text"
        await q.edit_message_text(
            "✏️ أرسل نص الكليشة الثابتة التي تريد إضافتها لكل محتوى:",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "st_caption_clear":
        set_setting("global_caption", "")
        await q.edit_message_text("✅ تم حذف الكليشة الثابتة.", parse_mode="Markdown",
                                  reply_markup=kb_settings())
        return

    if d.startswith("ci_toggle_cap_"):
        bid = int(d[14:])
        toggle_btn_no_caption(bid)
        b = get_btn(bid)
        items = get_items(bid)
        no_cap = (b.get("no_caption", 0) or 0) if b else 0
        status = "🚫 كليشة الكلام مُلغاة لهذا الزر" if no_cap else "✅ كليشة الكلام مفعّلة لهذا الزر"
        await q.edit_message_text(
            f"📄 *{b['label']}*\n_{len(items)} عنصر_\n\n{status}",
            parse_mode="Markdown",
            reply_markup=kb_content_panel(bid)
        )
        return

    if d == "st_capbtn":
        btns = get_caption_buttons()
        txt = f"🔗 *كليشة الأزرار* — {len(btns)} زر\n\nهذه الأزرار تظهر أسفل كل محتوى يُرسله البوت." if btns else "🔗 *كليشة الأزرار*\n\nلا توجد أزرار بعد. اضغط ➕ لإضافة زر رابط."
        await q.edit_message_text(txt, parse_mode="Markdown",
                                  reply_markup=kb_caption_btn_settings())
        return

    if d == "st_capbtn_add":
        ctx.user_data["state"] = "wait_capbtn_label"
        await q.edit_message_text(
            "🔗 *إضافة زر رابط*\n\nأرسل *اسم الزر* الذي سيظهر للمستخدمين:",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d.startswith("st_capbtn_del_"):
        cbid = int(d[14:])
        del_caption_button(cbid)
        btns = get_caption_buttons()
        txt = f"🔗 *كليشة الأزرار* — {len(btns)} زر" if btns else "🔗 *كليشة الأزرار*\n\nلا توجد أزرار بعد."
        await q.edit_message_text(txt, parse_mode="Markdown",
                                  reply_markup=kb_caption_btn_settings())
        return

    if d.startswith("ci_toggle_btn_cap_"):
        bid = int(d[18:])
        toggle_btn_no_btn_caption(bid)
        b = get_btn(bid)
        items = get_items(bid)
        no_btn_cap = (b.get("no_btn_caption", 0) or 0) if b else 0
        status = "🚫 كليشة الأزرار مُلغاة لهذا الزر" if no_btn_cap else "✅ كليشة الأزرار مفعّلة لهذا الزر"
        await q.edit_message_text(
            f"📄 *{b['label']}*\n_{len(items)} عنصر_\n\n{status}",
            parse_mode="Markdown",
            reply_markup=kb_content_panel(bid)
        )
        return

    # ── إعدادات النظام 1: رسالة الاشتراك ────────────────────────
    if d == "st_notif1":
        msg      = get_setting("notif_message", "")
        chan     = get_setting("notif_channel", "")
        on       = get_setting("notif_enabled", "1") == "1"
        every_op = get_setting("notif_every_opens", "5")
        status_txt  = "✅ مفعّلة" if on else "⭕ موقوفة"
        msg_preview = f"\n\n📝 *النص:*\n{msg}" if msg else "\n\n📝 لا يوجد نص بعد."
        chan_txt     = f"\n📢 القناة: `{chan}`" if chan else ""
        await q.edit_message_text(
            f"📢 *رسالة الاشتراك* — {status_txt}\n"
            f"📂 يظهر كل {every_op} ضغطة على محتوى"
            f"{chan_txt}{msg_preview}",
            parse_mode="Markdown",
            reply_markup=kb_notif1_settings()
        )
        return

    if d == "st_notif_toggle":
        cur = get_setting("notif_enabled", "1")
        set_setting("notif_enabled", "0" if cur == "1" else "1")
        await q.edit_message_text("📢 *رسالة الاشتراك*", parse_mode="Markdown",
                                  reply_markup=kb_notif1_settings())
        return

    if d == "st_notif_msg":
        ctx.user_data["state"] = "wait_notif_msg"
        await q.edit_message_text(
            "✏️ أرسل نص رسالة الاشتراك التي تظهر كل N ضغطة:\n\n"
            "_يمكنك استخدام إيموجي وتنسيق ماركداون_",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "st_notif_chan":
        ctx.user_data["state"] = "wait_notif_chan"
        await q.edit_message_text(
            "📢 أرسل *رابط القناة* أو *يوزرنيم* القناة (مثال: @mychannel أو https://t.me/mychannel):\n\n"
            "⚠️ _تأكد أن البوت مشرف في القناة حتى يتمكن من التحقق من الاشتراك._\n\n"
            "اضغط إلغاء لإزالة القناة الحالية.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 إزالة القناة", callback_data="st_notif_chan_clear"),
                InlineKeyboardButton("❌ إلغاء", callback_data="st_notif1"),
            ]])
        )
        return

    if d == "st_notif_chan_clear":
        set_setting("notif_channel", "")
        await q.edit_message_text("✅ تم إزالة رابط القناة.", parse_mode="Markdown",
                                  reply_markup=kb_notif1_settings())
        return

    if d == "st_notif_ok_text":
        ctx.user_data["state"] = "wait_notif_ok_text"
        cur = get_setting("notif_ok_text", "✅ نعم، اشتركت")
        await q.edit_message_text(
            f'✏️ *تعديل نص زر "نعم"*\n\nالنص الحالي: `{cur}`\n\nأرسل النص الجديد:',
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "st_notif_cancel_text":
        ctx.user_data["state"] = "wait_notif_cancel_text"
        cur = get_setting("notif_cancel_text", "❌ لا، لاحقاً")
        await q.edit_message_text(
            f'✏️ *تعديل نص زر "لا"*\n\nالنص الحالي: `{cur}`\n\nأرسل النص الجديد:',
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "st_notif_opens":
        ctx.user_data["state"] = "wait_notif_opens"
        every_op = get_setting("notif_every_opens", "5")
        await q.edit_message_text(
            f"📂 *عدد الضغطات قبل رسالة الاشتراك*\n\nالقيمة الحالية: *{every_op}* ضغطة\n\n"
            "أرسل رقماً لتحديد كم ضغطة على محتوى قبل ظهور رسالة الاشتراك.\n"
            "_أرسل 0 لتعطيل هذا الشرط_",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "st_notif_sessions":
        ctx.user_data["state"] = "wait_notif_sessions"
        every_ses = get_setting("notif_every_sessions", "3")
        await q.edit_message_text(
            f"🔄 *فترية الجلسات*\n\nالقيمة الحالية: *{every_ses}* جلسات\n\n"
            "أرسل رقماً لتحديد كم جلسة قبل ظهور التنبيه.\n"
            "_أرسل 0 لتعطيل هذا الشرط_",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    # ── حذف الكل ──────────────────────────────────────────────────
    if d.startswith("delall_"):
        pctx = d[7:]
        del_pid = None if pctx == "r" else int(pctx)
        btns = get_buttons(del_pid)
        count = len(btns)
        for b in btns:
            del_btn(b["id"])
        ctx.user_data["pid"] = del_pid
        level_name = "القائمة الرئيسية" if del_pid is None else (get_btn(del_pid) or {}).get("label", "القائمة الحالية")
        await q.edit_message_text(f"🗑 تم حذف {count} زر من *{level_name}*.", parse_mode="Markdown")
        await q.message.reply_text("🔄", reply_markup=build_kb(uid, del_pid))
        return

    # ── إضافة سريعة (اضف) ─────────────────────────────────────────
    if d in ("qa_menu", "qa_content"):
        btn_type = "menu" if d == "qa_menu" else "content"
        lines = ctx.user_data.pop("quick_add_lines", [])
        qa_pid = ctx.user_data.pop("quick_add_pid", pid)
        if not lines:
            await q.edit_message_text("⚠️ انتهت صلاحية الكليشة، أعد إرسالها.")
            return
        existing_btns = get_buttons(qa_pid)
        last_bid = existing_btns[-1]["id"] if existing_btns else None
        first_add = (last_bid is None)
        all_added = []
        for line in lines:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            parts = list(reversed(parts))
            for col_idx, label in enumerate(parts):
                if not label:
                    continue
                is_new_row = (col_idx == 0)
                nr = 1 if is_new_row else 0
                if first_add:
                    last_bid = add_btn(qa_pid, btn_type, label)
                    first_add = False
                else:
                    last_bid = add_btn_after(last_bid, qa_pid, btn_type, label, new_row=nr)
                all_added.append((label, is_new_row))
        if all_added:
            names = "\n".join(
                f"  {'🔹' if nr else '  ▪️'} {lbl}" for lbl, nr in all_added
            )
            type_label = "📂 قائمة" if btn_type == "menu" else "📄 محتوى"
            await q.edit_message_text(
                f"✅ تم إضافة {len(all_added)} زر ({type_label}):\n{names}",
                parse_mode="Markdown"
            )
            await q.message.reply_text("🔄", reply_markup=build_kb(uid, qa_pid))
        else:
            await q.edit_message_text("⚠️ لم يتم إضافة أي زر.")
        return

    # ── تنقل في لوحة الإدارة العامة ──────────────────────────────
    if d == "m_r":
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage()); return

    if d.startswith("m_"):
        ep = int(d[2:]); b = get_btn(ep)
        if b and b["type"] == "content":
            items = get_items(ep)
            await q.edit_message_text(f"📄 *{b['label']}*\n_{len(items)} عنصر_",
                                      parse_mode="Markdown", reply_markup=kb_content_panel(ep))
        else:
            await q.edit_message_text(f"📂 *{b['label']}*" if b else "⚙️ *إدارة الأزرار*:",
                                      parse_mode="Markdown", reply_markup=kb_manage(ep if b else None))
        return

    # ── فتح تفاصيل زر من لوحة الإدارة ───────────────────────────
    if d.startswith("e_"):
        bid = int(d[2:]); b = get_btn(bid)
        if not b: return
        if b["type"] == "content":
            items = get_items(bid)
            await q.edit_message_text(f"📄 *{b['label']}*\n_{len(items)} عنصر_",
                                      parse_mode="Markdown", reply_markup=kb_content_panel(bid))
        else:
            await q.edit_message_text(f"📂 *{b['label']}*", parse_mode="Markdown",
                                      reply_markup=kb_edit_menu_btn(bid))
        return

    # ── تبديل موضع زرين ──────────────────────────────────────────
    if d.startswith("swp_start_"):
        pctx = d[10:]; ep = None if pctx == "r" else int(pctx)
        await q.edit_message_text("🔀 *اختر الزر الأول:*", parse_mode="Markdown",
                                  reply_markup=kb_swap_select(ep)); return

    if d.startswith("swp1_"):
        bid1 = int(d[5:]); b = get_btn(bid1)
        ep = b["parent_id"] if b else None
        await q.edit_message_text(f"🔀 *الزر الأول: {b['label']}*\n\nاختر الزر الثاني:",
                                  parse_mode="Markdown",
                                  reply_markup=kb_swap_select(ep, first_bid=bid1)); return

    if d.startswith("swp2_"):
        parts = d[5:].split("_"); bid1 = int(parts[0]); bid2 = int(parts[1])
        b1 = get_btn(bid1); b2 = get_btn(bid2)
        swap_btns(bid1, bid2)
        ep = b1["parent_id"] if b1 else None
        await q.edit_message_text(
            f"✅ تم تبديل موضع *{b1['label']}* و *{b2['label']}*",
            parse_mode="Markdown", reply_markup=kb_manage(ep)); return

    # ── تأكيد حذف زر ──────────────────────────────────────────────
    if d.startswith("confirm_x_"):
        bid = int(d[10:]); b = get_btn(bid)
        label = b["label"] if b else "؟"
        await q.edit_message_text(
            f"⚠️ هل أنت متأكد من حذف الزر *{label}*؟",
            parse_mode="Markdown",
            reply_markup=kb_confirm_delete(bid)
        )
        return

    # ── حذف زر ────────────────────────────────────────────────────
    if d.startswith("x_"):
        bid = int(d[2:]); b = get_btn(bid); ep = b["parent_id"] if b else None
        del_btn(bid)
        ctx.user_data["pid"] = ep
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage(ep))
        await q.message.reply_text("✅ تم الحذف.", reply_markup=build_kb(uid, ep))
        return

    # ── زر + جنب زر موجود ────────────────────────────────────────
    if d.startswith("plus_e_"):
        pctx = d[7:]; ep = None if pctx == "r" else int(pctx)
        ctx.user_data["add_pid"] = ep
        ctx.user_data.pop("add_after", None)
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=kb_add_type()); return

    if d.startswith("pladd_above_"):
        before_bid = int(d[12:]); b = get_btn(before_bid)
        ctx.user_data["add_pid"]    = b["parent_id"] if b else None
        ctx.user_data["add_before"] = before_bid
        ctx.user_data.pop("add_after", None)
        ctx.user_data.pop("add_new_row", None)
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=kb_add_type()); return

    if d.startswith("pladd_same_"):
        after_bid = int(d[11:]); b = get_btn(after_bid)
        ctx.user_data["add_pid"]   = b["parent_id"] if b else None
        ctx.user_data["add_after"] = after_bid
        ctx.user_data["add_new_row"] = 0
        ctx.user_data.pop("add_before", None)
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=kb_add_type()); return

    if d.startswith("pladd_new_"):
        after_bid = int(d[10:]); b = get_btn(after_bid)
        ctx.user_data["add_pid"]   = b["parent_id"] if b else None
        ctx.user_data["add_after"] = after_bid
        ctx.user_data["add_new_row"] = 1
        ctx.user_data.pop("add_before", None)
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=kb_add_type()); return

    if d == "pt_addtop":
        # إضافة في الأعلى: نستخدم add_after=None لإدراجه قبل الأول
        ctx.user_data["add_after"]   = None
        ctx.user_data["add_new_row"] = 1
        ctx.user_data.pop("add_before", None)
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=kb_add_type()); return

    if d == "pt_addbottom":
        ctx.user_data.pop("add_after", None)
        ctx.user_data.pop("add_new_row", None)
        ctx.user_data.pop("add_before", None)
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=kb_add_type()); return

    if d.startswith("plus_"):
        after_bid = int(d[5:]); b = get_btn(after_bid)
        ctx.user_data["add_pid"] = b["parent_id"] if b else None
        await q.edit_message_text("أين تريد إضافة الزر الجديد؟", reply_markup=kb_add_position(after_bid)); return

    if d in ("pt_m", "pt_c"):
        t = "menu" if d == "pt_m" else "content"
        ctx.user_data["new_type"] = t
        ctx.user_data["state"] = "wait_label"
        await q.edit_message_text("✏️ اكتب اسم الزر الجديد:", reply_markup=kb_cancel_inline()); return

    if d == "pt_cancel":
        ctx.user_data.pop("state", None); ctx.user_data.pop("new_type", None)
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_pid", None)
        ctx.user_data.pop("add_new_row", None); ctx.user_data.pop("add_before", None)
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_text("تم الإلغاء.")
        return

    # ── تعديل اسم الزر ───────────────────────────────────────────
    if d.startswith("el_"):
        bid = int(d[3:]); ctx.user_data["edit_bid"] = bid; b = get_btn(bid)
        ctx.user_data["state"] = "wait_edit_label"
        await q.edit_message_text(f"✏️ الاسم الحالي: *{b['label']}*\n\nاكتب الاسم الجديد:",
                                  parse_mode="Markdown", reply_markup=kb_cancel_inline()); return

    # ── لوحة محتوى الزر: إضافة عنصر ─────────────────────────────
    if d.startswith("ci_add_"):
        bid = int(d[7:])
        ctx.user_data["state"] = "wait_item_content"
        ctx.user_data["item_bid"] = bid
        await q.edit_message_text("📤 أرسل المحتوى (نص، صورة، ملف، فيديو، صوت):",
                                  reply_markup=kb_cancel_inline()); return

    # ── عرض عناصر الزر مع أزرار إدارة لكل عنصر ──────────────────
    if d.startswith("ci_view_"):
        bid = int(d[8:]); items = get_items(bid)
        if not items:
            return
        for item in items:
            await send_file_item(q.message, item, reply_markup=kb_item_actions(item["id"]))
        return

    # ── تغيير وصف عنصر ───────────────────────────────────────────
    if d.startswith("ci_edit_"):
        iid = int(d[8:])
        ctx.user_data["state"] = "wait_item_desc"
        ctx.user_data["item_iid"] = iid
        ctx.user_data["item_msg_id"] = q.message.message_id
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ إلغاء", callback_data=f"ci_cancel_edit_{iid}")
        ]]))
        await q.message.reply_text("✏️ أرسل الوصف الجديد:"); return

    # ── إلغاء تعديل وصف عنصر ─────────────────────────────────────
    if d.startswith("ci_cancel_edit_"):
        iid = int(d[15:])
        ctx.user_data.pop("state", None)
        ctx.user_data.pop("item_iid", None)
        ctx.user_data.pop("item_msg_id", None)
        await q.edit_message_reply_markup(reply_markup=kb_item_actions(iid)); return

    # ── حذف عنصر من رسالته ────────────────────────────────────────
    if d.startswith("ci_del_"):
        iid = int(d[7:])
        del_item(iid)
        await q.edit_message_reply_markup(reply_markup=None)
        await q.answer("✅ تم الحذف.", show_alert=False); return

    # ── إدارة المشرفين ────────────────────────────────────────────
    if d == "aa":
        ctx.user_data["state"] = "wait_admin_id"
        await q.edit_message_text("👤 أرسل معرّف المستخدم (ID):", reply_markup=kb_cancel_inline()); return

    if d.startswith("da_"):
        tid = int(d[3:])
        if tid == uid: await q.answer("❌ لا يمكنك إزالة نفسك!", show_alert=True); return
        del_admin(tid)
        await q.edit_message_text(f"👥 *المشرفون* ({len(all_admins())}):",
                                  parse_mode="Markdown", reply_markup=kb_admins_inline()); return

# ── خاصية الذكاء الاصطناعي (Gemini) ─────────────────────────────
AI_SYSTEM_PROMPT = """أنت مساعد ذكي مدمج في بوت تلغرام لإدارة قوائم الأزرار.
اقرأ طلب المشرف وحالة الأزرار الحالية بعناية، افهم القصد الحقيقي، ثم أرجع JSON ينفّذ ما طُلب بدقة.

━━━ تنسيق JSON المطلوب ━━━
{
  "action": "add" | "delete_all" | "delete_some" | "delete_then_add",
  "delete_indices": [],
  "operations": [
    {
      "insert_after_index": -1,
      "buttons": [
        {
          "label": "النص",
          "type": "menu",
          "new_row": true,
          "children": [
            {
              "label": "زر فرعي",
              "type": "menu",
              "new_row": true,
              "children": [
                {"label": "محتوى", "type": "content", "new_row": true}
              ]
            }
          ]
        }
      ]
    }
  ]
}

━━━ شرح الحقول ━━━

action:
  "add"            → إضافة أزرار جديدة فقط
  "delete_all"     → حذف جميع الأزرار الموجودة، operations تكون []
  "delete_some"    → حذف أزرار محددة بفهارسها في delete_indices، operations تكون []
  "delete_then_add"→ حذف أزرار معينة ثم إضافة أخرى

delete_indices: قائمة فهارس الأزرار المراد حذفها، مثل [0, 2]

operations: قائمة عمليات الإضافة — يمكن أن تكون عملية واحدة أو أكثر حسب الطلب
  insert_after_index:
    -1      → أضف في نهاية القائمة
    "start" → أضف في بداية القائمة
    رقم     → أضف مباشرةً بعد الزر ذي هذا الفهرس
  buttons: الأزرار المراد إضافتها
    label    → نص الزر
    type     → "menu" يفتح قائمة فرعية | "content" يعرض محتوى
    new_row  → true: الزر يبدأ سطراً جديداً (يظهر تحت السابق)
               false: الزر يكمل نفس سطر الزر السابق (يظهر بجانبه)
    children → (اختياري) قائمة أزرار تُضاف داخل هذا الزر تلقائياً إذا كان type="menu"
               يدعم التداخل بأي عمق — كل زر فرعي يمكن أن يحتوي children خاصة به

━━━ أمثلة توضيحية ━━━

مثال 1 — "أضف 3 أزرار عمودياً":
  operation واحدة، insert_after_index: -1، كل زر new_row: true

مثال 2 — "أضف 3 أزرار أفقياً في نفس السطر":
  operation واحدة، insert_after_index: -1، الأول new_row: true، الباقي new_row: false

مثال 3 — "أضف زر لكل سطر" والسياق يحتوي 3 أسطر:
  السطر 1: [0] "خدمات" ← آخر فهرس: 0
  السطر 2: [1] "من نحن"، [2] "فريق" ← آخر فهرس: 2
  السطر 3: [3] "تواصل" ← آخر فهرس: 3
  → 3 عمليات منفصلة، كل عملية تُضيف زر واحد بجانب آخر زر في سطره:
    {insert_after_index: 0, buttons: [{new_row: false, label: "...", type: "menu"}]}
    {insert_after_index: 2, buttons: [{new_row: false, label: "...", type: "menu"}]}
    {insert_after_index: 3, buttons: [{new_row: false, label: "...", type: "menu"}]}

مثال 4 — "احذف الزر الثاني":
  action: "delete_some"، delete_indices: [1]

مثال 5 — "استبدل زر X بـ Y":
  action: "delete_then_add"، delete_indices: [فهرسه]، operations تحتوي الزر الجديد

مثال 6 — "أضف قائمة اسمها الخدمات وبداخلها زرين: دعم فني وشحن":
  زر type="menu" label="الخدمات" مع children يحتويان الزرين الفرعيين:
  {"label": "الخدمات", "type": "menu", "new_row": true, "children": [
    {"label": "دعم فني", "type": "menu", "new_row": true},
    {"label": "شحن", "type": "menu", "new_row": true}
  ]}

مثال 7 — بناء هيكل متداخل (قائمة > قوائم فرعية > محتوى):
  المشرف: "أضف قائمة المنتجات بها ملابس وإلكترونيات، وداخل كل منها أضف 3 أزرار محتوى"
  → قائمة "المنتجات" مع children:
    - "ملابس" type="menu" مع children: [3 أزرار type="content"]
    - "إلكترونيات" type="menu" مع children: [3 أزرار type="content"]

━━━ مفهوم السطر والموضع ━━━
السياق يُظهر الأزرار مُجمَّعة في أسطر أفقية. كل سطر هو صف أفقي من الأزرار.
مثال على السياق:
  السطر 1 (3 زر): [0](زر1 من السطر) "ألف" (menu)،  [1](زر2 من السطر) "باء" (menu)،  [2](زر3 من السطر) "جيم" (menu)  ← آخر فهرس: 2
  السطر 2 (2 زر): [3](زر1 من السطر) "دال" (menu)،  [4](زر2 من السطر) "هاء" (menu)  ← آخر فهرس: 4

عندما يقول المشرف:
• "السطر الثاني"         → يقصد الصف الأفقي رقم 2 (في المثال: السطر الذي يحوي "دال" و"هاء")
• "الزر الثاني من السطر الأول" → يقصد الزر2 من السطر 1، أي الفهرس [1] "باء"
• "الزر الثالث من السطر الثاني" → يقصد الزر3 من السطر 2، أي الفهرس بـ pos3 في السطر 2
• "أضف زر بعد الزر الثاني من السطر الأول" → insert_after_index: 1، new_row: false

━━━ ملاحظات ━━━
• افهم النية من أي وصف طبيعي بالعربية.
• إذا ذُكر موضوع (مطعم، متجر، خدمات...) ابتكر أزراراً مناسبة له.
• إذا لم يُحدد الاتجاه (عمودي/أفقي) فالافتراضي عمودي (new_row: true لكل زر).
• فكّر جيداً قبل الإجابة: هل يريد إضافة لأسطر موجودة أم أسطر جديدة؟

أرجع JSON صالح فقط بدون أي نص إضافي خارجه."""

def _repair_json(raw: str) -> str:
    """يحاول إغلاق JSON مقطوع بإضافة الأقواس والنصوص المفقودة."""
    stack = []
    in_string = False
    escape_next = False
    for ch in raw:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in ('}', ']') and stack:
            stack.pop()
    # إذا كنا داخل نص مقطوع أغلقه أولاً
    suffix = '"' if in_string else ''
    suffix += ''.join(reversed(stack))
    return raw + suffix

def _parse_ai_response(raw: str):
    """يستخرج action وقائمة العمليات وقائمة الحذف من JSON.
    يُرجع: (action, operations, del_idx)
    حيث operations = [{"insert": int|str, "buttons": list}, ...]
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    # محاولة التحليل المباشر أولاً، وإصلاح JSON المقطوع عند الفشل
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(f"[AI] JSON malformed, attempting repair. Raw snippet: {raw[-200:]}")
        data = json.loads(_repair_json(raw))
    action  = data.get("action", "add")
    del_idx = data.get("delete_indices", [])

    # دعم تنسيق operations (الجديد) وتنسيق buttons المسطح (القديم)
    if "operations" in data:
        operations = []
        for op in data["operations"]:
            operations.append({
                "insert": op.get("insert_after_index", -1),
                "buttons": op.get("buttons", []),
            })
    else:
        operations = [{
            "insert": data.get("insert_after_index", -1),
            "buttons": data.get("buttons", []),
        }]
    return action, operations, del_idx

async def _download_image_base64(bot, file_id: str):
    """يحمّل الصورة من تيليغرام ويحوّلها إلى base64."""
    import base64, io
    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode(), "image/jpeg"

GEMINI_VISION_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]

async def _call_gemini_vision(client: httpx.AsyncClient, prompt: str, images: list):
    """يستدعي Gemini Vision API مع تدوير المفاتيح والنماذج تلقائياً."""
    parts = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": {"mime_type": img["mime"], "data": img["data"]}})
    payload = {"contents": [{"parts": parts}]}
    for model in GEMINI_VISION_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for key in GEMINI_KEYS:
            try:
                resp = await client.post(url, params={"key": key}, json=payload, timeout=60)
                if resp.status_code in (429, 503):
                    logging.warning(f"Gemini Vision {model} key ...{key[-6:]} rate-limited, trying next...")
                    continue
                if resp.status_code == 404:
                    logging.warning(f"Gemini Vision model {model} not found, trying next model...")
                    break
                resp.raise_for_status()
                data = resp.json()
                candidate = data.get("candidates", [{}])[0]
                finish = candidate.get("finishReason", "")
                if finish in ("SAFETY", "RECITATION", "OTHER"):
                    logging.warning(f"Gemini Vision blocked: {finish}")
                    return None
                text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                if text:
                    logging.info(f"Gemini Vision raw response: {text[:300]}")
                    return text
            except Exception as e:
                logging.warning(f"Gemini Vision {model} exception: {e}")
    return None

async def _process_image_batch(wait_msg, m, ctx, uid, pid, images: list, btn_type: str):
    """يحلّل مجموعة صور ويضيف الأزرار المستخرجة منها بالترتيب."""
    import re
    if not GEMINI_KEYS:
        await wait_msg.edit_text("❌ تحليل الصور يتطلب مفتاح Gemini API. أضف GEMINI_API_KEY في الإعدادات.")
        return
    all_added = []
    existing_labels = set()
    last_bid = None
    for img in images:
        existing_str = "، ".join(f'"{l}"' for l in existing_labels) if existing_labels else "لا شيء"
        prompt = (
            "أنت مساعد لاستخراج أسماء أزرار واجهة تيليغرام من الصور.\n"
            "انظر إلى الصورة واستخرج جميع أسماء الأزرار الظاهرة بنفس ترتيبها وتخطيطها.\n"
            f"الأزرار المضافة مسبقاً (لا تكررها أبداً): {existing_str}\n\n"
            "أرجع JSON فقط بهذا الشكل بدون أي نص إضافي:\n"
            '{"buttons": [{"label": "اسم الزر", "new_row": true}, ...]}\n\n'
            "- new_row: true إذا كان الزر في سطر جديد، false إذا في نفس سطر الزر السابق.\n"
            "- لا تضف أزرار تنقل مثل: رجوع، الرئيسية، القائمة الرئيسية، ⬅️، 🏠.\n"
            '- إذا لم توجد أزرار أو كلها مكررة: {"buttons": []}'
        )
        try:
            async with httpx.AsyncClient() as client:
                raw = await _call_gemini_vision(client, prompt, [img])
            if not raw:
                continue
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if not json_match:
                continue
            data = json.loads(json_match.group())
            buttons = data.get("buttons", [])
        except Exception as e:
            logging.warning(f"Image batch parse error: {e}")
            continue
        for btn_data in buttons:
            label = (btn_data.get("label") or "").strip()
            if not label or label in existing_labels:
                continue
            new_row = btn_data.get("new_row", True)
            nr = 1 if new_row else 0
            if last_bid is None:
                last_bid = add_btn(pid, btn_type, label)
            else:
                last_bid = add_btn_after(last_bid, pid, btn_type, label, new_row=nr)
            all_added.append(label)
            existing_labels.add(label)
    if all_added:
        names = "\n".join(f"  • {l}" for l in all_added)
        await wait_msg.edit_text(f"✅ تم إضافة {len(all_added)} زر:\n{names}", parse_mode="Markdown")
        await m.reply_text("🔄", reply_markup=build_kb(uid, pid))
    else:
        await wait_msg.edit_text("⚠️ لم يُعثر على أزرار في الصور.")

async def _call_gemini(client: httpx.AsyncClient, prompt: str):
    """يستدعي Gemini API مع تدوير المفاتيح تلقائياً."""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    for key in GEMINI_KEYS:
        resp = await client.post(url, params={"key": key}, json=payload, timeout=30)
        if resp.status_code in (429, 503):
            logging.warning(f"Gemini key ...{key[-6:]} rate-limited, trying next key...")
            continue
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None

async def process_ai_request(user_request: str, current_btns: list = None):
    """يستدعي Gemini ويُرجع (action, operations, del_idx, error)."""
    if not GEMINI_KEYS:
        return None, [], [], "❌ لم يُعَيَّن أي مفتاح Gemini API."

    if current_btns:
        ctx_lines = [f"الأزرار الحالية الموجودة ({len(current_btns)} زر) مُجمَّعة حسب الأسطر:"]
        current_row_btns = []
        rows = []
        for i, b in enumerate(current_btns):
            if i == 0 or b.get("new_row", 1):
                if current_row_btns:
                    rows.append(current_row_btns)
                current_row_btns = [(i, b)]
            else:
                current_row_btns.append((i, b))
        if current_row_btns:
            rows.append(current_row_btns)
        for r_idx, row in enumerate(rows):
            btns_str = "،  ".join(
                f"[{i}](زر{pos+1} من السطر) \"{b['label']}\" ({b['type']})"
                for pos, (i, b) in enumerate(row)
            )
            last_idx = row[-1][0]
            ctx_lines.append(f"  السطر {r_idx + 1} ({len(row)} زر): {btns_str}  ← آخر فهرس في هذا السطر: {last_idx}")
        ctx_text = "\n".join(ctx_lines)
    else:
        ctx_text = "لا توجد أزرار حالية (القائمة فارغة)."

    prompt = f"{AI_SYSTEM_PROMPT}\n\n{ctx_text}\n\nطلب المشرف: {user_request}"

    async with httpx.AsyncClient() as client:
        try:
            raw = await _call_gemini(client, prompt)
            if raw:
                action, operations, del_idx = _parse_ai_response(raw)
                return action, operations, del_idx, None
            return None, [], [], "⚠️ جميع مفاتيح Gemini وصلت لحد الطلبات. حاول لاحقاً."
        except json.JSONDecodeError:
            return None, [], [], "⚠️ لم أتمكن من تفسير رد الذكاء الاصطناعي. حاول مرة أخرى."
        except Exception as e:
            logging.warning(f"Gemini exception: {e}")
    return None, [], [], "⚠️ تعذّر الاتصال بـ Gemini. تحقق من المفاتيح وحاول مرة أخرى."

# ── النسخ الاحتياطي ───────────────────────────────────────────────
async def send_backup(bot, chat_id: int):
    """يُنشئ ملف ZIP يحتوي قاعدة البيانات والملفات ويرسله للمستخدم."""
    from telegram.request import HTTPXRequest
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_path = f"/tmp/backup_{now}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(DB):
                zf.write(DB, arcname="data.db")
            if os.path.isdir(MEDIA_DIR):
                for fname in os.listdir(MEDIA_DIR):
                    fpath = os.path.join(MEDIA_DIR, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, arcname=os.path.join("media", fname))
        with open(zip_path, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=f"backup_{now}.zip",
                caption=f"💾 نسخة احتياطية — {now}",
                write_timeout=300,
                read_timeout=300,
                connect_timeout=60,
            )
    except Exception as e:
        logging.warning(f"فشل إرسال النسخة الاحتياطية: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ فشل إرسال النسخة الاحتياطية:\n{e}")
        except Exception:
            pass
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

async def restore_backup(zip_path: str) -> tuple[bool, str]:
    """يستعيد النسخة الاحتياطية من ملف ZIP — يُعيد (نجاح, رسالة)."""
    import shutil
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "data.db" not in names:
                return False, "⚠️ الملف لا يحتوي على data.db — تأكد أنه نسخة احتياطية صحيحة."
            db_bak = DB + ".bak"
            if os.path.exists(DB):
                shutil.copy2(DB, db_bak)
            zf.extract("data.db", path=".")
            media_files = [n for n in names if n.startswith("media/") and not n.endswith("/")]
            for mf in media_files:
                zf.extract(mf, path=".")
        if os.path.exists(db_bak):
            os.remove(db_bak)
        return True, f"✅ تمت الاستعادة بنجاح!\n🗂 قاعدة البيانات: محدّثة\n📁 ملفات الميديا المستعادة: {len(media_files)}"
    except zipfile.BadZipFile:
        return False, "❌ الملف المرسل ليس ملف ZIP صالح."
    except Exception as e:
        return False, f"❌ فشلت الاستعادة: {e}"

async def _auto_backup_job(ctx):
    """مهمة الجدولة التلقائية — ترسل النسخة لـ SUPER_ADMIN_ID."""
    sid = os.environ.get("SUPER_ADMIN_ID", "").strip()
    if sid.isdigit():
        await send_backup(ctx.bot, int(sid))

# ── إعداد البوت ──────────────────────────────────────────────────
async def post_init(app):
    sid = os.environ.get("SUPER_ADMIN_ID", "").strip()
    if sid.isdigit() and not is_admin(int(sid)):
        add_admin(int(sid)); logging.info(f"Super admin {sid} added.")
    if sid.isdigit():
        app.job_queue.run_repeating(_auto_backup_job, interval=86400, first=3600, name="auto_backup")
        logging.info("تم جدولة النسخ الاحتياطي التلقائي كل 24 ساعة.")

def main():
    if not BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN غير موجود!"); return
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    media_filter = (filters.TEXT | filters.PHOTO | filters.Document.ALL |
                    filters.VIDEO | filters.AUDIO | filters.VOICE) & ~filters.COMMAND

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CallbackQueryHandler(cb_manage))
    app.add_handler(MessageHandler(media_filter, on_message))

    logging.info("البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
