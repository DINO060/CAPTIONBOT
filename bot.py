import asyncio
import os
import time
from typing import List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
	Application,
	CommandHandler,
	MessageHandler,
	CallbackQueryHandler,
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
	get_stats,
	get_force_config,
	format_uptime,
	format_bytes,
	parse_tokens,
	parse_settemplate_values,
	check_user_joined,
	build_join_buttons,
	add_caption,
    delete_caption,
)

from admin import register_admin_handlers


def kb_home():
	return InlineKeyboardMarkup([
		[InlineKeyboardButton("⚙️ Settings", callback_data="set:home"),
		 InlineKeyboardButton("🗂 Captions", callback_data="cap:list:1")],
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
	await update.message.reply_text(
		"👋 *Auto-Caption Bot*\n\n"
		"• Envoyez du texte avec `/n`, `/v`, `/l` pour créer des légendes\n"
		"• Envoyez des fichiers pour générer votre légende\n\n"
		"*Commandes:*\n"
		"/settemplate - Définir la série et l'épisode\n"
		"/captions - Gérer les légendes\n"
		"/status - Statistiques du bot\n\n"
		"*Admin:* /forceon /forceoff /addforce /delforce /forcelist",
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

	# 1) Mode valeurs: "<series> — Episode <ep> — <version> — <lang>"
	parsed = parse_settemplate_values(raw)
	if parsed:
		series, ep, zero_pad, version, lang = parsed
		# Fixe le modèle standard
		tpl = "{series} — Episode {ep} — {version} — {lang}"
		await set_user(user_id, template=tpl)
		# Crée/active la caption correspondante
		ok, msg, cid = await add_caption(user_id, series, version, lang)
		if not ok and cid:
			pass
		elif not ok and "existe déjà" in msg:
			caps = await list_captions(user_id)
			from config import norm
			found = next((c for c in caps if norm(c.get("name",""))==norm(series) and norm(c.get("version",""))==norm(version) and norm(c.get("lang",""))==norm(lang)), None)
			cid = found["_id"] if found else None
			if not cid:
				await update.message.reply_text("⚠️ Caption déjà existante mais introuvable. Réessaie.")
				return
		elif not ok:
			await update.message.reply_text(msg)
			return
		await set_active_caption_id(user_id, cid)
		await set_caption_fields(user_id, cid, next_ep=int(ep), zero_pad=int(zero_pad))
		await update.message.reply_text(
			"✅ Modèle enregistré **et** légende active préparée.\n"
			f"• Série : `{series}`\n"
			f"• Épisode actuel : `{str(ep).zfill(zero_pad)}`\n"
			f"• Version : `{version or '—'}`\n"
			f"• Langue : `{lang or '—'}`\n\n"
			"➡️ Envoie maintenant un fichier pour générer la légende.",
			parse_mode=ParseMode.MARKDOWN
		)
		return

	# 2) Ancien mode: placeholders bruts
	parts = raw.split(None, 1)
	if len(parts) < 2:
		await update.message.reply_text(
			"Usage (valeurs) :\n"
			"`/settemplate One Piece — Episode 12 — 1080p — VF`\n\n"
			"Ou (modèle personnalisé avec placeholders) :\n"
			"`/settemplate {series} — Episode {ep} — {version} — {lang}`",
			parse_mode=ParseMode.MARKDOWN,
		)
		return
	tpl = parts[1].strip()
	await set_user(user_id, template=tpl)
	await update.message.reply_text(f"✅ Modèle sauvegardé:\n`{tpl}`", parse_mode=ParseMode.MARKDOWN)


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
		await update.message.reply_text("Liste vide. Envoyez du texte avec `/n`, `/v`, `/l`.", parse_mode=ParseMode.MARKDOWN)
		return
	await update.message.reply_text("🗂 *Caption List*:", reply_markup=kb_list(caps, page=1), parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	act = await get_active_caption_id(user_id)
	cap = await get_caption(user_id, act) if act else None
	my_caps = await list_captions(user_id)
	parts = [
		"👤 *Votre statut*",
		f"• Légendes: {len(my_caps)}",
		"• Active: " + (f"**{cap['name']}** — {cap.get('version') or '—'} — {cap.get('lang') or '—'} (next: {cap.get('next_ep', 1)})" if cap else "aucune"),
	]
	if is_admin(user_id):
		total_users = await get_total_users()
		force = await get_force_config()
		stats = await get_stats()
		uptime = format_uptime(time.time() - START_TIME)
		parts += [
			"",
			"🛡 *Global*",
			f"• Users: {total_users}",
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
		f"🔸 *Active maintenant*: **{cap['name']}** — {cap.get('version') or '—'} — {cap.get('lang') or '—'} (next: {cap.get('next_ep', 1)})\n"
		f"➡️ Envoyez des fichiers pour publier.",
		parse_mode=ParseMode.MARKDOWN,
	)


async def open_caption_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	cq = update.callback_query
	await cq.answer()
	uid = cq.from_user.id
	try:
		cid = int(cq.data.split(":")[2])
	except Exception:
		await cq.message.edit_text("❌ ID invalide.")
		return
	cap = await get_caption(uid, cid)
	if not cap:
		await cq.message.edit_text("⚠️ Caption introuvable.")
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
		await cq.message.edit_text("⚠️ Caption introuvable.")
		return
	if mode == "start":
		await set_caption_fields(uid, cid, next_ep=1)
	await set_active_caption_id(uid, cid)
	await cq.message.edit_text(
		"✅ Caption activée.\n"
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
		await cq.message.edit_text("ℹ️ Rien à supprimer.")
		return
	caps = await list_captions(uid)
	if not caps:
		await cq.message.edit_text("Liste vide.")
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
		await cq.message.edit_text("Liste vide.")
		return
	await cq.message.edit_text("🗂 *Caption List*:", reply_markup=kb_list(caps, page=page), parse_mode=ParseMode.MARKDOWN)

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

	# Légende active requise
	cid = await get_active_caption_id(user_id)
	if not cid:
		await msg.reply_text("⚠️ Aucune légende active. Utilisez `/captions`.", parse_mode=ParseMode.MARKDOWN)
		return

	cap = await get_caption(user_id, cid)
	if not cap:
		await set_active_caption_id(user_id, None)
		await msg.reply_text("⚠️ Légende introuvable.")
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

	# Copie le même message dans CE chat avec la caption ajoutée
	try:
		await context.bot.copy_message(
			chat_id=msg.chat_id,
			from_chat_id=msg.chat_id,
			message_id=msg.message_id,
			caption=caption
		)

		# Stats & incrément de l'épisode
		file_size = (
			(msg.document and msg.document.file_size) or
			(msg.video and msg.video.file_size) or
			(msg.animation and msg.animation.file_size) or
			(msg.photo and msg.photo[-1].file_size) or
			0
		)
		await update_stats(files_delta=1, bytes_delta=file_size)
		await set_caption_fields(user_id, cid, next_ep=int(cap.get("next_ep", 1)) + 1)

		# (Optionnel) accusé texte
		await msg.reply_text(
			f"✅ Légende ajoutée.\n➡️ Prochain épisode: {int(cap.get('next_ep', 1))+1}"
		)

	except Exception as e:
		await msg.reply_text(f"❌ Erreur: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def fs_refresh_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
	if not update.callback_query:
		return
	cq = update.callback_query
	uid = cq.from_user.id
	ok, _ = await check_user_joined(context.bot, uid)
	if ok:
		await cq.message.edit_text("✅ Accès accordé !")
	else:
		force = await get_force_config()
		await cq.message.edit_text(
			"⏳ Pas encore rejoint. Réessayez après.", reply_markup=build_join_buttons(force)
		)
	await cq.answer()


async def debug_trap(update: Update, context: ContextTypes.DEFAULT_TYPE):
	try:
		if os.getenv("DEBUG", "0") == "1" and is_admin(update.effective_user.id):
			txt = update.message.text or (update.message.caption or "<no text>")
			await update.message.reply_text(f"[debug] reçu: {txt}")
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
	await application.bot.set_my_commands([
		BotCommand("start", "Démarrer le bot"),
		BotCommand("settemplate", "Définir la série et l'épisode"),
		BotCommand("captions", "Gérer vos légendes"),
		BotCommand("status", "Voir votre statut"),
		BotCommand("forceon", "(Admin) Activer force join"),
		BotCommand("forceoff", "(Admin) Désactiver force join"),
		BotCommand("addforce", "(Admin) Ajouter force channel"),
		BotCommand("delforce", "(Admin) Supprimer force channel"),
		BotCommand("forcelist", "(Admin) Lister force channels"),
	])
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

	# Message handlers (order matters)
	application.add_handler(MessageHandler(
		filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.PHOTO | filters.ANIMATION),
		on_media
	))
	application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND), parse_text_for_caption))

	# Callback queries
	application.add_handler(CallbackQueryHandler(fs_refresh_cb, pattern=r"^fs:refresh$"))
	application.add_handler(CallbackQueryHandler(list_captions_cb, pattern=r"^cap:list:\d+$"))
	application.add_handler(CallbackQueryHandler(open_caption_cb, pattern=r"^cap:open:\d+$"))
	application.add_handler(CallbackQueryHandler(use_caption_cb, pattern=r"^cap:use:\d+:(cont|start)$"))
	application.add_handler(CallbackQueryHandler(delete_caption_cb, pattern=r"^cap:del:\d+$"))

	# Admin handlers
	register_admin_handlers(application)

	# Debug / echo (last)
	application.add_handler(MessageHandler(filters.ChatType.PRIVATE, debug_trap))
	application.add_handler(MessageHandler(filters.ChatType.PRIVATE, echo_all))

	# Run bot (blocking)
	application.run_polling()


if __name__ == "__main__":
	main()


