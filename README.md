# substack-replies

A personal tool that scrapes your Substack replies and surfaces them in a local HTML dashboard so you can track which ones need a response.

Built for writers who publish on multiple Substack publications and want a single inbox view across all of them.

---

## How it works

1. Authenticates with Substack using your session cookie
2. Fetches your activity feed (note replies, comment replies) and all comments on your own posts
3. Stores everything in a local SQLite database (`replies.db`)
4. Generates a self-contained HTML dashboard you open in your browser

> **Note on the API:** This tool uses Substack's internal API, which is unofficial and undocumented. It works as of the time of writing but could break if Substack changes their API. No data is sent anywhere — everything stays on your machine.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create your config file

Copy `config.example.py` to `config.py` and fill in your values:

```bash
cp config.example.py config.py
```

Then open `config.py` and set:

- **`USER_ID`** — your numeric Substack user ID
- **`HANDLE`** — your Substack handle (e.g. `janedoe`)
- **`OWN_PUBS`** — a dict of your publications: `{"yourhandle": pub_id, ...}`

**How to find your USER_ID and publication IDs:**

1. Open [substack.com](https://substack.com) and log in
2. Open DevTools (Cmd+Option+I on Mac) → **Network** tab
3. Reload the page and look for a request to `/api/v1/subscriber` or `/api/v1/activity-feed-web`
4. In the response JSON, your `user_id` and publication `id` values will be visible

> **Security note:** `config.py` is gitignored and never committed. It contains your user ID and publication IDs — these are public Substack identifiers, but there's no reason to expose them in a public repo.

### 3. Set your session cookie

You need your `substack.sid` session cookie to authenticate API requests.

**To get it:**
1. Open [substack.com](https://substack.com) logged in
2. Open DevTools → **Application** tab → **Cookies** → `https://substack.com`
3. Find the cookie named `substack.sid` and copy its value

**To store it:**
```bash
echo 'export SUBSTACK_SID="paste-your-value-here"' >> ~/.zshrc
source ~/.zshrc
```

> **Security note:** The cookie is a live session credential — anyone who has it can act as you on Substack. It's stored in `~/.zshrc` on disk, readable by anything running as your user. It is never written to this repo or committed to git. If you think it's been exposed, log out of Substack to invalidate it, then repeat the steps above with the new cookie value. **Never paste the cookie value into chat** (including to Claude) — conversation content is sent to Anthropic's servers.

---

## Usage

```bash
# Fetch latest replies and comments (run this periodically)
python scraper.py sync

# Generate the dashboard and open it in your browser
python dashboard.py

# Generate without auto-opening
python dashboard.py --no-open
```

The dashboard shows:
- Replies to your notes and comments that you haven't responded to yet
- Comments on your own posts that are waiting for a reply
- A "Liked / reviewed" section for items you've already engaged with
- A "Done" section to track what you've handled

---

## Files

```
substack-replies/
├── scraper.py          # fetches data from Substack API, stores in replies.db
├── dashboard.py        # generates the HTML dashboard from replies.db
├── config.example.py   # template — copy to config.py and fill in your values
├── config.py           # your personal config (gitignored, never committed)
├── replies.db          # local SQLite database (gitignored, never committed)
├── dashboard.html      # generated output (gitignored, regenerated each run)
├── check.py            # sanity checks — run after code changes to verify nothing is broken
├── requirements.txt    # Python dependencies (just: requests)
└── dev/
    └── explore.py      # API exploration reference — used to reverse-engineer
                        # the Substack API during development, not needed for normal use
```

---

## Security summary

| What | Where | Risk |
|------|-------|------|
| Session cookie (`SUBSTACK_SID`) | `~/.zshrc` | Live credential. Rotate by logging out of Substack if exposed. |
| User config (`config.py`) | Local only, gitignored | Contains public Substack IDs. Not sensitive, but kept off the repo. |
| Reply data (`replies.db`) | Local only, gitignored | Contains your readers' names and comment text. Never committed. |
| Generated dashboard (`dashboard.html`) | Local only, gitignored | Contains reply content. Never committed. |
| Substack API | Unofficial, undocumented | Could break without notice. No write operations — read-only. |
