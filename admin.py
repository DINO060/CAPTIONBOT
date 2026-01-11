from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
	get_force_config,
	set_force_config,
	add_force_channel,
	remove_force_channel,
	is_admin,
	get_all_user_ids,
)


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
		await update.message.reply_text(
			f"✅ Force Join: **ON**",
			parse_mode=ParseMode.MARKDOWN,
		)

	async def forceoff_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		force = await get_force_config()
		force["enabled"] = False
		await set_force_config(force)
		await update.message.reply_text(
			f"✅ Force Join: **OFF**",
			parse_mode=ParseMode.MARKDOWN,
		)

	async def forcelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		force = await get_force_config()
		if not force.get("channels"):
			await update.message.reply_text("Empty list.")
			return
		lines = []
		for ch in force["channels"]:
			lines.append(
				f"• {ch.get('title') or ch.get('username') or ch.get('chat_id')} (`{ch.get('chat_id')}`)"
			)
		await update.message.reply_text(
			"📋 *Force Channels:*\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN
		)

	async def addforce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		if not context.args:
			await update.message.reply_text("Usage: `/addforce @channel`", parse_mode=ParseMode.MARKDOWN)
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
				await update.message.reply_text(
					f"[OK] Added: **{title}** (`{chat_id}`)", parse_mode=ParseMode.MARKDOWN
				)
			else:
				await update.message.reply_text("⚠️ Already in list.")
		except Exception as e:
			await update.message.reply_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)

	async def delforce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
		if not await admin_only(update):
			return
		if not context.args:
			await update.message.reply_text("Usage: `/delforce -1001234567890`", parse_mode=ParseMode.MARKDOWN)
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

		# Get broadcast message
		if not context.args:
			await update.message.reply_text(
				"📢 *Broadcast Usage:*\n\n"
				"Reply to a message with `/broadcast` to forward it to all users.\n"
				"Or use: `/broadcast Your message here`",
				parse_mode=ParseMode.MARKDOWN
			)
			return

		# Get message to broadcast
		broadcast_msg = None
		if update.message.reply_to_message:
			# Forward the replied message
			broadcast_msg = update.message.reply_to_message
			is_forward = True
		else:
			# Use the text after /broadcast
			text = " ".join(context.args)
			is_forward = False

		# Get all user IDs
		user_ids = await get_all_user_ids()
		total = len(user_ids)

		if total == 0:
			await update.message.reply_text("❌ No users found.")
			return

		# Confirm before sending
		status_msg = await update.message.reply_text(
			f"📤 Broadcasting to {total} users...\n⏳ Please wait..."
		)

		# Send to all users
		success = 0
		failed = 0
		blocked = 0

		for user_id in user_ids:
			try:
				if is_forward:
					# Copy the message
					await context.bot.copy_message(
						chat_id=user_id,
						from_chat_id=broadcast_msg.chat_id,
						message_id=broadcast_msg.message_id
					)
				else:
					# Send text message
					await context.bot.send_message(
						chat_id=user_id,
						text=text,
						parse_mode=ParseMode.MARKDOWN
					)
				success += 1
			except Exception as e:
				error_msg = str(e).lower()
				if "blocked" in error_msg or "user is deactivated" in error_msg:
					blocked += 1
				else:
					failed += 1

		# Final report
		report = (
			f"✅ *Broadcast Complete*\n\n"
			f"👥 Total: {total}\n"
			f"✅ Success: {success}\n"
			f"🚫 Blocked: {blocked}\n"
			f"❌ Failed: {failed}"
		)
		await status_msg.edit_text(report, parse_mode=ParseMode.MARKDOWN)

	application.add_handler(CommandHandler("forceon", forceon_cmd))
	application.add_handler(CommandHandler("forceoff", forceoff_cmd))
	application.add_handler(CommandHandler("forcelist", forcelist_cmd))
	application.add_handler(CommandHandler("addforce", addforce_cmd))
	application.add_handler(CommandHandler("delforce", delforce_cmd))
	application.add_handler(CommandHandler("broadcast", broadcast_cmd))


