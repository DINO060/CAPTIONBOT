import os, re, json, time
import aiosqlite
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatMemberStatus
from dotenv import load_dotenv

# Auto-load variables from a .env file if present
load_dotenv()

# -----------------------------
# ENV / CONSTANTS
# -----------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DB_PATH = os.environ.get("SQLITE_PATH", "autocaption.db")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")  # "123,456"
HELP_URL = os.environ.get("HELP_URL", "")  # Optional Telegraph/Docs URL

DEFAULT_TEMPLATE = "{series} Episode {ep}  {version}  {lang}"
START_TIME = time.time()

# -----------------------------
# Global connection & cache
# -----------------------------
_db: aiosqlite.Connection | None = None

# Force-join cache: {user_id: (is_joined: bool, timestamp: float)}
# Cache expires after 5 minutes
_force_join_cache: dict[int, tuple[bool, float]] = {}
FORCE_JOIN_CACHE_TTL = 300  # 5 minutes in seconds

async def init_db():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row

    # Tables
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            template    TEXT DEFAULT '{template}',
            joined_date TEXT,
            last_activity TEXT
        );

        CREATE TABLE IF NOT EXISTS state (
            user_id           INTEGER PRIMARY KEY,
            active_caption_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS captions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            name         TEXT NOT NULL,
            name_norm    TEXT NOT NULL,
            version      TEXT,
            version_norm TEXT NOT NULL,
            lang         TEXT,
            lang_norm    TEXT NOT NULL,
            next_ep      INTEGER NOT NULL DEFAULT 1,
            zero_pad     INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, name_norm, version_norm, lang_norm)
        );

        -- settings(key,value) for flags and counters
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        -- force channels
        CREATE TABLE IF NOT EXISTS force_channels (
            chat_id     INTEGER PRIMARY KEY,
            username    TEXT,
            title       TEXT,
            invite_link TEXT
        );

        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id    INTEGER PRIMARY KEY,
            tag        TEXT,
            position   TEXT DEFAULT 'end'
        );

        -- Multi-caption state (selection & pointer)
        CREATE TABLE IF NOT EXISTS user_multi (
            user_id   INTEGER PRIMARY KEY,
            enabled   INTEGER NOT NULL DEFAULT 0,
            ids_json  TEXT NOT NULL DEFAULT '[]',
            pointer   INTEGER NOT NULL DEFAULT 0
        );
        """.replace("{template}", DEFAULT_TEMPLATE.replace("'", "''"))
    )

    # Default values
    await _set_setting_default("force_enabled", "0")  # 0=OFF, 1=ON
    await _set_setting_default("stats_files", "0")
    await _set_setting_default("stats_storage_bytes", "0")
    await _db.commit()

async def _set_setting_default(key: str, default_val: str):
    cur = await _db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    if not row:
        await _db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (key, default_val))

# -----------------------------
# Admin / Force-join
# -----------------------------
def get_admin_ids() -> set[int]:
    if not ADMIN_IDS:
        return set()
    try:
        return set(int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip())
    except:
        return set()

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

async def get_force_config() -> dict:
    enabled = await _get_setting_int("force_enabled", 0)
    cur = await _db.execute("SELECT chat_id, username, title, invite_link FROM force_channels")
    channels = [dict(row) for row in await cur.fetchall()]
    return {"enabled": bool(enabled), "channels": channels}

async def set_force_config(force: dict):
    # Toggle ON/OFF only here
    await _set_setting("force_enabled", "1" if force.get("enabled") else "0")
    # The channel list is maintained by add/remove
    await _db.commit()

async def add_force_channel(chat_id: int, username: str = None, title: str = None, invite_link: str = None):
    try:
        await _db.execute(
            "INSERT OR IGNORE INTO force_channels(chat_id, username, title, invite_link) VALUES(?,?,?,?)",
            (chat_id, username, title or str(chat_id), invite_link)
        )
        await _db.commit()
        # True if newly added (INSERT OR IGNORE cannot easily distinguish)
        cur = await _db.execute("SELECT changes() AS ch")
        ch = (await cur.fetchone())["ch"]
        return ch > 0
    except:
        return False

async def remove_force_channel(chat_id: int):
    await _db.execute("DELETE FROM force_channels WHERE chat_id = ?", (chat_id,))
    await _db.commit()
    cur = await _db.execute("SELECT changes() AS ch")
    ch = (await cur.fetchone())["ch"]
    return ch > 0

async def check_user_joined(bot, user_id: int, use_cache: bool = True) -> Tuple[bool, list]:
    """
    Check if user has joined all required channels.

    Args:
        bot: Telegram bot instance
        user_id: User ID to check
        use_cache: If True, use cached result if available and not expired

    Returns:
        Tuple of (is_joined: bool, missing_channels: list)
    """
    global _force_join_cache

    force = await get_force_config()
    if not force.get("enabled"):
        return True, []
    if is_admin(user_id):
        return True, []

    # Check cache first
    if use_cache and user_id in _force_join_cache:
        is_joined, timestamp = _force_join_cache[user_id]
        if time.time() - timestamp < FORCE_JOIN_CACHE_TTL:
            # Cache is still valid
            if is_joined:
                return True, []
            # If cached as not joined, we still recheck (user might have joined)

    # Perform actual check
    missing = []
    for ch in force.get("channels", []):
        cid = ch.get("chat_id")
        if not cid:
            continue
        try:
            member = await bot.get_chat_member(cid, user_id)
            if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER):
                missing.append(ch)
        except Exception:
            missing.append(ch)

    # Update cache
    is_joined = len(missing) == 0
    _force_join_cache[user_id] = (is_joined, time.time())

    return is_joined, missing

def clear_force_join_cache(user_id: Optional[int] = None):
    """Clear force-join cache for a specific user or all users"""
    global _force_join_cache
    if user_id is not None:
        _force_join_cache.pop(user_id, None)
    else:
        _force_join_cache.clear()

def build_join_buttons(force_cfg: dict) -> InlineKeyboardMarkup:
    btns = []
    for ch in force_cfg.get("channels", []):
        label = ch.get("title") or (f"@{ch['username']}" if ch.get("username") else str(ch.get("chat_id")))
        url = None
        if ch.get("username"):
            url = f"https://t.me/{ch['username']}"
        elif ch.get("invite_link"):
            url = ch["invite_link"]
        if url:
            btns.append([InlineKeyboardButton(f"➕ Join • {label}", url=url)])
    btns.append([InlineKeyboardButton("🔄 I have joined", callback_data="fs:refresh")])
    return InlineKeyboardMarkup(btns)

# -----------------------------
# Stats
# -----------------------------
async def update_stats(files_delta: int = 0, bytes_delta: int = 0):
    files = await _get_setting_int("stats_files", 0) + int(files_delta)
    bytes_ = await _get_setting_int("stats_storage_bytes", 0) + int(bytes_delta)
    await _set_setting("stats_files", str(max(0, files)))
    await _set_setting("stats_storage_bytes", str(max(0, bytes_)))
    await _db.commit()

async def get_stats() -> dict:
    files = await _get_setting_int("stats_files", 0)
    bytes_ = await _get_setting_int("stats_storage_bytes", 0)
    return {"files": files, "storage_bytes": bytes_}

async def track_user(user_id: int):
    # upsert
    now = datetime.now().isoformat(timespec="seconds")
    cur = await _db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if not row:
        await _db.execute(
            "INSERT INTO users(user_id, template, joined_date, last_activity) VALUES(?,?,?,?)",
            (user_id, DEFAULT_TEMPLATE, now, now)
        )
    else:
        await _db.execute(
            "UPDATE users SET last_activity = ? WHERE user_id = ?",
            (now, user_id)
        )
    await _db.commit()

async def get_total_users() -> int:
    cur = await _db.execute("SELECT COUNT(*) AS c FROM users")
    return (await cur.fetchone())["c"]

async def get_user_stats() -> dict:
    """Get detailed user activity statistics"""
    from datetime import datetime, timedelta

    now = datetime.now()
    one_hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    one_day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    seven_days_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")

    # Total users
    cur = await _db.execute("SELECT COUNT(*) AS c FROM users")
    total = (await cur.fetchone())["c"]

    # Active in last hour
    cur = await _db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE last_activity >= ?",
        (one_hour_ago,)
    )
    active_1h = (await cur.fetchone())["c"]

    # Active in last 24 hours
    cur = await _db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE last_activity >= ?",
        (one_day_ago,)
    )
    active_24h = (await cur.fetchone())["c"]

    # Active in last 7 days
    cur = await _db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE last_activity >= ?",
        (seven_days_ago,)
    )
    active_7d = (await cur.fetchone())["c"]

    # Inactive (7+ days)
    inactive = total - active_7d

    return {
        "total": total,
        "active_1h": active_1h,
        "active_24h": active_24h,
        "active_7d": active_7d,
        "inactive_7d": inactive
    }

async def get_all_user_ids() -> List[int]:
    """Get all user IDs for broadcast"""
    cur = await _db.execute("SELECT user_id FROM users")
    rows = await cur.fetchall()
    return [row["user_id"] for row in rows]

# -----------------------------
# Utils
# -----------------------------
def norm(s: Optional[str]) -> str:
    if s is None: return ""
    s = s.strip()
    return s.lower() if s else ""

def format_bytes(n: int) -> str:
    units = ["B","KB","MB","GB","TB","PB"]
    n = float(n)
    for u in units:
        if n < 1024: return f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} EB"

def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    h, r = divmod(seconds, 3600); m, s = divmod(r, 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"

TOKEN_RE = re.compile(r"(?i)(?:^|\s)/(n|v|l)\s+([^/]+?)(?=$|\s/)", re.S)
SETTEMPLATE_SPLIT = re.compile(r"\s+—\s+| +- +| *— *|\s{2,}")
# Accept "Episode 12" as well as short forms like "EP12" or "E12"
EP_EXTRACT = re.compile(r"(?i)(?:episode|ep|e)\s*([0-9]+)")

def parse_tokens(text: str) -> dict:
    out = {}
    for key, val in TOKEN_RE.findall(text or ""):
        key = key.lower(); val = val.strip()
        if key == "n": out["name"] = val
        elif key == "v": out["version"] = normalize_version(val)
        elif key == "l": out["lang"] = val
    return out

def parse_settemplate_values(text: str):
    """
    Expects a string like:
      "<series> — Episode <ep> — <version> — <lang>"
    Returns (series, ep:int, zero_pad:int, version, lang) or None if not conforming.
    """
    if not text:
        return None
    # Remove the command itself
    parts = text.split(None, 1)
    if len(parts) < 2:
        return None
    args = parts[1].strip()

    # 1) Attempt: strict split by '—', '-' or double spaces
    segs = SETTEMPLATE_SPLIT.split(args)
    if len(segs) == 4:
        series = segs[0].strip()
        ep_raw = segs[1].strip()
        m = EP_EXTRACT.search(ep_raw)
        if not m:
            return None
        ep_str = m.group(1)
        zero_pad = len(ep_str) if ep_str.startswith("0") else 0
        try:
            ep = int(ep_str)
        except ValueError:
            return None
        version = segs[2].strip()
        lang = segs[3].strip()
        return series, ep, zero_pad, version, lang

    # 2) Variant: space separators (supports "Episode", "EP", or "E")
    m2 = re.match(r"^(?P<series>.+?)\s*(?:—|-)?\s*(?:Episode|EP|E)\s*(?P<ep>\d+)\s*(?:—|-)?\s*(?P<version>\S+)\s*(?:—|-)?\s*(?P<lang>\S+)\s*$", args, re.IGNORECASE)
    if not m2:
        return None
    series = m2.group("series").strip()
    ep_str = m2.group("ep").strip()
    zero_pad = len(ep_str) if ep_str.startswith("0") else 0
    try:
        ep = int(ep_str)
    except ValueError:
        return None
    version = m2.group("version").strip()
    lang = m2.group("lang").strip()
    return series, ep, zero_pad, version, lang

def build_caption(template: str, series: str, ep: int, zero_pad: int, version: str, lang: str) -> str:
    ep_str = str(ep).zfill(zero_pad or 0)
    cap = (template
           .replace("{series}", (series or "").strip())
           .replace("{ep}", ep_str)
           .replace("{version}", (version or "").strip())
           .replace("{lang}", (lang or "").strip()))
    return re.sub(r"\s+", " ", cap).strip()

# -----------------------------
# Normalization helpers (version)
# -----------------------------
def normalize_version(raw: Optional[str]) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    # capture optional trailing number (e.g., "full hd 1")
    m_idx = re.match(r"^(.*?)(?:\s+(\d+))?$", s, re.IGNORECASE)
    base = (m_idx.group(1) or "").strip().lower()
    idx = m_idx.group(2)

    def with_idx(v: str) -> str:
        return f"{v} {idx}" if idx else v

    # Friendly labels
    if any(k in base for k in ("ultra hd", "ultrahd", "uhd", "4k")):
        return with_idx("Ultra HD")
    if any(k in base for k in ("full hd", "fullhd", "fhd")):
        return with_idx("Full HD")
    if re.fullmatch(r"8k|4320p?", base):
        return with_idx("8K")
    if re.fullmatch(r"720p?|hd", base):
        return with_idx("HD")
    if re.fullmatch(r"480p?|sd", base):
        return with_idx("SD")

    # Numeric forms like 1080p, 1440p, 2160p
    m_res = re.match(r"^(\d{3,4})p$", base)
    if m_res:
        try:
            n = int(m_res.group(1))
        except Exception:
            n = None
        if n is not None:
            if n >= 4300:
                return with_idx("8K")
            if n >= 2160:
                return with_idx("Ultra HD")
            if n == 1080:
                return with_idx("Full HD")
            if n == 720:
                return with_idx("HD")
            if n == 480:
                return with_idx("SD")
        return with_idx(f"{m_res.group(1)}p")

    # plain numbers and aliases
    if re.fullmatch(r"4320", base):
        return with_idx("8K")
    if re.fullmatch(r"2160|4k", base):
        return with_idx("Ultra HD")
    if re.fullmatch(r"1080", base):
        return with_idx("Full HD")
    if re.fullmatch(r"720", base):
        return with_idx("HD")
    if re.fullmatch(r"480", base):
        return with_idx("SD")

    # standalone numbers like 1080 → assume {num}p
    m_num = re.match(r"^(\d{3,4})(?:\s*p?)$", base)
    if m_num:
        n = int(m_num.group(1))
        if n >= 4300:
            return with_idx("8K")
        if n >= 2160:
            return with_idx("Ultra HD")
        if n == 1080:
            return with_idx("Full HD")
        if n == 720:
            return with_idx("HD")
        if n == 480:
            return with_idx("SD")
        return with_idx(f"{n}p")

    # default: clean repeated spaces and return original (plus optional idx)
    base_clean = re.sub(r"\s+", " ", (raw or "").strip())
    return base_clean

# -----------------------------
# User data / captions
# -----------------------------
async def get_user(user_id: int) -> dict:
    cur = await _db.execute("SELECT user_id, template FROM users WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if not row:
        await track_user(user_id)
        return {"user_id": user_id, "template": DEFAULT_TEMPLATE}
    return {"user_id": row["user_id"], "template": row["template"] or DEFAULT_TEMPLATE}

async def set_user(user_id: int, **updates):
    u = await get_user(user_id)
    # Merge
    template = updates.get("template", u["template"])
    await _db.execute("INSERT INTO users(user_id, template, joined_date) VALUES(?,?,?) "
                      "ON CONFLICT(user_id) DO UPDATE SET template=excluded.template",
                      (user_id, template, datetime.now().isoformat(timespec="seconds")))
    await _db.commit()

async def get_active_caption_id(user_id: int) -> Optional[int]:
    cur = await _db.execute("SELECT active_caption_id FROM state WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    return row["active_caption_id"] if row else None

async def set_active_caption_id(user_id: int, caption_id: Optional[int]):
    await _db.execute("INSERT INTO state(user_id, active_caption_id) VALUES(?,?) "
                      "ON CONFLICT(user_id) DO UPDATE SET active_caption_id=excluded.active_caption_id",
                      (user_id, caption_id))
    await _db.commit()

async def add_caption(user_id: int, name: str, version: Optional[str], lang: Optional[str]) -> Tuple[bool, str, Optional[int]]:
    name = (name or "").strip()
    version = normalize_version(version)
    lang = (lang or "").strip()
    if not name:
        return False, "❌ Name is required (/n).", None
    try:
        await _db.execute(
            "INSERT INTO captions(user_id, name, name_norm, version, version_norm, lang, lang_norm, next_ep, zero_pad) "
            "VALUES(?,?,?,?,?,?,?,1,0)",
            (user_id, name, norm(name), (version or None), norm(version), (lang or None), norm(lang))
        )
        await _db.commit()
        cur = await _db.execute("SELECT last_insert_rowid() AS lid")
        lid = (await cur.fetchone())["lid"]
        return True, f"✅ Caption saved: **{name}** — {version or '—'} — {lang or '—'}", int(lid)
    except aiosqlite.IntegrityError:
        # If it already exists, fetch and return its id
        cur = await _db.execute(
            "SELECT id FROM captions WHERE user_id=? AND name_norm=? AND version_norm=? AND lang_norm=?",
            (user_id, norm(name), norm(version), norm(lang))
        )
        existing = await cur.fetchone()
        if existing:
            return False, "⚠️ This caption already exists.", existing["id"]
        return False, "⚠️ This caption already exists.", None

async def list_captions(user_id: int) -> List[dict]:
    cur = await _db.execute(
        "SELECT id AS _id, user_id, name, version, lang, next_ep, zero_pad FROM captions WHERE user_id = ? ORDER BY name_norm ASC",
        (user_id,)
    )
    rows = await cur.fetchall()
    return [dict(row) for row in rows]

async def get_caption(user_id: int, caption_id: int) -> Optional[dict]:
    cur = await _db.execute(
        "SELECT id AS _id, user_id, name, version, lang, next_ep, zero_pad FROM captions WHERE id = ? AND user_id = ?",
        (caption_id, user_id)
    )
    row = await cur.fetchone()
    return dict(row) if row else None

async def set_caption_fields(user_id: int, caption_id: int, **fields):
    # Prepare a dynamic update
    allowed = {"name","version","lang","next_ep","zero_pad"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return
    vals.extend([caption_id, user_id])
    await _db.execute(f"UPDATE captions SET {', '.join(sets)} WHERE id = ? AND user_id = ?", vals)
    await _db.commit()

async def delete_caption(user_id: int, caption_id: int) -> bool:
    await _db.execute("DELETE FROM captions WHERE id = ? AND user_id = ?", (caption_id, user_id))
    await _db.commit()
    cur = await _db.execute("SELECT changes() AS ch")
    ch = (await cur.fetchone())["ch"]
    return ch > 0

# -----------------------------
# Settings helpers
# -----------------------------
async def _get_setting_int(key: str, default_val: int) -> int:
    cur = await _db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    if not row: return default_val
    try:
        return int(row["value"])
    except:
        return default_val

async def _get_setting_str(key: str, default_val: str) -> str:
    cur = await _db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else default_val

async def _set_setting(key: str, val: str):
    await _db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, val))

# -----------------------------
# User tag preferences
# -----------------------------
async def get_user_tag_prefs(user_id: int) -> dict:
    cur = await _db.execute("SELECT tag, position FROM user_prefs WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if not row:
        return {"tag": None, "position": "end"}
    pos = row["position"] if row["position"] in ("start", "end") else "end"
    return {"tag": row["tag"], "position": pos}

async def set_user_tag(user_id: int, tag: Optional[str]):
    tag = (tag or "").strip()
    if not tag:
        await _db.execute(
            "INSERT INTO user_prefs(user_id, tag) VALUES(?, NULL) ON CONFLICT(user_id) DO UPDATE SET tag=NULL",
            (user_id,)
        )
    else:
        await _db.execute(
            "INSERT INTO user_prefs(user_id, tag) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET tag=excluded.tag",
            (user_id, tag)
        )
    await _db.commit()

async def set_tag_position(user_id: int, position: str):
    position = position if position in ("start", "end") else "end"
    await _db.execute(
        "INSERT INTO user_prefs(user_id, position) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET position=excluded.position",
        (user_id, position)
    )
    await _db.commit()

def _normalize_tag(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if not s.startswith("@") and not s.startswith("#"):
        s = "@" + s
    return s

def apply_tag_to_caption(caption: str, tag: Optional[str], position: str = "end") -> str:
    tag_norm = _normalize_tag(tag or "")
    if not tag_norm:
        return caption.strip()
    cap = (caption or "").strip()
    if tag_norm.lower() in cap.lower():
        return cap
    if position == "start":
        return f"{tag_norm} {cap}".strip()
    return f"{cap} {tag_norm}".strip()

# -----------------------------
# Filename helpers
# -----------------------------
INVALID_FS_CHARS = re.compile(r"[\\/:*?\"<>|]")
USERNAME_RE = re.compile(r"@[\w_]+|#[\w_]+", re.UNICODE)

def _clean_base_filename(name: str) -> str:
    base = USERNAME_RE.sub("", name or "").strip()
    base = re.sub(r"\s+", " ", base)
    # Remove some common emoji ranges to avoid odd filenames
    base = re.sub(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]", "", base)
    base = base.strip()
    return INVALID_FS_CHARS.sub("_", base)

async def build_final_filename(user_id: int, original_name: str) -> str:
    """Return a safe filename with the user's tag at start or end.
    If no tag saved, only cleans invalid characters.
    """
    original_name = original_name or "file"
    base, ext = os.path.splitext(original_name)
    if not ext:
        ext = ""
    base = _clean_base_filename(base)

    prefs = await get_user_tag_prefs(user_id)
    tag_norm = _normalize_tag(prefs.get("tag") or "")
    if tag_norm:
        if prefs.get("position") == "start":
            base = f"{tag_norm} {base}".strip()
        else:
            base = f"{base} {tag_norm}".strip()
    # final sanitize and limit
    base = INVALID_FS_CHARS.sub("_", base).strip()
    if len(base) > 230:
        base = base[:230].rstrip()
    return f"{base}{ext}"

# -----------------------------
# Multi-caption helpers
# -----------------------------
async def _multi_row(user_id: int) -> dict:
    cur = await _db.execute("SELECT enabled, ids_json, pointer FROM user_multi WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if not row:
        await _db.execute("INSERT INTO user_multi(user_id, enabled, ids_json, pointer) VALUES(?,0,'[]',0)", (user_id,))
        await _db.commit()
        return {"enabled": 0, "ids": [], "pointer": 0}
    return {"enabled": int(row["enabled"]), "ids": json.loads(row["ids_json"] or "[]"), "pointer": int(row["pointer"])}

async def get_multi_state(user_id: int) -> dict:
    return await _multi_row(user_id)

async def set_multi_enabled(user_id: int, enabled: bool):
    await _db.execute("UPDATE user_multi SET enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
    await _db.commit()

async def set_multi_ids(user_id: int, ids: List[int], keep_pointer: bool = False):
    if not keep_pointer:
        await _db.execute("UPDATE user_multi SET ids_json=?, pointer=0 WHERE user_id=?", (json.dumps(ids), user_id))
    else:
        await _db.execute("UPDATE user_multi SET ids_json=? WHERE user_id=?", (json.dumps(ids), user_id))
    await _db.commit()

async def clear_multi(user_id: int):
    await _db.execute("UPDATE user_multi SET enabled=0, ids_json='[]', pointer=0 WHERE user_id= ?", (user_id,))
    await _db.commit()

async def toggle_multi_id(user_id: int, cid: int):
    st = await _multi_row(user_id)
    ids = st["ids"]
    if cid in ids:
        ids = [x for x in ids if x != cid]
    else:
        ids = ids + [cid]
    await set_multi_ids(user_id, ids, keep_pointer=True)

async def advance_multi_pointer(user_id: int):
    st = await _multi_row(user_id)
    if not st["ids"]:
        return
    ptr = (st["pointer"] + 1) % len(st["ids"])
    await _db.execute("UPDATE user_multi SET pointer=? WHERE user_id=?", (ptr, user_id))
    await _db.commit()

