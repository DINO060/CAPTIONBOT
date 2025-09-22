from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
	get_force_config,
	set_force_config,
	add_force_channel,
	remove_force_channel,
	is_admin,
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
				f"• {ch.get('title') or ch.get('username') or ch.get('chat_id')} (\`{ch.get('chat_id')}\`)"
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
					f"✅ Added: **{title}** (\`{chat_id}\`)", parse_mode=ParseMode.MARKDOWN
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

	application.add_handler(CommandHandler("forceon", forceon_cmd))
	application.add_handler(CommandHandler("forceoff", forceoff_cmd))
	application.add_handler(CommandHandler("forcelist", forcelist_cmd))
	application.add_handler(CommandHandler("addforce", addforce_cmd))
	application.add_handler(CommandHandler("delforce", delforce_cmd))


