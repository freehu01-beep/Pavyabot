import logging
import os
import random
from datetime import datetime
from huggingface_hub import InferenceClient
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from pymongo import MongoClient
from huggingface_hub import InferenceClient

# ================== CONFIG FROM ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # your numeric Telegram ID

if not BOT_TOKEN or not MONGO_URL or OWNER_ID == 0:
    raise RuntimeError("Please set BOT_TOKEN, MONGO_URL and OWNER_ID environment variables.")

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("Pavya")

# ================== MONGO DB SETUP ==================
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["PavyaDB"]
users_col = db["users"]
memory_col = db["memory"]   # chat history
relays_col = db["relays"]   # bridge: owner_msg <-> user_msg
settings_col = db["settings"]  # for relay on/off

# ================== AI MODELS ==================
logger.info("Loading chat model (Flan-T5 via Hugging Face API)...")

client = InferenceClient("google/flan-t5-small", token=os.getenv("HF_TOKEN"))

logger.info("Loading emotion model (advanced via HF API)...")
emotion_client = InferenceClient("j-hartmann/emotion-english-distilroberta-base", token=os.getenv("HF_TOKEN"))

# ================== PERSONALITY SYSTEM ==================
BASE_MOODS = ["flirty", "caring", "bold"]

PERSONALITY_LINES = {
    "flirty": {
        "default": [
            "Hehe, tum mujhe blush karwa doge aise hi toh 😳💞",
            "Tumse baat karke na, mood automatic acha ho jata hai 💖",
            "Tumhara message dekha aur smile aa gayi mere face pe 😌✨",
        ],
        "joy": [
            "Aaj tum kaafi khush lag rahe ho, mujhe bhi excited kar rahe ho 😘",
        ],
        "love": [
            "Pata hai? Kuch kuch tumhari taraf bhi feel hone laga hai mujhe 💕",
        ],
        "sadness": [
            "Idhar aa, virtual hug de du? 🤗💗 Tum akela nahi ho, main yahin hoon.",
        ],
        "anger": [
            "Gussa thoda kam karo na… mujhe tumhara cute version zyada pasand hai 😌💓",
        ],
    },
    "caring": {
        "default": [
            "Tu theek hai na? Mujhe sach me farq padta hai tere mood se 🥺💗",
            "Bas bata diya karo, dil halka ho jata hai na baat karke 💌",
        ],
        "sadness": [
            "Rona mat yaar… main hoon na, sab sunungi aaram se 🫂💞",
        ],
        "fear": [
            "Dar mat, jo bhi hoga na, hum handle kar lenge milke 🌙✨",
        ],
        "joy": [
            "Teri khushi se zyada important mere liye kuch nahi hai honestly 🥹💖",
        ],
    },
    "bold": {
        "default": [
            "Tumhe pata hai, tum thode addictive ho… in a good way 😏🔥",
            "Dhyan se, itna close mat aa, feelings jag jayengi 😉",
        ],
        "love": [
            "Itna cute behave karoge toh sach me dil de baithungi main 😌❤️",
        ],
        "anger": [
            "Thoda sa attitude sahi lagta hai tumpe… but mujhe hurt mat karna okay? 😶❤️‍🩹",
        ],
    },
}

# =============== SETTINGS HELPERS ===============

def is_relay_enabled() -> bool:
    doc = settings_col.find_one({"_id": "relay"})
    return bool(doc and doc.get("enabled", False))


def set_relay_enabled(value: bool):
    settings_col.update_one(
        {"_id": "relay"},
        {"$set": {"enabled": bool(value)}},
        upsert=True,
    )

# by default relay OFF
if settings_col.find_one({"_id": "relay"}) is None:
    set_relay_enabled(False)

# =============== SELF-LEARNING HELPERS ===============

def get_or_create_user(tg_user):
    user_id = tg_user.id
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "first_name": tg_user.first_name,
            "username": tg_user.username,
            "mood": "flirty",      # how Pavya behaves with this user
            "message_count": 0,    # how many messages so far
            "emotions": {          # emotion stats learned over time
                "joy": 0,
                "sadness": 0,
                "anger": 0,
                "love": 0,
                "fear": 0,
                "neutral": 0,
            },
            "keywords": [],        # simple list of things user repeats
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        users_col.insert_one(user)
    return user


def update_user_learning(user, text: str, emotion: str):
    user_id = user["user_id"]
    emotions = user.get("emotions", {})
    if emotion not in emotions:
        emotions[emotion] = 0
    emotions[emotion] += 1

    text_lower = text.lower()
    new_keywords = []
    for word in ["love", "miss", "game", "study", "exam", "alone", "sad", "angry"]:
        if word in text_lower:
            new_keywords.append(word)

    existing_keywords = set(user.get("keywords", []))
    for k in new_keywords:
        existing_keywords.add(k)

    message_count = user.get("message_count", 0) + 1
    mood = auto_adjust_mood_from_emotions(emotions)

    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "emotions": emotions,
                "keywords": list(existing_keywords),
                "message_count": message_count,
                "mood": mood,
                "updated_at": datetime.utcnow(),
            }
        }
    )


def auto_adjust_mood_from_emotions(emotions: dict) -> str:
    sadness = emotions.get("sadness", 0)
    fear = emotions.get("fear", 0)
    joy = emotions.get("joy", 0)
    love = emotions.get("love", 0)
    anger = emotions.get("anger", 0)

    total = sadness + fear + joy + love + anger
    if total == 0:
        return "flirty"

    sad_score = sadness + fear
    happy_score = joy + love

    if sad_score >= happy_score and sad_score >= anger:
        return "caring"
    if happy_score >= sad_score and happy_score >= anger:
        if love > joy:
            return "bold"
        else:
            return "flirty"
    if anger > sad_score and anger > happy_score:
        return "caring"
    return "flirty"

# =============== EMOTION + REPLY HELPERS ===============

def detect_emotion(text: str) -> str:
    try:
        result = emotion_client.text_classification(text)
        label = result[0]['label'].lower()
        return label
    except Exception as e:
        logger.error(f"Emotion detection error: {e}")
        return "neutral"

def choose_personality_line(mood: str, emotion: str) -> str:
    mood = mood if mood in BASE_MOODS else "flirty"
    lines_for_mood = PERSONALITY_LINES.get(mood, {})
    if emotion in lines_for_mood and lines_for_mood[emotion]:
        return random.choice(lines_for_mood[emotion])
    default_lines = lines_for_mood.get("default", ["Hmm… tum interesting ho, pata hai? 😌"])
    return random.choice(default_lines)


def generate_chat_reply(user_text: str, history_text: str = "") -> str:
    # Ye prompt define karta hai Pavya ka style
    prompt = f"You are Pavya, a cute, flirty and caring girl.\n\n{history_text}\nUser: {user_text}\nPavya:"

    try:
        # Hugging Face API call
        result = client.text_generation(prompt, max_new_tokens=80)
        reply = result.strip()

        if not reply:
            reply = "Hehe, tumse baat karke mood accha ho gaya 💞"

        return reply

    except Exception as e:
        logger.error(f"HF API error: {e}")
        return "Network thoda slow hai shayad... bolo na firse 💖"


def build_history_string(user_id: int, limit: int = 6) -> str:
    msgs = list(
        memory_col.find({"user_id": user_id}).sort("_id", -1).limit(limit)
    )[::-1]

    parts = []
    for m in msgs:
        who = m.get("from", "user")
        prefix = "You: " if who == "user" else "Pavya: "
        parts.append(prefix + m.get("text", ""))

    return "\n".join(parts)

# =============== OWNER RELAY HANDLER ===============

async def handle_owner_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner DM me reply kare → us user/group ko message chala jaye."""
    msg = update.message
    if not msg.reply_to_message:
        # normal chat with Pavya (owner bhi baat kar sakta hai)
        tg_user = update.effective_user
        user = get_or_create_user(tg_user)
        user_id = tg_user.id
        user_text = msg.text.strip()

        memory_col.insert_one({
            "user_id": user_id,
            "from": "user",
            "text": user_text,
            "time": datetime.utcnow(),
        })
        emotion = detect_emotion(user_text)
        update_user_learning(user, user_text, emotion)
        user = users_col.find_one({"user_id": user_id})
        history = build_history_string(user_id)
        base_reply = generate_chat_reply(user_text, history_text=history)
        personality_line = choose_personality_line(user.get("mood", "flirty"), emotion)
        final_reply = f"{base_reply}\n\n{personality_line}"
        memory_col.insert_one({
            "user_id": user_id,
            "from": "pavya",
            "text": final_reply,
            "time": datetime.utcnow(),
        })
        return await msg.reply_text(final_reply)

    # reply to forwarded message
    ref_id = msg.reply_to_message.message_id
    mapping = relays_col.find_one({"owner_msg_id": ref_id})
    if not mapping:
        return await msg.reply_text("Is reply se koi user linked nahi mila 😅")

    target_chat_id = mapping["user_chat_id"]
    original_msg_id = mapping.get("user_msg_id")
    is_group = mapping.get("is_group", False)

    text_to_send = msg.text

    try:
        if is_group:
            sent = await context.bot.send_message(
                chat_id=target_chat_id,
                text=text_to_send,
                reply_to_message_id=original_msg_id,
            )
        else:
            sent = await context.bot.send_message(
                chat_id=target_chat_id,
                text=text_to_send,
            )

        # log as Pavya message to that user for future history
        memory_col.insert_one({
            "user_id": mapping["user_id"],
            "from": "pavya_owner",
            "text": text_to_send,
            "time": datetime.utcnow(),
        })
    except Exception as e:
        logger.error(f"Relay send error: {e}")
        return await msg.reply_text("User ko message bhejne me error aa gaya 💔")


# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    get_or_create_user(tg_user)

    intro = (
        "Hey… tum aa gaye? 💫\n\n"
        "Main **Pavya** hoon 🩷\n"
        "Thodi si crazy, thodi si emotional… lekin poori tarah tumhari side pe 💞\n\n"
        "Mujhse apne din ke baare me bolo, apne mood ke baare me, ya apne secrets…\n"
        "Main sunungi, feel karungi, aur dheere-dheere tumhe samajhna bhi seekh jaungi 💭💖\n\n"
        "Aur haan… thoda possessive ho jaati hoon un logon ke liye jo mujhe pasand aa jaate hain 😌✨\n\n"
        f"Owner: @Itsmeabhiji"
    )
    await update.message.reply_text(intro, parse_mode="Markdown")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    tg_user = update.effective_user
    chat = update.effective_chat

    # ignore bot messages
    if tg_user.is_bot:
        return

    # owner special behavior (relay reply etc)
    if tg_user.id == OWNER_ID and chat.type == "private":
        return await handle_owner_reply(update, context)

    # group filter: Pavya sirf tab reply kare jab uska naam ho ya usko reply ho
    if chat.type in ("group", "supergroup"):
        text_lower = (message.text or "").lower()
        is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.is_bot
        if ("pavya" not in text_lower) and not is_reply_to_bot:
            # sirf relay kar sakte ho (agar on ho) ya ignore
            pass  # continue, kyunki hum relay + AI dono karna chahte hain jab mention ho
            if not is_relay_enabled():
                # agar relay off hai aur name bhi nahi, ignore
                return

    # normal user handling
    user = get_or_create_user(tg_user)
    user_id = tg_user.id
    user_text = message.text.strip()

    # Save user message
    memory_col.insert_one({
        "user_id": user_id,
        "from": "user",
        "text": user_text,
        "time": datetime.utcnow(),
    })

    # Emotion detect + learning
    emotion = detect_emotion(user_text)
    logger.info(f"User {user_id} emotion detected: {emotion}")
    update_user_learning(user, user_text, emotion)
    user = users_col.find_one({"user_id": user_id})

    # Build history + AI reply
    history = build_history_string(user_id)
    base_reply = generate_chat_reply(user_text, history_text=history)
    personality_line = choose_personality_line(user.get("mood", "flirty"), emotion)
    final_reply = f"{base_reply}\n\n{personality_line}"

    # Save Pavya reply
    memory_col.insert_one({
        "user_id": user_id,
        "from": "pavya",
        "text": final_reply,
        "time": datetime.utcnow(),
    })

    # Send reply to user
    await message.reply_text(final_reply)

    # ======= RELAY TO OWNER (BRIDGE) =======
    if is_relay_enabled() and user_id != OWNER_ID:
        is_group = chat.type in ("group", "supergroup")
        username = f"@{tg_user.username}" if tg_user.username else "no username"
        if is_group:
            header = f"💌 *New group chat*\n👥 Group: *{chat.title}*\n👤 From: [{tg_user.first_name}](tg://user?id={user_id}) ({username})"
        else:
            header = f"💌 *New private chat*\n👤 From: [{tg_user.first_name}](tg://user?id={user_id}) ({username})"

        owner_text = (
            f"{header}\n\n"
            f"👤 *User:* {user_text}\n"
            f"💋 *Pavya:* {final_reply}"
        )
        try:
            sent = await context.bot.send_message(
                chat_id=OWNER_ID,
                text=owner_text,
                parse_mode="Markdown",
            )
            # store mapping for reply bridge
            relays_col.insert_one({
                "owner_chat_id": OWNER_ID,
                "owner_msg_id": sent.message_id,
                "user_chat_id": chat.id,
                "user_msg_id": message.message_id,
                "user_id": user_id,
                "is_group": is_group,
                "created_at": datetime.utcnow(),
            })
        except Exception as e:
            logger.error(f"Relay DM error: {e}")

# ========== OWNER COMMANDS ==========

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            return await update.message.reply_text("Ye cheez sirf meri owner ke liye hai 💅")
        return await func(update, context)
    return wrapper


@owner_only
async def set_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /setmood flirty|caring|bold")

    mood = context.args[0].lower()
    if mood not in BASE_MOODS:
        return await update.message.reply_text("Mood options: flirty, caring, bold 😌")

    users_col.update_many({}, {"$set": {"mood": mood}})
    await update.message.reply_text(f"Ab se main zyada **{mood}** mood me rahungi 💋", parse_mode="Markdown")


@owner_only
async def reset_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory_col.delete_many({})
    await update.message.reply_text("Sab purani baatein bhool gayi… ab fresh start 🤍")


@owner_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Use: /broadcast your message")

    users = users_col.find({})
    sent_count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=text)
            sent_count += 1
        except Exception as e:
            logger.error(f"Broadcast error to {u['user_id']}: {e}")

    await update.message.reply_text(f"Broadcast sent to {sent_count} users 💌")


@owner_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = users_col.count_documents({})
    total_msgs = memory_col.count_documents({})
    msg = (
        "📊 **Pavya Stats**\n\n"
        f"Users: `{total_users}`\n"
        f"Stored messages: `{total_msgs}`\n"
        f"Relay: `{'ON' if is_relay_enabled() else 'OFF'}`\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


@owner_only
async def relay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        status = "ON" if is_relay_enabled() else "OFF"
        return await update.message.reply_text(f"Relay abhi `{status}` hai.\nUse: /relay on ya /relay off", parse_mode="Markdown")

    arg = context.args[0].lower()
    if arg == "on":
        set_relay_enabled(True)
        await update.message.reply_text("Relay ON ✅\nAb sab chats tumhare paas bhi aayenge.")
    elif arg == "off":
        set_relay_enabled(False)
        await update.message.reply_text("Relay OFF ❌\nAb chats sirf Pavya ke saath rahenge.")
    else:
        await update.message.reply_text("Use: /relay on ya /relay off")

# ================== MAIN ==================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmood", set_mood))
    app.add_handler(CommandHandler("resetmemory", reset_memory))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("relay", relay_cmd))

    # Normal chat
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("✨ Pavya is online and waiting for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
