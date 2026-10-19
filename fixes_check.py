"""Offline check of the 2026-10-19 round (python fixes_check.py), fake Telegram, throw-away database:
- force join: a channel the bot can't check no longer locks everyone out (the admins are alerted, once);
  /forcelist says which channels are really checked; « I have joined » opens the home screen;
- one caption chosen (Continue / Start Over) turns multi-caption off; the multi « Start » warning shows;
- the admin commands only for admins (home text, command menu);
- the update notice: once per version to every user, the admins told of every restart (force join, big files);
- /help: the guide in English and French; coloured buttons."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp())
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(errors="replace")
os.environ.update(SQLITE_PATH=str(WORK / "t.db"), BOT_TOKEN="1:x", ADMIN_IDS="42", API_ID="", API_HASH="")
os.chdir(WORK)                       # no .env of the real bot is read

from telegram.constants import ChatMemberStatus  # noqa: E402
from telegram.error import BadRequest  # noqa: E402

import config  # noqa: E402
import bot as acb  # noqa: E402

acb.ANNOUNCED_FILE = str(WORK / "data" / "announced_version.txt")
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


class Msg(SimpleNamespace):
    async def edit_text(self, text, **kw):
        self.owner.log.append(("edit", self.chat_id, text, kw.get("reply_markup")))

    async def reply_text(self, text, **kw):
        self.owner.log.append(("reply", self.chat_id, text, kw.get("reply_markup")))


class FakeBot:
    id = 999

    def __init__(self):
        self.log, self.members, self.not_admin, self.commands = [], set(), set(), []

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.not_admin:
            raise BadRequest("Member list is inaccessible")
        if user_id == self.id or (chat_id, user_id) in self.members:
            return SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR if user_id == self.id else ChatMemberStatus.MEMBER)
        return SimpleNamespace(status=ChatMemberStatus.LEFT)

    async def send_message(self, chat_id, text, **kw):
        self.log.append(("msg", chat_id, text, kw.get("reply_markup")))
        return Msg(owner=self, chat_id=chat_id)

    async def set_my_commands(self, commands, scope=None, **kw):
        self.commands.append(([c.command for c in commands], getattr(scope, "chat_id", None)))

    async def get_me(self):
        return SimpleNamespace(username="auttocaptionbot", id=self.id)


bot = FakeBot()
ctx = SimpleNamespace(bot=bot, args=[])


def command(uid, text):
    msg = Msg(owner=bot, chat_id=uid, text=text, reply_to_message=None)
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid), effective_message=msg, callback_query=None)


def callback(uid, data):
    answers = []

    async def answer(text=None, show_alert=False, **kw):
        answers.append((text, show_alert))
    cq = SimpleNamespace(data=data, from_user=SimpleNamespace(id=uid), answer=answer,
                         message=Msg(owner=bot, chat_id=uid))
    return SimpleNamespace(callback_query=cq, effective_user=cq.from_user, message=None), answers


def last(uid, kinds=("msg", "reply", "edit")):
    rows = [e for e in bot.log if e[1] == uid and e[0] in kinds]
    return rows[-1] if rows else (None, None, "", None)


def buttons(markup):
    return [b for row in (markup.inline_keyboard if markup else []) for b in row]


async def main():
    await config.init_db()
    for uid in (42, 50, 51, 52):
        await config.track_user(uid)

    # 1. force join
    await config.add_force_channel(-1001, "chanA", "Channel A", None)
    await config.add_force_channel(-1002, None, "Private B", "https://t.me/+bbb")
    await config.set_force_config({"enabled": True})
    bot.not_admin.add(-1002)
    await acb.start_cmd(command(50, "/start"), ctx)
    check("not a member: access restricted, Join buttons", "Access Restricted" in last(50)[2]
          and any(getattr(b, "url", None) == "https://t.me/chanA" for b in buttons(last(50)[3])))
    bot.members |= {(-1001, 51), (-1001, 52)}
    mark = len(bot.log)
    await acb.start_cmd(command(51, "/start"), ctx)
    await acb.start_cmd(command(52, "/start"), ctx)
    alerts = [e for e in bot.log if e[1] == 42 and "can't check" in e[2]]      # since the first check
    check("a channel the bot can't check: members of the others get in (ALL were locked out), admin alerted once",
          "Auto-Caption Bot" in last(51)[2] and "Auto-Caption Bot" in last(52)[2] and len(alerts) == 1,
          f"{last(51)[2][:40]} | {len(alerts)}")
    upd = command(42, "/forcelist")
    app = SimpleNamespace(handlers=[], add_handler=lambda h: app.handlers.append(h))
    acb.register_admin_handlers(app)
    forcelist = next(h.callback for h in app.handlers if "forcelist" in h.commands)
    await forcelist(upd, ctx)
    text = last(42)[2]
    check("/forcelist: which channels are really checked", "Channel A" in text and "✅ checked" in text
          and "Private B" in text and "NOT checked" in text, text)

    bot.members.add((-1001, 50))
    upd, answers = callback(50, "fs:refresh")
    await acb.fs_refresh_cb(upd, ctx)
    check("« I have joined »: access granted and the home screen with its buttons",
          "Access granted" in last(50)[2] and any(b.callback_data == "set:home" for b in buttons(last(50)[3])))

    # 2. the admin commands only for admins
    await acb.start_cmd(command(42, "/start"), ctx)
    check("home: the admin line for the admin only", "/forceon" in last(42)[2] and "/forceon" not in last(51)[2])

    # 3. multi-caption off when one caption is chosen; the multi « Start » warning
    _, _, a = await config.add_caption(51, "Show A", "1080p", "VF")
    _, _, b = await config.add_caption(51, "Show B", "1080p", "VOSTFR")
    await config.set_multi_ids(51, [a, b])
    await config.set_multi_enabled(51, True)
    upd, answers = callback(51, f"cap:use:{a}:cont")
    await acb.use_caption_cb(upd, ctx)
    st = await config.get_multi_state(51)
    check("Continue on one caption: multi-caption off (it kept going and won)", not st["enabled"]
          and await config.get_active_caption_id(51) == a)
    await config.set_multi_ids(51, [a])
    upd, answers = callback(51, "mc:start")
    await acb.mc_start_cb(upd, ctx)
    check("multi « Start » with 1 caption: the warning is the only answer (a 2nd one was refused, nothing showed)",
          answers == [("Choose between 2 and 10 captions.", True)], str(answers))

    # 4. the command menu
    fake_app = SimpleNamespace(bot=bot, create_task=lambda coro: tasks.append(asyncio.ensure_future(coro)))
    tasks = []
    await acb.post_init(fake_app)
    default = [c for c, scope in bot.commands if scope is None][-1]
    admin = [c for c, scope in bot.commands if scope == 42][-1]
    check("command menu: users without the admin commands, the admin with them",
          "help" in default and "forceon" not in default and "forceon" in admin, str(bot.commands))

    # 5. the update notice (started by post_init)
    await asyncio.gather(*tasks)
    news = [e for e in bot.log if e[0] == "msg" and "has been updated" in e[2]]
    note = [e for e in bot.log if e[0] == "msg" and e[1] == 42 and "restarted" in e[2]]
    check("a new version: every user told once, with what's new and the guide (EN + FR)",
          sorted(e[1] for e in news) == [42, 50, 51, 52] and acb.GUIDE_EN in news[0][2] and acb.GUIDE_FR in news[0][2],
          str([e[1] for e in news]))
    check("… the admin's restart note: force join per channel and big files",
          note and "Channel A: ✅ checked" in note[-1][2] and "Private B: ❌ NOT checked" in note[-1][2]
          and "Big files" in note[-1][2], note and note[-1][2])
    mark = len(bot.log)
    await acb.announce_update(bot)
    check("… restarted again, no new version: users told nothing, the admin still told",
          not [e for e in bot.log[mark:] if "has been updated" in e[2]]
          and any(e[1] == 42 and "No new version" in e[2] for e in bot.log[mark:]))

    # 6. "/n Name /v 1080p /l VF": a command for Telegram, it now has its handler
    app_real = acb.build_application()
    n_handlers = [h for g in app_real.handlers.values() for h in g
                  if type(h).__name__ == "CommandHandler" and "n" in h.commands]
    check("« /n Name /v … /l … » reaches the bot (Telegram sees a command: nothing handled it)",
          n_handlers and n_handlers[0].callback is acb.parse_text_for_caption)
    await acb.parse_text_for_caption(command(52, "/n Moon Garden /v 720p /l VOSTFR"), ctx)
    caps = await config.list_captions(52)
    check("… and makes the caption (720p written « HD »)", [(c["name"], c["version"], c["lang"]) for c in caps]
          == [("Moon Garden", "HD", "VOSTFR")], str(caps))

    # 7. /help and the colours
    await acb.help_cmd(command(51, "/help"), ctx)
    urls = [b.url for b in buttons(last(51)[3])]
    check("/help: the guide in English and French", urls == [acb.GUIDE_EN, acb.GUIDE_FR], str(urls))
    styles = {b.text: b.to_dict().get("style") for b in buttons(acb.kb_caption_actions(a, "Show A", 1))}
    check("coloured buttons: Continue green, Start Over blue, Delete red",
          styles.get("▶️ Continue") == "success" and styles.get("🔁 Start Over") == "primary"
          and styles.get("🗑 Delete") == "danger", str(styles))
    print("\nALL OK" if ok else "\nFAILED")


asyncio.run(main())
