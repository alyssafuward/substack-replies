# substack-replies

Substack's notification inbox is hard to work with — replies get buried, threads are hard to follow, and it's easy to miss comments that deserve a response.

This tool pulls all your replies and comments into a single local dashboard so you can see everything in one place, mark items done, and actually keep up.

Built for Substack writers who publish across multiple publications and want a proper inbox, not a notification feed.

> **Note:** This tool uses Substack's internal API, which is unofficial and undocumented. It works as of the time of writing but could break if Substack changes their API. Everything runs locally — no data is sent anywhere, no accounts, no servers.

---

## The easiest way to get started

**Use Claude Code.** Clone the repo, open it in Claude Code, and just say what you want — Claude will walk you through setup, find your account details automatically, and get you to a working dashboard without you having to touch a config file.

```bash
git clone https://github.com/alyssafuward/substack-replies.git
cd substack-replies
```

Then open the folder in Claude Code and say: *"help me set up Substack replies."*

---

## How it works

1. Authenticates with Substack using your session cookie
2. Fetches your activity feed (note replies, comment replies) and all comments on your own posts
3. Stores everything in a local SQLite database (`replies.db`)
4. Generates a self-contained HTML dashboard you open in your browser

---

## Manual setup (without Claude Code)

### 1. Clone the repo (if you haven't already)

```bash
git clone https://github.com/alyssafuward/substack-replies.git
cd substack-replies
pip install -r requirements.txt
```

### 2. Set your session cookie

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

> **Security note:** The cookie is a live session credential — anyone who has it can act as you on Substack. It's stored in `~/.zshrc` on disk, readable by anything running as your user. It is never written to this repo or committed to git. If you think it's been exposed, log out of Substack to invalidate it and repeat the steps above with the new value. **Never paste the cookie value into chat** (including to Claude) — conversation content is sent to Anthropic's servers.

### 3. Create your config file

Copy `config.example.py` to `config.py`:

```bash
cp config.example.py config.py
```

`config.py` needs three values: your numeric user ID, your handle, and a dict of your publication subdomains and their IDs.

**The easiest way to fill this in:** open Claude Code in this directory and say *"help me set up my config."* Claude can look up your account details automatically using your session cookie — no manual digging required.

**To find the values yourself** (if not using Claude):
1. Open [substack.com](https://substack.com) and log in
2. Open DevTools → **Network** tab → reload the page
3. Look for a request to `/api/v1/subscriber` — the response JSON contains your `user_id`
4. For publication IDs, look for requests to `/api/v1/posts` — the publication `id` is in the response

> **Security note:** `config.py` is gitignored and never committed. It contains your user ID and publication IDs — these are public Substack identifiers, but there's no reason to expose them in a public repo.

---

## Usage

```bash
# Fetch latest replies and comments (run this periodically)
python scraper.py sync

# Generate the dashboard and open it in your browser
python dashboard.py
```

The dashboard shows:
- Replies to your notes and comments that haven't been addressed yet
- Comments on your own posts that are waiting for a reply
- A "Show liked comments" toggle for items you've already engaged with
- A "Done" section to track what you've handled this session

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
