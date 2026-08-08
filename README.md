# 🤖 Telegram AI Bot

An AI-powered Telegram bot that posts daily AI-news updates and handles real-time chat replies — fully controlled via Telegram messages, no manual scheduling or GitHub Actions needed.

`Python` `Groq API` `Supabase` `Render` `python-telegram-bot`

🔗 **Live/Deployed on:** Render (Background Worker)

---

## ✨ What it does

- **Daily AI-news posts** — automatically fetches and posts fresh AI news to a Telegram channel.
- **Real-time chat replies** — responds to messages instantly using Groq-powered AI.
- **Fully chat-controlled** — no code changes needed to manage posting; just message the bot:
  - `"abhi post karo"` → posts immediately
  - `"5 min baad post karo"` → schedules a delayed post
  - `"roz 7 baje post karo"` → sets a daily recurring post
  - `"har 10 min post karo"` → sets a repeating interval post
  - `"posting band karo"` → cancels scheduled/recurring posts
- **Access-controlled** — only approved Telegram user IDs can control posting/scheduling.

## 🛠️ How it's built

| Part | Role |
|---|---|
| `reply_bot.py` | Main worker — runs 24/7, handles chat replies and scheduling logic |
| `daily_post.py` | Builds and sends the daily AI-news post |
| `render.yaml` | Render Blueprint config — defines the Background Worker |
| Groq API | Powers AI chat replies and news summarization |
| Supabase | Stores schedule/state data |
| SerpAPI / Pixabay | Sourcing news content and images for posts |

## 📁 Project structure

.
├── .github/workflows/   # (legacy) GitHub Actions config — not required with Render
├── daily_post.py        # builds & sends the daily AI-news post
├── reply_bot.py         # main bot worker — chat replies + scheduling
├── render.yaml          # Render Background Worker config
├── requirements.txt     # Python dependencies
├── .python-version      # Python version for Render
└── README.md

Then run:

```bash
python reply_bot.py
```

## ☁️ Deploy on Render

1. Push code to GitHub (no GitHub Action needs to run).
2. In Render Dashboard → **New → Blueprint** → connect this repository. `render.yaml` will create a Background Worker automatically.
3. Add all environment variables listed above in Render's dashboard.
4. Make sure only **one** polling process runs per bot token — stop any old local/Actions process before deploying.

## 📄 License

MIT
