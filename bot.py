import asyncio
import html
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
	set_ep_from_name,
	episode_in_name,
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

import big_files
from admin import register_admin_handlers

H = ParseMode.HTML
esc = html.escape


def cap_label(cap: dict) -> str:
	"""A caption as shown in messages (HTML, the user's text escaped)."""
	return (f"<b>{esc(cap['name'])}</b> — {esc(cap.get('version') or '—')} — {esc(cap.get('lang') or '—')} "
			f"(next: {cap.get('next_ep', 1)})")


ACCESS_RESTRICTED = "🔒 <b>Access Restricted</b>\n\nPlease join the required channels to use this bot."
HOME_TEXT = (
	"👋 <b>Auto-Caption Bot</b>\n\n"
	"• Send files to generate your caption\n\n"
	"<b>Commands:</b>\n"
	"/settemplate - Set series and episode\n"
	"/captions - Manage captions\n"
	"/status - Bot stats\n"
	"/help - Help / Guide\n"
	"\n<b>Admin:</b> /forceon /forceoff /addforce /delforce /forcelist /broadcast"
)


def kb_home():
	rows = [[InlineKeyboardButton("⚙️ Settings", callback_data="set:home"), InlineKeyboardButton("🗂 Captions", callback_data="cap:list:1")]]
	if HELP_URL:
		rows.append([InlineKeyboardButton("📘 Guide (Telegraph)", url=HELP_URL)])
	return InlineKeyboardMarkup(rows)


SET_WAIT_TAG = 9101

def kb_settings_menu(prefs: dict):
	return InlineKeyboardMarkup([
		[InlineKeyboardButton("📍 Change Position", callback_data="set:pos")],
		[InlineKeyboardButton("➕ Add/Edit Hashtag", callback_data="set:add")],
		[InlineKeyboardButton("🗑 Remove Hashtag", callback_data="set:rm")],
		[InlineKeyboardButton("🔢 Episode: " + ("from file name ✅" if prefs.get("ep_from_name", True) else "counter only"),
							  callback_data="set:epn")],
		[InlineKeyboardButton("⬅️ Back", callback_data="home")],
	])


def settings_text(prefs: dict, note: str = "") -> str:
	return (
		"⚙️ <b>Settings</b>\n"
		+ (f"{note}\n" if note else "")
		+ f"• Hashtag: <code>{esc(prefs['tag'] or '—')}</code>\n"
		f"• Position: <code>{prefs['position']}</code>\n"
		"• Episode number: " + ("taken from the file name when it has one (<i>- 03</i>, <i>S02E03</i>, <i>EP12</i>), "
								"else the counter" if prefs.get("ep_from_name", True) else "the counter only") + "\n\n"
		"Choose an option:"
	)


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


async def _restricted(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
	"""True (and the join buttons sent) when a non-admin hasn't joined the required channels."""
	if is_admin(user_id):
		return False
	ok, _ = await check_user_joined(context.bot, user_id)
	if ok:
		return False
	force = await get_force_config()
	await update.effective_message.reply_text(ACCESS_RESTRICTED, reply_markup=build_join_buttons(force),
											  disable_web_page_preview=True, parse_mode=H)
	return True


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
		if await _restricted(update, context, user_id):
			return
	except Exception as e:
		print(f"force_join check failed: {e}")
	# Warm user profile (best effort)
	try:
		await get_user(user_id)
	except Exception as e:
		print(f"get_user failed: {e}")
	await update.message.reply_text(HOME_TEXT, reply_markup=kb_home(), disable_web_page_preview=True, parse_mode=H)


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text("pong")


async def settemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	await track_user(user_id)
	if await _restricted(update, context, user_id):
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
		if not ok and not cid:
			await update.message.reply_text(msg, parse_mode=H)
			return
		await set_active_caption_id(user_id, cid)
		await set_caption_fields(user_id, cid, next_ep=int(ep), zero_pad=int(zero_pad))
		await update.message.reply_text(
			"✅ Template saved and active caption prepared.\n"
			f"• Series: <code>{esc(series)}</code>\n"
			f"• Current Episode: <code>{str(ep).zfill(zero_pad)}</code>\n"
			f"• Version: <code>{esc(version or '—')}</code>\n"
			f"• Language: <code>{esc(lang or '—')}</code>\n\n"
			"➡️ Now send a file to generate the caption.",
			parse_mode=H
		)
		return

	# 2) Ancien mode: placeholders bruts
	parts = raw.split(None, 1)
	if len(parts) < 2:
		await update.message.reply_text(
			"Usage (values):\n"
			"<code>/settemplate One Piece — Episode 12 — 1080p — VF</code>\n\n"
			"Or (custom template with placeholders):\n"
			"<code>/settemplate {series} Episode {ep}  {version}  {lang}</code>",
			parse_mode=H,
		)
		return
	tpl = parts[1].strip()
	await set_user(user_id, template=tpl)
	await update.message.reply_text(f"✅ Template saved:\n<code>{esc(tpl)}</code>", parse_mode=H)


async def captions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	await track_user(user_id)
	if await _restricted(update, context, user_id):
		return
	caps = await list_captions(user_id)
	if not caps:
		await update.message.reply_text("Empty list. Use /settemplate to create a caption.")
		return
	await update.message.reply_text("🗂 <b>Caption List</b>:", reply_markup=kb_list(caps, page=1), parse_mode=H)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	await track_user(user_id)
	act = await get_active_caption_id(user_id)
	cap = await get_caption(user_id, act) if act else None
	my_caps = await list_captions(user_id)
	parts = [
		"👤 <b>Your status</b>",
		f"• Captions: {len(my_caps)}",
		"• Active: " + (cap_label(cap) if cap else "none"),
	]
	if is_admin(user_id):
		user_stats = await get_user_stats()
		force = await get_force_config()
		stats = await get_stats()
		uptime = format_uptime(time.time() - START_TIME)
		parts += [
			"",
			"👥 <b>Users:</b>",
			f"• Total: {user_stats['total']}",
			f"• Active (1 hour): {user_stats['active_1h']}",
			f"• Active (24 hours): {user_stats['active_24h']}",
			f"• Active (7 days): {user_stats['active_7d']}",
			f"• Inactive (7+ days): {user_stats['inactive_7d']}",
			"",
			"🛡 <b>System</b>",
			f"• Files: {stats['files']}",
			f"• Storage: {format_bytes(stats['storage_bytes'])}",
			f"• Force: {'ON' if force.get('enabled') else 'OFF'} ({len(force.get('channels', []))})",
			f"• Big files (over 20 MB) renamed: {'yes' if big_files.available() else 'no — caption only (API_ID/API_HASH missing)'}",
			f"• Uptime: {uptime}",
		]
	await update.message.reply_text("\n".join(parts), parse_mode=H)


async def parse_text_for_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	tokens = parse_tokens(update.message.text or "")
	if not tokens:
		return
	await track_user(user_id)
	if await _restricted(update, context, user_id):
		return
	ok, msg, cid = await add_caption(user_id, tokens.get("name"), tokens.get("version"), tokens.get("lang"))
	if not ok:
		await update.message.reply_text(msg, parse_mode=H)
		return
	await set_active_caption_id(user_id, cid)
	cap = await get_caption(user_id, cid)
	await update.message.reply_text(
		f"{msg}\n"
		f"🔸 <b>Now Active</b>: {cap_label(cap)}\n"
		f"➡️ Send files to publish.",
		parse_mode=H,
	)


async def settings_home_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	prefs = await get_user_tag_prefs(cq.from_user.id)
	await cq.message.edit_text(settings_text(prefs), reply_markup=kb_settings_menu(prefs), parse_mode=H)


async def home_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	await cq.message.edit_text(HOME_TEXT, reply_markup=kb_home(), disable_web_page_preview=True, parse_mode=H)


async def settings_toggle_pos_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	prefs = await get_user_tag_prefs(uid)
	new_pos = "start" if prefs["position"] == "end" else "end"
	await set_tag_position(uid, new_pos)
	prefs = await get_user_tag_prefs(uid)
	await cq.message.edit_text(settings_text(prefs, "✅ Position updated."), reply_markup=kb_settings_menu(prefs), parse_mode=H)


async def settings_toggle_epn_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	prefs = await get_user_tag_prefs(uid)
	await set_ep_from_name(uid, not prefs.get("ep_from_name", True))
	prefs = await get_user_tag_prefs(uid)
	await cq.message.edit_text(settings_text(prefs, "✅ Episode numbering updated."), reply_markup=kb_settings_menu(prefs),
							   parse_mode=H)


async def settings_add_hashtag_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	await cq.message.edit_text(
		"✍️ <b>Send your hashtag/username now.</b>\n"
		"Examples: <code>@djd208</code> • <code>#AnimeClub</code> • <code>djd208</code>",
		parse_mode=H
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
	await update.message.reply_text("✅ Hashtag saved.", reply_markup=kb_settings_menu(prefs))
	return ConversationHandler.END


async def settings_remove_hashtag_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	await set_user_tag(uid, None)
	prefs = await get_user_tag_prefs(uid)
	await cq.message.edit_text(settings_text(prefs, "🗑 Hashtag removed."), reply_markup=kb_settings_menu(prefs), parse_mode=H)


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
	await cq.message.edit_text(f"📄 {cap_label(cap)}", reply_markup=kb_caption_actions(cid, cap["name"], cap.get("next_ep", 1)),
							   parse_mode=H)


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
		cap["next_ep"] = 1
	await set_active_caption_id(uid, cid)
	await cq.message.edit_text(f"✅ Caption activated.\n• {cap_label(cap)}", parse_mode=H)


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
	await cq.message.edit_text("🗂 <b>Caption List</b>:", reply_markup=kb_list(caps, page=1), parse_mode=H)


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
	await cq.message.edit_text("🗂 <b>Caption List</b>:", reply_markup=kb_list(caps, page=page), parse_mode=H)


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

	txt = f"🎯 <b>Multi-select</b>\nSelect 2 to 10 captions.\nSelected: {len(selected)}"
	await cq.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(rows), parse_mode=H)


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
	await cq.message.edit_text(f"✅ Multi-caption <b>enabled</b> ({n} selected). Send your files.", parse_mode=H)


# -----------------------------
# Files: caption now, sent back in order through each user's queue
# -----------------------------
SMALL_LIMIT = 20 * 1024 * 1024     # the Bot API downloads files up to 20 MB; bigger ones go through MTProto
SUMMARY_WAIT = 3.0                 # seconds after a user's last file before the "✅ captions added" summary
_QUEUES: dict[int, asyncio.Queue] = {}
_WORKERS: dict[int, asyncio.Task] = {}
_DONE: dict[int, list] = {}        # user → [(caption id, episode, note)] since the last summary
_SUMMARY_TASKS: dict[int, asyncio.Task] = {}


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
	msg = update.message
	if not msg:
		return

	user_id = update.effective_user.id
	await track_user(user_id)
	if await _restricted(update, context, user_id):
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
			await msg.reply_text("⚠️ No active caption. Use /captions.")
			return
		cap = await get_caption(user_id, cid)
		if not cap:
			await set_active_caption_id(user_id, None)
			await msg.reply_text("⚠️ Caption not found.")
			return

	# The episode: from the file name when it has one (unless the user turned it off), else the counter
	prefs = await get_user_tag_prefs(user_id)
	counter = int(cap.get("next_ep", 1))
	file_name = (msg.document and msg.document.file_name) or (msg.video and msg.video.file_name) or ""
	named = episode_in_name(file_name) if prefs.get("ep_from_name", True) else None
	ep = named or counter

	u = await get_user(user_id)
	caption = build_caption(u["template"], cap["name"], ep, int(cap.get("zero_pad", 0)),
							cap.get("version") or "", cap.get("lang") or "")
	caption = apply_tag_to_caption(caption, prefs.get("tag"), prefs.get("position"))

	# The number is taken now, so the next file gets the next one even while this one is still on its way
	await set_caption_fields(user_id, cid, next_ep=max(counter, ep + 1))
	if use_multi:
		await advance_multi_pointer(user_id)

	file_size = (
		(msg.document and msg.document.file_size) or
		(msg.video and msg.video.file_size) or
		(msg.animation and msg.animation.file_size) or
		(msg.photo and msg.photo[-1].file_size) or
		0
	)
	job = {"chat_id": msg.chat_id, "message_id": msg.message_id, "caption": caption, "cid": cid, "ep": ep,
		   "size": file_size, "kind": "copy"}
	if msg.document:
		job["final_name"] = await build_final_filename(user_id, msg.document.file_name or "file")
		job["kind"] = "small" if file_size <= SMALL_LIMIT else "big"
		job["file_id"] = msg.document.file_id
		job["file_unique_id"] = msg.document.file_unique_id
	_enqueue(user_id, job, context.bot)


def _enqueue(user_id: int, job: dict, bot) -> None:
	pending = _SUMMARY_TASKS.pop(user_id, None)       # more files: the summary waits for them
	if pending and not pending.done():
		pending.cancel()
	q = _QUEUES.setdefault(user_id, asyncio.Queue())
	q.put_nowait(job)
	task = _WORKERS.get(user_id)
	if task is None or task.done():
		_WORKERS[user_id] = asyncio.create_task(_worker(user_id, q, bot))


async def _worker(user_id: int, q: asyncio.Queue, bot) -> None:
	"""One user's files, one after the other, in the order they came (a big one takes minutes: other
	users' files don't wait for it)."""
	while True:
		if q.empty():                               # no await between this check and leaving
			_WORKERS.pop(user_id, None)
			_schedule_summary(user_id, bot)
			return
		job = q.get_nowait()
		try:
			note = await _send(job, bot)
			_DONE.setdefault(user_id, []).append((job["cid"], job["ep"], note))
			await update_stats(files_delta=1, bytes_delta=job["size"] or 0)
		except Exception as e:
			try:
				await bot.send_message(job["chat_id"], f"❌ Episode {job['ep']}: <code>{esc(str(e)[:300])}</code>",
									   parse_mode=H, reply_to_message_id=job["message_id"])
			except Exception:
				pass


async def _send(job: dict, bot) -> str | None:
	"""Send one file back with its caption (and its new name). Returns a note for the summary."""
	chat_id, message_id = job["chat_id"], job["message_id"]
	if job["kind"] == "copy":
		await bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=message_id, caption=job["caption"])
		return None
	if job["kind"] == "small":
		file = await bot.get_file(job["file_id"])
		tmp_path = os.path.join(tempfile.gettempdir(), f"acb_{job['file_unique_id']}_{job['final_name']}")
		await file.download_to_drive(custom_path=tmp_path)
		try:
			await bot.send_document(chat_id=chat_id, document=InputFile(tmp_path, filename=job["final_name"]),
									caption=job["caption"])
		finally:
			try:
				os.remove(tmp_path)
			except Exception:
				pass
		return None
	# big: renamed through MTProto when the bot can, else the caption only (the name unchanged)
	if not big_files.available():
		await bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=message_id, caption=job["caption"])
		return "name kept (file over 20 MB)"
	status = await bot.send_message(chat_id, f"⏳ Big file ({format_bytes(job['size'])}): renaming…",
									reply_to_message_id=message_id)

	async def progress(text: str):
		await status.edit_text(f"⏳ Big file ({format_bytes(job['size'])}): {text}")
	try:
		await big_files.rename(chat_id, message_id, job["final_name"], job["caption"], progress)
	finally:
		try:
			await status.delete()
		except Exception:
			pass
	return None


def _schedule_summary(user_id: int, bot) -> None:
	old = _SUMMARY_TASKS.pop(user_id, None)
	if old and not old.done():
		old.cancel()
	_SUMMARY_TASKS[user_id] = asyncio.create_task(_summary_after(user_id, bot))


async def _summary_after(user_id: int, bot) -> None:
	"""One message for a whole group of files, once they are all back."""
	try:
		await asyncio.sleep(SUMMARY_WAIT)
	except asyncio.CancelledError:
		return
	_SUMMARY_TASKS.pop(user_id, None)
	done = _DONE.pop(user_id, [])
	if not done:
		return
	lines = []
	if len(done) == 1:
		lines.append("✅ Caption added.")
	else:
		eps = [ep for _, ep, _ in done]
		lines.append(f"✅ {len(done)} captions added (episodes {min(eps)} → {max(eps)}).")
	for cid in dict.fromkeys(c for c, _, _ in done):
		cap = await get_caption(user_id, cid)
		if cap:
			lines.append(f"➡️ Next episode{(' of ' + esc(cap['name'])) if len(done) > 1 else ''}: {cap.get('next_ep', 1)}")
	notes = [n for _, _, n in done if n]
	if notes:
		lines.append(f"ℹ️ {len(notes)} file(s): {esc(notes[0])}.")
	lines.append("\n🙏 Please share this bot with your friends.")
	try:
		await bot.send_message(user_id, "\n".join(lines), parse_mode=H)
	except Exception:
		pass


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
	print("Big files (over 20 MB): " + ("renamed through MTProto" if big_files.available()
										 else "caption only — set API_ID / API_HASH to rename them"))


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


def build_application() -> Application:
	application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

	# Register command handlers
	application.add_handler(CommandHandler("start", start_cmd))
	application.add_handler(CommandHandler("ping", ping_cmd))
	application.add_handler(CommandHandler("settemplate", settemplate_cmd))
	application.add_handler(CommandHandler("captions", captions_cmd))
	application.add_handler(CommandHandler("status", status_cmd))
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
	application.add_handler(CallbackQueryHandler(settings_toggle_epn_cb, pattern=r"^set:epn$"))
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
	return application


def main():
	# Initialize database (async) before starting polling
	asyncio.run(init_db())
	# Run bot (blocking)
	build_application().run_polling()


if __name__ == "__main__":
	main()
