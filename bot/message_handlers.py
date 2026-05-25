from .shared import *

async def cmd_start(update: Update, ctx):
    uid = update.effective_user.id
    ctx.user_data.clear()
    kb = build_kb(uid)
    start_msg = get_start_message()
    if not kb:
        await update.message.reply_text(f"{start_msg}\n\n👋 لا توجد أزرار متاحة حالياً.")
        return
    await update.message.reply_text(start_msg, reply_markup=kb)
    if not is_admin(uid):
        inc_user_sessions(uid)

async def cmd_myid(update: Update, ctx):
    await update.message.reply_text(f"🆔 `{update.effective_user.id}`", parse_mode="Markdown")

async def cmd_storage_status(update: Update, ctx):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    ch = get_storage_channel_id()
    summary = get_storage_summary()
    access_text = "غير مفحوص"
    if ch:
        try:
            me = await ctx.bot.get_me()
            member = await ctx.bot.get_chat_member(ch, me.id)
            access_text = f"متصل بالقناة — صلاحية البوت: {member.status}"
        except Exception as e:
            access_text = f"تعذر الوصول للقناة: {e}"
    else:
        access_text = "لم يتم تحديد قناة تخزين"
    await update.message.reply_text(
        "📦 *حالة تخزين الملفات*\n\n"
        f"قناة التخزين: `{ch or 'غير محددة'}`\n"
        f"الفحص: {access_text}\n\n"
        f"كل الملفات: *{summary.get('total_files') or 0}*\n"
        f"محفوظة بالقناة: *{summary.get('in_channel') or 0}*\n"
        f"ناقصة من القناة: *{summary.get('missing_channel') or 0}*\n"
        f"يمكن إصلاحها من ملفات محلية: *{summary.get('repairable_local') or 0}*\n"
        f"يمكن تجربتها عبر file_id الحالي: *{summary.get('repairable_file_id') or 0}*\n\n"
        "لإصلاح الناقص أرسل /repair_storage",
        parse_mode="Markdown"
    )

async def cmd_repair_storage(update: Update, ctx):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    ch = get_storage_channel_id()
    if not ch:
        await update.message.reply_text("⚠️ لم يتم تحديد قناة التخزين.")
        return
    items = get_items_missing_channel()
    if not items:
        await update.message.reply_text("✅ كل الملفات محفوظة في قناة التخزين.")
        return
    status_msg = await update.message.reply_text(f"🔄 جاري إصلاح {len(items)} ملف ناقص...")
    fixed = 0
    failed = []
    for item in items:
        channel_msg_id = await upload_item_to_channel(ctx.bot, item)
        if channel_msg_id:
            upd_item_channel_msg_id(item["id"], channel_msg_id)
            fixed += 1
        else:
            failed.append(item["id"])
    text = (
        "📦 *نتيجة إصلاح التخزين*\n\n"
        f"✅ تم إصلاح: *{fixed}*\n"
        f"⚠️ بقي بدون إصلاح: *{len(failed)}*"
    )
    if failed:
        sample = ", ".join(str(i) for i in failed[:30])
        text += (
            f"\n\nالعناصر المتبقية: `{sample}`\n"
            "إذا كانت هذه الملفات أُضيفت بالتوكن القديم ولا توجد لها نسخة محلية، شغّل البوت مؤقتاً بالتوكن القديم ثم أرسل /repair_storage حتى تُرفع للقناة."
        )
    await status_msg.edit_text(text, parse_mode="Markdown")

async def _show_cloned_panel(ctx, chat_id, new_bid, cloned_label, cloned_type):
    """يعرض لوحة الإدارة المناسبة بعد استنساخ زر."""
    if cloned_type == "content":
        items = get_items(new_bid)
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}📄 *{cloned_label}*\n_{len(items)} عنصر منسوخ_",
                        kb_content_panel(new_bid))
    elif cloned_type == "quiz":
        qs = get_quiz_questions(new_bid)
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}📊 *{cloned_label}*\n_{len(qs)} سؤال منسوخ_",
                        kb_quiz_panel(new_bid))
    elif cloned_type == "exam":
        qs = get_exam_questions(new_bid)
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}📝 *{cloned_label}*\n_{len(qs)} سؤال منسوخ_",
                        kb_exam_panel(new_bid))
    elif cloned_type == "compound":
        ch = get_buttons(new_bid)
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}🧩 *{cloned_label}*\n_{len(ch)} زر داخلي منسوخ_",
                        kb_compound_quick(new_bid))
    elif cloned_type == "exam_group":
        ch = get_buttons(new_bid)
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}🎓 *{cloned_label}*\n_{len(ch)} موضوع منسوخ_",
                        kb_exam_group_quick(new_bid))
    elif cloned_type == "special":
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}⭐ *{cloned_label}*\n_زر مخصص — منسوخ_",
                        kb_special_manage(new_bid))
    else:
        ch = get_buttons(new_bid)
        await set_panel(ctx, chat_id,
                        f"{btn_id_header(new_bid)}📂 *{cloned_label}*\n_{len(ch)} زر منسوخ_",
                        kb_menu_quick(new_bid))

# ── معالج الرسائل الرئيسي ─────────────────────────────────────────
async def on_message(update: Update, ctx):
    m = update.message
    uid = update.effective_user.id
    raw_text = (m.text or "").strip()
    # نفك البصمة غير المرئية الملصقة بنص أزرار الردود لمعرفة الزر المضغوط
    # بدقة حتى لو وُجد أكثر من زر بنفس الاسم في أماكن مختلفة.
    text, marker_bid = _decode_bid(raw_text)
    state = ctx.user_data.get("state")
    pid = ctx.user_data.get("pid")
    chat_id = m.chat_id

    track_message(uid)
    _u = update.effective_user
    update_user_info(uid, username=_u.username, first_name=_u.first_name)
    if is_admin(uid) and _u.username:
        update_admin_username(uid, _u.username)

    if state == "wait_file_upload":
        if is_bot_button_text(text, pid) and not (m.document or m.photo or m.video or m.audio or m.voice):
            ctx.user_data.pop("state", None)
            state = None
        else:
            t, content, fid = detect_content(m)
            if t is None or t == "text":
                await m.reply_text(
                    "⚠️ الرجاء إرسال ملف (صورة، مستند، فيديو، أو صوت).",
                    reply_markup=kb_file_upload_cancel()
                )
                return
            ctx.user_data.pop("state", None)
            admins = get_file_request_admins()
            if not admins:
                admins = [{"user_id": a["id"], "username": a.get("username")} for a in all_admins()]
            user = update.effective_user
            username = f"@{user.username}" if user.username else "لا يوجد"
            full_name = user.full_name or "مستخدم"
            def _escape_md(s: str) -> str:
                for ch in ("\\", "*", "_", "`", "["):
                    s = s.replace(ch, f"\\{ch}")
                return s
            header = (
                "📤 *ملف جديد من مستخدم*\n\n"
                f"👤 الاسم: *{_escape_md(full_name)}*\n"
                f"🆔 الآيدي: `{uid}`\n"
                f"🔗 اليوزر: {_escape_md(username)}"
            )
            reply_btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ رد على المستخدم", callback_data=f"freply_{uid}")
            ]])
            sent_count = 0
            for admin in admins:
                admin_id = admin["user_id"]
                try:
                    await ctx.bot.send_message(admin_id, header, parse_mode="Markdown")
                    copied = await ctx.bot.copy_message(
                        chat_id=admin_id,
                        from_chat_id=chat_id,
                        message_id=m.message_id,
                        reply_markup=reply_btn
                    )
                    save_file_reply_session(admin_id, copied.message_id, uid)
                    sent_count += 1
                except Exception as e:
                    logging.warning(f"file upload forward failed to {admin_id}: {e}")
            thanks_msg = get_setting(
                "file_upload_thanks_message",
                "❤️ *شكراً جزيلاً!*\n\nتم استلام ملفك وسيتم مراجعته من قبل المشرفين."
            )
            if sent_count:
                try:
                    await m.reply_text(
                        thanks_msg,
                        parse_mode="Markdown",
                        api_kwargs={"message_effect_id": "5159385139981059251"}
                    )
                except Exception:
                    await m.reply_text(thanks_msg, parse_mode="Markdown")
            else:
                await m.reply_text("⚠️ تعذر تحويل ملفك حالياً. حاول مرة أخرى لاحقاً.")
            return

    if state == "wait_fu_thanks":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً لرسالة الشكر."); return
        set_setting("file_upload_thanks_message", m.text)
        bid = ctx.user_data.pop("fu_thanks_bid", None)
        ctx.user_data.pop("state", None)
        b = get_btn(bid) if bid else None
        await m.reply_text("✅ تم حفظ رسالة الشكر.", reply_markup=build_kb(uid, pid))
        if bid and b:
            await set_panel(ctx, chat_id,
                            f"⭐ *{b['label']}* (#{bid})\n_زر رفع الملفات_\n\n✅ رسالة الشكر:\n{m.text}",
                            kb_special_quick(bid))
        return

    if state == "wait_file_request":
        if is_bot_button_text(text, pid):
            ctx.user_data.pop("file_request_bid", None)
            ctx.user_data.pop("state", None)
            state = None
        else:
            bid = ctx.user_data.pop("file_request_bid", None)
            ctx.user_data.pop("state", None)
            admins = get_file_request_admins()
            if not admins:
                admins = [{"user_id": a["id"], "username": a.get("username")} for a in all_admins()]
            user = update.effective_user
            username = f"@{user.username}" if user.username else "لا يوجد"
            full_name = user.full_name or "مستخدم"
            def _escape_md(t: str) -> str:
                for ch in ("\\", "*", "_", "`", "["):
                    t = t.replace(ch, f"\\{ch}")
                return t
            header = (
                "📩 *طلب إضافة ملف جديد*\n\n"
                f"👤 الاسم: *{_escape_md(full_name)}*\n"
                f"🆔 الآيدي: `{uid}`\n"
                f"🔗 اليوزر: {_escape_md(username)}\n\n"
                "محتوى الطلب في الرسالة التالية:"
            )
            reply_btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ رد على المستخدم", callback_data=f"freply_{uid}")
            ]])
            sent_count = 0
            for admin in admins:
                admin_id = admin["user_id"]
                try:
                    await ctx.bot.send_message(admin_id, header, parse_mode="Markdown")
                    copied = await ctx.bot.copy_message(
                        chat_id=admin_id,
                        from_chat_id=chat_id,
                        message_id=m.message_id,
                        reply_markup=reply_btn
                    )
                    save_file_reply_session(admin_id, copied.message_id, uid)
                    sent_count += 1
                except Exception as e:
                    logging.warning(f"file request forward failed to {admin_id}: {e}")
            if sent_count:
                await m.reply_text("✅ تم تحويل طلبك للمشرفين وسوف يتم الرد بأسرع وقت.")
            else:
                await m.reply_text("⚠️ تعذر تحويل طلبك حالياً. حاول مرة أخرى لاحقاً.")
            return

    # ── المستخدم في محادثة نشطة مع المشرف ────────────────────────────
    if not is_file_supervisor(uid) and not state and is_file_convo_active(uid):
        if is_bot_button_text(text, pid):
            clear_file_convo(uid)
            await m.reply_text("🔚 تم إنهاء المحادثة مع المشرف.", reply_markup=build_kb(uid, pid))
        else:
            admins = get_file_request_admins()
            if not admins:
                admins = [{"user_id": a["id"], "username": a.get("username")} for a in all_admins()]
            reply_btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ رد على المستخدم", callback_data=f"freply_{uid}")
            ]])
            for admin in admins:
                try:
                    copied = await ctx.bot.copy_message(
                        chat_id=admin["user_id"],
                        from_chat_id=chat_id,
                        message_id=m.message_id,
                        reply_markup=reply_btn
                    )
                    save_file_reply_session(admin["user_id"], copied.message_id, uid)
                except Exception as e:
                    logging.warning(f"active convo forward to admin failed: {e}")
            return

    # ── رد المستخدم على رسالة المشرف (reply مباشر) ───────────────────
    if m.reply_to_message and not is_file_supervisor(uid):
        replied_mid = m.reply_to_message.message_id
        if is_user_reply_msg(uid, replied_mid):
            admins = get_file_request_admins()
            if not admins:
                admins = [{"user_id": a["id"], "username": a.get("username")} for a in all_admins()]
            sent_count = 0
            for admin in admins:
                try:
                    await ctx.bot.copy_message(
                        chat_id=admin["user_id"],
                        from_chat_id=chat_id,
                        message_id=m.message_id
                    )
                    sent_count += 1
                except Exception as e:
                    logging.warning(f"user reply to admin failed: {e}")
            if sent_count:
                await m.reply_text("✅ تم إرسال ردك للمشرفين.")
            else:
                await m.reply_text("⚠️ تعذر إرسال ردك.")
            return

    # ── رد المشرف على المستخدم (عبر زر الرد) ─────────────────────────
    if state and state.startswith("wait_freply_"):
        if is_bot_button_text(text, pid):
            ctx.user_data.pop("state", None)
            state = None
        else:
            target_uid = int(state.split("_", 2)[2])
            ctx.user_data.pop("state", None)
            try:
                copied = await ctx.bot.copy_message(
                    chat_id=target_uid,
                    from_chat_id=chat_id,
                    message_id=m.message_id
                )
                save_user_reply_session(target_uid, copied.message_id)
                set_file_convo_active(target_uid)
                await m.reply_text("✅ تم إرسال ردك للمستخدم.")
            except Exception as e:
                logging.warning(f"file reply to user failed: {e}")
                await m.reply_text("⚠️ تعذر إرسال الرد للمستخدم.")
            return

    # ── رد مباشر (Telegram reply) من المشرف على رسالة المستخدم ───────
    if m.reply_to_message and is_file_supervisor(uid):
        replied_mid = m.reply_to_message.message_id
        target_uid = get_file_reply_user(uid, replied_mid)
        if target_uid:
            try:
                copied = await ctx.bot.copy_message(
                    chat_id=target_uid,
                    from_chat_id=chat_id,
                    message_id=m.message_id
                )
                save_user_reply_session(target_uid, copied.message_id)
                set_file_convo_active(target_uid)
            except Exception as e:
                logging.warning(f"file direct reply to user failed: {e}")
                await m.reply_text("⚠️ تعذر إرسال الرد للمستخدم.")
            return

    if state == "wait_file_admin_id":
        if not m.text:
            await m.reply_text("⚠️ أرسل آيدي مشرف الملفات أو اليوزر، مثال: `123456` أو `@username`.", parse_mode="Markdown"); return
        raw_admin = m.text.strip()
        username = None
        if raw_admin.lstrip("-").isdigit():
            target_id = int(raw_admin)
        else:
            username = raw_admin.lstrip("@")
            known_admin = get_admin_by_username(username)
            if known_admin:
                target_id = known_admin["id"]
                username = known_admin.get("username") or username
            else:
                try:
                    chat = await ctx.bot.get_chat(f"@{username}")
                    target_id = chat.id
                    username = getattr(chat, "username", None) or username
                except Exception:
                    await m.reply_text(
                        "⚠️ ما قدرت أتعرف على هذا اليوزر.\n\n"
                        "حتى أضيفه باليوزر لازم يكون مشرف عام ومحدّث يوزره داخل البوت، أو أرسل الآيدي الرقمي مباشرة."
                    )
                    return
        bid = ctx.user_data.pop("file_admin_bid", None)
        ctx.user_data.pop("state", None)
        add_file_request_admin(target_id, username)
        await set_panel(ctx, chat_id, "👥 *مشرفين الملفات*", kb_file_request_admins(bid))
        await m.reply_text("✅ تم إضافة مشرف الملفات.", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار رقم الزر المراد استنساخه ──────────────────────────
    if state == "wait_clone_id":
        if not text or not text.strip().isdigit():
            await m.reply_text("⚠️ أرسل رقماً صحيحاً (ID الزر)."); return
        source_bid = int(text.strip())
        src = get_btn_any(source_bid)
        if src is None:
            await m.reply_text(
                f"⚠️ لا يوجد زر بالرقم *#{source_bid}*.\n\nأرسل رقماً صحيحاً.",
                parse_mode="Markdown"
            )
            return
        add_pid     = ctx.user_data.get("add_pid")
        add_after   = ctx.user_data.get("add_after", "END")
        add_new_row = ctx.user_data.get("add_new_row", 0)
        add_before  = ctx.user_data.get("add_before")
        new_bid = clone_btn(source_bid, add_pid,
                            add_after=add_after, add_before=add_before, new_row=add_new_row)
        if not new_bid:
            await m.reply_text("⚠️ حدث خطأ أثناء الاستنساخ. حاول مجدداً."); return
        cloned_b     = get_btn(new_bid)
        cloned_label = cloned_b["label"] if cloned_b else src["label"]
        cloned_type  = cloned_b["type"]  if cloned_b else src["type"]
        status_note  = " ♻️ _(مُستعاد من محذوف)_" if src.get("deleted") else " 📋 _(منسوخ)_"
        ctx.user_data.pop("state", None)
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_pid", None)
        ctx.user_data.pop("add_new_row", None); ctx.user_data.pop("add_before", None)
        ctx.user_data["pid"] = add_pid
        await m.reply_text(
            f"✅ تم استنساخ *{cloned_label}*{status_note}",
            parse_mode="Markdown",
            reply_markup=build_kb(uid, add_pid)
        )
        await _show_cloned_panel(ctx, chat_id, new_bid, cloned_label, cloned_type)
        return

    # ── انتظار اسم الزر ───────────────────────────────────────────
    if state == "wait_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للاسم."); return

        add_pid     = ctx.user_data.get("add_pid")
        add_after   = ctx.user_data.get("add_after", "END")
        add_new_row = ctx.user_data.get("add_new_row", 0)
        add_before  = ctx.user_data.get("add_before")

        t = ctx.user_data.get("new_type")
        if add_before is not None:
            bid = add_btn_before(add_before, add_pid, t, text)
        elif add_after != "END":
            bid = add_btn_after(add_after, add_pid, t, text, new_row=add_new_row)
        else:
            bid = add_btn(add_pid, t, text)
        ctx.user_data.pop("state", None); ctx.user_data.pop("new_type", None)
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_pid", None)
        ctx.user_data.pop("add_new_row", None); ctx.user_data.pop("add_before", None)
        from_exg = ctx.user_data.pop("_from_exg", None)
        from_compound = ctx.user_data.pop("_from_compound", None)
        ctx.user_data["pid"] = add_pid

        # عند إنشاء زر مدمج: لوحة الإدارة فارغة جاهزة لإضافة الأزرار الداخلية
        if t == "compound":
            await m.reply_text(f"✅ تم إنشاء *{text}*", parse_mode="Markdown",
                               reply_markup=build_kb(uid, add_pid))
            await set_panel(ctx, chat_id,
                            f"🧩 *{text}*\n\nزر مدمج جديد. اضغط ➕ إضافة زر داخلي لإنشاء أول زر.",
                            kb_compound_quick(bid))
            return

        # إنشاء زر داخلي تحت زر مدمج: نعود للوحة المدمج (الخيارات مستقلة لكل زر داخلي)
        if from_compound and t == "content":
            parent_b = get_btn(from_compound)
            new_pid = parent_b.get("parent_id") if parent_b else None
            ctx.user_data["pid"] = new_pid
            await m.reply_text(
                f"✅ تم إنشاء الزر الداخلي *{text}* — أضف محتواه الآن.",
                parse_mode="Markdown",
                reply_markup=build_kb(uid, new_pid)
            )
            items = get_items(bid)
            await set_panel(ctx, chat_id,
                            f"📄 *{text}*\n_{len(items)} عنصر_\n\nأضف محتوى الزر الداخلي:",
                            kb_content_panel(bid))
            return

        await m.reply_text(f"✅ تم إنشاء *{text}*", parse_mode="Markdown",
                           reply_markup=build_kb(uid, add_pid))
        if t == "content":
            await set_panel(ctx, chat_id,
                            f"📄 *{text}*\n\nلا يوجد محتوى بعد. اضغط ➕ لإضافة محتوى.",
                            kb_content_panel(bid))
        elif t == "exam_group":
            await set_panel(ctx, chat_id,
                            f"🎓 *{text}*\n\nزر امتحان رئيسي. اضغط على إدارة المواضيع لإضافة الاختبارات.",
                            kb_exam_group_quick(bid))
        elif t == "exam":
            parent_btn = get_btn(add_pid) if add_pid else None
            if parent_btn and parent_btn["type"] == "exam_group":
                await set_panel(ctx, chat_id,
                                f"📝 *{text}*\n\n_موضوع جديد — أضف أسئلته الآن._",
                                kb_exam_panel(bid))
            else:
                await set_panel(ctx, chat_id,
                                f"📝 *{text}*\n\nلا يوجد أسئلة بعد. اضغط ➕ لإضافة سؤال.",
                                kb_exam_panel(bid))
        elif t == "special":
            await set_panel(ctx, chat_id,
                            f"⭐ *{text}*\n🔢 رقم الزر (ID): `{bid}`\n\n_هذا الزر مخصص — سلوكه يُحدَّد برمجياً._",
                            kb_special_manage(bid))
        elif t == "quiz":
            await set_panel(ctx, chat_id,
                            f"📊 *{text}*\n\nلا يوجد أسئلة بعد. اضغط ➕ لإضافة سؤال.",
                            kb_quiz_panel(bid))
        return

    # ── انتظار محتوى جديد لزر موجود ──────────────────────────────
    if state == "wait_item_content":
        if m.text and is_bot_button_text(text, pid):
            ctx.user_data.pop("state", None)
            ctx.user_data.pop("item_bid", None)
            await clear_add_content_control(ctx, chat_id)
            state = None
            await m.reply_text("✅ تم إنهاء إضافة المحتوى.", reply_markup=build_kb(uid, pid))
        else:
            bid = ctx.user_data.get("item_bid")
            t, content, fid = detect_content(m)
            if t is None:
                await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً أو فيديو أو صوتاً."); return
            channel_msg_id = None
            if fid:
                channel_msg_id = await upload_to_channel(ctx.bot, fid, t, content)
                if get_storage_channel_id() and not channel_msg_id:
                    await m.reply_text(
                        "⚠️ لم يتم حفظ الملف.\n\n"
                        "السبب: تعذر رفعه إلى قناة التخزين. حتى تبقى الملفات تعمل بعد تغيير التوكن، يجب أن يكون البوت أدمن في قناة التخزين وأن يكون آيدي القناة صحيحاً.",
                        reply_markup=kb_add_content_active(bid)
                    )
                    return
            add_item(bid, t, content, fid, None, channel_msg_id)
            b = get_btn(bid)
            items = get_items(bid)
            await set_panel(ctx, chat_id,
                            f"📄 *{b['label']}*\n_{len(items)} عنصر_",
                            kb_content_panel(bid))
            await clear_add_content_control(ctx, chat_id)
            control_msg = await m.reply_text(
                f"✅ تمت الإضافة. العدد الحالي: *{len(items)}*\n\n"
                "أرسل محتوى آخر، أو اضغط ✅ انتهاء الإضافة.",
                parse_mode="Markdown",
                reply_markup=kb_add_content_active(bid)
            )
            ctx.user_data["add_content_control_msg_id"] = control_msg.message_id
            return

    # ── انتظار نص رسالة الزر المدمج ─────────────────────────────
    if state == "wait_compound_text":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للرسالة."); return
        bid = ctx.user_data.pop("compound_text_bid", None)
        ctx.user_data.pop("state", None)
        if not bid:
            return
        set_compound_text(bid, m.text.strip())
        b = get_btn(bid)
        children = get_buttons(bid)
        await set_panel(ctx, chat_id,
                        f"🧩 *{b['label'] if b else 'زر مدمج'}*\n_{len(children)} زر داخلي_\n\n✅ تم حفظ نص الرسالة.",
                        kb_compound_quick(bid))
        await m.reply_text("✅ تم حفظ النص.", reply_markup=build_kb(uid, pid))
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

    # ── انتظار رسالة البداية ──────────────────────────────────────
    if state == "wait_start_msg":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً لرسالة البداية."); return
        set_start_message(m.text.strip())
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id,
                        f"✅ تم حفظ رسالة البداية:\n\n{m.text}\n\n⚙️ *الإعدادات*",
                        kb_settings())
        await m.reply_text("✅ تم حفظ رسالة البداية.", reply_markup=build_kb(uid, pid))
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

    if state == "wait_donation_thanks":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً لرسالة الشكر."); return
        set_setting("donation_thanks_message", m.text)
        ctx.user_data.pop("state", None)
        await set_panel(ctx, chat_id,
                        f"✅ تم حفظ رسالة شكر التبرع:\n\n{m.text}\n\n"
                        "تقدر تستخدم `{stars}` داخل النص حتى يظهر عدد النجوم.",
                        kb_settings())
        await m.reply_text("✅ تم حفظ رسالة شكر التبرع.", reply_markup=build_kb(uid, pid))
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

    # ── انتظار نص سؤال كويز جديد ────────────────────────────────
    if state == "wait_quiz_question":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للسؤال."); return
        bid = ctx.user_data.pop("quiz_bid", None)
        ctx.user_data.pop("state", None)
        if not bid: return
        qid = add_quiz_question(bid, m.text)
        b = get_btn(bid)
        await set_panel(ctx, chat_id,
                        f"📊 *{b['label'] if b else 'كويز'}*\n\n✅ تم إضافة السؤال.\nالآن أضف الخيارات وحدد الإجابة الصحيحة.",
                        kb_quiz_question_manage(qid))
        await m.reply_text(f"✅ تم إضافة السؤال:\n_{m.text}_\n\nالآن أضف الخيارات.",
                           parse_mode="Markdown", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار نص خيار لسؤال كويز ────────────────────────────────
    if state == "wait_quiz_option":
        if not m.text or m.text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للخيار."); return
        qid = ctx.user_data.pop("quiz_qid", None)
        ctx.user_data.pop("state", None)
        if not qid: return
        add_quiz_option(qid, m.text)
        q = get_quiz_question(qid)
        opts = get_quiz_options(qid)
        await set_panel(ctx, chat_id,
                        f"📊 *السؤال:* {q['question'] if q else ''}\n_{len(opts)} خيار_ — اضغط على الخيار لتحديده كإجابة صحيحة ✅",
                        kb_quiz_question_manage(qid))
        await m.reply_text(f"✅ تمت إضافة الخيار: _{m.text}_",
                           parse_mode="Markdown", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار عدد أسئلة الكويز التلقائي ────────────────────────
    if state == "wait_quiz_ai_count":
        if not m.text or not m.text.strip().isdigit():
            await m.reply_text("⚠️ أرسل رقماً صحيحاً (مثال: 10)."); return
        count = int(m.text.strip())
        if count < 1 or count > 50:
            await m.reply_text("⚠️ العدد يجب أن يكون بين 1 و 50."); return
        ctx.user_data["quiz_ai_count"] = count
        ctx.user_data["state"] = "wait_quiz_ai_source"
        bid = ctx.user_data.get("quiz_ai_bid")
        await m.reply_text(
            f"✅ سيتم توليد *{count}* سؤال.\n\n"
            "📎 الآن أرسل المصدر:\n"
            "• نص مباشر\n"
            "• ملف TXT أو PDF\n"
            "• صورة تحتوي نصاً",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("إلغاء", callback_data=f"qz_panel_{bid}")
            ]])
        )
        return

    # ── انتظار مصدر الكويز التلقائي (نص / ملف / صورة) ───────────
    if state == "wait_quiz_ai_source":
        bid = ctx.user_data.pop("quiz_ai_bid", None)
        count = ctx.user_data.pop("quiz_ai_count", 10)
        ctx.user_data.pop("state", None)
        if not bid: return

        if not GEMINI_KEYS:
            await m.reply_text("❌ خاصية الملء التلقائي تتطلب مفتاح Gemini API."); return

        wait_msg = await m.reply_text(f"⏳ جاري توليد {count} سؤال بالذكاء الاصطناعي...")

        questions = None
        error = None

        if m.text and m.text.strip():
            questions, error = await generate_quiz_questions(m.text.strip(), count)
        elif m.document:
            import base64 as _b64, io as _io
            doc = m.document
            mime = doc.mime_type or ""
            tg_file = await ctx.bot.get_file(doc.file_id)
            buf = _io.BytesIO()
            await tg_file.download_to_memory(buf)
            buf.seek(0)
            if "pdf" in mime:
                b64 = _b64.b64encode(buf.read()).decode()
                questions, error = await generate_quiz_questions_from_file(b64, "application/pdf", count)
            else:
                try:
                    source_text = buf.read().decode("utf-8")
                except Exception:
                    buf.seek(0)
                    source_text = buf.read().decode("latin-1", errors="ignore")
                questions, error = await generate_quiz_questions(source_text, count)
        elif m.photo:
            import base64 as _b64, io as _io
            photo = m.photo[-1]
            tg_file = await ctx.bot.get_file(photo.file_id)
            buf = _io.BytesIO()
            await tg_file.download_to_memory(buf)
            buf.seek(0)
            b64 = _b64.b64encode(buf.read()).decode()
            questions, error = await generate_quiz_questions_from_file(b64, "image/jpeg", count)
        else:
            await wait_msg.edit_text("⚠️ أرسل نصاً أو ملفاً أو صورة."); return

        if error:
            await wait_msg.edit_text(error); return
        if not questions:
            await wait_msg.edit_text("⚠️ لم يتم توليد أي سؤال من المصدر المقدم."); return

        added = 0
        for q_data in questions:
            q_text = (q_data.get("question") or "").strip()
            options = q_data.get("options", [])
            correct = q_data.get("correct", 0)
            if not q_text or len(options) < 2:
                continue
            qid = add_quiz_question(bid, q_text)
            for opt in options:
                add_quiz_option(qid, str(opt).strip())
            try:
                correct_idx = int(correct)
            except Exception:
                correct_idx = 0
            correct_idx = max(0, min(correct_idx, len(options) - 1))
            set_correct_option(qid, correct_idx)
            added += 1

        b = get_btn(bid)
        total = len(get_quiz_questions(bid))
        await wait_msg.edit_text(
            f"✅ تم توليد وإضافة *{added}* سؤال بنجاح!\n"
            f"📊 إجمالي الأسئلة في الكويز: *{total}*",
            parse_mode="Markdown"
        )
        await set_panel(ctx, chat_id,
                        f"📊 *{b['label'] if b else 'كويز'}*\n_{total} سؤال_",
                        kb_quiz_panel(bid))
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

    # ── انتظار مفاتيح Gemini API ──────────────────────────────────
    if state == "wait_api_keys":
        if not m.text or m.text.strip() in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً يحتوي المفاتيح."); return
        ctx.user_data.pop("state", None)
        raw = m.text.strip()
        keys = [k.strip() for k in raw.splitlines() if k.strip()]
        if not keys:
            await m.reply_text("⚠️ لم يُتعرَّف على أي مفتاح صالح."); return
        set_setting("gemini_keys_db", "\n".join(keys))
        await set_panel(ctx, chat_id, "⚙️ *الاعدادات*", kb_settings())
        await m.reply_text(
            f"✅ تم حفظ *{len(keys)}* مفتاح Gemini في قاعدة البيانات.\n"
            "سيتم استخدامها تلقائياً مع مفاتيح البيئة.",
            parse_mode="Markdown",
            reply_markup=build_kb(uid, pid)
        )
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

    if state == "wait_pom_study_min":
        val = parse_pomodoro_minutes(text)
        if val is None:
            await m.reply_text("⚠️ أرسل وقت الدراسة بالدقائق كرقم بين 1 و 240."); return
        ctx.user_data["pom_custom_study"] = val
        ctx.user_data["state"] = "wait_pom_break_min"
        await m.reply_text(
            f"✅ وقت الدراسة: *{val} دقيقة*\n\nأرسل الآن وقت الاستراحة بالدقائق:",
            parse_mode="Markdown"
        )
        return

    if state == "wait_pom_break_min":
        val = parse_pomodoro_minutes(text, max_minutes=120)
        if val is None:
            await m.reply_text("⚠️ أرسل وقت الاستراحة بالدقائق كرقم بين 1 و 120."); return
        study = ctx.user_data.pop("pom_custom_study", None)
        ctx.user_data.pop("state", None)
        if study is None:
            await m.reply_text("⚠️ انتهت عملية التخصيص. اضغط زر التخصيص مرة ثانية."); return
        save_pomodoro_settings(uid, study_min=study, break_min=val)
        await m.reply_text(
            f"✅ تم حفظ الوقت المخصص:\n\n"
            f"📚 الدراسة: *{study} دقيقة*\n"
            f"🧘 الاستراحة: *{val} دقيقة*",
            parse_mode="Markdown",
            reply_markup=kb_pomodoro_settings(uid)
        )
        return

    if state == "wait_comment":
        target_type = ctx.user_data.pop("comment_target_type", None)
        target_id = ctx.user_data.pop("comment_target_id", None)
        ctx.user_data.pop("state", None)
        if not target_type or not target_id:
            return
        if not text or not text.strip():
            await m.reply_text("⚠️ أرسل نصاً فقط للتعليق.")
            ctx.user_data["state"] = "wait_comment"
            ctx.user_data["comment_target_type"] = target_type
            ctx.user_data["comment_target_id"] = target_id
            return
        display_name = (update.effective_user.first_name or "مجهول").strip()
        save_comment(target_type, target_id, uid, display_name, text.strip())
        await m.reply_text(
            "✅ تم نشر تعليقك!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 عرض التعليقات", callback_data=f"cmts_{target_type}_{target_id}")
            ]])
        )
        return

    if state == "wait_donate_stars":
        stars = parse_stars_amount(text)
        if stars is None:
            await m.reply_text("⚠️ أرسل عدد النجوم كرقم بين 1 و 10000."); return
        ctx.user_data.pop("state", None)
        await m.reply_text(f"✅ تم اختيار *{stars} نجمة*، سأرسل لك فاتورة الدفع الآن.", parse_mode="Markdown")
        try:
            await send_stars_invoice(ctx.bot, chat_id, stars)
        except Exception as e:
            logging.warning(f"send_stars_invoice custom failed: {e}")
            await m.reply_text("❌ تعذر إرسال فاتورة النجوم حالياً. حاول مرة أخرى لاحقاً.")
        return

    # ── انتظار سؤال امتحان ─────────────────────────────────────────
    if state == "wait_exam_q":
        bid = ctx.user_data.pop("exam_q_bid", None)
        if not bid:
            ctx.user_data.pop("state", None); return
        q_type, q_text, q_file_id = detect_content(m)
        if not q_type:
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً."); return
        q_channel_msg_id = None
        if q_file_id:
            q_channel_msg_id = await upload_to_channel(ctx.bot, q_file_id, q_type, q_text)
            if get_storage_channel_id() and not q_channel_msg_id:
                await m.reply_text("⚠️ لم يتم حفظ السؤال لأن رفعه لقناة التخزين فشل.")
                return
        qid = add_exam_question(bid, q_type, q_text, q_file_id, q_channel_msg_id)
        ctx.user_data["state"] = "wait_exam_a"
        ctx.user_data["exam_a_qid"] = qid
        await m.reply_text(
            "✅ تم حفظ السؤال.\n\nأرسل الجواب الآن (نص، صورة، أو ملف):",
            reply_markup=kb_cancel_inline()
        )
        return

    # ── انتظار جواب امتحان ─────────────────────────────────────────
    if state == "wait_exam_a":
        qid = ctx.user_data.pop("exam_a_qid", None)
        q_obj = get_exam_question(qid) if qid else None
        if not q_obj:
            ctx.user_data.pop("state", None); return
        a_type, a_text, a_file_id = detect_content(m)
        if not a_type:
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً.")
            ctx.user_data["exam_a_qid"] = qid; return
        a_channel_msg_id = None
        if a_file_id:
            a_channel_msg_id = await upload_to_channel(ctx.bot, a_file_id, a_type, a_text)
            if get_storage_channel_id() and not a_channel_msg_id:
                await m.reply_text("⚠️ لم يتم حفظ الجواب لأن رفعه لقناة التخزين فشل.")
                ctx.user_data["exam_a_qid"] = qid
                return
        set_exam_answer(qid, a_type, a_text, a_file_id, a_channel_msg_id)
        ctx.user_data.pop("state", None)
        bid = q_obj["button_id"]
        questions = get_exam_questions(bid)
        b_obj = get_btn(bid)
        await set_panel(ctx, chat_id,
                        f"📝 *{b_obj['label'] if b_obj else 'امتحان'}*\n_{len(questions)} سؤال_",
                        kb_exam_panel(bid))
        await m.reply_text("✅ تم إضافة السؤال والجواب بنجاح!", reply_markup=build_kb(uid, pid))
        return

    # ── انتظار تعديل سؤال امتحان ───────────────────────────────────
    if state == "wait_exam_edit_q":
        qid = ctx.user_data.pop("exam_edit_qid", None)
        if not qid:
            ctx.user_data.pop("state", None); return
        q_type, q_text, q_file_id = detect_content(m)
        if not q_type:
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً.")
            ctx.user_data["exam_edit_qid"] = qid; return
        q_channel_msg_id = None
        if q_file_id:
            q_channel_msg_id = await upload_to_channel(ctx.bot, q_file_id, q_type, q_text)
            if get_storage_channel_id() and not q_channel_msg_id:
                await m.reply_text("⚠️ لم يتم تعديل السؤال لأن رفعه لقناة التخزين فشل.")
                ctx.user_data["exam_edit_qid"] = qid
                return
        with db() as _c:
            _c.execute("UPDATE exam_questions SET q_type=?, q_text=?, q_file_id=?, q_channel_msg_id=? WHERE id=?",
                       (q_type, q_text, q_file_id, q_channel_msg_id, qid))
        ctx.user_data.pop("state", None)
        await m.reply_text("✅ تم تعديل السؤال.")
        q_obj = get_exam_question(qid)
        if q_obj:
            await set_panel(ctx, chat_id, "📝 إدارة السؤال", kb_exam_question_manage(qid))
        return

    # ── انتظار تعديل جواب امتحان ───────────────────────────────────
    if state == "wait_exam_edit_a":
        qid = ctx.user_data.pop("exam_edit_aqid", None)
        if not qid:
            ctx.user_data.pop("state", None); return
        a_type, a_text, a_file_id = detect_content(m)
        if not a_type:
            await m.reply_text("⚠️ أرسل نصاً أو صورة أو ملفاً.")
            ctx.user_data["exam_edit_aqid"] = qid; return
        a_channel_msg_id = None
        if a_file_id:
            a_channel_msg_id = await upload_to_channel(ctx.bot, a_file_id, a_type, a_text)
            if get_storage_channel_id() and not a_channel_msg_id:
                await m.reply_text("⚠️ لم يتم تعديل الجواب لأن رفعه لقناة التخزين فشل.")
                ctx.user_data["exam_edit_aqid"] = qid
                return
        set_exam_answer(qid, a_type, a_text, a_file_id, a_channel_msg_id)
        ctx.user_data.pop("state", None)
        await m.reply_text("✅ تم تعديل الجواب.")
        await set_panel(ctx, chat_id, "📝 إدارة السؤال", kb_exam_question_manage(qid))
        return

    # ── انتظار اسم جديد للتعديل ───────────────────────────────────
    if state == "wait_edit_label":
        if not text or text in SPECIAL_BTNS:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        bid = ctx.user_data.get("edit_bid"); upd_btn_label(bid, text)
        b = get_btn(bid); ctx.user_data.pop("state", None)
        if b and b["type"] == "content":
            await set_panel(ctx, chat_id, f"📄 *{text}*", kb_content_panel(bid))
        elif b and b["type"] == "exam_group":
            await set_panel(ctx, chat_id, f"🎓 *{text}*", kb_exam_group_quick(bid))
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

    # ── ملزمة: انتظار معلومة ناقصة ───────────────────────────────
    if state in ("wait_mlz_subject", "wait_mlz_teacher", "wait_mlz_grade", "wait_mlz_year"):
        val = m.text.strip() if m.text else ""
        if not val:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً."); return
        key_map = {
            "wait_mlz_subject": "mlz_subject",
            "wait_mlz_teacher": "mlz_teacher",
            "wait_mlz_grade":   "mlz_grade",
            "wait_mlz_year":    "mlz_year",
        }
        ctx.user_data[key_map[state]] = val
        ctx.user_data.pop("state", None)
        await _ask_next_missing(m, ctx, uid, chat_id)
        return

    # ── ملزمة: انتظار الوصف اليدوي ───────────────────────────────
    if state == "wait_mlz_desc":
        val = m.text.strip() if m.text else ""
        if not val:
            await m.reply_text("⚠️ أرسل نصاً صحيحاً للوصف."); return
        ctx.user_data["mlz_desc"] = val
        ctx.user_data["state"] = "wait_mlz_type"
        await m.reply_text(
            "📌 *ما نوع الملزمة؟*\n_(مثال: مراجعة، ملخص، نموذج امتحان)_",
            parse_mode="Markdown"
        )
        return

    # ── ملزمة: انتظار النوع ───────────────────────────────────────
    if state == "wait_mlz_type":
        val = m.text.strip() if m.text else ""
        if not val:
            await m.reply_text("⚠️ أرسل نصاً للنوع."); return
        ctx.user_data.pop("state", None)
        await finish_mlz_flow(m, ctx, uid, chat_id, ctx.bot, val)
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

    # ── ملزمة: ملف جديد من المشرف (خارج وضع الإضافة اليدوية) ────────
    if not state and is_admin(uid) and (
        m.document or m.video or m.audio or m.voice or
        (m.photo and not (m.caption or "").strip().startswith("."))
    ):
        handled = await start_mlz_flow(m, ctx, uid, chat_id)
        if handled:
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
                to_delete = [(b["id"], b["label"]) for b in current_btns]
            else:
                to_delete = [(current_btns[i]["id"], current_btns[i]["label"]) for i in del_idx
                             if isinstance(i, int) and 0 <= i < len(current_btns)]
            for bid, _ in to_delete:
                del_btn(bid)
            if to_delete:
                del_lines = "\n".join(f"• `{bid}` — {lbl}" for bid, lbl in to_delete)
                result_lines.append(f"🗑 تم حذف {len(to_delete)} زر\n{del_lines}\n📌 _احتفظ بالأرقام للاستعادة_")
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
                "الفاصلة | تضع الأزرار جنب بعض في نفس السطر.\n\n"
                "بعدها سيُطلب منك اختيار نوع الأزرار من بين: "
                "📂 قائمة، 📄 محتوى، 📊 كويز، 📝 اختبار، 🎓 زر امتحان، 🧩 زر مدمج، ⭐ مميز.",
                parse_mode="Markdown"
            )
            return
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        if not lines:
            await m.reply_text("⚠️ لم يتم العثور على أزرار.")
            return
        ctx.user_data["quick_add_lines"] = lines
        ctx.user_data["quick_add_pid"] = pid
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📂 قائمة", callback_data="qa_menu"),
                InlineKeyboardButton("📄 محتوى", callback_data="qa_content"),
            ],
            [
                InlineKeyboardButton("📊 كويز", callback_data="qa_quiz"),
                InlineKeyboardButton("📝 اختبار", callback_data="qa_exam"),
            ],
            [
                InlineKeyboardButton("🎓 زر امتحان", callback_data="qa_examg"),
                InlineKeyboardButton("🧩 زر مدمج", callback_data="qa_compound"),
            ],
            [InlineKeyboardButton("⭐ مميز (للمشرفين فقط)", callback_data="qa_special")],
        ])
        preview = "\n".join(
            " | ".join(p.strip() for p in l.split("|") if p.strip()) for l in lines
        )
        await m.reply_text(
            f"📋 *الأزرار المراد إضافتها:*\n`{preview}`\n\nما نوع الأزرار؟",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    # ── إحصائيات زر الامتحان الرئيسي ─────────────────────────────
    if text == BTN_EXAM_STATS and not is_admin(uid):
        parent_btn = get_btn(pid) if pid else None
        if parent_btn and parent_btn["type"] == "exam_group":
            await m.reply_text(
                exam_group_stats_text(pid, uid),
                parse_mode="Markdown",
                reply_markup=build_exam_group_kb(uid, pid)
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
            current_btn = get_btn(pid)
            if current_btn and current_btn.get("type") == "exam_group":
                for topic in get_exam_topics(pid):
                    sess_key = _exam_session_key(topic["id"])
                    if sess_key in ctx.user_data:
                        sess = ctx.user_data.pop(sess_key)
                        restore_exam_progress(uid, topic["id"], sess.get("old_progress", {}))
            b = get_btn(pid); new_pid = b["parent_id"] if b else None
            ctx.user_data["pid"] = new_pid
            await m.reply_text(".", reply_markup=build_kb(uid, new_pid))
        else:
            ctx.user_data["pid"] = None
            await m.reply_text(".", reply_markup=build_kb(uid, None))
        return

    # ── القائمة الرئيسية ──────────────────────────────────────────
    if text == BTN_HOME:
        if pid is not None:
            current_btn = get_btn(pid)
            if current_btn and current_btn.get("type") == "exam_group":
                for topic in get_exam_topics(pid):
                    sess_key = _exam_session_key(topic["id"])
                    if sess_key in ctx.user_data:
                        sess = ctx.user_data.pop(sess_key)
                        restore_exam_progress(uid, topic["id"], sess.get("old_progress", {}))
        ctx.user_data["pid"] = None
        start_msg = get_start_message()
        await m.reply_text(start_msg, reply_markup=build_kb(uid, None))
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
            current_btn = get_btn(pid) if pid else None
            if current_btn and current_btn["type"] == "exam_group":
                ctx.user_data["new_type"] = "exam"
                ctx.user_data["state"] = "wait_label"
                ctx.user_data["_from_exg"] = pid
                await set_panel(ctx, chat_id, "✏️ *إضافة موضوع جديد*\n\nاكتب اسم الموضوع:", kb_cancel_inline())
            else:
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
        if text in (BTN_SWAP, "تغير", "تغيير"):
            current_pid = ctx.user_data.get("pid")
            btns = get_buttons(current_pid)
            if len(btns) < 2:
                await m.reply_text("⚠️ يجب أن يكون هناك زران على الأقل للتبديل.")
            else:
                await set_panel(ctx, chat_id, "🔀 *اختر الزر الأول:*", kb_swap_select(current_pid))
            return
        if text == BTN_SETTINGS:
            await set_panel(ctx, chat_id, "⚙️ *الاعدادات*", kb_settings())
            return

    # ── ضغط زر من القائمة ─────────────────────────────────────────
    # تنظيف علامات الحالة ✅/❌ من بداية ونهاية النص (تُضاف لأزرار الامتحانات)
    import re as _re
    _clean = _re.sub(r'^[✅❌]\s*', '', text)
    _clean = _re.sub(r'\s*[✅❌]$', '', _clean).strip()

    matched = None
    # أولاً: لو حملت الرسالة بصمة الزر غير المرئية فاللوكاب يكون مباشرًا
    # ومضموناً لا يتأثر بكشف الأزرار المتشابهة الاسم في أماكن مختلفة.
    if marker_bid is not None:
        matched = get_btn(marker_bid)
        if matched and matched.get("label") not in (text, _clean):
            # حماية إضافية: لو تم تعديل اسم الزر بعد بناء الكيبورد، نتجاهل البصمة
            matched = None
        if matched:
            ctx.user_data["pid"] = matched.get("parent_id")

    if not matched:
        btns = get_buttons(pid)
        matched = next((b for b in btns if b['label'] in (text, _clean)), None)
    if not matched:
        # البوت أُعيد تشغيله وضاع الموقع، نبحث في كل الأزرار عبر MongoDB
        matched = get_btn_by_label(text) or get_btn_by_label(_clean)
        if matched:
            ctx.user_data["pid"] = matched.get("parent_id")
        else:
            return

    b = matched
    if b["type"] == "menu":
        ctx.user_data["pid"] = b["id"]
        await m.reply_text(".", reply_markup=build_kb(uid, b["id"]))
        if is_admin(uid):
            await set_panel(ctx, chat_id, f"{btn_id_header(b['id'])}📂 *{b['label']}*", kb_menu_quick(b["id"]))

    elif b["type"] == "content":
        if is_admin(uid):
            items = get_items(b["id"])
            await set_panel(ctx, chat_id,
                            f"{btn_id_header(b['id'])}📄 *{b['label']}*\n_{len(items)} عنصر_",
                            kb_content_quick(b["id"]))
        else:
            await send_items(m, b["id"], uid=uid, bot=ctx.bot)

    elif b["type"] == "quiz":
        if is_admin(uid):
            questions = get_quiz_questions(b["id"])
            await set_panel(ctx, chat_id,
                            f"{btn_id_header(b['id'])}📊 *{b['label']}*\n_{len(questions)} سؤال_",
                            kb_quiz_quick(b["id"]))
        else:
            await send_quiz_ready(m, b["id"])

    elif b["type"] == "exam":
        if is_admin(uid):
            questions = get_exam_questions(b["id"])
            await set_panel(ctx, chat_id,
                            f"{btn_id_header(b['id'])}📝 *{b['label']}*\n_{len(questions)} سؤال_",
                            kb_exam_quick(b["id"]))
        else:
            questions = get_exam_questions(b["id"])
            if not questions:
                await m.reply_text("📭 لا توجد أسئلة في هذا الامتحان بعد.")
            else:
                parent_btn = get_btn(b.get("parent_id")) if b.get("parent_id") else None
                progress = get_exam_progress(uid, b["id"])
                if progress.get("completed") and parent_btn and parent_btn.get("type") == "exam_group":
                    await m.reply_text(
                        exam_topic_stats_text(uid, b["id"]),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔄 إعادة الامتحان", callback_data=f"exg_retry_{parent_btn['id']}_{b['id']}")
                        ]])
                    )
                else:
                    await send_exam_ready(m, b["id"])

    elif b["type"] == "exam_group":
        if is_admin(uid):
            ctx.user_data["pid"] = b["id"]
            await m.reply_text(".", reply_markup=build_kb(uid, b["id"]))
            await set_panel(ctx, chat_id,
                            f"{btn_id_header(b['id'])}🎓 *{b['label']}*\n_زر امتحان رئيسي — أضف داخله أزرار اختبار كمواضيع._",
                            kb_exam_group_quick(b["id"]))
        else:
            ctx.user_data["pid"] = b["id"]
            await m.reply_text(
                exam_group_text(b["id"], uid),
                parse_mode="Markdown",
                reply_markup=build_exam_group_kb(uid, b["id"])
            )

    elif b["type"] == "compound":
        if is_admin(uid):
            children = get_buttons(b["id"])
            await set_panel(ctx, chat_id,
                            f"{btn_id_header(b['id'])}🧩 *{b['label']}*\n_{len(children)} زر داخلي_",
                            kb_compound_quick(b["id"]))
        else:
            children = get_buttons(b["id"])
            # زر مدمج بمحتوى واحد فقط → عرض المحتوى مباشرة بدون قائمة اختيار
            if len(children) == 1 and children[0].get("type") == "content":
                await send_items(m, children[0]["id"], uid=uid, bot=ctx.bot)
            else:
                text_msg = get_compound_text(b["id"])
                await m.reply_text(text_msg, reply_markup=kb_compound_user(b["id"]))

    elif b["type"] == "special":
        action = b.get("special_action")
        if action == "container":
            ctx.user_data["pid"] = b["id"]
            await m.reply_text(".", reply_markup=build_kb(uid, b["id"]))
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_حاوية_",
                                kb_special_container_quick(b["id"]))
        elif action == "pomodoro":
            await m.reply_text(
                pomodoro_settings_text(uid),
                parse_mode="Markdown",
                reply_markup=kb_pomodoro_settings(uid)
            )
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_زر بومودورو_",
                                kb_special_quick(b["id"]))
        elif action == "donate_stars":
            await m.reply_text(
                donation_text(),
                parse_mode="Markdown",
                reply_markup=kb_donation_stars(uid)
            )
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_زر تبرع بالنجوم_",
                                kb_special_quick(b["id"]))
        elif action == "toggle_ratings":
            await m.reply_text(
                toggle_ratings_text(uid),
                parse_mode="Markdown",
                reply_markup=kb_toggle_ratings(uid)
            )
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_زر إعدادات التقييمات_",
                                kb_special_quick(b["id"]))
        elif action == "file_request":
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_زر طلبات إضافة الملفات_",
                                kb_special_quick(b["id"]))
            else:
                ctx.user_data["state"] = "wait_file_request"
                ctx.user_data["file_request_bid"] = b["id"]
                await m.reply_text(
                    "📩 *التواصل مع المشرفين*\n\n"
                    "من خلال هذا الزر يعمل البوت\n"
                    "كوسيط بينك وبين المشرفين.\n\n"
                    "🔒 *خصوصيتك محفوظة تماماً:*\n"
                    "حسابك يبقى مخفياً عنهم،\n"
                    "والتواصل يتم عبر البوت فقط.\n\n"
                    "📎 *يمكنك إرسال:*\n"
                    "نص، صورة، ملف، أو صوت.\n\n"
                    "✏️ أرسل طلبك الآن 👇",
                    parse_mode="Markdown",
                    reply_markup=kb_file_request_cancel()
                )
        elif action == "file_upload":
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_زر رفع الملفات_",
                                kb_special_quick(b["id"]))
            else:
                ctx.user_data["state"] = "wait_file_upload"
                await m.reply_text(
                    "📤 *رفع ملف*\n\n"
                    "أرسل الملف الذي تريد رفعه\n"
                    "(صورة، مستند، فيديو، أو صوت)\n\n"
                    "سيصل ملفك مباشرة للمشرفين 👇",
                    parse_mode="Markdown",
                    reply_markup=kb_file_upload_cancel()
                )
        elif action == "top_users":
            await m.reply_text(
                top_users_text(),
                parse_mode="Markdown"
            )
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_زر أبرز المستخدمين_",
                                kb_special_quick(b["id"]))
        else:
            if is_admin(uid):
                await set_panel(ctx, chat_id,
                                f"{btn_id_header(b['id'])}⭐ *{b['label']}*\n_هذا الزر مخصص — سلوكه يُحدَّد برمجياً._",
                                kb_special_quick(b["id"]))
