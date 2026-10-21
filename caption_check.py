"""Offline check of the Auto-Caption bot (python caption_check.py), fake Telegram, throw-away database:
files sent back in order through each user's queue, one summary per group, the episode taken from the
file name, big files (over 20 MB) renamed through MTProto or captioned only, a failure that doesn't stop
the rest, users that don't wait for each other, captions with _ * < > that don't break messages,
/broadcast (reply mode, plain text, too-fast retry, blocked users), the database upgrade."""
import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp())
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(errors="replace")
# an older database (before the "episode from file name" setting) must be upgraded at start
with sqlite3.connect(WORK / "old.db") as c:
    c.execute("CREATE TABLE user_prefs (user_id INTEGER PRIMARY KEY, tag TEXT, position TEXT DEFAULT 'end')")
    c.execute("INSERT INTO user_prefs VALUES (5, '@old', 'end')")
os.environ.update(SQLITE_PATH=str(WORK / "old.db"), BOT_TOKEN="1:x", ADMIN_IDS="42", API_ID="", API_HASH="")
os.chdir(WORK)                       # no .env of the real bot is read

import config  # noqa: E402
import bot as acb  # noqa: E402
import big_files  # noqa: E402

REAL_RENAME = big_files.rename

acb.SUMMARY_WAIT = 1.5      # the real bot waits 3 s; SQLite on Windows takes ~0.2 s a file
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


class Sent(SimpleNamespace):
    async def edit_text(self, text, **kw):
        self.edits = getattr(self, "edits", []) + [text]

    async def delete(self):
        self.deleted = True


class FakeBot:
    def __init__(self):
        self.log = []

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        self.log.append(("copy", chat_id, message_id, caption))

    async def get_file(self, file_id):
        async def download_to_drive(custom_path=None):
            Path(custom_path).write_bytes(b"x")
        return SimpleNamespace(download_to_drive=download_to_drive)

    async def send_document(self, chat_id, document, caption=None, **kw):
        self.log.append(("doc", chat_id, document.filename, caption))

    async def send_message(self, chat_id, text, **kw):
        m = Sent(chat_id=chat_id, text=text, kw=kw)
        self.log.append(("msg", chat_id, text, kw.get("parse_mode")))
        self.markups = getattr(self, "markups", []) + [kw.get("reply_markup")]
        return m


bot = FakeBot()
ctx = SimpleNamespace(bot=bot, args=[])
replies = []


def message(uid, msg_id, name=None, size=1000, video=False):
    async def reply_text(text, **kw):
        replies.append((uid, text, kw.get("parse_mode")))
    doc = SimpleNamespace(file_name=name, file_size=size, file_id=f"F{msg_id}", file_unique_id=f"U{msg_id}") if name and not video else None
    vid = SimpleNamespace(file_name=name, file_size=size) if video else None
    return SimpleNamespace(chat_id=uid, message_id=msg_id, document=doc, video=vid, animation=None, photo=None,
                           text=None, caption=None, reply_text=reply_text, reply_to_message=None)


async def send(uid, msg):
    await acb.on_media(SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid), effective_message=msg), ctx)


async def settle(t=2.2):
    await asyncio.sleep(t)


def files_of(uid):
    return [e for e in bot.log if e[0] in ("copy", "doc", "big") and e[1] == uid]


def summaries(uid):
    return [e[2] for e in bot.log if e[0] == "msg" and e[1] == uid and "captions added" in e[2] or
            e[0] == "msg" and e[1] == uid and e[2].startswith("✅ Caption added")]


async def main():
    await config.init_db()

    # 0. the database upgrade
    prefs = await config.get_user_tag_prefs(5)
    check("older database: the new setting is added, ON, the old tag kept", prefs["tag"] == "@old" and prefs["ep_from_name"])

    # 1. episode numbers in file names
    cases = {"[Erai-raws] Ao no Hako - 03 [1080p].mkv": 3, "Blue.Box.S02E03.VOSTFR.1080p.mkv": 3,
             "One Piece EP1120 VF.mp4": 1120, "Mob Psycho 100 - 12.mkv": 12, "Movie 2024 1080p.mkv": None,
             "86 Eighty Six.mkv": None, "Show_E07_x264.mkv": 7, "Naruto Episode 220.mp4": 220}
    got = {n: config.episode_in_name(n) for n in cases}
    check("episode read from file names (not years, resolutions or title numbers)", got == cases,
          str({n: g for n, g in got.items() if g != cases[n]}))

    # 2. a caption with characters that used to break the messages
    upd = SimpleNamespace(message=SimpleNamespace(text="/settemplate One_Piece *Special* <Arc> — Episode 1 — 1080p — VF",
                                                  reply_text=lambda *a, **k: _rec(7, *a, **k)),
                          effective_user=SimpleNamespace(id=7), effective_message=None)
    upd.effective_message = upd.message
    await acb.settemplate_cmd(upd, ctx)
    text, mode = replies[-1][1], replies[-1][2]
    check("/settemplate with _ * < >: HTML, escaped", mode == "HTML" and "One_Piece *Special* &lt;Arc&gt;" in text, text)
    upd.message.text = "/status"
    await acb.status_cmd(upd, ctx)
    check("/status with that name: escaped too", "&lt;Arc&gt;" in replies[-1][1] and replies[-1][2] == "HTML")

    # 3. a group: a video (copied), a small file (renamed), a big file (no MTProto here: caption only)
    await send(7, message(7, 10, "clip.mp4", video=True))
    await send(7, message(7, 11, "Small file.mkv", size=5 * 1024 * 1024))
    await send(7, message(7, 12, "Big file.mkv", size=900 * 1024 * 1024))
    await settle()
    f = files_of(7)
    check("3 files back in order: video copied, small renamed, big captioned",
          [e[0] for e in f] == ["copy", "doc", "copy"] and f[1][2] == "Small file.mkv", str(f))
    check("… episodes 1, 2, 3 in the captions", [e[3].split(" Episode ")[1].split()[0] for e in f] == ["1", "2", "3"],
          str([e[3] for e in f]))
    s = summaries(7)
    check("… one summary for the group: episodes 1 → 3, next 4, the big file's name kept",
          len(s) == 1 and "3 captions added (episodes 1 → 3)" in s[0] and "Next episode" in s[0] and ": 4" in s[0]
          and "name kept" in s[0], str(s))

    # 4. the episode from the file name; an older one doesn't move the counter back; the setting off
    bot.log.clear()
    await send(7, message(7, 20, "One_Piece - 07 [1080p].mkv"))
    await send(7, message(7, 21, "no number here.mkv"))
    await send(7, message(7, 22, "One_Piece - 03.mkv"))
    await settle()
    eps = [e[3].split(" Episode ")[1].split()[0] for e in files_of(7)]
    cap = await config.get_caption(7, await config.get_active_caption_id(7))
    check("file name 07 → episode 7; then the counter goes on (8); an old one (03) keeps the counter",
          eps == ["7", "8", "3"] and cap["next_ep"] == 9, f"{eps} next={cap['next_ep']}")
    s, markup = summaries(7)[-1], bot.markups[-1]
    check("… the summary says 2 numbers came from the file names, with « Always use my counter »",
          "2 episode numbers were read from the file names" in s and markup is not None
          and markup.inline_keyboard[0][0].callback_data == "set:epn0", s)

    # 4b. the reported case: counter at 12, a file named "…-vf-ep01" → Episode 1, and the summary says why
    cid7 = await config.get_active_caption_id(7)
    await config.set_caption_fields(7, cid7, next_ep=12)
    bot.log.clear()
    await send(7, message(7, 30, "one-piece-saison1-vf-ep01.mp4", video=True))
    await settle()
    s = summaries(7)[-1]
    check("counter 12, file « …-ep01 »: the summary explains Episode 1 (counter was at 12), next stays 12",
          "Episode 1 was read from the file name (your counter was at 12)" in s and ": 12" in s, s)
    bot.log.clear()
    await send(7, message(7, 31, "clip without number.mp4", video=True))
    await settle()
    check("… a file without a number: no such line, no button",
          "read from the file" not in summaries(7)[-1] and bot.markups[-1] is None, summaries(7)[-1])
    answers = []
    cq = SimpleNamespace(from_user=SimpleNamespace(id=7), message=Sent(),
                         answer=lambda *a, **k: _rec_answer(answers, *a, **k))
    cq.message.edit_reply_markup = lambda **k: _rec_answer(answers, "markup", **k)
    await acb.settings_counter_only_cb(SimpleNamespace(callback_query=cq), ctx)
    check("« Always use my counter »: the setting goes off, told, the button removed",
          not (await config.get_user_tag_prefs(7))["ep_from_name"] and len(answers) == 2, str(answers))
    await config.set_caption_fields(7, cid7, next_ep=9)
    await config.set_ep_from_name(7, False)
    bot.log.clear()
    await send(7, message(7, 23, "One_Piece - 20.mkv"))
    await settle()
    check("setting off: the counter only", files_of(7)[0][3].split(" Episode ")[1].split()[0] == "9")
    await config.set_ep_from_name(7, True)

    # 5. big files through MTProto, in order, with progress; a slow one doesn't hold another user
    calls = []

    async def fake_rename(chat_id, message_id, final_name, caption, progress=None):
        if progress:
            await progress("⬇️ 50%")
        await asyncio.sleep(0.5)
        calls.append((chat_id, message_id, final_name))
        bot.log.append(("big", chat_id, final_name, caption))
    big_files.available, big_files.rename = (lambda: True), fake_rename
    await config.set_active_caption_id(8, (await config.add_caption(8, "Other", "", ""))[2])
    bot.log.clear()
    await send(7, message(7, 30, "Huge.mkv", size=1500 * 1024 * 1024))
    await send(7, message(7, 31, "after.mkv", size=1000))
    await asyncio.sleep(0.1)
    await send(8, message(8, 40, "someone else.mkv", size=1000))
    await asyncio.sleep(0.2)
    check("another user's file isn't held by a big one", any(e[1] == 8 for e in files_of(8)) and not calls)
    await settle(2.5)
    order = [e[0] for e in files_of(7)]
    check("big file renamed through MTProto, then the next one (order kept)", order == ["big", "doc"]
          and calls == [(7, 30, "Huge.mkv")], str(order))
    status = [e for e in bot.log if e[0] == "msg" and e[1] == 7 and "Big file" in e[2]]
    check("… a « ⏳ Big file » message while it runs", bool(status))

    # 6. a failure doesn't stop the rest
    async def broken(*a, **k):
        raise RuntimeError("network down")
    big_files.rename = broken
    bot.log.clear()
    await send(7, message(7, 50, "Huge2.mkv", size=1500 * 1024 * 1024))
    await send(7, message(7, 51, "next.mkv", size=1000))
    await settle()
    errors = [e for e in bot.log if e[0] == "msg" and e[1] == 7 and e[2].startswith("❌ Episode")]
    check("a failed file: « ❌ Episode N », the next one still goes", errors and "network down" in errors[0][2]
          and [e[0] for e in files_of(7)] == ["doc"])

    # 7. /broadcast: reply mode without text, plain text, too fast, blocked
    from telegram.error import Forbidden, RetryAfter  # noqa: PLC0415
    import admin  # noqa: PLC0415,F401
    for uid in (101, 102, 103):
        await config.track_user(uid)
    sent, tries = [], {}

    class BBot(FakeBot):
        async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
            tries[chat_id] = tries.get(chat_id, 0) + 1
            if chat_id == 102 and tries[chat_id] == 1:
                raise RetryAfter(0)
            if chat_id == 103:
                raise Forbidden("bot was blocked by the user")
            sent.append(("copy", chat_id))

        async def send_message(self, chat_id, text, **kw):
            sent.append(("text", chat_id, text, kw.get("parse_mode")))
            return Sent(text=text)
    handlers = {}

    class App:
        def add_handler(self, h):
            handlers[list(h.commands)[0]] = h.callback
    admin.register_admin_handlers(App())
    report = []

    async def reply_text(text, **kw):
        report.append(text)
        return Sent(text=text, edit_text=None)
    status_box = Sent()

    async def admin_reply(text, **kw):
        report.append(text)
        return status_box
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=SimpleNamespace(
        reply_to_message=SimpleNamespace(chat_id=42, message_id=999), reply_text=admin_reply))
    await handlers["broadcast"](upd, SimpleNamespace(bot=BBot(), args=[]))
    final = status_box.edits[-1] if getattr(status_box, "edits", None) else ""
    check("/broadcast replying to a message, no text: sent to everyone", ("copy", 101) in sent and ("copy", 102) in sent
          and "Success:" in final, str((sent, final)))
    check("… « too fast » retried once, blocked counted", tries.get(102) == 2 and "Blocked: 1" in final, final)
    sent.clear()
    upd.message.reply_to_message = None
    await handlers["broadcast"](upd, SimpleNamespace(bot=BBot(), args=["Hello", "*world_"]))
    texts = [s for s in sent if s[0] == "text"]
    check("/broadcast text: sent as typed (no formatting that could fail)", texts and texts[0][2] == "Hello *world_"
          and texts[0][3] is None, str(texts[:1]))

    # 8. the MTProto rename itself (a fake Telethon client): the new name, the other attributes and the
    #    original thumbnail kept, progress reported, the temporary files removed
    from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo  # noqa: PLC0415

    class TClient:
        sent = None

        async def get_messages(self, chat, ids=None):
            return SimpleNamespace(document=SimpleNamespace(thumbs=[1], attributes=[
                DocumentAttributeFilename("old.mkv"), DocumentAttributeVideo(duration=1440, w=1920, h=1080)]))

        async def download_media(self, msg, file=None, progress_callback=None, thumb=None):
            Path(file).write_bytes(b"x")
            if progress_callback:
                await progress_callback(50, 100)
            return file

        async def send_file(self, chat, path, **kw):
            self.sent = (chat, Path(path).name, kw, Path(path).parent)
    tc = TClient()

    async def fake_client():
        return tc
    big_files.client = fake_client
    texts = []

    async def prog(t):
        texts.append(t)
    await REAL_RENAME(7, 60, "New Name @me.mkv", "Show Episode 4", prog)
    chat, name, kw, folder = tc.sent
    names = [a.file_name for a in kw["attributes"] if isinstance(a, DocumentAttributeFilename)]
    check("MTProto rename: new name, video length kept, original thumbnail, as a file, caption, progress",
          name == "New Name @me.mkv" and names == ["New Name @me.mkv"]
          and any(isinstance(a, DocumentAttributeVideo) for a in kw["attributes"])
          and str(kw.get("thumb", "")).endswith("thumb.jpg") and kw["force_document"]
          and kw["caption"] == "Show Episode 4" and texts and texts[0].startswith("⬇️"),
          str((name, names, kw.get("thumb"), texts)))
    check("… temporary files removed", not folder.exists())

    print("\nALL OK" if ok else "\nFAILED")


async def _rec(uid, text, **kw):
    replies.append((uid, text, kw.get("parse_mode")))


async def _rec_answer(into, *args, **kw):
    into.append((args, kw))


asyncio.run(main())
