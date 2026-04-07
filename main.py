import logging
import os
import sqlite3
import json
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
DB = "data.db"

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

BTN_BACK   = "🔙 رجوع"
BTN_ADD    = "➕ إضافة"
BTN_MANAGE = "⚙️ إدارة"
BTN_ADMINS = "👥 مشرفون"
BTN_CANCEL = "❌ إلغاء"

TYPE_MAP = {
    "📂 قائمة":  "menu",
    "📄 محتوى": "content",
}

BTN_SWAP = "🔀 تغيير"

ADMIN_BTNS   = {BTN_MANAGE, BTN_ADMINS}
SPECIAL_BTNS = {BTN_BACK, BTN_ADD, BTN_MANAGE, BTN_ADMINS, BTN_CANCEL, BTN_SWAP} | set(TYPE_MAP.keys())

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
                ord INTEGER DEFAULT 0
            );
        """)
        try:
            c.execute("ALTER TABLE buttons ADD COLUMN new_row INTEGER DEFAULT 1")
            c.commit()
        except Exception:
            pass

def is_admin(uid):
    return db().execute("SELECT 1 FROM admins WHERE id=?", (uid,)).fetchone() is not None

def add_admin(uid, name=None):
    c = db(); c.execute("INSERT OR IGNORE INTO admins VALUES(?,?)", (uid, name)); c.commit(); c.close()

def del_admin(uid):
    c = db(); c.execute("DELETE FROM admins WHERE id=?", (uid,)); c.commit(); c.close()

def all_admins():
    return [dict(r) for r in db().execute("SELECT * FROM admins").fetchall()]

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

def del_btn(bid):
    c = db(); c.execute("DELETE FROM buttons WHERE id=?", (bid,)); c.commit(); c.close()


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

def add_item(bid, t, content=None, file_id=None):
    c = db(); cur = c.cursor()
    n = cur.execute("SELECT COALESCE(MAX(ord),0)+1 FROM content_items WHERE button_id=?", (bid,)).fetchone()[0]
    cur.execute("INSERT INTO content_items(button_id,type,content,file_id,ord) VALUES(?,?,?,?,?)",
                (bid, t, content, file_id, n))
    c.commit(); c.close()

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

# ── بناء لوحة مفاتيح الرد ────────────────────────────────────────
ICON = {"menu": "📂", "content": "📄"}

def build_kb(uid, pid=None):
    btns = get_buttons(pid)
    rows = []
    current_row = []
    for i, b in enumerate(btns):
        if i > 0 and b.get('new_row', 1):
            if current_row:
                rows.append(current_row)
            current_row = []
        current_row.append(KeyboardButton(b['label']))
    if current_row:
        rows.append(current_row)
    if pid is not None:
        rows.append([KeyboardButton(BTN_BACK)])
    if is_admin(uid):
        rows.append([KeyboardButton(BTN_MANAGE), KeyboardButton(BTN_ADMINS)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True) if (rows or is_admin(uid)) else None

def build_type_kb():
    return ReplyKeyboardMarkup([
        ["📂 قائمة", "📄 محتوى"],
        [BTN_CANCEL],
    ], resize_keyboard=True)

# ── لوحات Inline ─────────────────────────────────────────────────
def kb_manage(pid=None):
    ctx = "r" if pid is None else str(pid)
    rows = []
    btns = get_buttons(pid)
    if btns:
        rows.append([InlineKeyboardButton("➕ إضافة في البداية", callback_data=f"add_first_{ctx}")])
    for b in btns:
        rows.append([
            InlineKeyboardButton(b['label'], callback_data=f"e_{b['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"x_{b['id']}"),
            InlineKeyboardButton("➕↕", callback_data=f"add_after_{b['id']}"),
            InlineKeyboardButton("➕↔", callback_data=f"add_same_{b['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة في النهاية", callback_data=f"add_{ctx}")])
    if len(btns) >= 2:
        rows.append([InlineKeyboardButton("🔀 تبديل موضع زرين", callback_data=f"swp_start_{ctx}")])
    if pid is not None:
        b = get_btn(pid); back = b["parent_id"] if b else None
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="m_r" if back is None else f"m_{back}")])
    return InlineKeyboardMarkup(rows)

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
        [InlineKeyboardButton("🗑 حذف",          callback_data=f"x_{bid}")],
    ]
    pid = b["parent_id"] if b else None
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="m_r" if pid is None else f"m_{pid}")])
    return InlineKeyboardMarkup(rows)

def kb_content_panel(bid):
    """لوحة إدارة محتوى الزر."""
    items = get_items(bid)
    b = get_btn(bid)
    rows = []
    if items:
        rows.append([InlineKeyboardButton("👁 عرض المحتوى", callback_data=f"ci_view_{bid}")])
    rows.append([InlineKeyboardButton("➕ إضافة محتوى", callback_data=f"ci_add_{bid}")])
    rows.append([InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"el_{bid}")])
    rows.append([InlineKeyboardButton("🗑 حذف الزر",    callback_data=f"x_{bid}")])
    pid = b["parent_id"] if b else None
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="m_r" if pid is None else f"m_{pid}")])
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
    return InlineKeyboardMarkup(rows)

def kb_cancel_inline():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]])


# ── مساعد اللوحة الثابتة ─────────────────────────────────────────
async def set_panel(ctx, chat_id, text, markup=None):
    pid = ctx.user_data.get("panel_id")
    if pid:
        try:
            await ctx.bot.edit_message_text(chat_id=chat_id, message_id=pid,
                                            text=text, reply_markup=markup, parse_mode="Markdown")
            return
        except Exception:
            pass
    msg = await ctx.bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")
    ctx.user_data["panel_id"] = msg.message_id

# ── عرض عناصر المحتوى للمستخدم ───────────────────────────────────
async def send_items(m, bid):
    items = get_items(bid)
    if not items:
        await m.reply_text("📭 لا يوجد محتوى بعد.")
        return
    for item in items:
        t = item["type"]; fid = item.get("file_id"); cap = item.get("content") or ""
        if t == "text":
            await m.reply_text(cap)
        elif t == "photo" and fid:
            await m.reply_photo(fid, caption=cap)
        elif t == "file" and fid:
            await m.reply_document(fid, caption=cap)
        elif t == "video" and fid:
            await m.reply_video(fid, caption=cap)
        elif t == "audio" and fid:
            await m.reply_audio(fid, caption=cap)

# ── /start ────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx):
    uid = update.effective_user.id
    ctx.user_data.clear()
    kb = build_kb(uid)
    if not kb:
        await update.message.reply_text("👋 أهلاً! لا توجد أزرار متاحة حالياً.")
        return
    await update.message.reply_text("👋 أهلاً!", reply_markup=kb)

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

    # ── انتظار اسم الزر ───────────────────────────────────────────
    if state == "wait_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للاسم."); return
        t = ctx.user_data.get("new_type"); add_pid = ctx.user_data.get("add_pid")
        add_after = ctx.user_data.get("add_after", "END")
        add_position = ctx.user_data.get("add_position")
        add_same_row = ctx.user_data.get("add_same_row", False)
        if add_position == "first":
            bid = add_btn_after(None, add_pid, t, text)
        elif add_after != "END":
            bid = add_btn_after(add_after, add_pid, t, text, new_row=0 if add_same_row else 1)
        else:
            bid = add_btn(add_pid, t, text)
        ctx.user_data.pop("state", None); ctx.user_data.pop("new_type", None)
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_position", None)
        ctx.user_data.pop("add_same_row", None)
        if t == "menu":
            await m.reply_text(f"✅ تم إنشاء القائمة *{text}*", parse_mode="Markdown",
                               reply_markup=build_kb(uid, pid))
        else:
            # content button: create and open its management panel
            await m.reply_text(f"✅ تم إنشاء الزر *{text}*\n\nيمكنك الآن إضافة المحتوى:",
                               parse_mode="Markdown", reply_markup=build_kb(uid, pid))
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
        add_item(bid, t, content, fid)
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

    # ── انتظار اسم جديد للتعديل ───────────────────────────────────
    if state == "wait_edit_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        bid = ctx.user_data.get("edit_bid"); upd_btn_label(bid, text)
        b = get_btn(bid); ctx.user_data.pop("state", None)
        if b and b["type"] == "content":
            await set_panel(ctx, chat_id, f"📄 *{text}*", kb_content_panel(bid))
        else:
            ep = b["parent_id"] if b else None
            await set_panel(ctx, chat_id, f"✅ تم تغيير الاسم إلى *{text}*", kb_manage(ep))
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار رقم المشرف ─────────────────────────────────────────
    if state == "wait_admin_id":
        try: tid = int(text)
        except ValueError: await m.reply_text("⚠️ أرسل رقم ID صحيح."); return
        add_admin(tid); ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, f"👥 *المشرفون* ({len(all_admins())}):", kb_admins_inline())
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── إشارة النقطة للذكاء الاصطناعي (للمشرفين فقط) ────────────
    if not state and text.startswith(".") and is_admin(uid):
        request_text = text[1:].strip()
        if not request_text:
            await m.reply_text("💡 اكتب طلبك بعد النقطة. مثال:\n. أضف أزرار: خدماتنا، من نحن، تواصل معنا")
            return
        if not GROQ_API_KEY and not GEMINI_API_KEY:
            await m.reply_text("❌ لم يُعَيَّن أي مفتاح AI.")
            return
        wait_msg = await m.reply_text("⏳ جاري التواصل مع الذكاء الاصطناعي...")
        buttons, error = await generate_buttons(request_text)
        if error:
            await wait_msg.edit_text(error)
            return
        added = []
        last_id = None
        for btn in buttons:
            label = btn.get("label", "").strip()
            btype = btn.get("type", "menu")
            new_row = btn.get("new_row", True)
            if not label:
                continue
            if btype not in ("menu", "content"):
                btype = "menu"
            if last_id is None:
                last_id = add_btn(pid, btype, label)
            else:
                last_id = add_btn_after(last_id, pid, btype, label, new_row=0 if not new_row else 1)
            added.append(f"{'📂' if btype == 'menu' else '📄'} {label}")
        if not added:
            await wait_msg.edit_text("⚠️ لم تُضَف أي أزرار.")
            return
        summary = "\n".join(f"  • {a}" for a in added)
        await wait_msg.edit_text(
            f"✅ *تمت إضافة {len(added)} زر بواسطة الذكاء الاصطناعي:*\n\n{summary}",
            parse_mode="Markdown"
        )
        await m.reply_text("🔄", reply_markup=build_kb(uid, pid))
        return

    # ── اختيار نوع الزر ───────────────────────────────────────────
    if state == "wait_type" and text in TYPE_MAP:
        t = TYPE_MAP[text]; ctx.user_data["new_type"] = t; ctx.user_data["state"] = "wait_label"
        await m.reply_text("✏️ اكتب اسم الزر:", reply_markup=build_kb(uid, pid))
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
            await m.reply_text("🔙", reply_markup=build_kb(uid, new_pid))
        return

    # ── أزرار المشرف ──────────────────────────────────────────────
    if is_admin(uid):
        if text == BTN_SWAP:
            btns = get_buttons(pid)
            if len(btns) < 2:
                await m.reply_text("⚠️ يجب أن يكون هناك زران على الأقل للتبديل.")
            else:
                await set_panel(ctx, chat_id, "🔀 *اختر الزر الأول:*", kb_swap_select(pid))
            return
        if text == BTN_MANAGE:
            await set_panel(ctx, chat_id, "⚙️ *إدارة الأزرار*:", kb_manage(pid))
            return
        if text == BTN_ADMINS:
            await set_panel(ctx, chat_id, f"👥 *المشرفون* ({len(all_admins())}):", kb_admins_inline())
            return

    # ── ضغط زر من القائمة ─────────────────────────────────────────
    btns = get_buttons(pid)
    matched = next((b for b in btns
                    if b['label'] == text), None)
    if not matched:
        return

    b = matched
    if b["type"] == "menu":
        ctx.user_data["pid"] = b["id"]
        await m.reply_text(f"📂 {b['label']}", reply_markup=build_kb(uid, b["id"]))

    elif b["type"] == "content":
        if is_admin(uid):
            items = get_items(b["id"])
            await set_panel(ctx, chat_id,
                            f"📄 *{b['label']}*\n_{len(items)} عنصر_",
                            kb_content_panel(b["id"]))
        else:
            await send_items(m, b["id"])

# ── معالج أزرار Inline ────────────────────────────────────────────
async def cb_manage(update: Update, ctx):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_admin(uid): return
    d = q.data; chat_id = q.message.chat_id
    ctx.user_data["panel_id"] = q.message.message_id
    pid = ctx.user_data.get("pid")

    if d == "noop": return

    if d == "cancel":
        ctx.user_data.pop("state", None)
        await q.edit_message_text("✅ تم الإلغاء."); return

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

    # ── حذف زر ────────────────────────────────────────────────────
    if d.startswith("x_"):
        bid = int(d[2:]); b = get_btn(bid); ep = b["parent_id"] if b else None
        del_btn(bid)
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage(ep))
        await q.message.reply_text("✅ تم الحذف.", reply_markup=build_kb(uid, pid))
        return

    # ── إضافة بجانب زر (نفس السطر) ──────────────────────────────
    if d.startswith("add_same_"):
        after_bid = int(d[9:]); b = get_btn(after_bid)
        ctx.user_data["state"] = "wait_type"
        ctx.user_data["add_pid"] = b["parent_id"] if b else None
        ctx.user_data["add_after"] = after_bid
        ctx.user_data["add_same_row"] = True
        ctx.user_data.pop("add_position", None)
        await q.message.reply_text("اختر نوع الزر:", reply_markup=build_type_kb()); return

    # ── إضافة من لوحة الإدارة (في النهاية) ──────────────────────
    if d.startswith("add_after_"):
        after_bid = int(d[10:]); b = get_btn(after_bid)
        ctx.user_data["state"] = "wait_type"
        ctx.user_data["add_pid"] = b["parent_id"] if b else None
        ctx.user_data["add_after"] = after_bid
        await q.message.reply_text("اختر نوع الزر:", reply_markup=build_type_kb()); return

    if d.startswith("add_first_"):
        pctx = d[10:]; ep = None if pctx == "r" else int(pctx)
        ctx.user_data["state"] = "wait_type"
        ctx.user_data["add_pid"] = ep
        ctx.user_data["add_after"] = None          # None = في البداية
        ctx.user_data["add_position"] = "first"
        await q.message.reply_text("اختر نوع الزر:", reply_markup=build_type_kb()); return

    if d.startswith("add_"):
        pctx = d[4:]; ep = None if pctx == "r" else int(pctx)
        ctx.user_data["state"] = "wait_type"; ctx.user_data["add_pid"] = ep
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_position", None)
        await q.message.reply_text("اختر نوع الزر:", reply_markup=build_type_kb()); return

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
            t = item["type"]; fid = item.get("file_id"); cap = item.get("content") or ""
            kb = kb_item_actions(item["id"])
            if t == "text":
                await q.message.reply_text(cap, reply_markup=kb)
            elif t == "photo" and fid:
                await q.message.reply_photo(fid, caption=cap, reply_markup=kb)
            elif t == "file" and fid:
                await q.message.reply_document(fid, caption=cap, reply_markup=kb)
            elif t == "video" and fid:
                await q.message.reply_video(fid, caption=cap, reply_markup=kb)
            elif t == "audio" and fid:
                await q.message.reply_audio(fid, caption=cap, reply_markup=kb)
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
AI_SYSTEM_PROMPT = """أنت مساعد لبوت تلغرام لإدارة الأزرار.
مهمتك: عندما يطلب المشرف إضافة أزرار، تُرجع JSON فقط بالشكل التالي (بدون أي نص إضافي):
{
  "buttons": [
    {"label": "اسم الزر", "type": "menu", "new_row": true},
    {"label": "اسم آخر", "type": "content", "new_row": false}
  ]
}
قواعد:
- type يكون "menu" إذا كان الزر قائمة فرعية، أو "content" إذا كان يحتوي محتوى.
- new_row: true يعني الزر في سطر جديد، false يعني بجانب الزر السابق في نفس السطر.
- رتّب الأزرار بشكل منطقي حسب طلب المستخدم.
- أرجع JSON صالح فقط، لا تضف أي شرح أو نص خارج JSON."""

def _parse_ai_response(raw: str):
    """يستخرج قائمة الأزرار من نص JSON مع تنظيف markdown."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    return data.get("buttons", [])

async def _call_groq(client: httpx.AsyncClient, prompt: str):
    """يستدعي Groq API."""
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    resp = await client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

async def _call_gemini(client: httpx.AsyncClient, prompt: str):
    """يستدعي Gemini API مع تجربة نماذج بديلة."""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        resp = await client.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=30)
        if resp.status_code in (429, 503):
            logging.warning(f"Gemini {model} unavailable ({resp.status_code}), trying next...")
            continue
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None

async def generate_buttons(user_request: str):
    """يجرب Groq أولاً ثم Gemini كاحتياط."""
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        return None, "❌ لم يُعَيَّن أي مفتاح AI (GROQ_API_KEY أو GEMINI_API_KEY)."
    prompt = f"{AI_SYSTEM_PROMPT}\n\nطلب المشرف: {user_request}"
    async with httpx.AsyncClient() as client:
        # ── Groq أولاً ────────────────────────────────────────────
        if GROQ_API_KEY:
            try:
                raw = await _call_groq(client, prompt)
                buttons = _parse_ai_response(raw)
                if buttons:
                    return buttons, None
            except json.JSONDecodeError:
                return None, "⚠️ لم أتمكن من تفسير رد الذكاء الاصطناعي. حاول مرة أخرى."
            except httpx.HTTPStatusError as e:
                logging.warning(f"Groq error {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                logging.warning(f"Groq exception: {e}")
        # ── Gemini احتياط ─────────────────────────────────────────
        if GEMINI_API_KEY:
            try:
                raw = await _call_gemini(client, prompt)
                if raw:
                    buttons = _parse_ai_response(raw)
                    if buttons:
                        return buttons, None
            except json.JSONDecodeError:
                return None, "⚠️ لم أتمكن من تفسير رد الذكاء الاصطناعي. حاول مرة أخرى."
            except Exception as e:
                logging.warning(f"Gemini exception: {e}")
    return None, "⚠️ تعذّر الاتصال بالذكاء الاصطناعي. حاول مرة أخرى."

# ── إعداد البوت ──────────────────────────────────────────────────
async def post_init(app):
    sid = os.environ.get("SUPER_ADMIN_ID", "").strip()
    if sid.isdigit() and not is_admin(int(sid)):
        add_admin(int(sid)); logging.info(f"Super admin {sid} added.")

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
