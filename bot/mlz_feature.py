from .shared import *
import re as _re

# ── استدعاء Gemini نصياً ──────────────────────────────────────────
async def _call_gemini_text(prompt: str) -> str | None:
    keys = get_all_gemini_keys()
    if not keys:
        return None
    models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient() as client:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for key in keys:
                try:
                    resp = await client.post(url, params={"key": key}, json=payload, timeout=30)
                    if resp.status_code in (429, 503):
                        continue
                    if resp.status_code == 404:
                        break
                    resp.raise_for_status()
                    text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    if text:
                        return text
                except Exception as e:
                    logging.warning(f"[MLZ] Gemini error: {e}")
    return None

# ── استخراج المعلومات الأربع بالذكاء الاصطناعي ───────────────────
async def extract_mlz_info(source_text: str) -> dict:
    prompt = (
        "استخرج من النص التالي أربع معلومات بالضبط:\n"
        "1. المادة الدراسية (مثل: كيمياء، فيزياء، رياضيات، أحياء، عربي)\n"
        "2. اسم المدرس كاملاً\n"
        "3. الصف الدراسي (مثل: السادس علمي، السادس أدبي، الخامس علمي، الثالث متوسط)\n"
        "4. سنة الإصدار (أربعة أرقام مثل 2025)\n\n"
        f"النص: {source_text}\n\n"
        "أرجع JSON فقط بدون أي نص إضافي:\n"
        '{"subject": "", "teacher": "", "grade": "", "year": ""}\n'
        "إذا لم تجد معلومة اتركها فارغة تماماً."
    )
    try:
        raw = await _call_gemini_text(prompt)
        if not raw:
            return {}
        match = _re.search(r'\{[^{}]*\}', raw, _re.DOTALL)
        if not match:
            return {}
        data = json.loads(match.group())
        return {k: (v or "").strip() for k, v in data.items() if k in ("subject", "teacher", "grade", "year")}
    except Exception as e:
        logging.warning(f"[MLZ] extract_mlz_info error: {e}")
        return {}

# ── تطبيع النص للمقارنة الناعمة ──────────────────────────────────
def _norm(text: str) -> str:
    text = text.strip()
    text = _re.sub(r'[\u064B-\u065F\u0670]', '', text)
    text = text.replace('ة', 'ه').replace('ى', 'ي')
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    return text.lower()

def _fuzzy_match(query: str, btns: list) -> dict | None:
    if not query or not btns:
        return None
    q = _norm(query)
    for b in btns:
        if _norm(b['label']) == q:
            return b
    for b in btns:
        lbl = _norm(b['label'])
        if q in lbl or lbl in q:
            return b
    q_words = set(w for w in q.split() if len(w) > 1)
    best, best_score = None, 0
    for b in btns:
        lbl_words = set(w for w in _norm(b['label']).split() if len(w) > 1)
        score = len(q_words & lbl_words)
        if score > best_score:
            best_score = score
            best = b
    return best if best_score >= 1 else None

# ── البحث عن المسار وإنشاء ما يلزم ──────────────────────────────
def find_or_build_mlz_path(grade: str, subject: str, teacher: str):
    """
    يبحث ويُنشئ المسار: الصف → الملازم (ثابت) → المادة → المدرس (مدمج)
    يُرجع: (grade_btn, mlz_btn, subject_btn, teacher_btn)
    أي منها قد يكون None عند الفشل.
    """
    root_btns = [b for b in get_buttons(None) if not b.get('deleted')]
    grade_btn = _fuzzy_match(grade, root_btns)
    if not grade_btn:
        return None, None, None, None

    grade_children = get_buttons(grade_btn['id'])
    mlz_keywords = ['ملزم', 'ملازم']
    mlz_btn = None
    for b in grade_children:
        lbl_n = _norm(b['label'])
        if any(kw in lbl_n for kw in mlz_keywords):
            mlz_btn = b
            break
    if not mlz_btn:
        return grade_btn, None, None, None

    mlz_children = [b for b in get_buttons(mlz_btn['id']) if b['type'] == 'menu']
    subject_btn = _fuzzy_match(subject, mlz_children)
    if not subject_btn:
        new_id = add_btn(mlz_btn['id'], 'menu', subject)
        subject_btn = get_btn(new_id)

    subject_children = [b for b in get_buttons(subject_btn['id']) if b['type'] == 'compound']
    teacher_btn = _fuzzy_match(teacher, subject_children)
    if not teacher_btn:
        new_id = add_btn(subject_btn['id'], 'compound', teacher)
        teacher_btn = get_btn(new_id)

    return grade_btn, mlz_btn, subject_btn, teacher_btn

def _build_desc(subject, teacher, grade, year):
    return f"{subject} - {teacher} - {grade} - {year}"

def _build_btn_name(mlz_type, year):
    return f"📌 {mlz_type} {year}📌"

def _clear_mlz(ctx):
    for key in [
        'mlz_file_type', 'mlz_file_id', 'mlz_subject', 'mlz_teacher',
        'mlz_grade', 'mlz_year', 'mlz_desc', 'mlz_path_str',
    ]:
        ctx.user_data.pop(key, None)
    ctx.user_data.pop('state', None)

# ── السؤال عن أول معلومة ناقصة أو عرض التأكيد ───────────────────
async def _ask_next_missing(m, ctx, uid, chat_id):
    fields = [
        ('mlz_subject', 'wait_mlz_subject',
         '📚 ما هي *المادة الدراسية*؟\n_(مثال: كيمياء، فيزياء، رياضيات)_'),
        ('mlz_teacher', 'wait_mlz_teacher',
         '👨‍🏫 ما هو *اسم المدرس* كاملاً؟'),
        ('mlz_grade', 'wait_mlz_grade',
         '🏫 ما هو *الصف الدراسي*؟\n_(مثال: السادس علمي، الخامس علمي)_'),
        ('mlz_year', 'wait_mlz_year',
         '📅 ما هي *سنة الإصدار*؟\n_(مثال: 2025)_'),
    ]
    for key, state, question in fields:
        if not ctx.user_data.get(key):
            ctx.user_data['state'] = state
            await m.reply_text(question, parse_mode='Markdown')
            return
    await _show_mlz_confirm(m, ctx, uid, chat_id)

# ── عرض شاشة التأكيد ─────────────────────────────────────────────
async def _show_mlz_confirm(m, ctx, uid, chat_id):
    subject = ctx.user_data.get('mlz_subject', '')
    teacher = ctx.user_data.get('mlz_teacher', '')
    grade   = ctx.user_data.get('mlz_grade', '')
    year    = ctx.user_data.get('mlz_year', '')

    grade_btn, mlz_btn, subject_btn, teacher_btn = find_or_build_mlz_path(grade, subject, teacher)

    if not grade_btn:
        ctx.user_data['mlz_grade'] = ''
        ctx.user_data['state'] = 'wait_mlz_grade'
        await m.reply_text(
            f"⚠️ لم أجد زراً للصف *{grade}* في القائمة الرئيسية.\n\n"
            "أرسل اسم الصف كما هو مكتوب بالضبط في البوت:",
            parse_mode='Markdown'
        )
        return

    if not mlz_btn:
        await m.reply_text(
            f"⚠️ لم أجد زر *الملازم* داخل *{grade_btn['label']}*.\n\n"
            "تأكد من وجود زر الملازم داخل هذا الصف ثم أعد المحاولة."
        )
        _clear_mlz(ctx)
        return

    path_parts = [
        grade_btn['label'],
        mlz_btn['label'],
        subject_btn['label'] if subject_btn else subject,
        teacher_btn['label'] if teacher_btn else teacher,
    ]
    path_str = " ← ".join(path_parts)
    desc = _build_desc(subject, teacher, grade, year)
    ctx.user_data['mlz_path_str'] = path_str

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأكيد", callback_data="mlz_confirm"),
        InlineKeyboardButton("✏️ تعديل الوصف", callback_data="mlz_edit"),
    ]])
    await m.reply_text(
        f"📂 *الموقع:*\n`{path_str}`\n\n"
        f"📝 *الوصف:*\n`{desc}`\n\n"
        "هل المعلومات صحيحة؟",
        parse_mode='Markdown',
        reply_markup=markup
    )

# ── بدء تدفق الملزمة ─────────────────────────────────────────────
async def start_mlz_flow(m, ctx, uid, chat_id) -> bool:
    from .content_delivery import detect_content
    file_type, caption, file_id = detect_content(m)
    if not file_type or file_type == 'text':
        return False

    ctx.user_data['mlz_file_type'] = file_type
    ctx.user_data['mlz_file_id']   = file_id

    source_text = ""
    if caption:
        source_text += caption + " "
    if m.document and m.document.file_name:
        source_text += m.document.file_name
    source_text = source_text.strip()

    wait_msg = await m.reply_text("⏳ جاري تحليل الملف بالذكاء الاصطناعي...")

    if source_text and get_all_gemini_keys():
        info = await extract_mlz_info(source_text)
    else:
        info = {}

    ctx.user_data['mlz_subject'] = info.get('subject', '')
    ctx.user_data['mlz_teacher'] = info.get('teacher', '')
    ctx.user_data['mlz_grade']   = info.get('grade', '')
    ctx.user_data['mlz_year']    = info.get('year', '')

    try:
        await wait_msg.delete()
    except Exception:
        pass

    await _ask_next_missing(m, ctx, uid, chat_id)
    return True

# ── callback: تأكيد ───────────────────────────────────────────────
async def after_mlz_confirm(q, ctx, uid, chat_id):
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    ctx.user_data['state'] = 'wait_mlz_type'
    await q.message.reply_text(
        "📌 *ما نوع الملزمة؟*\n_(مثال: مراجعة، ملخص، نموذج امتحان)_",
        parse_mode='Markdown'
    )

# ── callback: تعديل الوصف ────────────────────────────────────────
async def after_mlz_edit(q, ctx, uid, chat_id):
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    subject = ctx.user_data.get('mlz_subject', '')
    teacher = ctx.user_data.get('mlz_teacher', '')
    grade   = ctx.user_data.get('mlz_grade', '')
    year    = ctx.user_data.get('mlz_year', '')
    current_desc = _build_desc(subject, teacher, grade, year)
    ctx.user_data['state'] = 'wait_mlz_desc'
    await q.message.reply_text(
        f"✏️ *اكتب الوصف كاملاً:*\n\nالوصف الحالي:\n`{current_desc}`",
        parse_mode='Markdown'
    )

# ── الإنهاء: إنشاء الأزرار وإضافة الملف ─────────────────────────
async def finish_mlz_flow(m, ctx, uid, chat_id, bot, mlz_type: str):
    from .content_delivery import upload_to_channel

    subject   = ctx.user_data.get('mlz_subject', '')
    teacher   = ctx.user_data.get('mlz_teacher', '')
    grade     = ctx.user_data.get('mlz_grade', '')
    year      = ctx.user_data.get('mlz_year', '')
    desc      = ctx.user_data.get('mlz_desc') or _build_desc(subject, teacher, grade, year)
    file_type = ctx.user_data.get('mlz_file_type')
    file_id   = ctx.user_data.get('mlz_file_id')

    if not file_id or not file_type:
        await m.reply_text("⚠️ حدث خطأ: بيانات الملف مفقودة. أعد إرسال الملف.")
        _clear_mlz(ctx)
        return

    wait_msg = await m.reply_text("⏳ جاري الإنشاء وإضافة الملف...")

    grade_btn, mlz_btn, subject_btn, teacher_btn = find_or_build_mlz_path(grade, subject, teacher)

    if not grade_btn or not mlz_btn:
        await wait_msg.edit_text("⚠️ حدث خطأ في تحديد المسار. أعد المحاولة.")
        _clear_mlz(ctx)
        return

    btn_name    = _build_btn_name(mlz_type, year)
    content_bid = add_btn(teacher_btn['id'], 'content', btn_name)

    channel_msg_id = await upload_to_channel(bot, file_id, file_type, desc)

    if get_storage_channel_id() and not channel_msg_id:
        del_btn(content_bid)
        await wait_msg.edit_text(
            "⚠️ لم يتم الحفظ لأن رفع الملف لقناة التخزين فشل.\n"
            "تأكد أن البوت أدمن في قناة التخزين."
        )
        _clear_mlz(ctx)
        return

    add_item(content_bid, file_type, desc, file_id, None, channel_msg_id)

    path_str = " ← ".join([
        grade_btn['label'],
        mlz_btn['label'],
        subject_btn['label'],
        teacher_btn['label'],
        btn_name,
    ])

    await wait_msg.edit_text(
        f"✅ *تمت الإضافة بنجاح!*\n\n"
        f"📂 *الموقع:*\n`{path_str}`\n\n"
        f"📝 *الوصف:*\n`{desc}`",
        parse_mode='Markdown'
    )
    _clear_mlz(ctx)

__all__ = [name for name in globals() if not name.startswith("__")]
