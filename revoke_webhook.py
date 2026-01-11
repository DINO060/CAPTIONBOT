"""
Script to delete webhook and clear pending updates.
Run this if you have bot conflicts.
"""
import asyncio
import os
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")

async def revoke_webhook():
    bot = Bot(token=BOT_TOKEN)

    print("Deleting webhook...")
    result = await bot.delete_webhook(drop_pending_updates=True)

    if result:
        print("[OK] Webhook deleted successfully!")
        print("     All pending updates cleared.")
        print("\nYou can now start the bot with polling.")
    else:
        print("[ERROR] Failed to delete webhook")

    # Show current webhook info
    info = await bot.get_webhook_info()
    print(f"\nWebhook status:")
    print(f"  URL: {info.url or 'None (polling mode)'}")
    print(f"  Pending updates: {info.pending_update_count}")

if __name__ == "__main__":
    asyncio.run(revoke_webhook())
