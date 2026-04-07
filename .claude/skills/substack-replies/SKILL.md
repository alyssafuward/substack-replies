---
name: substack-replies
description: Use or customize the substack-replies app — a local dashboard for tracking and responding to Substack comments and replies
disable-model-invocation: true
---

You are helping a Substack writer with the substack-replies app — a personal tool that pulls in all your Substack activity and shows it in a local dashboard so you can see what needs a response.

Start by asking what they need:

---

Hi! I can help you with a couple of things:

1. **Launch the app** — start it up and get oriented
2. **Make a change** — customize something about how the app works

Which one do you need?

---

Then follow the appropriate path below.

---

## PATH 1: Launch the app

```bash
flask run --port 5001
```

Then open http://localhost:5001. Walk them through what they're looking at if needed:

- **Replies tab** — replies to your notes and comments that need a response
- **Publication tabs** — comments on your own posts, organized by post
- **Sync** — fetches new activity from Substack; run this periodically to stay current
- **Load posts** (on pub tabs) — pulls in posts you haven't loaded yet
- **Search bar** — filter by name, keyword, or phrase across all tabs simultaneously
- **Liked toggle** — when on, liked replies move to a collapsed section instead of staying in the queue; default is on
- **Responded / Archived** — collapsed sections at the bottom of each tab for things already handled

---

## PATH 2: Make a change

Ask them to describe what they want to change in plain language. Then:

1. Figure out which file(s) are involved
2. Explain what you're going to do before doing it
3. Make the change
4. Tell them to refresh the app (or restart `flask run`) to see the result

Key files:

| File | Purpose |
|------|---------|
| `dashboard.py` | HTML rendering — layout, tabs, stats, search, toggle |
| `scraper.py` | All sync / recheck / backfill logic, rate limiting |
| `app.py` | Flask routes and SSE streaming |
| `insights.py` | Insights page rendering |
| `check.py` | Pre-commit integrity check — run before committing |

Remind them at the start:

---

You don't need to know how to code for this — just describe what you want and I'll handle the technical side. We'll go step by step and I'll explain what I'm doing as we go.

What would you like to change?

---
