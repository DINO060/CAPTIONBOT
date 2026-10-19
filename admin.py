import asyncio
import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
	get_force_config,
	set_force_config,
	add_force_channel,
	remove_force_channel,
	is_admin,
	get_all_user_ids,
)

H = ParseMode.HTML
BROADCAST_GAP = 0.05        # seconds between two users (≈ 20 a second, under Telegram's 30)


def register_admin_handlers(application: Application):
	async def admin_only(update: Update) -> bool:
		user_id = update.effective_user.id if update.effective_user else 0
		if not is_admin(user_id):
			if update.message:
				await update.message.reply_text("⛔ This command is for admins only.")
			return False
		return True

	async def forceon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		force = await get_force_config()
		force["enabled"] = True
		await set_force_config(force)
		await update.message.reply_text("✅ Force Join: <b>ON</b>", parse_mode=H)

	async def forceoff_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		force = await get_force_config()
		force["enabled"] = False
		await set_force_config(force)
		await update.message.reply_text("✅ Force Join: <b>OFF</b>", parse_mode=H)

	async def forcelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		force = await get_force_config()
		if not force.get("channels"):
			await update.message.reply_text("Empty list.")
			return
		lines = []
		for ch in force["channels"]:
			name = ch.get('title') or ch.get('username') or ch.get('chat_id')
			lines.append(f"• {html.escape(str(name))} (<code>{ch.get('chat_id')}</code>)")
		await update.message.reply_text("📋 <b>Force Channels:</b>\n" + "\n".join(lines), parse_mode=H)

	async def addforce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		if not context.args:
			await update.message.reply_text("Usage: <code>/addforce @channel</code>", parse_mode=H)
			return
		target = context.args[0]
		try:
			chat = await context.bot.get_chat(target)
			chat_id = chat.id
			username = getattr(chat, "username", None)
			title = getattr(chat, "title", None) or str(chat_id)
			invite_link = None
			if not username:
				try:
					link = await context.bot.create_chat_invite_link(chat_id)
					invite_link = link.invite_link
				except Exception:
					pass
			success = await add_force_channel(chat_id, username, title, invite_link)
			if success:
				await update.message.reply_text(f"[OK] Added: <b>{html.escape(title)}</b> (<code>{chat_id}</code>)",
												parse_mode=H)
			else:
				await update.message.reply_text("⚠️ Already in list.")
		except Exception as e:
			await update.message.reply_text(f"❌ Error: <code>{html.escape(str(e))}</code>", parse_mode=H)

	async def delforce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		if not context.args:
			await update.message.reply_text("Usage: <code>/delforce -1001234567890</code>", parse_mode=H)
			return
		try:
			chat_id = int(context.args[0])
		except Exception:
			await update.message.reply_text("Give numeric channel ID.")
			return
		success = await remove_force_channel(chat_id)
		await update.message.reply_text("🗑 Removed." if success else "ℹ️ Not found.")

	async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return

		# What to send: the message this command replies to (any kind, copied as it is), else the text after it
		source = update.message.reply_to_message
		text = " ".join(context.args or []).strip()
		if source is None and not text:
			await update.message.reply_text(
				"📢 <b>Broadcast Usage:</b>\n\n"
				"Reply to a message with <code>/broadcast</code> to send it to all users.\n"
				"Or use: <code>/broadcast Your message here</code>",
				parse_mode=H
			)
			return

		user_ids = await get_all_user_ids()
		total = len(user_ids)
		if total == 0:
			await update.message.reply_text("❌ No users found.")
			return
		status_msg = await update.message.reply_text(f"📤 Broadcasting to {total} users...\n⏳ Please wait...")

		async def send_one(user_id: int):
			if source is not None:
				await context.bot.copy_message(chat_id=user_id, from_chat_id=source.chat_id,
											   message_id=source.message_id)
			else:
				await context.bot.send_message(chat_id=user_id, text=text)   # as typed: no formatting to break

		success = failed = blocked = 0
		for user_id in user_ids:
			try:
				try:
					await send_one(user_id)
				except RetryAfter as e:                                       # too fast: wait as told, once
					await asyncio.sleep(float(getattr(e, "retry_after", 5)) + 1)
					await send_one(user_id)
				success += 1
			except Forbidden:
				blocked += 1
			except Exception as e:
				error_msg = str(e).lower()
				if "blocked" in error_msg or "deactivated" in error_msg:
					blocked += 1
				else:
					failed += 1
			await asyncio.sleep(BROADCAST_GAP)

		await status_msg.edit_text(
			f"✅ <b>Broadcast Complete</b>\n\n"
			f"👥 Total: {total}\n"
			f"✅ Success: {success}\n"
			f"🚫 Blocked: {blocked}\n"
			f"❌ Failed: {failed}",
			parse_mode=H)

	application.add_handler(CommandHandler("forceon", forceon_cmd))
	application.add_handler(CommandHandler("forceoff", forceoff_cmd))
	application.add_handler(CommandHandler("forcelist", forcelist_cmd))
	application.add_handler(CommandHandler("addforce", addforce_cmd))
	application.add_handler(CommandHandler("delforce", delforce_cmd))
	application.add_handler(CommandHandler("broadcast", broadcast_cmd))
