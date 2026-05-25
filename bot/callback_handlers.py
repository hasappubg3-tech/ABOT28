from .shared import *

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

    # ── ملزمة: تأكيد أو تعديل ────────────────────────────────────────────
    if d in ("mlz_confirm", "mlz_edit"):
        if not is_admin(uid):
            await q.answer("⛔ غير مصرح.", show_alert=True); return
        chat_id = q.message.chat_id
        if d == "mlz_confirm":
            await after_mlz_confirm(q, ctx, uid, chat_id)
        else:
            await after_mlz_edit(q, ctx, uid, chat_id)
        return

    # ── رد المشرف على المستخدم (زر الرد) ────────────────────────────────
    if d.startswith("freply_"):
        if not is_file_supervisor(uid):
            await q.answer("⛔ غير مصرح.", show_alert=True); return
        target_uid = int(d[len("freply_"):])
        ctx.user_data["state"] = f"wait_freply_{target_uid}"
        await q.answer()
        await ctx.bot.send_message(
            uid,
            f"✏️ أرسل ردك الآن وسيصل للمستخدم مباشرة.\n_(أي نص أو صورة أو ملف)_",
            parse_mode="Markdown"
        )
        return

    # ── تقييم الملفات (لجميع المستخدمين) ────────────────────────────────
    if d.startswith("rate_"):
        if d.startswith("rate_open_"):
            iid = int(d[len("rate_open_"):])
            if not get_item(iid):
                await q.answer("⚠️ الملف غير موجود.", show_alert=True); return
            await q.answer()
            await q.edit_message_text(
                f"{item_rating_text(iid, uid)}\n\nاختر تقييمك للملف:",
                reply_markup=kb_item_rating_choices(iid)
            )
            return

        if d.startswith("rate_back_"):
            iid = int(d[len("rate_back_"):])
            await q.answer()
            await q.edit_message_text(item_rating_text(iid, uid), reply_markup=kb_item_rating(iid))
            return

        if d.startswith("rate_set_"):
            parts = d[len("rate_set_"):].split("_")
            iid = int(parts[0])
            rating = int(parts[1])
            if rating < 1 or rating > 5 or not get_item(iid):
                await q.answer("⚠️ تقييم غير صالح.", show_alert=True); return
            save_item_rating(iid, uid, rating)
            await q.answer("✅ تم حفظ تقييمك")
            await q.edit_message_text(
                f"✅ شكراً على تقييمك!\n\n{item_rating_text(iid, uid)}",
                reply_markup=kb_item_rating(iid)
            )
            return

        return

    # ── تقييم موحد على مستوى الزر (لجميع المستخدمين) ───────────────────
    if d.startswith("brate_"):
        if d.startswith("brate_open_"):
            bid = int(d[len("brate_open_"):])
            await q.answer()
            await q.edit_message_text(
                f"{btn_rating_text(bid, uid)}\n\nاختر تقييمك للمحتوى:",
                reply_markup=kb_btn_rating_choices(bid)
            )
            return

        if d.startswith("brate_back_"):
            bid = int(d[len("brate_back_"):])
            await q.answer()
            await q.edit_message_text(btn_rating_text(bid, uid), reply_markup=kb_btn_rating(bid))
            return

        if d.startswith("brate_set_"):
            parts = d[len("brate_set_"):].split("_")
            bid = int(parts[0])
            rating = int(parts[1])
            if rating < 1 or rating > 5:
                await q.answer("⚠️ تقييم غير صالح.", show_alert=True); return
            save_btn_rating(bid, uid, rating)
            await q.answer("✅ تم حفظ تقييمك")
            await q.edit_message_text(
                f"✅ شكراً على تقييمك!\n\n{btn_rating_text(bid, uid)}",
                reply_markup=kb_btn_rating(bid)
            )
            return

        return

    # ── التعليقات — قائمة التعليقات ───────────────────────────────────────
    if d.startswith("cmts_"):
        # cmts_item_123  أو  cmts_btn_123
        rest = d[5:]
        sp = rest.split("_", 1)
        target_type, target_id = sp[0], int(sp[1])
        await q.answer()
        comments = get_comments(target_type, target_id)
        label = "الملف" if target_type == "item" else "المحتوى"
        text = f"💬 تعليقات {label}\n\nعدد التعليقات: {len(comments)}"
        if not comments:
            text += "\n\nلا يوجد تعليقات بعد، كن أول من يعلّق! 🙂"
        await q.edit_message_text(text, reply_markup=kb_comments_list(target_type, target_id))
        return

    # ── التعليقات — عرض / تفاعل / إضافة / رجوع ─────────────────────────
    if d.startswith("cmt_"):
        # ── رجوع لرسالة التقييم الأصلية ──
        if d.startswith("cmt_back_"):
            rest = d[len("cmt_back_"):]
            sp = rest.split("_", 1)
            target_type, target_id = sp[0], int(sp[1])
            await q.answer()
            if target_type == "item":
                await q.edit_message_text(item_rating_text(target_id, uid), reply_markup=kb_item_rating(target_id))
            else:
                await q.edit_message_text(btn_rating_text(target_id, uid), reply_markup=kb_btn_rating(target_id))
            return

        # ── عرض تعليق واحد ──
        if d.startswith("cmt_view_"):
            # cmt_view_item_123_456  أو  cmt_view_btn_123_456
            rest = d[len("cmt_view_"):]
            parts = rest.split("_")
            target_type = parts[0]
            cid = int(parts[-1])
            target_id = int(parts[-2])
            cmt = get_comment(cid)
            if not cmt:
                await q.answer("⚠️ التعليق غير موجود.", show_alert=True); return
            await q.answer()
            user_reaction = get_user_reaction(cid, uid)
            can_delete = (uid == cmt.get("user_id")) or is_admin(uid)
            await q.edit_message_text(
                f"💬 *تعليق:*\n\n{cmt['text']}",
                parse_mode="Markdown",
                reply_markup=kb_comment_view(target_type, target_id, cid,
                                             cmt.get("likes", 0), cmt.get("dislikes", 0),
                                             user_reaction, can_delete=can_delete)
            )
            return

        # ── تفاعل (👍 / 👎) ──
        if d.startswith("cmt_react_"):
            # cmt_react_item_123_456_like
            rest = d[len("cmt_react_"):]
            parts = rest.split("_")
            reaction = parts[-1]
            cid = int(parts[-2])
            target_id = int(parts[-3])
            target_type = parts[0]
            if reaction not in ("like", "dislike"):
                await q.answer(); return
            updated = react_comment(cid, uid, reaction)
            if not updated:
                await q.answer("⚠️ التعليق غير موجود.", show_alert=True); return
            await q.answer("✅")
            user_reaction = get_user_reaction(cid, uid)
            can_delete = (uid == updated.get("user_id")) or is_admin(uid)
            await q.edit_message_text(
                f"💬 *تعليق:*\n\n{updated['text']}",
                parse_mode="Markdown",
                reply_markup=kb_comment_view(target_type, target_id, cid,
                                             updated.get("likes", 0), updated.get("dislikes", 0),
                                             user_reaction, can_delete=can_delete)
            )
            return

        # ── حذف تعليق ──
        if d.startswith("cmt_del_"):
            # cmt_del_item_123_456
            rest = d[len("cmt_del_"):]
            parts = rest.split("_")
            target_type = parts[0]
            cid = int(parts[-1])
            target_id = int(parts[-2])
            cmt = get_comment(cid)
            if not cmt:
                await q.answer("⚠️ التعليق غير موجود.", show_alert=True); return
            if uid != cmt.get("user_id") and not is_admin(uid):
                await q.answer("⛔ ليس لديك صلاحية حذف هذا التعليق.", show_alert=True); return
            delete_comment(cid)
            await q.answer("✅ تم حذف التعليق.")
            comments = get_comments(target_type, target_id)
            label = "الملف" if target_type == "item" else "المحتوى"
            text = f"💬 تعليقات {label}\n\nعدد التعليقات: {len(comments)}"
            if not comments:
                text += "\n\nلا يوجد تعليقات بعد، كن أول من يعلّق! 🙂"
            await q.edit_message_text(text, reply_markup=kb_comments_list(target_type, target_id))
            return

        # ── إضافة تعليق ──
        if d.startswith("cmt_add_"):
            # cmt_add_item_123  أو  cmt_add_btn_123
            rest = d[len("cmt_add_"):]
            sp = rest.split("_", 1)
            target_type, target_id = sp[0], int(sp[1])
            existing = get_user_comment(target_type, target_id, uid)
            if existing:
                await q.answer("📝 لديك تعليق بالفعل، لا يمكن إضافة أكثر من تعليق واحد.", show_alert=True)
                return
            await q.answer()
            ctx.user_data["state"] = "wait_comment"
            ctx.user_data["comment_target_type"] = target_type
            ctx.user_data["comment_target_id"] = target_id
            await q.edit_message_text(
                "✏️ أرسل تعليقك الآن (نص فقط):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data=f"cmts_{target_type}_{target_id}")
                ]])
            )
            return

        return

    # ── معالجات التبرع بالنجوم (لجميع المستخدمين) ───────────────────────
    if d.startswith("don_"):
        await q.answer()
        chat_id = q.message.chat_id

        if d.startswith("don_amount_"):
            stars = int(d[len("don_amount_"):])
            try:
                await send_stars_invoice(ctx.bot, chat_id, stars)
            except Exception as e:
                logging.warning(f"send_stars_invoice preset failed: {e}")
                await ctx.bot.send_message(chat_id=chat_id, text="❌ تعذر إرسال فاتورة النجوم حالياً. حاول مرة أخرى لاحقاً.")
            return

        if d == "don_custom":
            ctx.user_data["state"] = "wait_donate_stars"
            await q.edit_message_text(
                "✏️ *تخصيص التبرع*\n\nأرسل عدد النجوم الذي تريد التبرع به، مثال: `75`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data="don_cancel")
                ]])
            )
            return

        if d == "don_cancel":
            ctx.user_data.pop("state", None)
            await q.edit_message_text(donation_text(), parse_mode="Markdown", reply_markup=kb_donation_stars(uid))
            return

        if d == "don_thanks_set":
            if not is_admin(uid):
                await q.answer("هذا الخيار للمشرفين فقط.", show_alert=True); return
            ctx.user_data["state"] = "wait_donation_thanks"
            await q.edit_message_text(
                "✏️ أرسل رسالة الشكر الجديدة.\n\n"
                "استخدم `{stars}` حتى يظهر عدد النجوم داخل الرسالة.\n"
                "مثال:\n"
                "شكراً لدعمك بـ {stars} نجمة، وجودك يسعدنا!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data="don_cancel")
                ]])
            )
            return

        if d == "don_close":
            try:
                await q.message.delete()
            except Exception:
                await q.edit_message_text("✅")
            return

        return

    # ── معالجات إعدادات التقييمات (لجميع المستخدمين) ────────────────
    if d.startswith("rating_"):
        await q.answer()

        if d == "rating_toggle":
            toggle_user_ratings_hidden(uid)
            await q.edit_message_text(
                toggle_ratings_text(uid),
                parse_mode="Markdown",
                reply_markup=kb_toggle_ratings(uid)
            )
            return

        if d == "rating_close":
            try:
                await q.message.delete()
            except Exception:
                await q.edit_message_text("✅")
            return

        return

    if d == "fr_cancel":
        await q.answer()
        ctx.user_data.pop("state", None)
        ctx.user_data.pop("file_request_bid", None)
        try:
            await q.edit_message_text("✅ تم إلغاء الطلب.")
        except Exception:
            pass
        return

    if d == "fu_cancel":
        await q.answer()
        ctx.user_data.pop("state", None)
        try:
            await q.edit_message_text("✅ تم الإلغاء.")
        except Exception:
            pass
        return

    if d.startswith("fu_thanks_set_"):
        await q.answer()
        bid = int(d[len("fu_thanks_set_"):])
        if not is_admin(uid):
            await q.answer("هذا الخيار للمشرفين فقط.", show_alert=True); return
        cur_thanks = get_setting(
            "file_upload_thanks_message",
            "❤️ *شكراً جزيلاً!*\n\nتم استلام ملفك وسيتم مراجعته من قبل المشرفين."
        )
        ctx.user_data["state"] = "wait_fu_thanks"
        ctx.user_data["fu_thanks_bid"] = bid
        await q.edit_message_text(
            f"✏️ *تعديل رسالة الشكر*\n\nالرسالة الحالية:\n_{cur_thanks}_\n\nأرسل رسالة الشكر الجديدة:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
            ]])
        )
        return

    # ── معالجات البومودورو (لجميع المستخدمين) ────────────────────────
    if d.startswith("pom_"):
        await q.answer()
        chat_id = q.message.chat_id

        if d == "pom_toggle":
            s = get_pomodoro_settings(uid)
            save_pomodoro_settings(uid, enabled=0 if s["enabled"] else 1)
            await q.edit_message_text(
                pomodoro_settings_text(uid),
                parse_mode="Markdown",
                reply_markup=kb_pomodoro_settings(uid)
            )
            return

        if d.startswith("pom_mode_"):
            parts = d[9:].split("_")
            sm, bm = int(parts[0]), int(parts[1])
            save_pomodoro_settings(uid, study_min=sm, break_min=bm)
            await q.edit_message_text(
                pomodoro_settings_text(uid),
                parse_mode="Markdown",
                reply_markup=kb_pomodoro_settings(uid)
            )
            return

        if d == "pom_custom":
            ctx.user_data["state"] = "wait_pom_study_min"
            ctx.user_data.pop("pom_custom_study", None)
            await q.edit_message_text(
                "✏️ *تخصيص مؤقت الدراسة*\n\nأرسل وقت الدراسة بالدقائق، مثال: `30`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data="pom_custom_cancel")
                ]])
            )
            return

        if d == "pom_custom_cancel":
            ctx.user_data.pop("state", None)
            ctx.user_data.pop("pom_custom_study", None)
            await q.edit_message_text(
                pomodoro_settings_text(uid),
                parse_mode="Markdown",
                reply_markup=kb_pomodoro_settings(uid)
            )
            return

        if d == "pom_start":
            s = get_pomodoro_settings(uid)
            if not s["enabled"]:
                await q.answer("⚠️ المؤقت موقف. فعّله أولاً.", show_alert=True); return
            study = s["study_min"]
            brk   = s["break_min"]
            for job in ctx.job_queue.get_jobs_by_name(f"pom_study_{uid}"):
                job.schedule_removal()
            for job in ctx.job_queue.get_jobs_by_name(f"pom_break_{uid}"):
                job.schedule_removal()
            ctx.job_queue.run_once(
                _pom_study_end,
                when=study * 60,
                data={"uid": uid, "study_min": study, "break_min": brk, "chat_id": chat_id},
                name=f"pom_study_{uid}"
            )
            try:
                await q.message.delete()
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🍅 *بدأت جلسة الدراسة!* 💪\n\n"
                    f"⏱ وقت الدراسة: *{study} دقيقة*\n"
                    f"سأُذكّرك عند انتهاء الوقت ✅"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✋ إيقاف الجلسة", callback_data="pom_stop")
                ]])
            )
            return

        if d.startswith("pom_break_start_"):
            parts = d[len("pom_break_start_"):].split("_")
            brk, study = int(parts[0]), int(parts[1])
            for job in ctx.job_queue.get_jobs_by_name(f"pom_break_{uid}"):
                job.schedule_removal()
            ctx.job_queue.run_once(
                _pom_break_end,
                when=brk * 60,
                data={"uid": uid, "study_min": study, "break_min": brk, "chat_id": chat_id},
                name=f"pom_break_{uid}"
            )
            try:
                await q.message.delete()
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🧘 *بدأت الاستراحة!*\n\n"
                    f"⏱ مدة الاستراحة: *{brk} دقيقة*\n"
                    f"سأُذكّرك عند انتهاء الاستراحة ✅"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✋ إنهاء الجلسة كاملاً", callback_data="pom_stop")
                ]])
            )
            return

        if d == "pom_stop":
            for job in ctx.job_queue.get_jobs_by_name(f"pom_study_{uid}"):
                job.schedule_removal()
            for job in ctx.job_queue.get_jobs_by_name(f"pom_break_{uid}"):
                job.schedule_removal()
            try:
                await q.message.delete()
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=chat_id,
                text="✋ *تم إيقاف الجلسة.*\n\nأحسنت على المحاولة! 💪",
                parse_mode="Markdown"
            )
            return

        if d == "pom_close":
            try:
                await q.message.delete()
            except Exception:
                await q.edit_message_text("✅")
            return

        return

    if d.startswith("quiz_"):
        chat_id = q.message.chat_id
        if d.startswith("quiz_start_"):
            bid = int(d[len("quiz_start_"):])
            await q.answer()
            start_quiz_session(ctx, uid, bid)
            import asyncio
            for n in ("3", "2", "1"):
                try:
                    await q.edit_message_text(f"⏳ يبدأ الكويز خلال *{n}*", parse_mode="Markdown")
                except Exception:
                    pass
                await asyncio.sleep(1)
            try:
                await q.edit_message_text("🚀 انطلق!")
            except Exception:
                pass
            await send_quiz(q.message, bid, uid=uid, bot=ctx.bot, ctx=ctx)
            return

        if d.startswith("quiz_finish_"):
            bid = int(d[len("quiz_finish_"):])
            await q.answer()
            await finish_quiz_session(q, ctx, bid, uid=uid, edit=True)
            return

        if d.startswith("quiz_next_"):
            parts = d[len("quiz_next_"):].split("_")
            if len(parts) < 2:
                await q.answer("⚠️ زر غير صالح.", show_alert=True)
                return
            bid = int(parts[0])
            current_qid = int(parts[1])
            await q.answer()
            try:
                await q.edit_message_text("⏭️ جاري إرسال السؤال التالي...")
            except Exception:
                pass
            b = get_btn(bid)
            random_q = (b.get("random_quiz", 0) or 0) if b else 0
            session = get_quiz_session(ctx, bid)
            if session and session.get("sent", 0) >= session.get("total", 0):
                await finish_quiz_session(q, ctx, bid, uid=uid, edit=True)
                return
            if random_q:
                question = get_next_random_question(bid, uid)
            else:
                question = get_next_ordered_quiz_question(bid, current_qid)
            await send_quiz_question(q.message, bid, question, uid=uid, random_q=random_q, ctx=ctx)
            return

        await q.answer()
        return

    # ── كول باكات الامتحان (لجميع المستخدمين) ──────────────────────
    if d.startswith("ex_start_"):
        bid = int(d[9:])
        await q.answer()
        questions = get_exam_questions(bid)
        if not questions:
            await q.edit_message_text("📭 لا توجد أسئلة في هذا الاختبار بعد.")
            return
        import asyncio
        for n in ("3", "2", "1"):
            try:
                await q.edit_message_text(f"⏳ يبدأ الاختبار خلال *{n}*", parse_mode="Markdown")
            except Exception:
                pass
            await asyncio.sleep(1)
        try:
            await q.edit_message_text("🚀 انطلق!")
        except Exception:
            pass
        session = start_exam_session(ctx, uid, bid)
        if session["q_ids"]:
            await send_exam_question_to_user(q.message, bid, session["q_ids"][0], 1, session["total"], bot=ctx.bot)
        return

    if d.startswith("ex_ans_"):
        parts = d[7:].split("_")
        qid = int(parts[0])
        bid = int(parts[1])
        await q.answer()
        session = get_exam_session(ctx, bid)
        current_idx = 0
        if session:
            try:
                current_idx = session["q_ids"].index(qid)
            except ValueError:
                current_idx = 0
        total = session["total"] if session else len(get_exam_questions(bid))
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await send_exam_answer_to_user(q.message, bid, qid, current_idx, total, bot=ctx.bot)
        return

    if d.startswith("ex_mark_"):
        parts = d[len("ex_mark_"):].split("_")
        bid = int(parts[0])
        qid = int(parts[1])
        correct = parts[2] == "1"
        await q.answer("✅ تم تسجيل إجابتك" if correct else "تم تسجيلها")
        try:
            await q.message.delete()
        except Exception:
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        session = get_exam_session(ctx, bid)
        if not session:
            return
        try:
            if correct:
                await q.message.reply_text(
                    "أحسنت يا بطل 🏆",
                    message_effect_id="5046509860389126442"
                )
            else:
                await q.message.reply_text(
                    "المهم عرفت الجواب الصح ❤️",
                    message_effect_id="5159385139981059251"
                )
        except Exception:
            pass
        if qid not in session.get("graded_qids", []):
            session.setdefault("graded_qids", []).append(qid)
            progress = mark_exam_answer(uid, bid, session["total"], correct)
        else:
            progress = get_exam_progress(uid, bid)
        try:
            current_idx = session["q_ids"].index(qid)
        except ValueError:
            current_idx = 0
        next_idx = current_idx + 1
        if next_idx >= session["total"]:
            ctx.user_data.pop(_exam_session_key(bid), None)
            parent = (get_btn(bid) or {}).get("parent_id")
            degree = exam_score(progress.get("correct") or 0, progress.get("total") or 0)
            await q.message.reply_text(
                "🎉 *أنهيت هذا الفصل!*\n\n"
                f"🧩 الأسئلة: *{progress.get('answered')}/{progress.get('total')}*\n"
                f"✅ عرفت: *{progress.get('correct')}*\n"
                f"❌ لم تعرف: *{progress.get('wrong')}*\n"
                f"🏅 درجتك: *{degree}/100*",
                parse_mode="Markdown"
            )
            if parent and (get_btn(parent) or {}).get("type") == "exam_group":
                await q.message.reply_text(
                    "اختر الفصل التالي 👇",
                    reply_markup=build_exam_group_kb(uid, parent)
                )
            return
        next_qid = session["q_ids"][next_idx]
        await send_exam_question_to_user(q.message, bid, next_qid, next_idx + 1, session["total"], bot=ctx.bot)
        return

    if d.startswith("ex_next_"):
        parts = d[8:].split("_")
        bid = int(parts[0])
        current_qid = int(parts[1])
        await q.answer()
        session = get_exam_session(ctx, bid)
        if not session:
            await q.message.reply_text("⚠️ انتهت الجلسة. اضغط على زر الاختبار مجدداً للبدء.")
            return
        try:
            current_idx = session["q_ids"].index(current_qid)
            next_idx = current_idx + 1
        except ValueError:
            next_idx = 0
        if next_idx >= session["total"]:
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            parent = (get_btn(bid) or {}).get("parent_id")
            ctx.user_data.pop(_exam_session_key(bid), None)
            await q.message.reply_text("🎉 *أحسنت! أنهيت الامتحان.*\n\nتم عرض جميع الأسئلة.", parse_mode="Markdown")
            if parent and (get_btn(parent) or {}).get("type") == "exam_group":
                await q.message.reply_text("اختر الفصل التالي 👇", reply_markup=build_exam_group_kb(uid, parent))
            return
        next_qid = session["q_ids"][next_idx]
        await send_exam_question_to_user(q.message, bid, next_qid, next_idx + 1, session["total"], bot=ctx.bot)
        return

    if d.startswith("ex_finish_"):
        bid = int(d[10:])
        await q.answer()
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        session = get_exam_session(ctx, bid)
        total = session["total"] if session else len(get_exam_questions(bid))
        progress = finish_exam_progress(uid, bid, total)
        degree = exam_score(progress.get("correct") or 0, progress.get("total") or 0)
        await q.message.reply_text(
            "🏁 *تم إنهاء الامتحان.*\n\n"
            f"🧩 الأسئلة المجابة: *{progress.get('answered')}/{progress.get('total')}*\n"
            f"✅ عرفت: *{progress.get('correct')}*\n"
            f"❌ لم تعرف: *{progress.get('wrong')}*\n"
            f"🏅 درجتك: *{degree}/100*",
            parse_mode="Markdown"
        )
        parent = (get_btn(bid) or {}).get("parent_id")
        ctx.user_data.pop(_exam_session_key(bid), None)
        if parent and (get_btn(parent) or {}).get("type") == "exam_group":
            await q.message.reply_text("اختر الفصل 👇", reply_markup=build_exam_group_kb(uid, parent))
        return

    if d.startswith("exg_retry_"):
        parts = d[len("exg_retry_"):].split("_")
        parent_bid = int(parts[0])
        topic_bid = int(parts[1])
        await q.answer()
        questions = get_exam_questions(topic_bid)
        if not questions:
            await q.answer("📭 هذا الفصل لا يحتوي أسئلة بعد.", show_alert=True)
            return
        await send_exam_ready(q.message, topic_bid)
        return

    if d.startswith("exg_topic_"):
        parts = d[len("exg_topic_"):].split("_")
        parent_bid = int(parts[0])
        topic_bid = int(parts[1])
        questions = get_exam_questions(topic_bid)
        if not questions:
            await q.answer("📭 هذا الفصل لا يحتوي أسئلة بعد.", show_alert=True)
            return
        await q.answer()
        await send_exam_ready(q.message, topic_bid)
        return

    if d.startswith("exg_stats_"):
        parent_bid = int(d[len("exg_stats_"):])
        await q.answer()
        await q.edit_message_text(exam_group_text(parent_bid, uid), parse_mode="Markdown", reply_markup=kb_exam_group_user(parent_bid, uid))
        return

    if d.startswith("exg_manage_"):
        bid = int(d[len("exg_manage_"):])
        await q.answer()
        b = get_btn(bid)
        topics = get_exam_topics(bid)
        await q.edit_message_text(
            f"🎓 *{b['label'] if b else 'امتحان'}*\n_{len(topics)} فصل_\n\nإدارة فصول الامتحان:",
            parse_mode="Markdown", reply_markup=kb_exam_group_manage(bid))
        return

    if d.startswith("exg_add_topic_"):
        bid = int(d[len("exg_add_topic_"):])
        await q.answer()
        ctx.user_data["new_type"] = "exam"
        ctx.user_data["add_pid"] = bid
        ctx.user_data.pop("add_after", None)
        ctx.user_data.pop("add_new_row", None)
        ctx.user_data.pop("add_before", None)
        ctx.user_data["state"] = "wait_label"
        ctx.user_data["_from_exg"] = bid
        await q.edit_message_text(
            "✏️ *إضافة فصل جديد*\n\nاكتب اسم الفصل:",
            parse_mode="Markdown", reply_markup=kb_cancel_inline())
        return

    # ── ضغط زر داخلي من زر مدمج (للمستخدم العادي والمشرف) ────────
    if d.startswith("cmp_open_"):
        await q.answer()
        child_bid = int(d[len("cmp_open_"):])
        child = get_btn(child_bid)
        if not child:
            return
        if is_admin(uid):
            items = get_items(child_bid)
            await set_panel(ctx, q.message.chat_id,
                            f"📄 *{child['label']}*\n_{len(items)} عنصر_",
                            kb_content_quick(child_bid))
            return
        await send_items(q.message, child_bid, uid=uid, bot=ctx.bot)
        return

    await q.answer()
    if not is_admin(uid): return
    chat_id = q.message.chat_id
    ctx.user_data["panel_id"] = q.message.message_id
    pid = ctx.user_data.get("pid")

    if d == "noop": return

    if d.startswith("fr_admins_"):
        bid = int(d[len("fr_admins_"):])
        await q.edit_message_text(
            "👥 *مشرفين الملفات*\n\nهؤلاء الأشخاص تصلهم طلبات إضافة الملفات من المستخدمين.",
            parse_mode="Markdown",
            reply_markup=kb_file_request_admins(bid)
        )
        return

    if d.startswith("fr_admin_add_"):
        bid = int(d[len("fr_admin_add_"):])
        ctx.user_data["state"] = "wait_file_admin_id"
        ctx.user_data["file_admin_bid"] = bid
        await q.edit_message_text(
            "➕ *إضافة مشرف ملفات*\n\nأرسل آيدي الشخص أو يوزره، مثال:\n`123456789`\n`@username`",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d.startswith("fr_admin_del_"):
        parts = d[len("fr_admin_del_"):].split("_")
        bid = int(parts[0])
        admin_id = int(parts[1])
        del_file_request_admin(admin_id)
        await q.edit_message_text(
            "👥 *مشرفين الملفات*\n\n✅ تم حذف مشرف الملفات.",
            parse_mode="Markdown",
            reply_markup=kb_file_request_admins(bid)
        )
        return

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

    if d == "st_api_keys":
        all_keys = get_all_gemini_keys()
        db_keys_str = get_setting("gemini_keys_db", "")
        db_keys = [k.strip() for k in db_keys_str.splitlines() if k.strip()] if db_keys_str else []
        env_count = len(GEMINI_KEYS)
        db_count = len(db_keys)
        status = "✅ متاحة" if all_keys else "❌ لا يوجد مفاتيح"
        await q.edit_message_text(
            f"🔑 *مفاتيح Gemini API*\n\n"
            f"🌐 مفاتيح البيئة (env): *{env_count}*\n"
            f"💾 مفاتيح قاعدة البيانات: *{db_count}*\n"
            f"📊 المجموع: *{len(all_keys)}* مفتاح — {status}\n\n"
            "البوت يبدأ بالمفتاح الأول وينتقل للتالي تلقائياً.\n"
            "كل مفتاح في سطر مستقل.",
            parse_mode="Markdown",
            reply_markup=kb_api_keys()
        )
        return

    if d == "st_api_keys_set":
        ctx.user_data["state"] = "wait_api_keys"
        db_keys_str = get_setting("gemini_keys_db", "")
        current_hint = f"\n\n_المفاتيح الحالية في DB: {len([k for k in db_keys_str.splitlines() if k.strip()])} مفتاح_" if db_keys_str else ""
        await q.edit_message_text(
            f"🔑 *إضافة / تعديل مفاتيح Gemini*{current_hint}\n\n"
            "أرسل المفاتيح — كل مفتاح في سطر مستقل:\n\n"
            "`AIzaSyXXXXXXXXXXXXXXXXXX`\n"
            "`AIzaSyYYYYYYYYYYYYYYYYYY`\n\n"
            "⚠️ سيحلّ هذا محلّ المفاتيح القديمة في قاعدة البيانات.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("إلغاء", callback_data="st_api_keys")
            ]])
        )
        return

    if d == "st_api_keys_clear":
        set_setting("gemini_keys_db", "")
        await q.edit_message_text(
            "✅ تم حذف مفاتيح قاعدة البيانات.\n\nسيستخدم البوت مفاتيح البيئة فقط.",
            reply_markup=kb_api_keys()
        )
        return

    if d == "st_donation_thanks":
        msg = get_setting("donation_thanks_message", default_donation_thanks_message())
        await q.edit_message_text(
            f"💝 *رسالة شكر التبرع الحالية:*\n\n{msg}\n\n"
            "ملاحظة: اكتب `{stars}` داخل الرسالة حتى يتم استبدالها بعدد النجوم.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ تغيير رسالة الشكر", callback_data="st_donation_thanks_set")],
                [InlineKeyboardButton("↩️ إرجاع الافتراضي", callback_data="st_donation_thanks_reset")],
                [InlineKeyboardButton("رجوع", callback_data="st_back")],
            ])
        )
        return

    if d == "st_donation_thanks_set":
        ctx.user_data["state"] = "wait_donation_thanks"
        await q.edit_message_text(
            "✏️ أرسل رسالة الشكر الجديدة.\n\n"
            "استخدم `{stars}` حتى يظهر عدد النجوم داخل الرسالة.\n"
            "مثال:\n"
            "شكراً لدعمك بـ {stars} نجمة، وجودك يسعدنا!",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "st_donation_thanks_reset":
        set_setting("donation_thanks_message", default_donation_thanks_message())
        await q.edit_message_text("✅ تم إرجاع رسالة الشكر الافتراضية.", reply_markup=kb_settings())
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

    # ── الأزرار المميزة ───────────────────────────────────────────────
    if d == "st_specials":
        sp_btns = get_all_special_btns()
        count = len(sp_btns)
        txt = (f"⭐ *الأزرار المميزة* — {count} زر\n\nهذه الأزرار تظهر فقط للمشرفين.\n"
               "لإنشاء زر مميز جديد: اضغط ➕ إضافة في الكيبورد واختر ⭐ مميز.")
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb_specials_list())
        return

    if d.startswith("st_special_view_"):
        bid = int(d[len("st_special_view_"):])
        b = get_btn(bid)
        if not b:
            await q.answer("⚠️ الزر غير موجود.", show_alert=True); return
        pid_info = "القائمة الرئيسية" if b.get("parent_id") is None else (
            (get_btn(b["parent_id"]) or {}).get("label", "—"))
        items = get_items(bid)
        await q.edit_message_text(
            f"{btn_id_header(bid)}⭐ *{b['label']}*\nالموضع: _{pid_info}_\n_{len(items)} عنصر_",
            parse_mode="Markdown",
            reply_markup=kb_special_manage(bid)
        )
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

    if d == "st_startmsg":
        current = get_start_message()
        ctx.user_data["state"] = "wait_start_msg"
        await q.edit_message_text(
            f"✏️ *رسالة البداية الحالية:*\n\n_{current}_\n\nأرسل الرسالة الجديدة:",
            parse_mode="Markdown",
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
            f"{btn_id_header(bid)}📄 *{b['label']}*\n_{len(items)} عنصر_\n\n{status}",
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
            f"{btn_id_header(bid)}📄 *{b['label']}*\n_{len(items)} عنصر_\n\n{status}",
            parse_mode="Markdown",
            reply_markup=kb_content_panel(bid)
        )
        return

    if d.startswith("ci_toggle_urating_"):
        bid = int(d[18:])
        toggle_btn_unified_rating(bid)
        b = get_btn(bid)
        items = get_items(bid)
        unified = (b.get("unified_rating", 0) or 0) if b else 0
        status = "✅ توحيد التقييم مفعّل — سيظهر تقييم واحد في الأسفل بعد كل المحتوى" if unified else "⭕ توحيد التقييم مُلغى — سيظهر تقييم لكل ملف على حدة"
        await q.edit_message_text(
            f"{btn_id_header(bid)}📄 *{b['label']}*\n_{len(items)} عنصر_\n\n{status}",
            parse_mode="Markdown",
            reply_markup=kb_content_panel(bid)
        )
        return

    # ── تبديل إخفاء/إظهار أي زر ─────────────────────────────────
    if d.startswith("btn_toggle_hide_"):
        bid = int(d[len("btn_toggle_hide_"):])
        b = get_btn(bid)
        if not b:
            return
        new_val = 0 if (b.get("hidden", 0) or 0) else 1
        set_btn_hidden(bid, new_val)
        b = get_btn(bid)
        status = "🚫 الزر مخفي الآن عن المستخدمين" if new_val else "👁 الزر مرئي الآن للمستخدمين"
        t = b.get("type", "")
        if t == "content":
            items = get_items(bid)
            kb = kb_content_quick(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📄 *{b['label']}*\n_{len(items)} عنصر_\n\n{status}",
                parse_mode="Markdown", reply_markup=kb)
        elif t == "menu":
            kb = kb_menu_quick(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📂 *{b['label']}*\n\n{status}",
                parse_mode="Markdown", reply_markup=kb)
        elif t == "compound":
            children = get_buttons(bid)
            kb = kb_compound_quick(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}🧩 *{b['label']}*\n_{len(children)} زر داخلي_\n\n{status}",
                parse_mode="Markdown", reply_markup=kb)
        elif t == "quiz":
            kb = kb_quiz_quick(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📊 *{b['label']}*\n\n{status}",
                parse_mode="Markdown", reply_markup=kb)
        elif t == "exam":
            kb = kb_exam_quick(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📝 *{b['label']}*\n\n{status}",
                parse_mode="Markdown", reply_markup=kb)
        else:
            kb = kb_special_quick(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}⭐ *{b['label']}*\n\n{status}",
                parse_mode="Markdown", reply_markup=kb)
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
        deleted_info = [(b["id"], b["label"]) for b in btns]
        for b in btns:
            del_btn(b["id"])
        ctx.user_data["pid"] = del_pid
        level_name = "القائمة الرئيسية" if del_pid is None else (get_btn(del_pid) or {}).get("label", "القائمة الحالية")
        lines = "\n".join(f"• `{bid}` — {lbl}" for bid, lbl in deleted_info)
        await q.edit_message_text(
            f"🗑 تم حذف {count} زر من *{level_name}*\n\n{lines}\n\n📌 _احتفظ بالأرقام للاستعادة إن احتجت_",
            parse_mode="Markdown"
        )
        await q.message.reply_text("🔄", reply_markup=build_kb(uid, del_pid))
        return

    # ── إضافة سريعة (اضف) ─────────────────────────────────────────
    if d.startswith("qa_"):
        qa_type_map = {
            "qa_menu": "menu", "qa_content": "content", "qa_special": "special",
            "qa_quiz": "quiz", "qa_exam": "exam",
            "qa_examg": "exam_group", "qa_compound": "compound",
        }
        if d not in qa_type_map:
            return
        btn_type = qa_type_map[d]
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
            type_labels = {
                "menu": "📂 قائمة", "content": "📄 محتوى", "special": "⭐ مميز",
                "quiz": "📊 كويز", "exam": "📝 اختبار",
                "exam_group": "🎓 زر امتحان", "compound": "🧩 زر مدمج",
            }
            type_label = type_labels.get(btn_type, btn_type)
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
        ctx.user_data["pid"] = None
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage()); return

    if d.startswith("m_"):
        ep = int(d[2:]); b = get_btn(ep)
        ctx.user_data["pid"] = ep
        if b and b["type"] == "content":
            items = get_items(ep)
            await q.edit_message_text(f"{btn_id_header(ep)}📄 *{b['label']}*\n_{len(items)} عنصر_",
                                      parse_mode="Markdown", reply_markup=kb_content_panel(ep))
        elif b and b["type"] == "exam":
            questions = get_exam_questions(ep)
            await q.edit_message_text(
                f"{btn_id_header(ep)}📝 *{b['label']}*\n_{len(questions)} سؤال_",
                parse_mode="Markdown", reply_markup=kb_exam_panel(ep))
        elif b and b["type"] == "exam_group":
            topics = get_exam_topics(ep)
            await q.edit_message_text(
                f"{btn_id_header(ep)}🎓 *{b['label']}*\n_{len(topics)} فصل_\n\nإدارة فصول الامتحان:",
                parse_mode="Markdown", reply_markup=kb_exam_group_manage(ep))
        elif b and b["type"] == "compound":
            ctx.user_data["pid"] = b.get("parent_id")
            children = get_buttons(ep)
            await q.edit_message_text(
                f"{btn_id_header(ep)}🧩 *{b['label']}*\n_{len(children)} زر داخلي_\n\nإدارة الأزرار الداخلية:",
                parse_mode="Markdown", reply_markup=kb_compound_manage(ep))
        elif b and b["type"] == "special":
            action = b.get("special_action")
            if action == "container":
                await q.edit_message_text(
                    f"{btn_id_header(ep)}⚙️ *إدارة أزرار: {b['label']}*", parse_mode="Markdown",
                    reply_markup=kb_manage(ep))
            else:
                await q.edit_message_text(
                    f"{btn_id_header(ep)}⭐ *{b['label']}*\n_هذا الزر مخصص._",
                    parse_mode="Markdown", reply_markup=kb_special_manage(ep))
        else:
            await q.edit_message_text(f"{btn_id_header(ep) if b else ''}📂 *{b['label']}*" if b else "⚙️ *إدارة الأزرار*:",
                                      parse_mode="Markdown", reply_markup=kb_manage(ep if b else None))
        return

    # ── فتح تفاصيل زر من لوحة الإدارة ───────────────────────────
    if d.startswith("e_"):
        bid = int(d[2:]); b = get_btn(bid)
        if not b: return
        if b["type"] == "content":
            items = get_items(bid)
            await q.edit_message_text(f"{btn_id_header(bid)}📄 *{b['label']}*\n_{len(items)} عنصر_",
                                      parse_mode="Markdown", reply_markup=kb_content_panel(bid))
        elif b["type"] == "quiz":
            questions = get_quiz_questions(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📊 *{b['label']}*\n_{len(questions)} سؤال_",
                parse_mode="Markdown", reply_markup=kb_quiz_panel(bid))
        elif b["type"] == "exam":
            questions = get_exam_questions(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📝 *{b['label']}*\n_{len(questions)} سؤال_",
                parse_mode="Markdown", reply_markup=kb_exam_panel(bid))
        elif b["type"] == "exam_group":
            topics = get_exam_topics(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}🎓 *{b['label']}*\n_{len(topics)} فصل_\n\nإدارة فصول الامتحان:",
                parse_mode="Markdown", reply_markup=kb_exam_group_manage(bid))
        elif b["type"] == "compound":
            children = get_buttons(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}🧩 *{b['label']}*\n_{len(children)} زر داخلي_\n\nإدارة الأزرار الداخلية:",
                parse_mode="Markdown", reply_markup=kb_compound_manage(bid))
        elif b["type"] == "special":
            action = b.get("special_action")
            if action == "container":
                await q.edit_message_text(
                    f"{btn_id_header(bid)}⭐ *{b['label']}*\n_حاوية — اضغط لإدارة الأزرار الداخلية:_",
                    parse_mode="Markdown", reply_markup=kb_special_container_quick(bid))
            else:
                await q.edit_message_text(
                    f"{btn_id_header(bid)}⭐ *{b['label']}*\n_هذا الزر مخصص — سلوكه يُحدَّد برمجياً._",
                    parse_mode="Markdown", reply_markup=kb_special_manage(bid))
        else:
            await q.edit_message_text(f"{btn_id_header(bid)}📂 *{b['label']}*", parse_mode="Markdown",
                                      reply_markup=kb_edit_menu_btn(bid))
        return

    # ── إدارة الكويز ──────────────────────────────────────────────
    if d.startswith("qz_"):
        await q.answer()

        if d.startswith("qz_panel_"):
            bid = int(d[9:])
            b = get_btn(bid)
            questions = get_quiz_questions(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📊 *{b['label'] if b else 'كويز'}*\n_{len(questions)} سؤال_",
                parse_mode="Markdown", reply_markup=kb_quiz_panel(bid))
            return

        if d.startswith("qz_list_"):
            bid = int(d[8:])
            b = get_btn(bid)
            questions = get_quiz_questions(bid)
            text = f"📋 *أسئلة: {b['label'] if b else 'كويز'}*\n_{len(questions)} سؤال_\n\n⚠️ = يحتاج خيارات | ✅ = جاهز"
            await q.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=kb_quiz_question_list(bid))
            return

        if d.startswith("qz_add_"):
            bid = int(d[7:])
            ctx.user_data["state"] = "wait_quiz_question"
            ctx.user_data["quiz_bid"] = bid
            await q.edit_message_text(
                "📊 *إضافة سؤال كويز*\n\nأرسل نص السؤال:",
                parse_mode="Markdown",
                reply_markup=kb_cancel_inline()
            )
            return

        if d.startswith("qz_q_"):
            qid = int(d[5:])
            q_obj = get_quiz_question(qid)
            if not q_obj:
                await q.answer("⚠️ السؤال غير موجود.", show_alert=True); return
            opts = get_quiz_options(qid)
            text = (
                f"📊 *السؤال:*\n{q_obj['question']}\n\n"
                f"_{len(opts)} خيار_\n\n"
                "اضغط على خيار لجعله الإجابة الصحيحة ✅\nاضغط 🗑 لحذف الخيار."
            )
            await q.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=kb_quiz_question_manage(qid))
            return

        if d.startswith("qz_addopt_"):
            qid = int(d[10:])
            ctx.user_data["state"] = "wait_quiz_option"
            ctx.user_data["quiz_qid"] = qid
            await q.edit_message_text(
                "✏️ أرسل نص الخيار الجديد:",
                reply_markup=kb_cancel_inline()
            )
            return

        if d.startswith("qz_setcorrect_"):
            parts = d[14:].split("_")
            qid = int(parts[0]); opt_idx = int(parts[1])
            set_correct_option(qid, opt_idx)
            q_obj = get_quiz_question(qid)
            opts = get_quiz_options(qid)
            await q.edit_message_text(
                f"📊 *السؤال:*\n{q_obj['question']}\n\n_{len(opts)} خيار_ — ✅ الإجابة الصحيحة محددة",
                parse_mode="Markdown",
                reply_markup=kb_quiz_question_manage(qid)
            )
            return

        if d.startswith("qz_delopt_"):
            rest = d[10:].split("_")
            oid = int(rest[0]); qid = int(rest[1])
            del_quiz_option(oid)
            q_obj = get_quiz_question(qid)
            opts = get_quiz_options(qid)
            correct = q_obj.get("correct_option", 0) if q_obj else 0
            if correct >= len(opts) and opts:
                set_correct_option(qid, 0)
            await q.edit_message_text(
                f"📊 *السؤال:*\n{q_obj['question'] if q_obj else ''}\n\n_{len(opts)} خيار_",
                parse_mode="Markdown",
                reply_markup=kb_quiz_question_manage(qid)
            )
            return

        if d.startswith("qz_delq_"):
            qid = int(d[8:])
            q_obj = get_quiz_question(qid)
            bid = q_obj["button_id"] if q_obj else None
            del_quiz_question(qid)
            if bid:
                b = get_btn(bid)
                questions = get_quiz_questions(bid)
                await q.edit_message_text(
                    f"✅ تم حذف السؤال.\n\n📊 *{b['label'] if b else 'كويز'}*\n_{len(questions)} سؤال_",
                    parse_mode="Markdown", reply_markup=kb_quiz_question_list(bid))
            return

        if d.startswith("qz_toggle_rand_"):
            bid = int(d[15:])
            toggle_random_quiz(bid)
            b = get_btn(bid)
            questions = get_quiz_questions(bid)
            random_q = (b.get("random_quiz", 0) or 0) if b else 0
            status = "✅ التوزيع العشوائي مفعّل — سؤال عشوائي بدون تكرار خلال ساعة" if random_q else "⭕ التوزيع العشوائي مُلغى — يُرسل السؤال الأول دائماً"
            await q.edit_message_text(
                f"{btn_id_header(bid)}📊 *{b['label'] if b else 'كويز'}*\n_{len(questions)} سؤال_\n\n{status}",
                parse_mode="Markdown", reply_markup=kb_quiz_panel(bid))
            return

        if d.startswith("qz_ai_fill_"):
            bid = int(d[11:])
            b = get_btn(bid)
            await q.edit_message_text(
                f"⚡ *ملء الكويز تلقائياً بالذكاء الاصطناعي*\n\n"
                f"📊 *{b['label'] if b else 'كويز'}*\n\n"
                "اختر عدد الأسئلة التي تريد توليدها:",
                parse_mode="Markdown",
                reply_markup=kb_quiz_ai_count(bid)
            )
            return

        if d.startswith("qz_ai_cnt_"):
            parts = d[10:].rsplit("_", 1)
            bid = int(parts[0]); count = int(parts[1])
            ctx.user_data["quiz_ai_bid"] = bid
            ctx.user_data["quiz_ai_count"] = count
            ctx.user_data["state"] = "wait_quiz_ai_source"
            await q.edit_message_text(
                f"⚡ سيتم توليد *{count}* سؤال.\n\n"
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

        if d.startswith("qz_ai_cust_"):
            bid = int(d[11:])
            ctx.user_data["quiz_ai_bid"] = bid
            ctx.user_data["state"] = "wait_quiz_ai_count"
            await q.edit_message_text(
                "✏️ أرسل عدد الأسئلة المطلوبة (رقم بين 1 و 50):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("إلغاء", callback_data=f"qz_panel_{bid}")
                ]])
            )
            return

        return

    # ── إدارة الامتحانات (للمشرفين) ───────────────────────────────
    if d.startswith("ex_"):
        await q.answer()

        if d.startswith("ex_panel_"):
            bid = int(d[9:])
            b = get_btn(bid)
            questions = get_exam_questions(bid)
            await q.edit_message_text(
                f"{btn_id_header(bid)}📝 *{b['label'] if b else 'امتحان'}*\n_{len(questions)} سؤال_",
                parse_mode="Markdown", reply_markup=kb_exam_panel(bid))
            return

        if d.startswith("ex_list_"):
            bid = int(d[8:])
            b = get_btn(bid)
            questions = get_exam_questions(bid)
            await q.edit_message_text(
                f"📋 *أسئلة: {b['label'] if b else 'امتحان'}*\n_{len(questions)} سؤال_\n\n⚠️ = يحتاج جواب | ✅ = جاهز",
                parse_mode="Markdown", reply_markup=kb_exam_question_list(bid))
            return

        if d.startswith("ex_add_"):
            bid = int(d[7:])
            ctx.user_data["state"] = "wait_exam_q"
            ctx.user_data["exam_q_bid"] = bid
            await q.edit_message_text(
                "📝 *إضافة سؤال امتحان*\n\nأرسل السؤال (نص، صورة، أو ملف):",
                parse_mode="Markdown", reply_markup=kb_cancel_inline())
            return

        if d.startswith("ex_q_"):
            qid = int(d[5:])
            q_obj = get_exam_question(qid)
            if not q_obj:
                await q.answer("⚠️ السؤال غير موجود.", show_alert=True); return
            has_answer = bool(q_obj.get("a_text") or q_obj.get("a_file_id"))
            q_label = q_obj.get("q_text") or f"[{q_obj.get('q_type','text')}]"
            a_label = (q_obj.get("a_text") or f"[{q_obj.get('a_type','text')}]") if has_answer else "لا يوجد جواب ⚠️"
            text = (
                f"📝 *السؤال:*\n{q_label[:300]}\n\n"
                f"✅ *الجواب:*\n{a_label[:300]}"
            )
            await q.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=kb_exam_question_manage(qid))
            return

        if d.startswith("ex_delq_"):
            qid = int(d[8:])
            q_obj = get_exam_question(qid)
            bid = q_obj["button_id"] if q_obj else None
            del_exam_question(qid)
            if bid:
                b = get_btn(bid)
                questions = get_exam_questions(bid)
                await q.edit_message_text(
                    f"✅ تم حذف السؤال.\n\n📝 *{b['label'] if b else 'امتحان'}*\n_{len(questions)} سؤال_",
                    parse_mode="Markdown", reply_markup=kb_exam_question_list(bid))
            return

        if d.startswith("ex_toggle_rand_"):
            bid = int(d[15:])
            toggle_random_exam(bid)
            b = get_btn(bid)
            questions = get_exam_questions(bid)
            random_e = (b.get("random_exam", 0) or 0) if b else 0
            status = "✅ التوزيع العشوائي مفعّل — الأسئلة بترتيب عشوائي" if random_e else "⭕ التوزيع العشوائي مُلغى — الأسئلة بالترتيب"
            await q.edit_message_text(
                f"{btn_id_header(bid)}📝 *{b['label'] if b else 'امتحان'}*\n_{len(questions)} سؤال_\n\n{status}",
                parse_mode="Markdown", reply_markup=kb_exam_panel(bid))
            return

        if d.startswith("ex_edit_q_"):
            qid = int(d[10:])
            ctx.user_data["state"] = "wait_exam_edit_q"
            ctx.user_data["exam_edit_qid"] = qid
            await q.edit_message_text(
                "✏️ أرسل السؤال الجديد (نص، صورة، أو ملف):",
                reply_markup=kb_cancel_inline())
            return

        if d.startswith("ex_edit_a_"):
            qid = int(d[10:])
            ctx.user_data["state"] = "wait_exam_edit_a"
            ctx.user_data["exam_edit_aqid"] = qid
            await q.edit_message_text(
                "✏️ أرسل الجواب الجديد (نص، صورة، أو ملف):",
                reply_markup=kb_cancel_inline())
            return

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
        label = b["label"] if b else "؟"
        del_btn(bid)
        ctx.user_data["pid"] = ep
        await q.edit_message_text("⚙️ *إدارة الأزرار*:", parse_mode="Markdown",
                                  reply_markup=kb_manage(ep))
        await q.message.reply_text(
            f"🗑 تم حذف الزر *{label}*\n📌 رقمه: `{bid}` _(احتفظ به للاستعادة إن احتجت)_",
            parse_mode="Markdown", reply_markup=build_kb(uid, ep)
        )
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

    if d in ("pt_m", "pt_c", "pt_s", "pt_q", "pt_e", "pt_g", "pt_x"):
        t = {"pt_m": "menu", "pt_c": "content", "pt_s": "special", "pt_q": "quiz",
             "pt_e": "exam", "pt_g": "exam_group", "pt_x": "compound"}[d]
        ctx.user_data["new_type"] = t
        ctx.user_data["state"] = "wait_label"
        await q.edit_message_text("✏️ اكتب اسم الزر الجديد:", reply_markup=kb_cancel_inline()); return

    if d == "pt_clone":
        ctx.user_data["state"] = "wait_clone_id"
        await q.edit_message_text(
            "♻️ *استنساخ زر*\n\n"
            "أرسل *رقم الزر* (ID) المراد استنساخه:\n"
            "_(يمكن استنساخ أي زر حتى لو كان محذوفاً — سيُنسخ مع كامل محتواه وأزراره الداخلية)_",
            parse_mode="Markdown",
            reply_markup=kb_cancel_inline()
        )
        return

    if d == "pt_cancel":
        ctx.user_data.pop("state", None); ctx.user_data.pop("new_type", None)
        ctx.user_data.pop("add_after", None); ctx.user_data.pop("add_pid", None)
        ctx.user_data.pop("add_new_row", None); ctx.user_data.pop("add_before", None)
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_text("تم الإلغاء.")
        return

    # ── إدارة الزر المدمج ───────────────────────────────────────
    if d.startswith("cmp_add_n_") or d.startswith("cmp_add_s_"):
        same_row = d.startswith("cmp_add_s_")
        bid = int(d[len("cmp_add_n_"):])
        ctx.user_data["new_type"] = "content"
        ctx.user_data["add_pid"] = bid
        ctx.user_data.pop("add_before", None)
        if same_row:
            children = get_buttons(bid)
            if children:
                last_child = children[-1]
                ctx.user_data["add_after"] = last_child["id"]
                ctx.user_data["add_new_row"] = 0
            else:
                ctx.user_data.pop("add_after", None)
                ctx.user_data.pop("add_new_row", None)
        else:
            ctx.user_data.pop("add_after", None)
            ctx.user_data.pop("add_new_row", None)
        ctx.user_data["state"] = "wait_label"
        ctx.user_data["_from_compound"] = bid
        position_hint = "بنفس سطر آخر زر داخلي" if same_row else "في سطر جديد"
        await q.edit_message_text(
            f"✏️ *إضافة زر داخلي جديد* ({position_hint})\n\nاكتب اسم الزر:",
            parse_mode="Markdown", reply_markup=kb_cancel_inline())
        return

    if d.startswith("cmp_text_"):
        bid = int(d[len("cmp_text_"):])
        ctx.user_data["state"] = "wait_compound_text"
        ctx.user_data["compound_text_bid"] = bid
        current = get_compound_text(bid)
        await q.edit_message_text(
            f"✏️ *تعديل نص رسالة الزر المدمج*\n\nالنص الحالي:\n_{current}_\n\nأرسل النص الجديد:",
            parse_mode="Markdown", reply_markup=kb_cancel_inline())
        return

    # تبديل موضع زرين داخل الزر المدمج
    if d.startswith("cmp_swap_"):
        bid = int(d[len("cmp_swap_"):])
        b = get_btn(bid)
        await q.edit_message_text(
            f"↔️ *تبديل موضع زرين* — {b['label'] if b else ''}\n\nاختر **الزر الأول** الذي تريد تبديله:",
            parse_mode="Markdown", reply_markup=kb_compound_swap_pick(bid))
        return

    if d.startswith("cmp_swap1_"):
        rest = d[len("cmp_swap1_"):]
        bid_s, first_s = rest.split("_", 1)
        bid = int(bid_s); first = int(first_s)
        b = get_btn(bid); fb = get_btn(first)
        await q.edit_message_text(
            f"↔️ *تبديل موضع زرين* — {b['label'] if b else ''}\n\nالأول: *{fb['label'] if fb else ''}*\nاختر **الزر الثاني**:",
            parse_mode="Markdown", reply_markup=kb_compound_swap_pick(bid, first=first))
        return

    if d.startswith("cmp_swap2_"):
        rest = d[len("cmp_swap2_"):]
        bid_s, first_s, second_s = rest.split("_", 2)
        bid = int(bid_s); first = int(first_s); second = int(second_s)
        swap_btns(first, second)
        b = get_btn(bid)
        children = get_buttons(bid)
        await q.edit_message_text(
            f"{btn_id_header(bid)}🧩 *{b['label'] if b else 'زر مدمج'}*\n_{len(children)} زر داخلي_\n\n✅ تم تبديل موضع الزرين.",
            parse_mode="Markdown", reply_markup=kb_compound_manage(bid))
        return

    if d.startswith("cmp_preview_"):
        bid = int(d[len("cmp_preview_"):])
        b = get_btn(bid)
        if not b:
            return
        text_msg = get_compound_text(bid)
        await q.message.reply_text(text_msg, reply_markup=kb_compound_user(bid))
        return

    # ── تعديل اسم الزر ───────────────────────────────────────────
    if d.startswith("el_"):
        bid = int(d[3:]); ctx.user_data["edit_bid"] = bid; b = get_btn(bid)
        ctx.user_data["state"] = "wait_edit_label"
        await q.edit_message_text(f"✏️ الاسم الحالي: *{b['label']}*\n\nاكتب الاسم الجديد:",
                                  parse_mode="Markdown", reply_markup=kb_cancel_inline()); return

    if d.startswith("ci_add_done_"):
        bid = int(d[len("ci_add_done_"):])
        ctx.user_data.pop("state", None)
        ctx.user_data.pop("item_bid", None)
        ctx.user_data.pop("add_content_control_msg_id", None)
        b = get_btn(bid)
        items = get_items(bid)
        await q.edit_message_text(
            f"{btn_id_header(bid)}📄 *{b['label'] if b else 'المحتوى'}*\n_{len(items)} عنصر_\n\n✅ تم إنهاء الإضافة.",
            parse_mode="Markdown",
            reply_markup=kb_content_panel(bid)
        ); return

    # ── لوحة محتوى الزر: إضافة عنصر ─────────────────────────────
    if d.startswith("ci_add_"):
        bid = int(d[7:])
        ctx.user_data["state"] = "wait_item_content"
        ctx.user_data["item_bid"] = bid
        try:
            await q.message.delete()
        except Exception:
            pass
        control_msg = await ctx.bot.send_message(
            chat_id=q.message.chat_id,
            text=(
                "📤 *إضافة محتوى متعددة*\n\n"
                "أرسل المحتوى الآن: نص، صورة، ملف، فيديو، أو صوت.\n"
                "بعد كل إضافة ابقَ ترسل ملفات أخرى، وعند الانتهاء اضغط الزر أدناه.\n\n"
                "_إذا ضغطت أي زر آخر من أزرار البوت تنتهي الإضافة تلقائياً._"
            ),
            parse_mode="Markdown",
            reply_markup=kb_add_content_active(bid)
        )
        ctx.user_data["add_content_control_msg_id"] = control_msg.message_id
        return

    # ── عرض عناصر الزر مع أزرار إدارة لكل عنصر ──────────────────
    if d.startswith("ci_view_"):
        bid = int(d[8:]); items = get_items(bid)
        if not items:
            return
        for item in items:
            await send_file_item(q.message, item, reply_markup=kb_item_actions(item["id"]), bot=ctx.bot)
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
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
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
