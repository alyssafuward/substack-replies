# Substack Replies — Claude Boot Sequence

This file tells you, Claude, how to set up and run this tool for the user. Read it fully before doing anything.

---

## What this tool does

Scrapes Substack replies and comments across the user's publications and activity feed, stores them locally, and generates an HTML dashboard so they can track which ones need a response.

---

## Every time the user opens this project

**Step 1: Check for the session cookie**

```bash
echo $SUBSTACK_SID
```

- If it prints a value → you're good, proceed
- If it's empty → ask the user to get their cookie (see below) and add it to `~/.zshrc`

**Never ask the user to paste the cookie value into chat.** It's a live credential and conversation content is sent to Anthropic's servers. Always tell them to run the export command directly in their terminal.

If the cookie is missing, share these instructions with the user:

1. Open [substack.com](https://substack.com) in their browser and make sure they're logged in
2. Open DevTools: Cmd+Option+I → Application tab → Cookies → substack.com
3. Find `substack.sid` and copy the value
4. Run this command directly in Terminal (do not paste the value into chat): `echo 'export SUBSTACK_SID="paste-value-here"' >> ~/.zshrc && source ~/.zshrc`

**Step 2: Check for config.py**

```bash
python check.py
```

- If it passes → ask the user what they want to do (sync, view dashboard, etc.)
- If config.py is missing → run first-time setup (see below)

---

## First-time setup (new user)

If `config.py` doesn't exist, create it automatically. Once `SUBSTACK_SID` is set, you can look up all the values — no manual digging needed.

Run this to get their user ID and handle:

```python
import requests, os, json
from urllib.parse import unquote

sid = os.environ.get("SUBSTACK_SID", "")
headers = {
    "Cookie": f"substack.sid={unquote(sid)}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

resp = requests.get("https://substack.com/api/v1/subscriber", headers=headers)
data = resp.json()
user_id = data.get("id") or data.get("user_id")
handle = data.get("handle", "")
print(f"USER_ID: {user_id}")
print(f"HANDLE: {handle}")
```

Ask the user which Substack publications they own (e.g. "alyssafuward", "createwithalyssa"), then fetch each pub ID:

```python
subdomain = "their-subdomain"  # replace with actual
resp = requests.get(f"https://{subdomain}.substack.com/api/v1/publication", headers=headers)
pub_id = resp.json().get("id")
print(f"{subdomain}: {pub_id}")
```

Write `config.py`:

```python
USER_ID = <user_id>
HANDLE = "<handle>"

OWN_PUBS = {
    "<subdomain>": <pub_id>,
}
```

Then run `python check.py` to confirm everything works.

**The database (`replies.db`) is created automatically** the first time you run `python scraper.py sync` — no manual setup needed. It stores all activity items, comments, and posts locally. It is gitignored and never committed.

---

## Common tasks

**Sync latest replies (fast, recommended daily):**
```bash
source ~/.zshrc && python scraper.py sync
```

**Open the dashboard:**
```bash
python dashboard.py
```

**Full resync (slower, use if data seems stale):**
```bash
source ~/.zshrc && python scraper.py sync --full
```

**Run sanity checks:**
```bash
python check.py
```

---

## How it works

1. Authenticates with Substack via session cookie (unofficial API, no public docs)
2. Fetches activity feed (note replies, comment replies) and comments on the user's own posts
3. Stores everything in `replies.db` (local SQLite, never committed to git)
4. `dashboard.py` generates a self-contained HTML file opened in the browser

---

## Key files

- `config.py` — user's personal config (gitignored, never committed)
- `config.example.py` — template for new users
- `replies.db` — local SQLite database (gitignored)
- `scraper.py` — fetches data from Substack
- `dashboard.py` — generates the HTML dashboard
- `check.py` — sanity checks

---

## Things to know

- Rate limiting: Substack returns 429 errors if you hit it too fast. The scraper handles this automatically with backoff.
- The session cookie expires when the user logs out of Substack in their browser. If scraping fails with auth errors, ask them to refresh their cookie.
- `replies.db` and `config.py` are gitignored — personal data never touches the repo.
