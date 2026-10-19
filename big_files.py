"""
Files over 20 MB. The Bot API (python-telegram-bot) can't download them (and can't upload over 50
MB), so they are renamed through MTProto: a Telethon client logged in as this same bot downloads the
file and sends it back with its new name, its caption and its original thumbnail — up to 2 GB.

Needs API_ID and API_HASH (my.telegram.org) in the .env; without them, available() is False and the
bot only puts the caption on big files (their name unchanged).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time

log = logging.getLogger(__name__)

SESSION = os.environ.get("MTPROTO_SESSION", "captionbot_mtproto")
_TRANSFERS = asyncio.Semaphore(int(os.environ.get("BIG_FILE_TRANSFERS", "2")))   # at once, all users
_client = None
_client_lock = asyncio.Lock()


def available() -> bool:
    if not (os.environ.get("API_ID", "").strip() and os.environ.get("API_HASH", "").strip()):
        return False
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False
    return True


async def client():
    """The Telethon client, started on first use (same bot token, its own session file)."""
    global _client
    async with _client_lock:
        if _client is None or not _client.is_connected():
            from telethon import TelegramClient  # noqa: PLC0415
            _client = TelegramClient(SESSION, int(os.environ["API_ID"]), os.environ["API_HASH"])
            await _client.start(bot_token=os.environ.get("BOT_TOKEN", ""))
        return _client


async def rename(chat_id: int, message_id: int, final_name: str, caption: str, progress=None) -> None:
    """Send the document of message ``message_id`` back to ``chat_id`` named ``final_name``.
    ``progress(text)`` is awaited now and then ("⬇️ 45%", "⬆️ 80%")."""
    from telethon.tl.types import DocumentAttributeFilename  # noqa: PLC0415
    async with _TRANSFERS:
        c = await client()
        msg = await c.get_messages(chat_id, ids=message_id)
        if msg is None or not getattr(msg, "document", None):
            raise RuntimeError("the original file is no longer available")
        work = tempfile.mkdtemp(prefix="acb_big_")
        try:
            last = [0.0]

            def report(arrow):
                async def cb(done, total):
                    if progress and total and time.monotonic() - last[0] > 8:
                        last[0] = time.monotonic()
                        try:
                            await progress(f"{arrow} {done * 100 // total}%")
                        except Exception:  # noqa: BLE001
                            pass
                return cb

            path = await c.download_media(msg, file=os.path.join(work, final_name), progress_callback=report("⬇️"))
            thumb = None
            if getattr(msg.document, "thumbs", None):
                try:
                    thumb = await c.download_media(msg, file=os.path.join(work, "thumb.jpg"), thumb=-1)
                except Exception:  # noqa: BLE001 — no thumbnail: Telegram makes one
                    thumb = None
            attributes = [a for a in msg.document.attributes if not isinstance(a, DocumentAttributeFilename)]
            attributes.append(DocumentAttributeFilename(final_name))
            await c.send_file(chat_id, path, caption=caption, parse_mode=None, force_document=True,
                              attributes=attributes, thumb=thumb, progress_callback=report("⬆️"))
        finally:
            shutil.rmtree(work, ignore_errors=True)
