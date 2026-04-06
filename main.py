import logging
import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DB = "data.db"

ICONS = {"menu": "📂", "text": "📄", "photo": "📄", "file": "📄", "video": "📄", "audio": "📄", "content": "📄"}

# ── أزرار خاصة ───────────────────────────────────────────────────
BTN_BACK      = "🔙 رجوع"
BTN_ADD       = "➕ إضافة"
BTN_MANAGE    = "⚙️ إدارة"
BTN_ADMINS    = "👥 مشرفون"
BTN_CANCEL    = "❌ إلغاء"

TYPE_MAP = {
    "📂 قائمة":  "menu",
    "📄 محتوى": "content",
}

ADMIN_BTNS   = {BTN_ADD, BTN_MANAGE, BTN_ADMINS}
SPECIAL_BTNS = {BTN_BACK, BTN_ADD, BTN_MANAGE, BTN_ADMINS, BTN_CANCEL} | set(TYPE_MAP.keys())

# ── قاعدة البيانات ───────────────────────────────────────────────
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
                content TEXT, file_id TEXT, ord INTEGER DEFAULT 0
            );
        """)

def is_admin(uid):
    return db().execute("SELECT 1 FROM admins WHERE id=?", (uid,)).fetchone() is not None

def add_admin(uid, name=None):
    c = db(); c.execute("INSERT OR IGNORE INTO admins VALUES(?,?)", (uid, name)); c.commit(); c.close()

def del_admin(uid):
    c = db(); c.execute("DELETE FROM admins WHERE id=?", (uid,)); c.commit(); c.close()

def all_admins():
    return [dict(r) for r in db().execute("SELECT * FROM admins").fetchall()]

def get_buttons(pid=None):
    q = "SELECT * FROM buttons WHERE parent_id IS NULL ORDER BY ord,id" if pid is None \
        else "SELECT * FROM buttons WHERE parent_id=? ORDER BY ord,id"
    return [dict(r) for r in (db().execute(q) if pid is None else db().execute(q, (pid,))).fetchall()]

def get_btn(bid):
    r = db().execute("SELECT * FROM buttons WHERE id=?", (bid,)).fetchone()
    return dict(r) if r else None

def add_btn(pid, t, label, content=None, file_id=None):
    c = db(); cur = c.cursor()
    q = "SELECT COALESCE(MAX(ord),0)+1 FROM buttons WHERE parent_id IS NULL" if pid is None \
        else "SELECT COALESCE(MAX(ord),0)+1 FROM buttons WHERE parent_id=?"
    n = (cur.execute(q) if pid is None else cur.execute(q, (pid,))).fetchone()[0]
    cur.execute("INSERT INTO buttons(parent_id,type,label,content,file_id,ord) VALUES(?,?,?,?,?,?)",
                (pid, t, label, content, file_id, n))
    c.commit(); lid = cur.lastrowid; c.close(); return lid

def upd_btn(bid, label=None, content=None, file_id=None):
    c = db(); cur = c.cursor()
    if label   is not None: cur.execute("UPDATE buttons SET label=?   WHERE id=?", (label,   bid))
    if content is not None: cur.execute("UPDATE buttons SET content=? WHERE id=?", (content, bid))
    if file_id is not None: cur.execute("UPDATE buttons SET file_id=? WHERE id=?", (file_id, bid))
    c.commit(); c.close()

def del_btn(bid):
    c = db(); c.execute("DELETE FROM buttons WHERE id=?", (bid,)); c.commit(); c.close()

def move_btn(bid, direction):
    c = db(); cur = c.cursor()
    row = dict(cur.execute("SELECT * FROM buttons WHERE id=?", (bid,)).fetchone())
    pid = row["parent_id"]
    q = "SELECT id FROM buttons WHERE parent_id IS NULL ORDER BY ord,id" if pid is None \
        else "SELECT id FROM buttons WHERE parent_id=? ORDER BY ord,id"
    ids = [r[0] for r in (cur.execute(q) if pid is None else cur.execute(q, (pid,))).fetchall()]
    i = ids.index(bid); j = i - 1 if direction == "up" else i + 1
    if not (0 <= j < len(ids)): c.close(); return
    o1 = cur.execute("SELECT ord FROM buttons WHERE id=?", (bid,)).fetchone()[0]
    o2 = cur.execute("SELECT ord FROM buttons WHERE id=?", (ids[j],)).fetchone()[0]
    cur.execute("UPDATE buttons SET ord=? WHERE id=?", (o2, bid))
    cur.execute("UPDATE buttons SET ord=? WHERE id=?", (o1, ids[j]))
    c.commit(); c.close()

# ── بناء الكيبورد ────────────────────────────────────────────────
def build_kb(uid, pid=None):
    btns = get_buttons(pid)
    rows = [[KeyboardButton(f"{ICONS.get(b['type'],'')} {b['label']}")] for b in btns]
    if pid is not None:
        rows.append([KeyboardButton(BTN_BACK)])
    if is_admin(uid):
        rows.append([KeyboardButton(BTN_ADD), KeyboardButton(BTN_MANAGE), KeyboardButton(BTN_ADMINS)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True) if (rows or is_admin(uid)) else None

def build_type_kb():
    return ReplyKeyboardMarkup([
        ["📂 قائمة", "📄 محتوى"],
        [BTN_CANCEL],
    ], resize_keyboard=True)

# ── لوحة إدارة الأزرار (Inline) ─────────────────────────────────
def kb_manage(pid=None):
    rows = []
    for b in get_buttons(pid):
        rows.append([
            InlineKeyboardButton(f"{ICONS.get(b['type'],'')} {b['label']}", callback_data=f"e_{b['id']}"),
            InlineKeyboardButton("⬆️", callback_data=f"u_{b['id']}"),
            InlineKeyboardButton("⬇️", callback_data=f"d_{b['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"x_{b['id']}"),
        ])
    ctx = "r" if pid is None else str(pid)
    rows.append([InlineKeyboardButton("➕ إضافة هنا", callback_data=f"add_{ctx}")])
    if pid is not None:
        b = get_btn(pid); back = b["parent_id"] if b else None
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="m_r" if back is None else f"m_{back}")])
    return InlineKeyboardMarkup(rows)

def kb_edit_btn(bid):
    b = get_btn(bid); rows = []
    if b and b["type"] == "menu":
        rows.append([InlineKeyboardButton("📂 فتح القائمة", callback_data=f"m_{bid}")])
    rows += [
        [InlineKeyboardButton("✏️ تعديل الاسم",    callback_data=f"el_{bid}")],
        [InlineKeyboardButton("✏️ تعديل المحتوى", callback_data=f"ec_{bid}")],
        [InlineKeyboardButton("🗑 حذف",             callback_data=f"x_{bid}")],
    ]
    pid = b["parent_id"] if b else None
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="m_r" if pid is None else f"m_{pid}")])
    return InlineKeyboardMarkup(rows)

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

# ── مساعد لوحة التحكم ────────────────────────────────────────────
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

# ── اكتشاف نوع المحتوى تلقائياً ─────────────────────────────────
def detect_content(m):
    """Returns (type, content, file_id) from a message, or (None,None,None)."""
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

# ── /start ───────────────────────────────────────────────────────
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

# ── معالج الرسائل الرئيسي ────────────────────────────────────────
async def on_message(update: Update, ctx):
    m = update.message
    uid = update.effective_user.id
    text = (m.text or "").strip()
    state = ctx.user_data.get("state")
    pid = ctx.user_data.get("pid")          # القائمة الحالية للتصفح
    chat_id = m.chat_id

    # ── حالات انتظار الإدخال ──────────────────────────────────────
    if state == "wait_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للاسم."); return
        t = ctx.user_data.get("new_type"); add_pid = ctx.user_data.get("add_pid")
        if t == "menu":
            add_btn(add_pid, "menu", text)
            ctx.user_data.pop("state", None); ctx.user_data.pop("new_type", None)
            await m.reply_text(f"✅ تم إنشاء القائمة *{text}*", parse_mode="Markdown",
                               reply_markup=build_kb(uid, pid))
        else:
            ctx.user_data["new_label"] = text; ctx.user_data["state"] = "wait_content"
            await m.reply_text("📤 أرسل المحتوى الآن:", reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True))
        return

    if state == "wait_content":
        add_pid = ctx.user_data.get("add_pid")
        label = ctx.user_data.get("new_label", "زر")
        t, content, fid = detect_content(m)
        if t is None:
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً أو فيديو أو صوتاً."); return
        add_btn(add_pid, t, label, content, fid)
        ctx.user_data.pop("state", None)
        await m.reply_text(f"✅ تم إضافة *{label}*", parse_mode="Markdown",
                           reply_markup=build_kb(uid, pid))
        return

    if state == "wait_edit_label":
        if not text or text in SPECIAL_BTNS: await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        bid = ctx.user_data.get("edit_bid"); upd_btn(bid, label=text)
        b = get_btn(bid); ep = b["parent_id"] if b else None
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, f"✅ تم تغيير الاسم إلى *{text}*", kb_manage(ep))
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    if state == "wait_edit_content":
        bid = ctx.user_data.get("edit_bid")
        t, content, fid = detect_content(m)
        if t is None or (t == "text" and text in SPECIAL_BTNS):
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً أو فيديو أو صوتاً."); return
        upd_btn(bid, content=content, file_id=fid)
        b = get_btn(bid); ep = b["parent_id"] if b else None
        # update the stored type too
        conn = db(); conn.execute("UPDATE buttons SET type=? WHERE id=?", (t, bid)); conn.commit(); conn.close()
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, "✅ تم تحديث المحتوى.", kb_manage(ep))
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    if state == "wait_admin_id":
        try: tid = int(text)
        except ValueError: await m.reply_text("⚠️ أرسل رقم ID صحيح."); return
        add_admin(tid); ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id, f"✅ تمت إضافة المشرف.\n\n👥 *المشرفون* ({len(all_admins())}):", kb_admins_inline())
        await m.reply_text("✅", reply_markup=build_kb(uid, pid))
        return

    # ── اختيار النوع ──────────────────────────────────────────────
    if state == "wait_type" and text in TYPE_MAP:
        t = TYPE_MAP[text]; ctx.user_data["new_type"] = t; ctx.user_data["state"] = "wait_label"
        await m.reply_text("✏️ اكتب اسم الزر وأرسله:", reply_markup=build_kb(uid, pid))
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
        if text == BTN_ADD:
            ctx.user_data["state"] = "wait_type"; ctx.user_data["add_pid"] = pid
            await m.reply_text("اختر نوع الزر:", reply_markup=build_type_kb())
            return

        if text == BTN_MANAGE:
            await set_panel(ctx, chat_id, "⚙️ *إدارة الأزرار*:", kb_manage(pid))
            return

        if text == BTN_ADMINS:
            await set_panel(ctx, chat_id, f"👥 *المشرفون* ({len(all_admins())}):", kb_admins_inline())
            return

    # ── ضغط زر مستخدم (تصفح / محتوى) ────────────────────────────
    btns = get_buttons(pid)
    matched = next((b for b in btns if f"{ICONS.get(b['type'],'')} {b['label']}" == text), None)
    if not matched:
        return

    b = matched
    if b["type"] == "menu":
        ctx.user_data["pid"] = b["id"]
        await m.reply_text(f"📂 {b['label']}", reply_markup=build_kb(uid, b["id"]))

    elif b["type"] == "text":
        await m.reply_text(f"📝 *{b['label']}*\n\n{b.get('content') or ''}", parse_mode="Markdown",
                           reply_markup=build_kb(uid, pid))

    elif b["type"] == "photo" and b.get("file_id"):
        cap = f"🖼 *{b['label']}*" + (f"\n\n{b['content']}" if b.get("content") else "")
        await m.reply_photo(b["file_id"], caption=cap, parse_mode="Markdown")

    elif b["type"] == "file" and b.get("file_id"):
        cap = f"📎 *{b['label']}*" + (f"\n\n{b['content']}" if b.get("content") else "")
        await m.reply_document(b["file_id"], caption=cap, parse_mode="Markdown")

    elif b["type"] == "video" and b.get("file_id"):
        cap = f"🎬 *{b['label']}*" + (f"\n\n{b['content']}" if b.get("content") else "")
        await m.reply_video(b["file_id"], caption=cap, parse_mode="Markdown")

    elif b["type"] == "audio" and b.get("file_id"):
        cap = f"🎵 *{b['label']}*" + (f"\n\n{b['content']}" if b.get("content") else "")
        await m.reply_audio(b["file_id"], caption=cap, parse_mode="Markdown")

    else:
        await m.reply_text("❌ لا يوجد محتوى.")

# ── معالج أزرار لوحة الإدارة (Inline) ───────────────────────────
async def cb_manage(update: Update, ctx):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_admin(uid): return
    d = q.data; chat_id = q.message.chat_id
    ctx.user_data["panel_id"] = q.message.message_id
    pid = ctx.user_data.get("pid")

    if d == "cancel":
        await q.edit_message_text("✅ تم الإلغاء."); return

    if d == "m_r":
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage()); return

    if d.startswith("m_"):
        ep = int(d[2:]); b = get_btn(ep)
        await q.edit_message_text(f"📂 *{b['label']}*", parse_mode="Markdown",
                                  reply_markup=kb_manage(ep)); return

    if d.startswith("e_"):
        bid = int(d[2:]); b = get_btn(bid)
        await q.edit_message_text(f"*{b['label']}*  —  {ICONS.get(b['type'],'')} {b['type']}",
                                  parse_mode="Markdown", reply_markup=kb_edit_btn(bid)); return

    if d.startswith("u_") or d.startswith("d_"):
        up = d.startswith("u_"); bid = int(d[2:])
        move_btn(bid, "up" if up else "down")
        b = get_btn(bid)
        await q.edit_message_reply_markup(reply_markup=kb_manage(b["parent_id"])); return

    if d.startswith("x_"):
        bid = int(d[2:]); b = get_btn(bid); ep = b["parent_id"] if b else None
        del_btn(bid)
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage(ep)); return

    if d.startswith("add_"):
        pctx = d[4:]; ep = None if pctx == "r" else int(pctx)
        ctx.user_data["state"] = "wait_type"; ctx.user_data["add_pid"] = ep
        await q.message.reply_text("اختر نوع الزر:", reply_markup=build_type_kb()); return

    if d.startswith("el_"):
        bid = int(d[3:]); ctx.user_data["edit_bid"] = bid; b = get_btn(bid)
        ctx.user_data["state"] = "wait_edit_label"
        await q.edit_message_text(f"✏️ الاسم الحالي: *{b['label']}*\n\nاكتب الاسم الجديد:",
                                  parse_mode="Markdown", reply_markup=kb_cancel_inline()); return

    if d.startswith("ec_"):
        bid = int(d[3:]); b = get_btn(bid)
        if b["type"] == "menu": await q.answer("القوائم لا تحتوي محتوى مباشر.", show_alert=True); return
        ctx.user_data["edit_bid"] = bid
        ctx.user_data["state"] = "wait_edit_content"
        await q.edit_message_text("✏️ أرسل المحتوى الجديد (نص أو صورة أو ملف...):", reply_markup=kb_cancel_inline()); return

    if d == "aa":
        ctx.user_data["state"] = "wait_admin_id"
        await q.edit_message_text("👤 أرسل معرّف المستخدم (ID):", reply_markup=kb_cancel_inline()); return

    if d.startswith("da_"):
        tid = int(d[3:])
        if tid == uid: await q.answer("❌ لا يمكنك إزالة نفسك!", show_alert=True); return
        del_admin(tid)
        await q.edit_message_text(f"👥 *المشرفون* ({len(all_admins())}):",
                                  parse_mode="Markdown", reply_markup=kb_admins_inline()); return

    if d == "noop": return

# ── إعداد البوت ─────────────────────────────────────────────────
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
