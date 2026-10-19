"""Publishes, or updates, the bot's Telegraph guide in English and French: python guide/telegraph_pages.py <commit>.
The pictures are served by jsDelivr from this public repo at that commit (guide/img, made by build_guide.py).
The Telegraph token stays out of every repo (~/.telegraph_accounts.json): it can edit the pages."""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ACCOUNTS = Path.home() / ".telegraph_accounts.json"     # never in a repo: the token edits the pages
KEY = "captionbot"
NAME = "Auto-Caption Bot"
BOT_URL = "https://t.me/auttocaptionbot"
COMMIT = sys.argv[1] if len(sys.argv) > 1 else "main"
IMG = f"https://cdn.jsdelivr.net/gh/DINO060/CAPTIONBOT@{COMMIT}/guide/img/"


def api(method, **params):
    data = urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                                   for k, v in params.items()}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegra.ph/{method}", data=data), timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(f"{method}: {res.get('error')}")
    return res["result"]


def node(tag, *children, **attrs):
    n = {"tag": tag, "children": [c for c in children if c not in (None, "")]}
    if attrs:
        n["attrs"] = attrs
    return n


def p(*c): return node("p", *c)
def h3(t): return node("h3", t)
def b(t): return node("b", t)
def code(t): return node("code", t)
def a(t, href): return node("a", t, href=href)
def ul(*items): return node("ul", *[node("li", *(i if isinstance(i, tuple) else (i,))) for i in items])
def ol(*items): return node("ol", *[node("li", *(i if isinstance(i, tuple) else (i,))) for i in items])
def fig(name, caption): return node("figure", node("img", src=IMG + name), node("figcaption", caption))
def video(name, caption): return node("figure", node("video", src=IMG + name), node("figcaption", caption))


def english(other_url):
    return [
        p(NAME, " puts ", b("your caption"), " on every episode you send — series, episode number, quality, language — and ",
          b("your channel's name"), " in the caption and in the file name. One file or a whole season, in order."),
        video("explainer_en.mp4", "The bot in 30 seconds"),
        p(a("🇫🇷 Version française", other_url)) if other_url else None,
        h3("1. Describe your series (once)"),
        p("Send ", code("/settemplate Blue Horizon — Episode 1 — 1080p — VF"), " (series — episode — quality — language)."),
        p("Or the short way: ", code("/n Blue Horizon /v 1080p /l VF"), ". The quality is written nicely: 1080p → Full HD, 720p → HD, 2160p → Ultra HD."),
        fig("flow_start.gif", "/settemplate, then a file: its caption"),
        h3("2. Send your files"),
        ul(("Each file comes back with its caption: ", code("Blue Horizon Episode 5 Full HD VF @MyChannel"), "."),
           ("The ", b("episode number"), " is read from the file name (« - 05 », « S02E05 », « EP12 »); without one, the counter goes on: 1, 2, 3…"),
           ("A document gets its ", b("new name"), " too, with your hashtag — up to 2 GB."),
           "Send a whole season at once: the files come back in the order you sent them, then one summary."),
        fig("flow_files.gif", "4 files at once: back in order, numbered, one summary"),
        fig("names.png", "How a caption and a file name are made"),
        h3("3. Several series"),
        p(code("/captions"), " lists your captions (one per series / quality / language). Open one:"),
        ul((b("▶️ Continue"), " — use it, from the episode where you were."),
           (b("🔁 Start Over"), " — use it, from episode 1."),
           (b("🗑 Delete"), " — remove it.")),
        fig("flow_captions.gif", "Pick a caption, continue where you were"),
        h3("4. Multi-caption (VF + VOSTFR…)"),
        p("In ", code("/captions"), " → 🎯 Multi-select, tick 2 to 10 captions, then ▶️ Start: the files you send take them in turn "
          "(one in VF, the next in VOSTFR…). Choosing a single caption again turns it off."),
        fig("multi.png", "Two captions in turn"),
        h3("5. Settings"),
        ul((b("➕ Hashtag"), " — @MyChannel or #AnimeClub, added to the captions and the file names."),
           (b("📍 Position"), " — at the start or at the end."),
           (b("🔢 Episode"), " — from the file name (default) or the counter only.")),
        fig("settings.png", "The settings"),
        h3("Commands"),
        ul((code("/start"), " — home"), (code("/settemplate"), " — describe a series"), (code("/captions"), " — your captions"),
           (code("/status"), " — your active caption"), (code("/help"), " — this guide")),
        h3("Good to know"),
        ul("Files over 20 MB are renamed too, up to 2 GB (the bot shows its progress).",
           "If the bot asks you to join a channel first, join it and tap 🔄 I have joined.",
           "When the bot gets new features, it tells you what's new — once."),
        p(a("👉 Open the bot", BOT_URL)),
    ]


def french(other_url):
    return [
        p(NAME, " met ", b("ta légende"), " sur chaque épisode que tu envoies — série, numéro d'épisode, qualité, langue — et ",
          b("le nom de ta chaîne"), " dans la légende et dans le nom du fichier. Un fichier ou toute une saison, dans l'ordre."),
        video("explainer_fr.mp4", "Le bot en 30 secondes"),
        p(a("🇬🇧 English version", other_url)) if other_url else None,
        h3("1. Décris ta série (une fois)"),
        p("Envoie ", code("/settemplate Blue Horizon — Episode 1 — 1080p — VF"), " (série — épisode — qualité — langue)."),
        p("Ou en court : ", code("/n Blue Horizon /v 1080p /l VF"), ". La qualité est écrite proprement : 1080p → Full HD, 720p → HD, 2160p → Ultra HD."),
        fig("flow_start.gif", "/settemplate, puis un fichier : sa légende"),
        h3("2. Envoie tes fichiers"),
        ul(("Chaque fichier revient avec sa légende : ", code("Blue Horizon Episode 5 Full HD VF @MyChannel"), "."),
           ("Le ", b("numéro d'épisode"), " est lu dans le nom du fichier (« - 05 », « S02E05 », « EP12 ») ; sinon le compteur continue : 1, 2, 3…"),
           ("Un document reçoit aussi son ", b("nouveau nom"), ", avec ton hashtag — jusqu'à 2 Go."),
           "Envoie toute une saison d'un coup : les fichiers reviennent dans l'ordre où tu les as envoyés, puis un seul résumé."),
        fig("flow_files.gif", "4 fichiers d'un coup : dans l'ordre, numérotés, un résumé"),
        fig("names.png", "Comment une légende et un nom de fichier sont faits"),
        h3("3. Plusieurs séries"),
        p(code("/captions"), " liste tes légendes (une par série / qualité / langue). Ouvre-en une :"),
        ul((b("▶️ Continue"), " — l'utiliser, depuis l'épisode où tu en étais."),
           (b("🔁 Start Over"), " — l'utiliser, depuis l'épisode 1."),
           (b("🗑 Delete"), " — la supprimer.")),
        fig("flow_captions.gif", "Choisis une légende, continue où tu en étais"),
        h3("4. Multi-légendes (VF + VOSTFR…)"),
        p("Dans ", code("/captions"), " → 🎯 Multi-select, coche 2 à 10 légendes, puis ▶️ Start : les fichiers que tu envoies les prennent "
          "à tour de rôle (un en VF, le suivant en VOSTFR…). Choisir à nouveau une seule légende désactive ce mode."),
        fig("multi.png", "Deux légendes à tour de rôle"),
        h3("5. Réglages"),
        ul((b("➕ Hashtag"), " — @MaChaine ou #AnimeClub, ajouté aux légendes et aux noms de fichiers."),
           (b("📍 Position"), " — au début ou à la fin."),
           (b("🔢 Épisode"), " — depuis le nom du fichier (par défaut) ou le compteur seulement.")),
        fig("settings.png", "Les réglages"),
        h3("Commandes"),
        ul((code("/start"), " — accueil"), (code("/settemplate"), " — décrire une série"), (code("/captions"), " — tes légendes"),
           (code("/status"), " — ta légende active"), (code("/help"), " — ce guide")),
        h3("Bon à savoir"),
        ul("Les fichiers de plus de 20 Mo sont renommés aussi, jusqu'à 2 Go (le bot affiche l'avancement).",
           "Si le bot te demande de rejoindre une chaîne d'abord, rejoins-la puis appuie sur 🔄 I have joined.",
           "Quand le bot reçoit de nouvelles fonctions, il te dit ce qui change — une seule fois."),
        p(a("👉 Ouvrir le bot", BOT_URL)),
    ]


def clean(nodes):
    return [n for n in nodes if n]


def main():
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8")) if ACCOUNTS.exists() else {}
    acc = accounts.get(KEY) or {}
    if not acc.get("token"):
        acc["token"] = api("createAccount", short_name=NAME[:32], author_name=NAME, author_url=BOT_URL)["access_token"]
    common = {"access_token": acc["token"], "author_name": NAME, "author_url": BOT_URL}
    titles = {"en": f"{NAME} — How to use it", "fr": f"{NAME} — Mode d'emploi"}

    def publish(lang, content):
        if acc.get(lang):
            return api(f"editPage/{acc[lang]}", title=titles[lang], content=clean(content), **common)
        return api("createPage", title=titles[lang], content=clean(content), **common)

    en = publish("en", english(f"https://telegra.ph/{acc['fr']}" if acc.get("fr") else None))
    acc["en"] = en["path"]
    fr = publish("fr", french(en["url"]))
    acc["fr"] = fr["path"]
    en = publish("en", english(fr["url"]))
    accounts[KEY] = acc
    ACCOUNTS.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    print("EN", en["url"])
    print("FR", fr["url"])


if __name__ == "__main__":
    main()
