# Substack Replies

A personal tool that scrapes Substack replies and displays them in a local Flask web app, so you can track which ones need a response.

## When starting a new session

`SUBSTACK_SID` should already be set via `~/.zshrc`. Check first:

```bash
echo $SUBSTACK_SID
```

If it's missing or expired:
1. Ask the user to get their `substack.sid` cookie from browser DevTools (Application tab → Cookies → substack.com)
2. Ask them to run in their terminal: `echo 'export SUBSTACK_SID="..."' >> ~/.zshrc && source ~/.zshrc`
3. **Do not ask them to paste the cookie value into chat** — it's a live credential and conversation content is sent to Anthropic's servers

## First-time setup (new user, no config.py)

If `config.py` doesn't exist, follow these steps in order.

### 1. Check prerequisites

```bash
python3 --version
git --version
```

If Python 3 isn't installed, tell the user to download it from python.org and come back. On Mac, if Git isn't installed, `git --version` may trigger a prompt to install Xcode Command Line Tools — warn them it's safe.

### 2. Fork or clone?

Ask the user:

> Quick question before we download the app: do you think you might want to customize it — change how it looks, what it tracks, how things are organized? Or do you just want to try it out as-is?
>
> - **Just try it out** → simple download, no GitHub account needed.
> - **I want to customize it** → we'll set up your own copy on GitHub. You'll need a free GitHub account.

**If just trying it out (clone):**

Ask where they'd like to put it — their Desktop, Documents, or a Projects folder all work. Then clone there:

```bash
git clone https://github.com/alyssafuward/substack-replies.git /path/they/chose/substack-replies
cd /path/they/chose/substack-replies
pip install -r requirements.txt
```

**If they want to customize (fork + clone):**

If they don't have a GitHub account, tell them to create one at github.com. Then:

1. Tell them to go to https://github.com/alyssafuward/substack-replies and click **Fork** → **Create fork**
2. Ask for their GitHub username and where they'd like to put it, then:

```bash
git clone https://github.com/THEIR-USERNAME/substack-replies.git /path/they/chose/substack-replies
cd /path/they/chose/substack-replies
pip install -r requirements.txt
```

### 3. Get the Substack session cookie

The user does this themselves — **do not have them paste the cookie value into chat**. Conversation content is sent to Anthropic's servers and the cookie is a live credential.

Tell the user:

> This is the one part I can't do for you. A session cookie is how your browser proves to Substack that you're logged in — we need it so the app can fetch your data. Don't share it with anyone, including me. I'll give you a command to store it safely on your machine.

Walk them through finding it:
1. Open [substack.com](https://substack.com) logged in
2. Open DevTools: `Cmd+Option+I` (Mac) or `F12` (Windows)
3. Click **Application** tab → **Cookies** → `https://substack.com`
4. Find `substack.sid` and copy its value

Give them this command to run in Terminal (they replace the placeholder with their value):

```bash
echo 'export SUBSTACK_SID="paste-your-value-here"' >> ~/.zshrc && source ~/.zshrc
```

Verify it took:

```bash
echo $SUBSTACK_SID
```

If it prints nothing, troubleshoot — they may be on a different shell (`echo $SHELL`).

### 4. Look up their account details

Once `SUBSTACK_SID` is set, fetch their user ID and handle automatically:

```python
import requests, os
from urllib.parse import unquote
sid = os.environ.get("SUBSTACK_SID", "")
headers = {
    "Cookie": f"substack.sid={unquote(sid)}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}
resp = requests.get("https://substack.com/api/v1/subscriber", headers=headers)
data = resp.json()
print(f"USER_ID: {data.get('id') or data.get('user_id')}")
print(f"HANDLE: {data.get('handle', '')}")
```

### 5. Get publication IDs

Ask for the subdomain(s) of their Substack publication(s) — the part before `.substack.com`. For each one:

```python
import requests, os
from urllib.parse import unquote
subdomain = "REPLACE_WITH_SUBDOMAIN"
sid = os.environ.get("SUBSTACK_SID", "")
headers = {
    "Cookie": f"substack.sid={unquote(sid)}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}
resp = requests.get(f"https://{subdomain}.substack.com/api/v1/publication", headers=headers)
data = resp.json()
print(f"{subdomain}: {data.get('id')}")
```

### 6. Create config.py

```python
USER_ID = <user_id>
HANDLE = "<handle>"

OWN_PUBS = {
    "<subdomain>": <pub_id>,
    # add more publications here
}
```

### 7. Verify and run

```bash
python check.py
```

If any checks fail, diagnose before continuing. Then start the app:

```bash
python app.py
```

Tell the user to open http://localhost:5001. Explain that this is local to their computer — it's not a website anyone else can see.

### 8. Walk them through first use

- **Replies tab** — replies to their Notes and comments. Hit **Sync** to fetch activity. The first sync may take several minutes while the database builds — this is normal.
- **Publication tabs** — comments on their own posts. Hit **Load posts** first, then **Sync** for ongoing updates.
- **Liked toggle** — when on, liked replies move to a collapsed "handled" section.
- **Search** — filters across all tabs simultaneously.

## Commands

```bash
python scraper.py sync        # fetch latest activity + comments
python app.py                 # start Flask app at http://localhost:5001
python check.py               # run sanity checks after any code changes
```

## Configuration

- User config (USER_ID, HANDLE, OWN_PUBS) lives in `config.py` — gitignored, never committed
- Data stored in `replies.db` (local SQLite, gitignored)

## How it works

1. Hits Substack's internal API (unofficial, no public docs) authenticated via session cookie
2. Fetches activity feed (note replies, comment replies) + comments on your own posts
3. Stores everything in a local SQLite database
4. `app.py` serves a Flask web app at localhost:5001

## Likes = acknowledged

**Liking a reply is intentional user behavior meaning "seen and acknowledged."** It is not a bug or a gap in detection. Items where the user has liked the reply are separated into a collapsed "liked comments" section and excluded from the main unanswered queue. The recheck logic in `scraper.py` intentionally skips liked items for the same reason — they don't need to be rechecked for a response. Do not flag this as missing functionality.
