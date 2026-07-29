import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from groq import Groq
from serpapi import GoogleSearch
from supabase import create_client

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

groq_client = Groq(api_key=GROQ_API_KEY)


def get_latest_ai_news():
    """SerpAPI se aaj ki latest AI news dhoondhna"""
    params = {
        "engine": "google",
        "q": "latest AI news today",
        "tbm": "nws",
        "api_key": SERPAPI_KEY
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    news_items = results.get("news_results", [])[:5]
    headlines = [item.get("title", "") for item in news_items]
    return headlines


def generate_post_content(headline):
    """Groq AI se SIRF is ek headline par post likhwana"""
    prompt = f"""You are writing a short, engaging Telegram post for a channel called "AI Updates".

Write about ONLY this single news item, don't mix in other unrelated topics:
"{headline}"

Write a concise, engaging Telegram post (max 130 words) focused entirely on this one topic.
Use a friendly tone, add 2-3 relevant emojis, and end with a short call-to-action like "Stay tuned for more AI updates!"
Plain text only, no markdown headers."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250
    )
    return response.choices[0].message.content


def generate_image_query(headline):
    """AI se is headline ke liye ek simple, generic image search keyword nikalwana"""
    prompt = f"""Given this AI news headline: "{headline}"

Suggest a simple 2-3 word search term for finding a relevant STOCK PHOTO (not a screenshot, not a logo).
Use generic visual concepts like: robot, computer chip, classroom technology, healthcare technology, data center, coding, smartphone app, self driving car, etc.
Do NOT use brand names or company names.
Reply with ONLY the 2-3 word search term, nothing else."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20
    )
    return response.choices[0].message.content.strip()


def get_image_url(query):
    """Pixabay se related image dhoondhna"""
    url = "https://pixabay.com/api/"
    params = {
        "key": PIXABAY_KEY,
        "q": query,
        "image_type": "photo",
        "orientation": "horizontal",
        "per_page": 3
    }
    response = requests.get(url, params=params)
    data = response.json()
    hits = data.get("hits", [])
    if hits:
        return hits[0]["largeImageURL"]
    return None


def post_to_telegram(text, image_url):
    """Telegram channel mein image ke saath post karna"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "photo": image_url,
        "caption": text
    }
    response = requests.post(url, data=payload)
    return response.json()


def cleanup_old_posts():
    """7 din se purane posts records delete karna, taaki Supabase full na ho"""
    try:
        cutoff_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
        supabase.table("posts").delete().lt("created_at", cutoff_date).execute()
        print("Purane posts clean ho gaye (7 din se zyada purane)")
    except Exception as e:
        print(f"Cleanup error: {e}")


def is_already_posted(headline):
    """Check karna ki ye headline pehle post ho chuki hai ya nahi"""
    result = supabase.table("posts").select("*").eq("headline", headline).execute()
    return len(result.data) > 0


def save_post_record(headline, content):
    """Naya post Supabase mein save karna"""
    supabase.table("posts").insert({
        "headline": headline,
        "post_content": content
    }).execute()


def main():
    cleanup_old_posts()

    print("Step 1: Latest AI news dhoondh rahe hai...")
    headlines = get_latest_ai_news()
    print(f"Mila: {headlines}")

    top_headline = headlines[0] if headlines else "AI news today"

    if is_already_posted(top_headline):
        print("Ye news pehle hi post ho chuki hai, skip kar rahe hai.")
        return

    print(f"Step 2: '{top_headline}' par post likhwa rahe hai...")
    post_text = generate_post_content(top_headline)
    print(f"Post content:\n{post_text}")

    print("Step 3: Relevant image keyword nikal rahe hai...")
    image_query = generate_image_query(top_headline)
    print(f"Image query: {image_query}")

    print("Step 4: Image dhoondh rahe hai...")
    image_url = get_image_url(image_query)
    print(f"Image URL: {image_url}")

    print("Step 5: Telegram par post kar rahe hai...")
    result = post_to_telegram(post_text, image_url)
    print(f"Result: {result}")

    print("Step 6: Supabase mein record save kar rahe hai...")
    save_post_record(top_headline, post_text)
    print("Save ho gaya!")


if __name__ == "__main__":
    main()