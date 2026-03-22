# substack-replies

Substack's notification inbox is hard to work with — replies get buried, threads are hard to follow, and it's easy to miss comments that deserve a response.

This tool pulls all your replies and comments into a single local dashboard so you can see everything in one place, mark items done, and actually keep up.

Built for Substack writers who publish across multiple publications and want a proper inbox, not a notification feed.

This is your project to own. You can take updates from this repo, modify it yourself with Claude's help, or take it in a completely different direction. Think of it less like software you install and more like a side project you happen to be running.

> **Note:** This tool uses Substack's internal API, which is unofficial and undocumented. It works as of the time of writing but could break if Substack changes their API. Everything runs locally — no data is sent anywhere, no accounts, no servers.

---

## Getting started

You'll need:
- [Claude Code](https://claude.ai/code) installed
- [Git](https://git-scm.com/downloads) installed — if you don't have it, Claude Code can help you get it set up

Clone the repo:

```bash
git clone https://github.com/alyssafuward/substack-replies.git
cd substack-replies
```

Then open Claude Code in that folder and say: **"set up this project."** Claude will handle the rest — installing dependencies, configuring your account, and getting you to the dashboard.

---

## What's under the hood

A few things worth knowing as the owner of this project:

- **Python** — the tool runs on Python. Claude will help you install it if you don't have it.
- **Local database** — your replies and comments are stored in a SQLite file (`replies.db`) on your machine. Nothing is sent to any server.
- **Unofficial Substack API** — this tool reads from Substack's internal API, which is undocumented and could break if Substack changes something. It only reads — it never posts, likes, or modifies anything on your behalf.
- **Session cookie** — to authenticate with Substack, the tool uses your browser session cookie, stored locally in `~/.zshrc`. Don't share it with anyone, and never paste it into chat — Claude knows not to ask for it that way.

---

## Ongoing use

After setup, open Claude Code in the project folder and say: *"sync my Substack replies and open the dashboard."* Claude handles the rest.

---

## Getting updates

When new versions of this project are available, Claude can pull them in for you:

```
git pull origin main
```

Or ask Claude: *"check for updates to substack-replies."*

---

## Security

| What | Where | Notes |
|------|-------|-------|
| Session cookie (`SUBSTACK_SID`) | `~/.zshrc` | Live credential. Rotate by logging out of Substack if exposed. |
| Your config | `config.py` (local, gitignored) | Your Substack user ID and publication IDs. Never committed. |
| Your data | `replies.db` (local, gitignored) | Your readers' names and comment text. Never committed. |

---

## Files

```
substack-replies/
├── app.py              # starts the local web server
├── scraper.py          # fetches data from Substack, stores in replies.db
├── dashboard.py        # builds the dashboard from replies.db
├── config.example.py   # template for config.py
├── config.py           # your personal config (gitignored)
├── replies.db          # your local data (gitignored)
├── check.py            # sanity checks after code changes
└── requirements.txt    # Python dependencies
```
