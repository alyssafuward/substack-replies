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

If `config.py` doesn't exist, the user needs to set it up. Once `SUBSTACK_SID` is set, Claude can look up all the values automatically — no manual digging needed.

Ask the user for their Substack handle and any publication subdomains they own, then run:

```python
import requests, os, json
from urllib.parse import unquote

sid = os.environ.get("SUBSTACK_SID", "")
headers = {
    "Cookie": f"substack.sid={unquote(sid)}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

# Get user ID
resp = requests.get("https://substack.com/api/v1/subscriber", headers=headers)
data = resp.json()
user_id = data.get("id") or data.get("user_id")
handle = data.get("handle", "")
print(f"USER_ID: {user_id}")
print(f"HANDLE: {handle}")
```

Then for each publication subdomain the user provides, fetch its ID:

```python
subdomain = "their-subdomain"  # replace with actual
resp = requests.get(f"https://{subdomain}.substack.com/api/v1/publication", headers=headers)
pub_data = resp.json()
pub_id = pub_data.get("id")
print(f"{subdomain}: {pub_id}")
```

Use the results to create `config.py`:

```python
USER_ID = <user_id>
HANDLE = "<handle>"

OWN_PUBS = {
    "<subdomain>": <pub_id>,
    # add more publications here
}
```

Then run `python check.py` to verify everything is working.

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
