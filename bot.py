import asyncio
import os
import tempfile
import time
from typing import List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, InputFile
from telegram.constants import ParseMode
from telegram.ext import (
	Application,
	CommandHandler,
	MessageHandler,
	CallbackQueryHandler,
	ConversationHandler,
	ContextTypes,
	filters,
)

from config import (
	BOT_TOKEN,
	START_TIME,
	init_db,
	track_user,
	is_admin,
	get_user,
	set_user,
	list_captions,
	get_active_caption_id,
	get_caption,
	set_active_caption_id,
	build_caption,
	set_caption_fields,
	update_stats,
	get_total_users,
	get_user_stats,
	get_all_user_ids,
	get_stats,
	get_force_config,
	format_uptime,
	format_bytes,
	parse_tokens,
	parse_settemplate_values,
	check_user_joined,
	clear_force_join_cache,
	build_join_buttons,
	add_caption,
    delete_caption,
    get_user_tag_prefs,
    set_user_tag,
    set_tag_position,
    apply_tag_to_caption,
    build_final_filename,
	get_multi_state,
	set_multi_enabled,
	set_multi_ids,
	clear_multi,
	toggle_multi_id,
	advance_multi_pointer,
	HELP_URL,
)

from admin import register_admin_handlers


def kb_home():
	rows = [[InlineKeyboardButton("⚙️ Settings", callback_data="set:home"), InlineKeyboardButton("🗂 Captions", callback_data="cap:list:1")]]
	if HELP_URL:
		rows.append([InlineKeyboardButton("📘 Guide (Telegraph)", url=HELP_URL)])
	return InlineKeyboardMarkup(rows)


SET_WAIT_TAG = 9101

def kb_settings_menu(tag: str | None, position: str):
	return InlineKeyboardMarkup([
		[InlineKeyboardButton("📍 Change Position", callback_data="set:pos")],
		[InlineKeyboardButton("➕ Add/Edit Hashtag", callback_data="set:add")],
		[InlineKeyboardButton("🗑 Remove Hashtag", callback_data="set:rm")],
		[InlineKeyboardButton("⬅️ Back", callback_data="home")],
	])


def kb_caption_actions(cid, name: str, next_ep: int):
	cid_hex = str(cid)
	return InlineKeyboardMarkup([
		[InlineKeyboardButton("▶️ Continue", callback_data=f"cap:use:{cid_hex}:cont"),
		 InlineKeyboardButton("🔁 Start Over", callback_data=f"cap:use:{cid_hex}:start")],
		[InlineKeyboardButton("🗑 Delete", callback_data=f"cap:del:{cid_hex}")],
		[InlineKeyboardButton("⬅️ Back", callback_data="cap:list:1")]
	])


def kb_list(caps: List[dict], page: int, page_size: int = 10):
	total = len(caps)
	start = (page - 1) * page_size
	end = start + page_size
	chunk = caps[start:end]
	btn_rows = []
	for doc in chunk:
		label = f"{doc['name']} — {doc.get('version') or '—'} — {doc.get('lang') or '—'} (next: {doc.get('next_ep', 1)})"
		btn_rows.append([InlineKeyboardButton(label[:64], callback_data=f"cap:open:{doc['_id']}")])
	nav = []
	if start > 0:
		nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"cap:list:{page-1}"))
	if end < total:
		nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"cap:list:{page+1}"))
	if nav:
		btn_rows.append(nav)
	# Multi-select entry
	btn_rows.append([InlineKeyboardButton("🎯 Multi-select", callback_data=f"mc:list:{page}")])
	btn_rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
	return InlineKeyboardMarkup(btn_rows)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	try:
		print(f"/start from user {update.effective_user.id}")
	except Exception:
		pass
	user_id = update.effective_user.id
	# Track user (best effort)
	try:
		await track_user(user_id)
	except Exception as e:
		print(f"track_user failed: {e}")
	# Force-join (best effort)
	try:
		if not is_admin(user_id):
			ok, _ = await check_user_joined(context.bot, user_id)
			if not ok:
				force = await get_force_config()
				await update.message.reply_text(
					"🔒 *Access Restricted*\n\nPlease join the required channels to use this bot.",
					reply_markup=build_join_buttons(force),
					disable_web_page_preview=True,
					parse_mode=ParseMode.MARKDOWN,
				)
				return
	except Exception as e:
		print(f"force_join check failed: {e}")
	# Warm user profile (best effort)
	try:
		await get_user(user_id)
	except Exception as e:
		print(f"get_user failed: {e}")
	text = (
		"👋 *Auto-Caption Bot*\n\n"
		"• Send files to generate your caption\n\n"
		"*Commands:*\n"
		"/settemplate - Set series and episode\n"
		"/captions - Manage captions\n"
		"/status - Bot stats\n"
	)
	text += "/help - Help / Guide\n"
	text += "\n*Admin:* /forceon /forceoff /addforce /delforce /forcelist /broadcast"
	await update.message.reply_text(
		text,
		reply_markup=kb_home(),
		disable_web_page_preview=True,
		parse_mode=ParseMode.MARKDOWN,
	)


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text("pong")


async def settemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	# Force-Join si non admin
	if not is_admin(user_id):
		ok, _ = await check_user_joined(context.bot, user_id)
		if not ok:
			force = await get_force_config()
			await update.message.reply_text(
				"🔒 *Access Restricted*\n\nPlease join the required channels to use this bot.",
				reply_markup=build_join_buttons(force),
				disable_web_page_preview=True,
				parse_mode=ParseMode.MARKDOWN,
			)
			return

	raw = update.message.text or ""

	# 1) Value mode: "<series> — Episode <ep> — <version> — <lang>"
	parsed = parse_settemplate_values(raw)
	if parsed:
		series, ep, zero_pad, version, lang = parsed
		# Set standard template (no dashes, double spaces as requested)
		tpl = "{series} Episode {ep}  {version}  {lang}"
		await set_user(user_id, template=tpl)
		# Create/activate the corresponding caption
		ok, msg, cid = await add_caption(user_id, series, version, lang)
		if not ok and cid:
			pass
		elif not ok and "exists" in msg or "existe" in msg:
			caps = await list_captions(user_id)
			from config import norm
			found = next((c for c in caps if norm(c.get("name",""))==norm(series) and norm(c.get("version",""))==norm(version) and norm(c.get("lang",""))==norm(lang)), None)
			cid = found["_id"] if found else None
			if not cid:
				await update.message.reply_text("⚠️ Existing caption not found. Try again.")
				return
		elif not ok:
			await update.message.reply_text(msg)
			return
		await set_active_caption_id(user_id, cid)
		await set_caption_fields(user_id, cid, next_ep=int(ep), zero_pad=int(zero_pad))
		await update.message.reply_text(
			"✅ Template saved and active caption prepared.\n"
			f"• Series: `{series}`\n"
			f"• Current Episode: `{str(ep).zfill(zero_pad)}`\n"
			f"• Version: `{version or '—'}`\n"
			f"• Language: `{lang or '—'}`\n\n"
			"➡️ Now send a file to generate the caption.",
			parse_mode=ParseMode.MARKDOWN
		)
		return

	# 2) Ancien mode: placeholders bruts
	parts = raw.split(None, 1)
	if len(parts) < 2:
		await update.message.reply_text(
			"Usage (values):\n"
			"`/settemplate One Piece — Episode 12 — 1080p — VF`\n\n"
			"Or (custom template with placeholders):\n"
			"`/settemplate {series} Episode {ep}  {version}  {lang}`",
			parse_mode=ParseMode.MARKDOWN,
		)
		return
	tpl = parts[1].strip()
	await set_user(user_id, template=tpl)
	await update.message.reply_text(f"✅ Template saved:\n`{tpl}`", parse_mode=ParseMode.MARKDOWN)


async def captions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	if not is_admin(user_id):
		ok, _ = await check_user_joined(context.bot, user_id)
		if not ok:
			force = await get_force_config()
			await update.message.reply_text(
				"🔒 *Access Restricted*\n\nPlease join the required channels to use this bot.",
				reply_markup=build_join_buttons(force),
				disable_web_page_preview=True,
				parse_mode=ParseMode.MARKDOWN,
			)
			return
	caps = await list_captions(user_id)
	if not caps:
		await update.message.reply_text("Empty list. Use /settemplate to create a caption.")
		return
	await update.message.reply_text("🗂 *Caption List*:", reply_markup=kb_list(caps, page=1), parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	act = await get_active_caption_id(user_id)
	cap = await get_caption(user_id, act) if act else None
	my_caps = await list_captions(user_id)
	parts = [
		"👤 *Your status*",
		f"• Captions: {len(my_caps)}",
		"• Active: " + (f"**{cap['name']}** — {cap.get('version') or '—'} — {cap.get('lang') or '—'} (next: {cap.get('next_ep', 1)})" if cap else "none"),
	]
	if is_admin(user_id):
		user_stats = await get_user_stats()
		force = await get_force_config()
		stats = await get_stats()
		uptime = format_uptime(time.time() - START_TIME)
		parts += [
			"",
			"👥 *Users:*",
			f"• Total: {user_stats['total']}",
			f"• Active (1 hour): {user_stats['active_1h']}",
			f"• Active (24 hours): {user_stats['active_24h']}",
			f"• Active (7 days): {user_stats['active_7d']}",
			f"• Inactive (7+ days): {user_stats['inactive_7d']}",
			"",
			"🛡 *System*",
			f"• Files: {stats['files']}",
			f"• Storage: {format_bytes(stats['storage_bytes'])}",
			f"• Force: {'ON' if force.get('enabled') else 'OFF'} ({len(force.get('channels', []))})",
			f"• Uptime: {uptime}",
		]
	await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.MARKDOWN)


async def parse_text_for_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	if not is_admin(user_id):
		ok, _ = await check_user_joined(context.bot, user_id)
		if not ok:
			force = await get_force_config()
			await update.message.reply_text(
				"🔒 *Access Restricted*\n\nPlease join the required channels to use this bot.",
				reply_markup=build_join_buttons(force),
				disable_web_page_preview=True,
				parse_mode=ParseMode.MARKDOWN,
			)
			return
	tokens = parse_tokens(update.message.text or "")
	if not tokens:
		return
	from config import add_caption  # defer to avoid circular import
	ok, msg, cid = await add_caption(user_id, tokens.get("name"), tokens.get("version"), tokens.get("lang"))
	if not ok:
		await update.message.reply_text(msg)
		return
	await set_active_caption_id(user_id, cid)
	cap = await get_caption(user_id, cid)
	await update.message.reply_text(
		f"{msg}\n"
		f"🔸 *Now Active*: **{cap['name']}** — {cap.get('version') or '—'} — {cap.get('lang') or '—'} (next: {cap.get('next_ep', 1)})\n"
		f"➡️ Send files to publish.",
		parse_mode=ParseMode.MARKDOWN,
	)


async def settings_home_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	prefs = await get_user_tag_prefs(uid)
	kb = kb_settings_menu(prefs["tag"], prefs["position"])
	info = (
		"⚙️ *Settings*\n"
		f"• Hashtag: `{prefs['tag'] or '—'}`\n"
		f"• Position: `{prefs['position']}`\n\n"
		"Choose an option:"
	)
	await cq.message.edit_text(info, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def home_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	text = (
		"👋 *Auto-Caption Bot*\n\n"
		"• Send files to generate your caption\n\n"
		"*Commands:*\n"
		"/settemplate - Set series and episode\n"
		"/captions - Manage captions\n"
		"/status - Bot stats\n"
	)
	text += "/help - Help / Guide\n"
	text += "\n*Admin:* /forceon /forceoff /addforce /delforce /forcelist /broadcast"
	await cq.message.edit_text(text, reply_markup=kb_home(), disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)


async def settings_toggle_pos_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	prefs = await get_user_tag_prefs(uid)
	new_pos = "start" if prefs["position"] == "end" else "end"
	await set_tag_position(uid, new_pos)
	prefs = await get_user_tag_prefs(uid)
	kb = kb_settings_menu(prefs["tag"], prefs["position"])
	await cq.message.edit_text("⚙️ *Settings*\n✅ Position updated.", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def settings_add_hashtag_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	await cq.message.edit_text(
		"✍️ *Send your hashtag/username now.*\n"
		"Examples: `@djd208` • `#AnimeClub` • `djd208`",
		parse_mode=ParseMode.MARKDOWN
	)
	return SET_WAIT_TAG


async def settings_receive_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE):
	uid = update.effective_user.id
	raw = (update.message.text or "").strip()
	try:
		print(f"[wait_tag] from {uid}: '{raw}'")
	except Exception:
		pass
	if not raw:
		await update.message.reply_text("❌ Empty. Try again or /cancel.")
		return SET_WAIT_TAG
	if len(raw) > 64:
		await update.message.reply_text("⚠️ Too long (max 64 chars). Try again.")
		return SET_WAIT_TAG
	await set_user_tag(uid, raw)
	prefs = await get_user_tag_prefs(uid)
	kb = kb_settings_menu(prefs["tag"], prefs["position"])
	await update.message.reply_text("✅ Hashtag saved.", reply_markup=kb)
	return ConversationHandler.END


async def settings_remove_hashtag_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	await set_user_tag(uid, None)
	prefs = await get_user_tag_prefs(uid)
	kb = kb_settings_menu(prefs["tag"], prefs["position"])
	await cq.message.edit_text("⚙️ *Settings*\n🗑 Hashtag removed.", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.callback_query.answer()


async def open_caption_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	try:
		cid = int(cq.data.split(":")[2])
	except Exception:
		await cq.message.edit_text("⚠️ Invalid ID.")
		return
	cap = await get_caption(uid, cid)
	if not cap:
		await cq.message.edit_text("⚠️ Caption not found.")
		return
	kb = InlineKeyboardMarkup([
		[InlineKeyboardButton("▶️ Continue", callback_data=f"cap:use:{cid}:cont"), InlineKeyboardButton("🔁 Start Over", callback_data=f"cap:use:{cid}:start")],
		[InlineKeyboardButton("🗑 Delete", callback_data=f"cap:del:{cid}")],
		[InlineKeyboardButton("⬅️ Back", callback_data="cap:list:1")],
	])
	label = f"**{cap['name']}** — {cap.get('version') or '—'} — {cap.get('lang') or '—'} (next: {cap.get('next_ep',1)})"
	await cq.message.edit_text(f"📄 {label}", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def use_caption_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	_, _, cid_str, mode = cq.data.split(":")
	cid = int(cid_str)
	cap = await get_caption(uid, cid)
	if not cap:
		await cq.message.edit_text("⚠️ Caption not found.")
		return
	if mode == "start":
		await set_caption_fields(uid, cid, next_ep=1)
	await set_active_caption_id(uid, cid)
	await cq.message.edit_text(
		"✅ Caption activated.\n"
		f"• **{cap['name']}** — {cap.get('version') or '—'} — {cap.get('lang') or '—'} "
		f"(next: {cap.get('next_ep',1) if mode!='start' else 1})",
		parse_mode=ParseMode.MARKDOWN
	)


async def delete_caption_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	cid = int(cq.data.split(":")[2])
	act = await get_active_caption_id(uid)
	if act == cid:
		await set_active_caption_id(uid, None)
	ok = await delete_caption(uid, cid)
	if not ok:
		await cq.message.edit_text("ℹ️ Nothing to delete.")
		return
	caps = await list_captions(uid)
	if not caps:
		await cq.message.edit_text("Empty list.")
		return
	await cq.message.edit_text("🗂 *Caption List*:", reply_markup=kb_list(caps, page=1), parse_mode=ParseMode.MARKDOWN)


async def list_captions_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	try:
		page = int(cq.data.split(":")[2])
	except Exception:
		page = 1
	caps = await list_captions(uid)
	if not caps:
		await cq.message.edit_text("Empty list.")
		return
	await cq.message.edit_text("🗂 *Caption List*:", reply_markup=kb_list(caps, page=page), parse_mode=ParseMode.MARKDOWN)


# -----------------------------
# Multi-caption UI & callbacks
# -----------------------------
def _mc_label(doc: dict, checked: bool) -> str:
	box = "☑️" if checked else "⬜"
	return f"{box} {doc['name']} — {doc.get('version') or '—'} — {doc.get('lang') or '—'}"


async def mc_list_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query; await cq.answer()
	uid = cq.from_user.id
	try:
		page = int(cq.data.split(":")[2])
	except Exception:
		page = 1

	caps = await list_captions(uid)
	st = await get_multi_state(uid)
	selected = set(st["ids"])

	total = len(caps); page_size = 10
	start = (page - 1) * page_size; end = start + page_size
	chunk = caps[start:end]

	rows = []
	for doc in chunk:
		checked = doc["_id"] in selected
		rows.append([InlineKeyboardButton(_mc_label(doc, checked)[:64], callback_data=f"mc:tg:{doc['_id']}:{page}")])

	nav = []
	if start > 0:
		nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"mc:list:{page-1}"))
	if end < total:
		nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"mc:list:{page+1}"))
	if nav:
		rows.append(nav)

	rows.append([InlineKeyboardButton("🧹 Clear", callback_data="mc:clear"), InlineKeyboardButton("▶️ Start", callback_data="mc:start")])
	rows.append([InlineKeyboardButton("⬅️ Back", callback_data="cap:list:1")])

	txt = f"🎯 *Multi-select*\nSelect 2 to 10 captions.\nSelected: {len(selected)}"
	await cq.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)


async def mc_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query; await cq.answer()
	uid = cq.from_user.id
	_, _, cid_str, page_str = cq.data.split(":")
	cid = int(cid_str); page = int(page_str)
	await toggle_multi_id(uid, cid)
	# refresh same page
	cq.data = f"mc:list:{page}"
	await mc_list_cb(update, context)


async def mc_clear_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query; await cq.answer()
	uid = cq.from_user.id
	await clear_multi(uid)
	cq.data = "mc:list:1"
	await mc_list_cb(update, context)


async def mc_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query; await cq.answer()
	uid = cq.from_user.id
	st = await get_multi_state(uid)
	n = len(st["ids"])
	if n < 2 or n > 10:
		await cq.answer("Choose between 2 and 10 captions.", show_alert=True)
		cq.data = "mc:list:1"
		await mc_list_cb(update, context)
		return
	await set_multi_enabled(uid, True)
	await set_active_caption_id(uid, None)
	await cq.message.edit_text(f"✅ Multi-caption *enabled* ({n} selected). Send your files.", parse_mode=ParseMode.MARKDOWN)

async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
	msg = update.message
	if not msg:
		return

	user_id = update.effective_user.id

	# Force-Join si non admin
	if not is_admin(user_id):
		ok, _ = await check_user_joined(context.bot, user_id)
		if not ok:
			force = await get_force_config()
			await msg.reply_text(
				"🔒 *Access Restricted*\n\nPlease join the required channels to use this bot.",
				reply_markup=build_join_buttons(force),
				disable_web_page_preview=True,
				parse_mode=ParseMode.MARKDOWN,
			)
			return

	# Priorité au mode multi-caption si activé
	st = await get_multi_state(user_id)
	use_multi = bool(st.get("enabled") and st.get("ids"))
	if use_multi:
		ids = st["ids"]
		ptr = st.get("pointer", 0) % len(ids)
		cid = int(ids[ptr])
		cap = await get_caption(user_id, cid)
		if not cap:
			# remove missing id and retry
			ids = [x for x in ids if x != cid]
			await set_multi_ids(user_id, ids)
			if not ids:
				await set_multi_enabled(user_id, False)
				await msg.reply_text("ℹ️ Multi-captions are empty. Use /captions → 🎯 Multi-select.")
				return
			await on_media(update, context)
			return
	else:
		# Légende active requise
		cid = await get_active_caption_id(user_id)
		if not cid:
			await msg.reply_text("⚠️ No active caption. Use `/captions`.", parse_mode=ParseMode.MARKDOWN)
			return
		cap = await get_caption(user_id, cid)
		if not cap:
			await set_active_caption_id(user_id, None)
			await msg.reply_text("⚠️ Caption not found.")
			return

	u = await get_user(user_id)
	caption = build_caption(
		u["template"],
		cap["name"],
		int(cap.get("next_ep", 1)),
		int(cap.get("zero_pad", 0)),
		cap.get("version") or "",
		cap.get("lang") or ""
	)

	# Appliquer le hashtag/username auto
	prefs = await get_user_tag_prefs(user_id)
	caption = apply_tag_to_caption(caption, prefs.get("tag"), prefs.get("position"))

	# Selon le type: pour les documents on renvoie avec un nom de fichier final,
	# sinon on copie simplement le message avec la légende mise à jour
	try:
		if msg.document:
			original_name = msg.document.file_name or "file"
			final_name = await build_final_filename(user_id, original_name)
			# Télécharge le fichier puis renvoie avec le nom final
			file = await msg.document.get_file()
			tmp_path = os.path.join(
				tempfile.gettempdir(), f"acb_{msg.document.file_unique_id}_{final_name}"
			)
			await file.download_to_drive(custom_path=tmp_path)
			try:
				await context.bot.send_document(
					chat_id=msg.chat_id,
					document=InputFile(tmp_path, filename=final_name),
					caption=caption,
				)
			finally:
				try:
					os.remove(tmp_path)
				except Exception:
					pass
		else:
			await context.bot.copy_message(
				chat_id=msg.chat_id,
				from_chat_id=msg.chat_id,
				message_id=msg.message_id,
				caption=caption
			)

		# Stats & episode increment
		file_size = (
			(msg.document and msg.document.file_size) or
			(msg.video and msg.video.file_size) or
			(msg.animation and msg.animation.file_size) or
			(msg.photo and msg.photo[-1].file_size) or
			0
		)
		await update_stats(files_delta=1, bytes_delta=file_size)
		await set_caption_fields(user_id, cid, next_ep=int(cap.get("next_ep", 1)) + 1)
		if use_multi:
			await advance_multi_pointer(user_id)

		# (Optional) ack text
		await msg.reply_text(
			f"✅ Caption added.\n➡️ Next episode: {int(cap.get('next_ep', 1))+1}\n\n🙏 Please share this bot with your friends."
		)

	except Exception as e:
		await msg.reply_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def fs_refresh_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	if not update.callback_query:
		return
	cq = update.callback_query
	uid = cq.from_user.id
	# Clear cache to force fresh check
	clear_force_join_cache(uid)
	ok, _ = await check_user_joined(context.bot, uid, use_cache=False)
	if ok:
		await cq.message.edit_text("✅ Access granted!")
	else:
		force = await get_force_config()
		await cq.message.edit_text(
			"⏳ Not joined yet. Try again after.", reply_markup=build_join_buttons(force)
		)
	await cq.answer()


async def debug_trap(update: Update, context: ContextTypes.DEFAULT_TYPE):
	try:
		if os.getenv("DEBUG", "0") == "1" and is_admin(update.effective_user.id):
			txt = update.message.text or (update.message.caption or "<no text>")
			await update.message.reply_text(f"[debug] received: {txt}")
			print(f"[debug] message from {update.effective_user.id}: {txt}")
	except Exception:
		pass


async def echo_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
	try:
		if os.getenv("ECHO_ALL", "0") == "1":
			txt = update.message.text or (update.message.caption or "<no text>")
			await update.message.reply_text(f"echo: {txt}")
	except Exception:
		pass


async def post_init(application: Application):
	# Set bot commands (menu) and print bot identity
	cmds = [
		BotCommand("start", "Start the bot"),
		BotCommand("settemplate", "Set series and episode"),
		BotCommand("captions", "Manage your captions"),
		BotCommand("status", "View your status"),
	]
	cmds.append(BotCommand("help", "Show help/guide"))
	cmds += [
		BotCommand("forceon", "(Admin) Enable force join"),
		BotCommand("forceoff", "(Admin) Disable force join"),
		BotCommand("addforce", "(Admin) Add force channel"),
		BotCommand("delforce", "(Admin) Delete force channel"),
		BotCommand("forcelist", "(Admin) List force channels"),
		BotCommand("broadcast", "(Admin) Broadcast message to all users"),
	]
	await application.bot.set_my_commands(cmds)
	me = await application.bot.get_me()
	print(f"Auto-Caption Bot started as @{me.username} (id={me.id})")


def main():
	# Initialize database (async) before starting polling
	asyncio.run(init_db())
	application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

	# Register command handlers
	application.add_handler(CommandHandler("start", start_cmd))
	application.add_handler(CommandHandler("ping", ping_cmd))
	application.add_handler(CommandHandler("settemplate", settemplate_cmd))
	application.add_handler(CommandHandler("captions", captions_cmd))
	application.add_handler(CommandHandler("status", status_cmd))
	async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if HELP_URL:
			kb = InlineKeyboardMarkup([[InlineKeyboardButton(text="📘 Full Guide (Telegraph)", url=HELP_URL)]])
			text = (
				"<b>Auto-Caption Bot — Help</b>\n\n"
				"Create a template with /settemplate, then send files to publish.\n"
				"Tap the button below for the full guide."
			)
			await update.message.reply_html(text, reply_markup=kb, disable_web_page_preview=True)
		else:
			await update.message.reply_text(
				"Help: Use /settemplate to set your template, then send files here.\n"
				"Commands: /settemplate, /captions, /status, /help"
			)
	application.add_handler(CommandHandler("help", help_cmd))

	# Conversation: saisie hashtag (register early so state handlers take precedence)
	application.add_handler(ConversationHandler(
		entry_points=[CallbackQueryHandler(settings_add_hashtag_cb, pattern=r"^set:add$")],
		states={
			SET_WAIT_TAG: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND), settings_receive_hashtag)],
		},
		fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
	))

	# Message handlers (order matters)
	application.add_handler(MessageHandler(
		filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.PHOTO | filters.ANIMATION),
		on_media
	))
	application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND), parse_text_for_caption))

	# Callback queries
	application.add_handler(CallbackQueryHandler(fs_refresh_cb, pattern=r"^fs:refresh$"))
	application.add_handler(CallbackQueryHandler(settings_home_cb, pattern=r"^set:home$"))
	application.add_handler(CallbackQueryHandler(settings_toggle_pos_cb, pattern=r"^set:pos$"))
	application.add_handler(CallbackQueryHandler(settings_remove_hashtag_cb, pattern=r"^set:rm$"))
	application.add_handler(CallbackQueryHandler(home_cb, pattern=r"^home$"))
	application.add_handler(CallbackQueryHandler(noop_cb, pattern=r"^noop$"))
	application.add_handler(CallbackQueryHandler(list_captions_cb, pattern=r"^cap:list:\d+$"))
	application.add_handler(CallbackQueryHandler(open_caption_cb, pattern=r"^cap:open:\d+$"))
	application.add_handler(CallbackQueryHandler(use_caption_cb, pattern=r"^cap:use:\d+:(cont|start)$"))
	application.add_handler(CallbackQueryHandler(delete_caption_cb, pattern=r"^cap:del:\d+$"))
	# Multi-caption handlers
	application.add_handler(CallbackQueryHandler(mc_list_cb, pattern=r"^mc:list:\d+$"))
	application.add_handler(CallbackQueryHandler(mc_toggle_cb, pattern=r"^mc:tg:\d+:\d+$"))
	application.add_handler(CallbackQueryHandler(mc_clear_cb, pattern=r"^mc:clear$"))
	application.add_handler(CallbackQueryHandler(mc_start_cb, pattern=r"^mc:start$"))


	# Admin handlers
	register_admin_handlers(application)

	# Debug / echo (last)
	application.add_handler(MessageHandler(filters.ChatType.PRIVATE, debug_trap))
	application.add_handler(MessageHandler(filters.ChatType.PRIVATE, echo_all))

	# Run bot (blocking)
	application.run_polling()


if __name__ == "__main__":
	main()


