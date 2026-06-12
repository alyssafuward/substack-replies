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

Walk through this interactively — one step at a time. Do not present all the steps upfront. Complete each step, confirm it worked, then move to the next.

---

**Step 1: Check prerequisites.** Run these and show the user the results:

```bash
python3 --version
git --version
```

If Python 3 isn't installed, tell them to download it from python.org and come back before continuing. On Mac, if Git isn't installed, running `git --version` may trigger a prompt to install Xcode Command Line Tools — warn them this might happen and that it's safe to install. Once both are confirmed, move to step 2.

---

**Step 2: Fork or clone?** Ask this before doing anything else:

> Quick question before we download the app: do you think you might want to customize it at some point — change how it looks, what it tracks, how things are organized? Or do you just want to try it out as-is?
>
> - **Just try it out** → simple download, no GitHub account needed.
> - **I want to customize it** → we'll set up your own copy on GitHub that you can modify. You'll need a free GitHub account.

Wait for their answer, then continue.

**If just trying it out:** Ask where they'd like to keep the app — Desktop, Documents, and home directory all work fine. Then clone there and install dependencies:

```bash
git clone https://github.com/alyssafuward/substack-replies.git ~/Desktop/substack-replies
pip install -r requirements.txt
```

(Replace the path with wherever they chose.)

**If they want to customize:** If they don't have a GitHub account, tell them to create one at github.com — it's free. Once they have one, tell them to:
1. Go to https://github.com/alyssafuward/substack-replies
2. Click **Fork** → **Create fork**

Then ask for their GitHub username and where they'd like to keep the app, and clone their fork:

```bash
git clone https://github.com/THEIR-USERNAME/substack-replies.git ~/Desktop/substack-replies
pip install -r requirements.txt
```

Confirm the clone and install succeeded before continuing.

---

**Step 3: Substack session cookie.** Tell the user this before anything else:

> This is the one part I can't do for you — and you should not paste the value into this chat. A session cookie is how your browser proves to Substack that you're logged in. We need it so the app can fetch your data on your behalf. Treat it like a password. I'll give you a command to store it safely on your machine.

Then walk them through finding it:
1. Open [substack.com](https://substack.com) in their browser, logged in
2. Open DevTools: `Cmd+Option+I` on Mac, `F12` on Windows
3. Click the **Application** tab → **Cookies** → `https://substack.com`
4. Find the row named `substack.sid` and copy the value

Tell them to run this command in Terminal, replacing the placeholder with the value they copied:

```bash
echo 'export SUBSTACK_SID="paste-your-value-here"' >> ~/.zshrc && source ~/.zshrc
```

Then verify it's set:

```bash
echo $SUBSTACK_SID
```

If it prints nothing, troubleshoot before continuing — they may be using a different shell (check with `echo $SHELL`).

---

**Step 4: Look up their account details.** Run this to fetch their user ID and handle:

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

Note the USER_ID and HANDLE values for the next step.

---

**Step 5: Publication IDs.** Ask: "What's the subdomain of your Substack publication — the part before `.substack.com`?" For each subdomain they give you:

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

---

**Step 6: Create config.py.** Write this file with the values from steps 4 and 5:

```python
USER_ID = <user_id>
HANDLE = "<handle>"

OWN_PUBS = {
    "<subdomain>": <pub_id>,
    # add more publications here
}
```

---

**Step 7: Verify.** Run the integrity check:

```bash
python check.py
```

If any checks fail, diagnose and fix before continuing.

---

**Step 8: Start the app.**

```bash
python app.py
```

Tell the user to open http://localhost:5001 in their browser. Explain that this address is local to their computer — it's not a website anyone else can see.

---

**Step 9: First use.** Walk them through what they're looking at:

- **Replies tab** — replies to their Substack Notes and comments. Hit **Sync** to fetch their activity. The first sync builds the database and may take several minutes — this is normal.
- **Publication tabs** — comments on their own posts. Hit **Load posts** first to pull them in, then **Sync** for ongoing updates.
- **Liked toggle** — when on, items you've liked on Substack move to a collapsed "handled" section instead of staying in your queue.
- **Search** — filters across all tabs simultaneously by name, keyword, or phrase.

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
