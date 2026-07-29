import os
import logging
import requests
from dotenv import load_dotenv
from groq import Groq
from serpapi import GoogleSearch
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")

logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=GROQ_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Main AI Updates Bot hu 🤖\n\n"
        "Commands:\n"
        "/post [topic] | [style instructions]\n"
        "  Jaise: /post latest AI news | casual tone, bullet points\n"
        "/help - Madad chahiye"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Format: /post [topic] | [style instructions]\n"
        "Jaise: /post latest AI news | casual tone, simple language, bullet points"
    )


def search_topic(topic):
    try:
        params = {"engine": "google", "q": topic, "tbm": "nws", "api_key": SERPAPI_KEY}
        search = GoogleSearch(params)
        results = search.get_dict()
        news_items = results.get("news_results", [])[:5]
        headlines = [item.get("title", "") for item in news_items]
        snippets = [item.get("snippet", "") for item in news_items if item.get("snippet")]
        return headlines if headlines else [topic], snippets
    except Exception as e:
        print(f"SerpAPI error: {e}")
        return [topic], []


def generate_content(topic, headlines, snippets, style_instructions):
    try:
        news_text = "\n".join(headlines)
        snippet_text = "\n".join(snippets) if snippets else "No extra details available."
        prompt = f"""You are writing a Telegram post for a channel called "AI Updates".

Real news headlines found:
{news_text}

Extra details/snippets:
{snippet_text}

Style instructions from the user:
{style_instructions if style_instructions else "simple everyday language, 2-3 emojis, under 130 words, friendly tone, end with a question"}

CRITICAL RULES:
- Pick ONE specific headline from above and write about it in detail
- Use SPECIFIC facts: company names, product names, numbers, dates - whatever is in the headline/snippet
- Do NOT write vague generic statements like "AI is getting smarter" or "new models can learn from mistakes" - be specific about WHAT happened, WHO did it
- If bold is requested, wrap text in **double asterisks**, make sure every ** has a matching closing **
- Follow the style instructions exactly"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq error: {e}")
        return f"Update on {topic}: Stay tuned for more AI news! 🤖"


def generate_image_query(post_text):
    """AI se post ke content ke hisaab se ek simple stock-photo keyword nikalwana"""
    try:
        prompt = f"""Given this social media post text:
"{post_text}"

Suggest a simple 2-3 word search term for finding a relevant STOCK PHOTO (generic visual concept, not brand names).
Examples: robot hand, computer chip, city skyline, classroom students, doctor hospital, self driving car, data center server.
Reply with ONLY the 2-3 word term, nothing else."""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=15
        )
        return response.choices[0].message.content.strip().strip('"')
    except Exception as e:
        print(f"Image query error: {e}")
        return "technology"


def get_image(query):
    try:
        url = "https://pixabay.com/api/"
        params = {"key": PIXABAY_KEY, "q": query, "image_type": "photo", "orientation": "horizontal", "per_page": 3}
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        hits = data.get("hits", [])
        if hits:
            return hits[0]["largeImageURL"]
        print(f"Pixabay: no image found for query '{query}'")
        return None
    except Exception as e:
        print(f"Pixabay error: {e}")
        return None


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Format: /post [topic] | [style instructions]\nJaise: /post latest AI news | casual tone, bullet points"
        )
        return

    full_text = " ".join(context.args)

    if "|" in full_text:
        topic, style_instructions = full_text.split("|", 1)
        topic = topic.strip()
        style_instructions = style_instructions.strip()
    else:
        topic = full_text.strip()
        style_instructions = ""

    await update.message.reply_text(f"⏳ '{topic}' par post bana rahe hai, thoda ruko...")

    try:
        headlines, snippets = search_topic(topic)
        post_text = generate_content(topic, headlines, snippets, style_instructions)
        image_query = generate_image_query(post_text)
        print(f"Image search query: {image_query}")
        image_url = get_image(image_query)

        if image_url:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            payload = {"chat_id": TELEGRAM_CHANNEL_ID, "photo": image_url, "caption": post_text, "parse_mode": "Markdown"}
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHANNEL_ID, "text": post_text, "parse_mode": "Markdown"}

        response = requests.post(url, data=payload, timeout=20)

        if response.status_code != 200:
            payload.pop("parse_mode", None)
            response = requests.post(url, data=payload, timeout=20)

        if response.status_code == 200:
            await update.message.reply_text("✅ Post ho gaya channel pe!")
        else:
            await update.message.reply_text(f"❌ Telegram ne reject kiya: {response.text[:300]}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error aaya: {str(e)}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a helpful assistant for a Telegram channel called 'AI Updates'. Answer questions about AI and technology in a friendly, concise way. Keep replies under 150 words."},
            {"role": "user", "content": user_message}
        ],
        max_tokens=300
    )
    reply_text = response.choices[0].message.content
    await update.message.reply_text(reply_text)


def main():
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot chalu ho gaya hai... (band karne ke liye Ctrl+C dabao)")
    app.run_polling()


if __name__ == "__main__":
    main()