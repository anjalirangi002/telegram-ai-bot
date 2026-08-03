import os
import logging
import json
import asyncio
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from groq import Groq
from serpapi import GoogleSearch
from supabase import create_client
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=GROQ_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

IST = timezone(timedelta(hours=5, minutes=30))
TELEGRAM_CAPTION_HARD_LIMIT = 1024   # Telegram ka technical limit, hardcode nahi kar rahe content ko, ye Telegram ka rule hai
TELEGRAM_MESSAGE_HARD_LIMIT = 4096
MAX_HISTORY = 20

recurring_jobs = {}

TOPIC_VARIANTS = [
    "latest AI news",
    "new AI model launch",
    "AI startup funding news",
    "open source AI release",
    "AI research breakthrough",
    "AI product update",
]


# ---------- Persistent memory (Supabase) ----------

_last_cleanup_time = None
CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60


def cleanup_old_history():
    global _last_cleanup_time
    now = datetime.now(timezone.utc)
    if _last_cleanup_time and (now - _last_cleanup_time).total_seconds() < CLEANUP_INTERVAL_SECONDS:
        return
    try:
        cutoff = (now - timedelta(days=7)).isoformat()
        supabase.table("conversation_history").delete().lt("created_at", cutoff).execute()
        supabase.table("posts").delete().lt("created_at", cutoff).execute()
        print("Purana data clean ho gaya (7 din se zyada purana)")
        _last_cleanup_time = now
    except Exception as e:
        print(f"cleanup_old_history error: {e}")


def get_history(chat_id):
    try:
        result = (
            supabase.table("conversation_history")
            .select("role, content")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(MAX_HISTORY)
            .execute()
        )
        rows = list(reversed(result.data))
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    except Exception as e:
        print(f"get_history error: {e}")
        return []


def add_to_history(chat_id, role, content):
    try:
        supabase.table("conversation_history").insert({
            "chat_id": chat_id,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"add_to_history error: {e}")


def is_already_posted(headline):
    try:
        result = supabase.table("posts").select("*").eq("headline", headline).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"is_already_posted error: {e}")
        return False


def save_post_record(headline, content):
    try:
        supabase.table("posts").insert({"headline": headline, "post_content": content}).execute()
    except Exception as e:
        print(f"save_post_record error: {e}")


# ---------- Helpers ----------

def get_current_datetime():
    return datetime.now(IST)


def get_current_time_str():
    return get_current_datetime().strftime("%I:%M %p, %d %B %Y")


def safe_json_parse(text, fallback):
    try:
        cleaned = text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"JSON parse error: {e} | raw text: {text}")
        return fallback


def trim_to_telegram_limit(text, max_len):
    """Ye sirf Telegram ke technical limit se bachne ke liye hai, content-style ko chhota karne ke liye nahi"""
    if len(text) <= max_len:
        return text
    trimmed = text[:max_len - 3]
    if '\n' in trimmed:
        trimmed = trimmed.rsplit('\n', 1)[0]
    return trimmed + "..."


def cancel_recurring_jobs(chat_id):
    jobs = recurring_jobs.get(chat_id, [])
    count = 0
    for job in jobs:
        if not job.done():
            job.cancel()
            count += 1
    recurring_jobs[chat_id] = []
    return count


# ---------- Command handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Main AI Updates Bot hu 🤖\n\n"
        "Mujhse jaise chaho, jab chaho, jitna chaho bol sakte ho - main samajh ke kaam karunga.\n"
        "Post karwane, style customize karne, schedule set karne, sab kuch bas bol ke ho sakta hai.\n"
        "Rokne ke liye: 'posting band karo'\n"
        "Command se bhi: /post [topic] | [style]\n"
        "/help - Madad chahiye"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bas jaise chaho bol do, main samajh ke karunga:\n"
        "- 'channel pe AI news post karo'\n"
        "- '5 min baad post karo' ya '12:35 pe post karo'\n"
        "- 'roz subah 7 baje post karo'\n"
        "- 'har 10 min baad post karte raho'\n"
        "- 'posting band karo'\n"
        "- Style bhi bata sakte ho: 'bullet points mein, emojis ke saath, 200 words ka post karo'\n\n"
        "Command: /post [topic] | [style instructions]"
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    count = cancel_recurring_jobs(chat_id)
    if count > 0:
        await update.message.reply_text(f"✅ {count} recurring posting task(s) band kar diye.")
    else:
        await update.message.reply_text("Koi active recurring posting nahi mil raha thi.")


# ---------- Content generation ----------

def search_topic(topic):
    try:
        params = {"engine": "google", "q": topic, "tbm": "nws", "api_key": SERPAPI_KEY}
        search = GoogleSearch(params)
        results = search.get_dict()
        news_items = results.get("news_results", [])[:8]
        headlines = [item.get("title", "") for item in news_items if item.get("title")]
        snippets_map = {item.get("title", ""): item.get("snippet", "") for item in news_items}
        return (headlines if headlines else [topic]), snippets_map
    except Exception as e:
        print(f"SerpAPI error: {e}")
        return [topic], {}


def pick_fresh_headline(topic):
    """Multiple queries try karta hai jab tak ek non-duplicate headline na mile"""
    queries_to_try = [topic] + [t for t in TOPIC_VARIANTS if t != topic]
    for query in queries_to_try[:4]:
        headlines, snippets_map = search_topic(query)
        for h in headlines:
            if not is_already_posted(h):
                return h, ([snippets_map.get(h, "")] if snippets_map.get(h) else [])
    headlines, snippets_map = search_topic(topic)
    h = headlines[0] if headlines else topic
    return h, ([snippets_map.get(h, "")] if snippets_map.get(h) else [])


def generate_post_text(topic, headline, snippets, style_instructions):
    """
    Style instructions ko poori tarah AI decide karne deta hai - koi hardcoded word/char limit nahi.
    Agar user ne kuch specific nahi bola, AI khud ek achha default format chunta hai (suggestion, rule nahi).
    """
    try:
        snippet_text = "\n".join(snippets) if snippets else "No extra details available."

        if style_instructions:
            style_section = f"""Follow these style instructions from the user EXACTLY, including any length, format, or tone they specify:
{style_instructions}"""
        else:
            style_section = """No specific style was given, so use good judgment: a clear bold headline, 
point-by-point details covering the key facts, relevant emojis to make it engaging, 
and use as many words as needed to cover the story well - don't artificially cut it short or pad it out."""

        prompt = f"""You are writing a Telegram post for a channel called "AI Updates".

The specific news headline to write about:
{headline}

Extra details/snippets:
{snippet_text}

{style_section}

CRITICAL RULES:
- Write about ONLY this headline, use SPECIFIC facts (names, numbers, dates) - no vague generic statements
- If bold is requested or used, wrap text in **double asterisks**, every ** must have a matching closing **
- Decide the length based on what the story and the user's instructions actually need"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800
        )
        text = response.choices[0].message.content
        return text if text else f"Update: {headline} 🤖"
    except Exception as e:
        print(f"Groq content generation error: {e}")
        return f"Update: {headline} 🤖"


def generate_image_query(post_text):
    try:
        prompt = f"""Given this social media post: "{post_text}"
Suggest a simple 2-3 word search term for a relevant STOCK PHOTO (generic concept, no brand names).
Reply with ONLY the 2-3 word term."""
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=15
        )
        result = response.choices[0].message.content
        return result.strip().strip('"') if result else "technology"
    except Exception as e:
        print(f"Image query error: {e}")
        return "technology"


def get_image(query):
    try:
        url = "https://pixabay.com/api/"
        params = {"key": PIXABAY_KEY, "q": query, "image_type": "photo", "orientation": "horizontal", "per_page": 3}
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            return None
        data = response.json()
        hits = data.get("hits", [])
        return hits[0]["largeImageURL"] if hits else None
    except Exception as e:
        print(f"Pixabay error: {e}")
        return None


# ---------- Posting logic ----------

async def send_photo_post(post_text, image_url):
    try:
        img_response = requests.get(image_url, timeout=15)
        if img_response.status_code != 200:
            return False, "image download failed"
        img_data = img_response.content

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("image.jpg", img_data)}
        payload = {"chat_id": TELEGRAM_CHANNEL_ID, "caption": post_text, "parse_mode": "Markdown"}
        response = requests.post(url, data=payload, files=files, timeout=20)

        if response.status_code != 200:
            payload.pop("parse_mode", None)
            response = requests.post(url, data=payload, files=files, timeout=20)

        return response.status_code == 200, response.text
    except Exception as e:
        print(f"send_photo_post error: {e}")
        return False, str(e)


async def send_text_post(post_text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHANNEL_ID, "text": post_text, "parse_mode": "Markdown"}
        response = requests.post(url, data=payload, timeout=20)

        if response.status_code != 200:
            payload.pop("parse_mode", None)
            response = requests.post(url, data=payload, timeout=20)

        return response.status_code == 200, response.text
    except Exception as e:
        print(f"send_text_post error: {e}")
        return False, str(e)


async def execute_post(chat_id, topic, style_instructions, bot):
    try:
        headline, snippets = pick_fresh_headline(topic)

        if is_already_posted(headline):
            await bot.send_message(chat_id=chat_id, text=f"⚠️ Naya update nahi mila abhi ('{topic}'), thodi der baad try karo.")
            return False

        post_text = generate_post_text(topic, headline, snippets, style_instructions)
        image_query = generate_image_query(post_text)
        image_url = get_image(image_query)

        success = False
        error_detail = ""

        if image_url:
            caption_text = trim_to_telegram_limit(post_text, TELEGRAM_CAPTION_HARD_LIMIT)
            success, error_detail = await send_photo_post(caption_text, image_url)

        if not success:
            message_text = trim_to_telegram_limit(post_text, TELEGRAM_MESSAGE_HARD_LIMIT)
            success, error_detail = await send_text_post(message_text)

        if success:
            save_post_record(headline, post_text)
            await bot.send_message(chat_id=chat_id, text="✅ Post ho gaya channel pe!")
            return True
        else:
            await bot.send_message(chat_id=chat_id, text=f"❌ Post fail hua: {error_detail[:300]}")
            return False

    except Exception as e:
        print(f"execute_post fatal error: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ Kuch galat ho gaya: {str(e)[:300]}")
        except Exception:
            pass
        return False


async def delayed_post(chat_id, topic, style_instructions, delay_seconds, bot):
    try:
        await asyncio.sleep(delay_seconds)
        await execute_post(chat_id, topic, style_instructions, bot)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"delayed_post error: {e}")


async def recurring_daily_post(chat_id, topic, style_instructions, hour, minute, bot):
    while True:
        now = get_current_datetime()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        try:
            await asyncio.sleep(wait_seconds)
            await execute_post(chat_id, topic, style_instructions, bot)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"recurring_daily_post error: {e}")


async def recurring_interval_post(chat_id, topic, style_instructions, interval_seconds, bot):
    """User jo bhi interval bole, exactly wahi use hoga - koi minimum force nahi"""
    try:
        while True:
            await execute_post(chat_id, topic, style_instructions, bot)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"recurring_interval_post error: {e}")


async def do_post(update, context, topic, style_instructions, delay_seconds=0):
    chat_id = update.effective_chat.id
    try:
        delay_seconds = float(delay_seconds)
    except (ValueError, TypeError):
        delay_seconds = 0

    if delay_seconds and delay_seconds > 0:
        minutes = round(delay_seconds / 60, 2)
        await update.message.reply_text(f"⏰ Theek hai! {minutes} minute baad '{topic}' par post ho jayega channel pe.")
        asyncio.create_task(delayed_post(chat_id, topic, style_instructions, delay_seconds, context.bot))
    else:
        await update.message.reply_text(f"⏳ '{topic}' par post bana rahe hai, thoda ruko...")
        await execute_post(chat_id, topic, style_instructions, context.bot)


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: /post [topic] | [style instructions]")
        return
    full_text = " ".join(context.args)
    if "|" in full_text:
        topic, style = full_text.split("|", 1)
        topic, style = topic.strip(), style.strip()
    else:
        topic, style = full_text.strip(), ""
    if not topic:
        topic = "latest AI news"
    await do_post(update, context, topic, style, delay_seconds=0)


# ---------- Message classification (fully flexible) ----------

def classify_message(user_message):
    fallback = {
        "type": "chat", "topic": "", "style": "", "schedule_kind": "none",
        "delay_seconds": 0, "hour": None, "minute": None, "interval_seconds": None
    }
    try:
        now = get_current_datetime()
        current_time_24hr = now.strftime("%H:%M")
        current_time_readable = now.strftime("%I:%M %p, %A, %d %B %Y")

        prompt = f"""Current real time is {current_time_readable} ({current_time_24hr} in 24-hour format).

User message: "{user_message}"

Understand what the user wants, however they phrase it (any language, casual, typos, whatever), 
and reply with ONLY valid JSON, nothing else:
{{
  "type": "time_query" or "post_request" or "stop_posting_request" or "chat",
  "topic": "extracted topic/subject if post_request, default 'latest AI news' if not specified, else empty string",
  "style": "any style/format/tone/length instructions the user mentioned for the post content itself, else empty string",
  "schedule_kind": "none" or "once" or "daily" or "interval",
  "delay_seconds": 0,
  "hour": null,
  "minute": null,
  "interval_seconds": null
}}

Field meanings:
- "type":
  - "time_query": asking what time it is
  - "post_request": wants a post published to the channel, in ANY form - now, later, once, daily, repeating
  - "stop_posting_request": wants to stop/cancel any ongoing repeating or scheduled posting
  - "chat": anything else - questions, conversation, general knowledge, asking about past actions
- "style": extract ANY instructions about how the post content should look - length, tone, format, emojis, bullet points, bold, etc. Preserve their exact intent, don't paraphrase away specifics.
- "schedule_kind" (only if type is post_request):
  - "none": post immediately
  - "once": one-time post after a delay or at a specific future moment. Fill "delay_seconds" = exact seconds from now.
  - "daily": every day at a fixed clock time. Fill "hour" (0-23) and "minute" (0-59).
  - "interval": repeatedly every fixed duration. Fill "interval_seconds" = duration in seconds, using EXACTLY what the user said (e.g. "30 sec" = 30, "0.5 min" = 30, "har 2 ghante" = 7200). Do not round or adjust this value.
- Use the current time above to calculate any relative/absolute times precisely.

Examples:
"abhi post karo" -> type: post_request, schedule_kind: none
"5 min baad post karo" -> type: post_request, schedule_kind: once, delay_seconds: 300
"har 30 sec post karo" -> type: post_request, schedule_kind: interval, interval_seconds: 30
"har 0.5 min post karo" -> type: post_request, schedule_kind: interval, interval_seconds: 30
"roz subah 7 baje post karo" -> type: post_request, schedule_kind: daily, hour: 7, minute: 0
"bullet points mein, 200 words ka casual post karo" -> type: post_request, style: "bullet points, 200 words, casual tone"
"posting rok do" -> type: stop_posting_request
"kya time hai" -> type: time_query"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        raw_text = response.choices[0].message.content
        if not raw_text:
            return fallback

        data = safe_json_parse(raw_text, fallback)

        msg_type = data.get("type", "chat")
        if msg_type not in ("time_query", "post_request", "stop_posting_request", "chat"):
            msg_type = "chat"

        schedule_kind = data.get("schedule_kind", "none")
        if schedule_kind not in ("none", "once", "daily", "interval"):
            schedule_kind = "none"

        topic = data.get("topic", "") or ""
        style = data.get("style", "") or ""

        delay = data.get("delay_seconds", 0)
        try:
            delay = float(delay)
            if delay < 0:
                delay = 0
        except (ValueError, TypeError):
            delay = 0

        hour = data.get("hour")
        minute = data.get("minute")
        try:
            hour = int(hour) if hour is not None else None
            minute = int(minute) if minute is not None else None
            if hour is not None and not (0 <= hour <= 23):
                hour = None
            if minute is not None and not (0 <= minute <= 59):
                minute = None
        except (ValueError, TypeError):
            hour, minute = None, None

        interval = data.get("interval_seconds")
        try:
            interval = float(interval) if interval is not None and interval > 0 else None
        except (ValueError, TypeError):
            interval = None

        return {
            "type": msg_type, "topic": topic, "style": style, "schedule_kind": schedule_kind,
            "delay_seconds": delay, "hour": hour, "minute": minute, "interval_seconds": interval
        }

    except Exception as e:
        print(f"classify_message error: {e}")
        return fallback


# ---------- Main message handler ----------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_old_history()

    chat_id = update.effective_chat.id
    user_message = update.message.text

    if not user_message:
        return

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    result = classify_message(user_message)
    msg_type = result["type"]
    topic = result["topic"] if result["topic"] else "latest AI news"
    style = result.get("style", "")
    schedule_kind = result.get("schedule_kind", "none")
    delay_seconds = result["delay_seconds"]
    rec_hour = result.get("hour")
    rec_minute = result.get("minute")
    interval_seconds = result.get("interval_seconds")

    if msg_type == "time_query":
        reply = f"Abhi time hai: {get_current_time_str()} (IST) 🕐"
        add_to_history(chat_id, "user", user_message)
        add_to_history(chat_id, "assistant", reply)
        await update.message.reply_text(reply)
        return

    if msg_type == "stop_posting_request":
        count = cancel_recurring_jobs(chat_id)
        reply = f"✅ {count} recurring posting task(s) band kar diye." if count > 0 else "Koi active recurring posting nahi mil rahi thi."
        add_to_history(chat_id, "user", user_message)
        add_to_history(chat_id, "assistant", reply)
        await update.message.reply_text(reply)
        return

    if msg_type == "post_request":
        add_to_history(chat_id, "user", user_message)

        if schedule_kind == "daily":
            if rec_hour is None or rec_minute is None:
                await update.message.reply_text("Kis time roz post karna hai, wo clearly batao (jaise 'roz subah 7 baje').")
                return
            time_str = f"{rec_hour:02d}:{rec_minute:02d}"
            add_to_history(chat_id, "assistant", f"[Daily recurring post set for {time_str}, topic: {topic}]")
            task = asyncio.create_task(recurring_daily_post(chat_id, topic, style, rec_hour, rec_minute, context.bot))
            recurring_jobs.setdefault(chat_id, []).append(task)
            await update.message.reply_text(
                f"✅ Theek hai! Roz {time_str} (IST) baje '{topic}' par post ho jayega, jab tak bot chalu hai. "
                f"Rokne ke liye 'posting band karo' bolna."
            )
            return

        if schedule_kind == "interval":
            if interval_seconds is None:
                await update.message.reply_text("Kitni der ke gap se post karna hai, wo batao (jaise 'har 10 min baad').")
                return
            if interval_seconds < 60:
                readable = f"{interval_seconds:.0f} second"
            else:
                readable = f"{round(interval_seconds / 60, 2)} minute"
            add_to_history(chat_id, "assistant", f"[Repeating post every {readable} set, topic: {topic}]")
            task = asyncio.create_task(recurring_interval_post(chat_id, topic, style, interval_seconds, context.bot))
            recurring_jobs.setdefault(chat_id, []).append(task)
            await update.message.reply_text(
                f"✅ Theek hai! Ab har {readable} mein '{topic}' par naya post hoga. "
                f"Rokne ke liye 'posting band karo' bolna."
            )
            return

        if schedule_kind == "once" and delay_seconds > 0:
            add_to_history(chat_id, "assistant", f"[Post scheduled once for {topic}]")
            await do_post(update, context, topic, style, delay_seconds)
            return

        add_to_history(chat_id, "assistant", f"[Post requested immediately: {topic}]")
        await do_post(update, context, topic, style, 0)
        return

    add_to_history(chat_id, "user", user_message)

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    f"Your name is 'AI Updates Bot'. You are the official assistant for a Telegram channel called 'AI Updates'. "
                    f"Current real time is {get_current_time_str()} IST. "
                    "You are knowledgeable and can answer ANY question - general knowledge, science, history, casual conversation, "
                    "or anything else - not just AI/tech topics. Be helpful and smart about everything. "
                    "IMPORTANT: If asked about past posts or actions, ONLY refer to what is explicitly shown in the conversation "
                    "history below. NEVER invent or fabricate details about posts or actions not confirmed in the history - "
                    "say so honestly if you don't have a record. "
                    "Keep replies friendly, clear, and concise unless the question needs more detail. "
                    "Remember what the user told you earlier in this conversation and refer back to it naturally."
                )
            }
        ]
        messages.extend(get_history(chat_id))

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=400
        )
        reply_text = response.choices[0].message.content or "Sorry, kuch samajh nahi aaya. Dobara try karo?"
        add_to_history(chat_id, "assistant", reply_text)
        await update.message.reply_text(reply_text)

    except Exception as e:
        print(f"handle_message chat error: {e}")
        await update.message.reply_text("❌ Kuch technical issue aa gaya, dobara try karo please.")


# ---------- Entry point ----------

def main():
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CommandHandler("stopposting", stop_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot chalu ho gaya hai... (band karne ke liye Ctrl+C dabao)")
    app.run_polling()


if __name__ == "__main__":
    main()