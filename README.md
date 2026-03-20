# substack-replies

Substack's notification inbox is hard to work with — replies get buried, threads are hard to follow, and it's easy to miss comments that deserve a response.

This tool pulls all your replies and comments into a single local dashboard so you can see everything in one place, mark items done, and actually keep up.

Built for Substack writers who publish across multiple publications and want a proper inbox, not a notification feed.

> **Note:** This tool uses Substack's internal API, which is unofficial and undocumented. It works as of the time of writing but could break if Substack changes their API. Everything runs locally — no data is sent anywhere, no accounts, no servers.

---

## Getting started

See [SETUP.md](SETUP.md) for step-by-step instructions. The recommended way to set this up is using Claude Code — it will walk you through everything in plain language, no technical experience required.

---

## How it works

1. Connects to Substack on your behalf using a session cookie — a temporary key your browser already uses to keep you logged in
2. Fetches your recent replies, note responses, and comments on your own posts
3. Saves everything locally on your computer
4. Generates a dashboard you open in your browser to review and track what needs a response

---

## Running the tool

**If you're using Claude Code** (recommended), after you've completed setup: open Terminal, navigate to your Substack Replies folder, type `claude`, and say: *"sync my Substack replies and open the dashboard."* Claude handles the rest.

**If you're running it manually** (for developers): open Terminal, navigate to the repo folder, and run:

```bash
# Fetch latest replies and comments
python scraper.py sync

# Generate the dashboard and open it in your browser
python dashboard.py
```

The dashboard shows:
- Replies to your notes and comments that haven't been addressed yet
- Comments on your own posts that are waiting for a reply
- A "Show liked comments" toggle for items you've already engaged with
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
├── SETUP.md            # step-by-step setup guide
├── requirements.txt    # Python dependencies (just: requests)
└── dev/
    └── explore.py      # API exploration used during development, not needed for normal use
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
