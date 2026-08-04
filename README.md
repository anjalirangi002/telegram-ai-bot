# Telegram AI Bot

Telegram bot jo AI-news posts aur normal chat handle karta hai. Posting ka timing,
topic aur style Telegram message se control hota hai; GitHub Actions ki zarurat nahi.

## Render deployment

1. Code ko GitHub repository mein push karein (Render source access ke liye GitHub use
   ho sakta hai, lekin koi GitHub Action run nahi hoga).
2. Render Dashboard mein **New → Blueprint** select karke repository connect karein.
   Repository ka `render.yaml` ek **Background Worker** banayega.
3. Render mein in environment variables ki values add karein: `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHANNEL_ID`, `GROQ_API_KEY`, `SERPAPI_KEY`, `PIXABAY_KEY`,
   `SUPABASE_URL`, aur `SUPABASE_KEY`.
   `TELEGRAM_ALLOWED_USER_IDS` mein apna numeric Telegram user ID bhi add karna
   recommended hai (multiple IDs ko comma se separate karein). Isse sirf aapke
   allowed accounts posting/schedule control kar sakte hain.
4. Deploy ke baad purani local/GitHub Actions bot process ko band rakhein. Ek Telegram
   token ke liye ek hi polling process chalna chahiye.

Worker ka start command `python reply_bot.py` hai. Isliye bot 24/7 running rehta hai
aur aap Telegram mein "abhi post karo", "5 min baad post karo", "roz 7 baje post
karo", ya "har 10 min post karo" jaisi instructions de sakte hain. `posting band
karo` ab one-time delayed posts ko bhi cancel karta hai.
