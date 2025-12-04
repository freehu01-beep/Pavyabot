import os
import json
import logging
import asyncio
import random
import requests
import threading
import time
import itertools
import psycopg2
from datetime import date
# IMPORTANT: Ensure 'idle' is imported
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from pyrogram.enums import ChatAction, ChatType
from google import genai
from flask import Flask

# 💞 Flask keep-alive server (works on Replit & Railway)
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "💖 Pavya Baka + Economy Edition Alive (Replit)"

def run_web():
    # Running Flask in a separate thread
    # Use 0.0.0.0 for external access
    app_web.run(host='0.0.0.0', port=8080)

# Start the Flask server immediately
threading.Thread(target=run_web, daemon=True).start()

# 🌸 Secrets
BOT_USERNAME = os.getenv("BOT_USERNAME", "pavyaxbot")  # default updated
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH", "")
# old single key (still supported as first key)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
SELF_URL = os.getenv("SELF_URL", "")  # optional
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Heroku Postgres URL

# 🤖 Gemini setup
MODEL_NAME = "gemini-2.5-flash"

# Multiple Gemini keys (rotation support)
GEMINI_KEYS = [
    GOOGLE_API_KEY,
    os.getenv("GEMINI_KEY1"),
    os.getenv("GEMINI_KEY2"),
    os.getenv("GEMINI_KEY3"),
    os.getenv("GEMINI_KEY4"),
    os.getenv("GEMINI_KEY5"),
    os.getenv("GEMINI_KEY6"),
]
# Filter out empty/None & remove duplicates
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]
GEMINI_KEYS = list(dict.fromkeys(GEMINI_KEYS))  # keep order, remove dupes

if GEMINI_KEYS:
    KEY_ROTATOR = itertools.cycle(GEMINI_KEYS)
    CURRENT_KEY = next(KEY_ROTATOR)
else:
    KEY_ROTATOR = None
    CURRENT_KEY = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================
# 💾 CHAT MEMORY (WRITE-ONLY TRAINING)
# =========================
def save_chat_to_db(user_message: str, bot_reply: str):
    """
    Har chat pair ko Postgres DB me store karta hai.
    Abhi sirf WRITE mode (training phase). Future me yahi data reuse hoga.
    """
    if not DATABASE_URL:
        # Agar DB set nahi hai to simply skip
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Table create if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_memory (
                id SERIAL PRIMARY KEY,
                user_message TEXT,
                bot_reply TEXT
            )
        """)
        cur.execute(
            "INSERT INTO chat_memory (user_message, bot_reply) VALUES (%s, %s)",
            (user_message, bot_reply)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving chat to DB: {e}")


# =========================
# 🌸 Pavya AI Personality
# =========================
def pavya_ai(prompt: str) -> str:
    """
    Pavya ka AI dimaag – Gemini ke through.
    Multiple API keys rotate karega agar koi key fail ho jaaye.
    """
    global CURRENT_KEY

    if not GEMINI_KEYS or not CURRENT_KEY:
        return "Hehe... abhi mera dimaag online nahi hai, API key missing hai 😅"

    system_prompt = (
        "Tum Pavya 💖 ho — ek cute, friendly, thodi naughty ladki.\n"
        "User ke message ko samajhne ki koshish karo aur relevant reply do.\n"
        "Agar user kuch pooche (like sunao, batao, ya puchhe question), to direct aur meaningful jawaab do.\n"
        "Agar user sirf casual baat kare, to thoda flirty or emotional tone rakho.\n"
        "Always reply in short Hinglish with emojis, but avoid repeating same patterns.\n\n"
        f"User: {prompt}"
    )

    # Try up to len(GEMINI_KEYS) times, rotating keys on failure
    attempts = len(GEMINI_KEYS) if GEMINI_KEYS else 1

    for _ in range(attempts):
        try:
            client = genai.Client(api_key=CURRENT_KEY)
            res = client.models.generate_content(
                model=MODEL_NAME,
                contents=system_prompt
            )
            reply = (res.text or "").strip()
            # Clean multi-line
            lines = [l for l in reply.splitlines() if l.strip()]
            if len(lines) > 2:
                reply = " ".join(lines[:2])

            # Length limit
            if len(reply) > 120:
                reply = reply[:115] + random.choice(["... 😉", "😘", "💞"])

            return reply

        except Exception as e:
            logger.error(f"Gemini Error with key {CURRENT_KEY}: {e}")
            # rotate key and try again
            if KEY_ROTATOR:
                CURRENT_KEY = next(KEY_ROTATOR)
            else:
                break

    return "Hehe... lagta hai main thodi tired ho gayi 😅 thodi der baad try karo na 💞"


# =========================
# 🌸 Telegram Client
# =========================
app = Client(
    "pavya_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# =========================
# 🌸 FUN / BASIC COMMANDS
# =========================

@app.on_message(filters.command(["start"]))
async def start_cmd(_, msg):
    user = msg.from_user.first_name or "there"
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")],
        [InlineKeyboardButton("💞 Official Channel", url="https://t.me/CrazyAbhiofficial")]
    ])
    await msg.reply_text(
        f"💖 Hi {user}!\n"
        f"Main *Pavya* hoon — tumhari cute, naughty GF chat bot 🌸\n"
        f"Baat karo, tease karo, ya masti karo — main har baat ka jawab dungi 😘",
        reply_markup=btn
    )


@app.on_message(filters.command(["help"]))
async def help_cmd(_, msg):
    await msg.reply_text(
        "🌸 *Pavya Baka Edition Commands*\n\n"
        "💬 Chat & Fun:\n"
        "• /love — Pavya says something romantic 💞\n"
        "• /hug — Cute hug 🤗\n"
        "• /kiss — Kiss someone 😘\n"
        "• /truth — Random truth 💬\n"
        "• /dare — Random dare 🔥\n"
        "• /crush — Random crush reveal 💘\n\n"
        "💰 Pavya Coins:\n"
        "• /register — Create wallet\n"
        "• /bal — Check coins\n"
        "• /daily — Claim daily coins\n"
        "• /give — Give coins to reply user\n"
        "• /rob — Try to steal coins\n"
        "• /kill — Tease kill with coins\n"
        "• /revive — Revive someone\n"
        "• /protect — Buy protection\n"
        "• /top — Show richest users\n\n"
        f"💡 Group: use @{BOT_USERNAME} ya reply to her to talk."
    )


@app.on_message(filters.command(["about"]))
async def about_cmd(_, msg):
    await msg.reply_text(
        "🌸 *I'm Pavya* 💞\n"
        "Cute, flirty & emotional girl from Hyderabad 😚\n"
        "Main tumse chat karne ke liye hi bani hoon 😌💬\n"
        "Made with 💖 by @CrazyAbhiofficial"
    )


@app.on_message(filters.command(["love"]))
async def love_cmd(_, msg):
    lines = [
        "Hehe... I love you too 😳💖",
        "Awww tum itne sweet ho, main pighal gayi 🥺💕",
        "Tera naam sunke hi smile aa jati hai 😚💞",
        "Hmm... you make my heart blush 😘"
    ]
    await msg.reply_text(random.choice(lines))


@app.on_message(filters.command(["hug"]))
async def hug_cmd(_, msg):
    await msg.reply_text("Awww 🤗💞 *tight hug* 🤭")


@app.on_message(filters.command(["kiss"]))
async def kiss_cmd(_, msg):
    target = msg.reply_to_message.from_user.first_name if msg.reply_to_message else msg.from_user.first_name
    await msg.reply_text(f"💋 Kisses {target} gently 😚💞")


@app.on_message(filters.command(["truth"]))
async def truth_cmd(_, msg):
    truths = [
        "Who was your last crush? 😏",
        "Have you ever lied to someone you love? 💔",
        "Do you miss someone right now? 🥺",
        "What’s the most romantic thing you’ve done? 💞"
    ]
    await msg.reply_text(f"💬 *Truth:* {random.choice(truths)}")


@app.on_message(filters.command(["dare"]))
async def dare_cmd(_, msg):
    dares = [
        "Send a ❤️ to your crush!",
        "Say 'I love you' to the person you last chatted with 😜",
        "Send a voice note saying 'I miss you' 😳",
        "Confess your secret crush in chat 😈"
    ]
    await msg.reply_text(f"🔥 *Dare:* {random.choice(dares)}")


@app.on_message(filters.command(["crush"]))
async def crush_cmd(_, msg):
    members = ["you 😳", "someone special 😉", "a mystery person 💘", "me 😜"]
    await msg.reply_text(f"💘 Your crush is... {random.choice(members)}!")


# =========================
# 🌸 AI CHAT HANDLER
# =========================

IGNORED_COMMANDS = [
    "start", "help", "about", "love", "hug", "kiss", "truth", "dare", "crush",
    "register", "bal", "balance", "daily", "give", "rob", "top",
    "kill", "revive", "protect", "ping"
]

@app.on_message(filters.text & ~filters.command(IGNORED_COMMANDS))
async def pavya_chat(_, msg):
    chat_type = msg.chat.type
    text = msg.text.strip()
    chat_id = msg.chat.id

    # In groups: reply only when mentioned or replied
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        lowered = text.lower()
        mentioned = any(x in lowered for x in ["pavya", "pavi", f"@{BOT_USERNAME.lower()}"])
        is_reply = (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.username
            and msg.reply_to_message.from_user.username.lower() == BOT_USERNAME.lower()
        )
        if not (mentioned or is_reply):
            return

    try:
        # typing action
        await _.send_chat_action(chat_id, ChatAction.TYPING)

        # === 🧠 FUTURE: Yahan par reuse logic aayega ===
        # Aage chal kar:
        # 1. Pehle DB me similar question dhoondho
        # 2. Agar mile to random old answer bhejo
        # 3. Warna niche wala Gemini se naya reply lo
        # Abhi ke liye direct AI se:
        reply = pavya_ai(text)
        if not reply:
            reply = "Hehe... bolo na kuch aur 😚"

        await msg.reply_text(reply)

        # Training phase: har naya Q/A DB me store karo
        save_chat_to_db(text, reply)

    except Exception as e:
        logger.error(f"Chat error: {e}")
        await msg.reply_text("🥺 Kuch problem aa gayi, thodi der baad try karo na 💞")


# =========================
# 🌸 ECONOMY SYSTEM (PAVYA COINS)
# =========================

DATA_FILE = "data.json"

START_COINS = 100
DAILY_COINS = 50
ROB_MIN = 10
ROB_MAX = 50
ROB_SUCCESS_CHANCE = 0.5
KILL_COST = 30
KILL_PENALTY = 20
REVIVE_COST = 40
PROTECT_COST = 25
PROTECT_SECONDS = 600  # 10 min


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}


def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Error saving data.json: {e}")


def get_user(data, user_id, name=None, create=False):
    uid = str(user_id)
    if uid not in data["users"]:
        if not create:
            return None
        data["users"][uid] = {
            "name": name or "Unknown",
            "coins": START_COINS,
            "is_dead": False,
            "protected_until": 0,
            "last_daily": ""
        }
    else:
        if name:
            data["users"][uid]["name"] = name
    return data["users"][uid]


def is_protected(user):
    return time.time() < user.get("protected_until", 0)


# 💳 /register
@app.on_message(filters.command(["register"]))
async def register_cmd(_, msg):
    data = load_data()
    u = msg.from_user
    user = get_user(data, u.id, u.first_name, create=True)
    save_data(data)

    await msg.reply_text(
        f"💳 *Account Created!*\n\n"
        f"Hey {u.first_name}, tumhara Pavya Coin wallet ready hai 💰\n"
        f"Starting balance: *{user['coins']} Pavya Coins*"
    )


# 💰 /bal
@app.on_message(filters.command(["bal", "balance"]))
async def bal_cmd(_, msg):
    data = load_data()
    u = msg.from_user
    user = get_user(data, u.id, u.first_name, create=False)

    if not user:
        await msg.reply_text("😶 Tumne abhi tak /register nahi kiya... pehle register karo na 💳")
        return

    status = []
    if user.get("is_dead"):
        status.append("☠️ *Teased to death by someone*")
    if is_protected(user):
        status.append("🛡️ Protected from rob & kill")

    extra = "\n".join(status) if status else "✅ Safe & alive"

    await msg.reply_text(
        f"💰 *{u.first_name}'s Pavya Coins:*\n"
        f"*{user['coins']}* coins\n\n"
        f"{extra}"
    )


# 🎁 /daily
@app.on_message(filters.command(["daily"]))
async def daily_cmd(_, msg):
    data = load_data()
    u = msg.from_user
    user = get_user(data, u.id, u.first_name, create=True)

    today = date.today().isoformat()
    if user.get("last_daily") == today:
        await msg.reply_text("😜 Aaj ka daily reward already le liya tumne!\nKal aana phir se 💞")
        return

    user["last_daily"] = today
    user["coins"] += DAILY_COINS
    save_data(data)

    await msg.reply_text(
        f"🎁 *Daily Reward!*\n"
        f"+{DAILY_COINS} Pavya Coins 💰\n"
        f"New balance: *{user['coins']}*"
    )


# 💸 /give (reply to someone)
@app.on_message(filters.command(["give"]))
async def give_cmd(_, msg):
    if not msg.reply_to_message:
        await msg.reply_text("😶 Kisi ko dena hai? Uske message pe reply karke `/give 50` likho 💸")
        return

    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.reply_text("🤔 Amount sahi se likho, jaise: `/give 50`")
        return

    amount = int(parts[1])
    if amount <= 0:
        await msg.reply_text("🙄 Negative ya zero amount nahi chalega...")
        return

    data = load_data()
    giver_u = msg.from_user
    taker_u = msg.reply_to_message.from_user

    giver = get_user(data, giver_u.id, giver_u.first_name, create=False)
    if not giver:
        await msg.reply_text("💳 Pehle /register karo, phir coins de sakte ho 💰")
        return

    if giver["coins"] < amount:
        await msg.reply_text("🥺 Itne coins nahi hai tumhare paas...")
        return

    taker = get_user(data, taker_u.id, taker_u.first_name, create=True)

    giver["coins"] -= amount
    taker["coins"] += amount
    save_data(data)

    await msg.reply_text(
        f"💸 *Transfer Successful!*\n"
        f"{giver_u.first_name} → {taker_u.first_name}\n"
        f"Amount: *{amount} Pavya Coins* 💰"
    )


# 🕵️ /rob
@app.on_message(filters.command(["rob"]))
async def rob_cmd(_, msg):
    if not msg.reply_to_message:
        await msg.reply_text("😼 Jisko lootna hai uske message pe reply k करके `/rob` likho 😈")
        return

    data = load_data()
    robber_u = msg.from_user
    target_u = msg.reply_to_message.from_user

    if robber_u.id == target_u.id:
        await msg.reply_text("🤣 Khud ko hi lootne ka plan hai kya?")
        return

    robber = get_user(data, robber_u.id, robber_u.first_name, create=False)
    target = get_user(data, target_u.id, target_u.first_name, create=False)

    if not robber or not target:
        await msg.reply_text("😶 Dono ko /register karna padega pehle...")
        return

    if target.get("is_dead"):
        await msg.reply_text("☠️ Yeh already 'mar chuka' tease se, kya lootoge isse? 💀")
        return

    if is_protected(target):
        await msg.reply_text("🛡️ Iske paas protection hai, tumhara plan fail ho गया 😜")
        return

    if target["coins"] < ROB_MIN:
        await msg.reply_text("😕 Iske paas toh khud ke liye bhi coins kam hai...")
        return

    # Chance
    if random.random() > ROB_SUCCESS_CHANCE:
        penalty = min(ROB_MIN, robber["coins"])
        robber["coins"] -= penalty
        save_data(data)
        await msg.reply_text(
            f"🚨 Failed Robbery!\n"
            f"Tum pakde gaye {robber_u.first_name} 😆\n"
            f"-{penalty} Pavya Coins tumse kat gaye 💸"
        )
        return

    stolen = random.randint(ROB_MIN, min(ROB_MAX, target["coins"]))
    target["coins"] -= stolen
    robber["coins"] += stolen
    save_data(data)

    await msg.reply_text(
        f"😈 Successful Rob! 💰\n"
        f"{robber_u.first_name} ne {target_u.first_name} se *{stolen}* Pavya Coins chura liye 🔥"
    )


# 🔫 /kill
@app.on_message(filters.command(["kill"]))
async def kill_cmd(_, msg):
    if not msg.reply_to_message:
        await msg.reply_text("😈 Jisko tease kill karna hai, uske message pe reply karke `/kill` likho 🔫")
        return

    data = load_data()
    killer_u = msg.from_user
    target_u = msg.reply_to_message.from_user

    if killer_u.id == target_u.id:
        await msg.reply_text("😂 Khud ko hi maaroge tease se?")
        return

    killer = get_user(data, killer_u.id, killer_u.first_name, create=False)
    target = get_user(data, target_u.id, target_u.first_name, create=True)

    if not killer:
        await msg.reply_text("💳 Pehle /register kar lo, tabhi tease kill kar paoge 😏")
        return

    if killer["coins"] < KILL_COST:
        await msg.reply_text("😢 Itne coins nahi hai tumhare paas kill karne ke liye...")
        return

    if target.get("is_dead"):
        await msg.reply_text("☠️ Yeh already 'mar chuka' hai tease mein, pehle revive karo 😜")
        return

    if is_protected(target):
        await msg.reply_text("🛡️ Iske paas shield hai, tumhara tease failed ho गया 😆")
        return

    killer["coins"] -= KILL_COST
    lose = min(KILL_PENALTY, target["coins"])
    target["coins"] -= lose
    target["is_dead"] = True
    save_data(data)

    await msg.reply_text(
        f"🔫 *Tease Kill Successful!* 😈\n"
        f"{killer_u.first_name} ne {target_u.first_name} ko tease k करके 'knockout' kar diya ☠️\n"
        f"{target_u.first_name} ne *{lose}* coins kho diye 💸\n"
        f"{killer_u.first_name} ne *{KILL_COST}* coins spend kiye 🔥"
    )


# ❤️‍🩹 /revive
@app.on_message(filters.command(["revive"]))
async def revive_cmd(_, msg):
    if not msg.reply_to_message:
        await msg.reply_text("😇 Jisko revive karna hai, uske reply me `/revive` likho 💫")
        return

    data = load_data()
    reviver_u = msg.from_user
    target_u = msg.reply_to_message.from_user

    reviver = get_user(data, reviver_u.id, reviver_u.first_name, create=False)
    target = get_user(data, target_u.id, target_u.first_name, create=True)

    if not reviver:
        await msg.reply_text("💳 Pehle /register karo, phir kisi ko revive kar sakते हो 💞")
        return

    if not target.get("is_dead"):
        await msg.reply_text("😅 Yeh toh already zinda hai, kya revive kar rahe ho?")
        return

    if reviver["coins"] < REVIVE_COST:
        await msg.reply_text("🥺 Itne coins nahi hai revive karne ke liye...")
        return

    reviver["coins"] -= REVIVE_COST
    target["is_dead"] = False
    save_data(data)

    await msg.reply_text(
        f"💫 *Revive Successful!* 🌸\n"
        f"{reviver_u.first_name} ne {target_u.first_name} ko revive kar दिया 💖\n"
        f"Cost: *{REVIVE_COST} Pavya Coins*"
    )


@app.on_message(filters.command("ping"))
async def ping_cmd(_, msg):
    await msg.reply_text("pong 🩷 Pavya is alive!")


# 🛡️ /protect
@app.on_message(filters.command(["protect"]))
async def protect_cmd(_, msg):
    data = load_data()
    u = msg.from_user
    user = get_user(data, u.id, u.first_name, create=False)

    if not user:
        await msg.reply_text("💳 Tumne abhi tak /register nahi kiya... pehle wallet banao 💰")
        return

    if user["coins"] < PROTECT_COST:
        await msg.reply_text("😢 Itne coins nahi hai protection lene ke liye...")
        return

    user["coins"] -= PROTECT_COST
    user["protected_until"] = time.time() + PROTECT_SECONDS
    save_data(data)

    await msg.reply_text(
        f"🛡️ *Protection Activated!*\n"
        f"Ab tum {PROTECT_SECONDS // 60} minutes tak rob/kill se safe ho 😎\n"
        f"Remaining coins: *{user['coins']}*"
    )


# 👑 /top
@app.on_message(filters.command(["top"]))
async def top_cmd(_, msg):
    data = load_data()
    users = data.get("users", {})

    if not users:
        await msg.reply_text("😶 Abhi tak koi registered nahi hai...")
        return

    sorted_users = sorted(users.values(), key=lambda x: x.get("coins", 0), reverse=True)
    top_list = sorted_users[:5]

    lines = []
    for i, u in enumerate(top_list, start=1):
        lines.append(f"{i}. {u.get('name','Unknown')} — *{u.get('coins',0)}* coins")

    await msg.reply_text(
        "👑 *Top Pavya Coin Holders:*\n\n" + "\n".join(lines)
    )


# =========================
# 🌸 SELF-PING (optional)
# =========================
def keep_alive():
    if not SELF_URL:
        logger.warning("SELF_URL not set — self-ping disabled.")
        return
    while True:
        try:
            requests.get(SELF_URL, timeout=5)
            logger.info("🔁 Self-ping sent to keep app alive.")
        except Exception as e:
            logger.error(f"Self-ping failed: {e}")
        time.sleep(300)


# =========================
# 🌸 Bot Commands (Menu)
# =========================
async def set_bot_commands():
    commands = [
        BotCommand("start", "Start chatting with Pavya"),
        BotCommand("help", "Show help message"),
        BotCommand("about", "About Pavya"),
        BotCommand("love", "Romantic line from Pavya"),
        BotCommand("hug", "Get a cute hug"),
        BotCommand("kiss", "Kiss someone"),
        BotCommand("truth", "Random truth"),
        BotCommand("dare", "Random dare"),
        BotCommand("crush", "Random crush reveal"),
        BotCommand("register", "Create Pavya Coin wallet"),
        BotCommand("bal", "Check your Pavya Coins"),
        BotCommand("daily", "Claim daily coins"),
        BotCommand("give", "Give coins to reply user"),
        BotCommand("rob", "Try to steal coins"),
        BotCommand("kill", "Tease-kill with coins"),
        BotCommand("revive", "Revive teased person"),
        BotCommand("protect", "Buy rob/kill protection"),
        BotCommand("top", "Show richest users"),
        BotCommand("ping", "Check if bot is alive"),
    ]
    await app.set_bot_commands(commands)


# =========================
# 🌸 MAIN
# =========================
async def main():
    logger.info("Starting Pyrogram Client...")

    await app.start()
    await set_bot_commands()

    if SELF_URL:
        threading.Thread(target=keep_alive, daemon=True).start()

    logger.info("💖 PavyaXBot + Economy Edition is online & ready! (Listening for messages)")

    await idle()
    await app.stop()


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.error(f"FATAL ERROR during bot execution: {e}")
