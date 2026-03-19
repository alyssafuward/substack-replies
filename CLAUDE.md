# Substack Replies

A personal tool that scrapes Substack replies and displays them in a local HTML dashboard, so you can track which ones need a response.

## Setup (required before running anything)

**1. Create your config file**

Copy `config.example.py` to `config.py` and fill in your values. See the README for how to find each value.

**2. Set your session cookie**

You need your `substack.sid` session cookie. To get it:

1. Open [substack.com](https://substack.com) in your browser and make sure you're logged in
2. Open DevTools: **Cmd+Option+I** (Mac) → go to **Application** tab → **Cookies** → `https://substack.com`
3. Find the cookie named `substack.sid` and copy its value
4. Add it permanently to your shell profile so it's available in every terminal session (including when Claude runs commands):
   ```
   echo 'export SUBSTACK_SID="paste-your-value-here"' >> ~/.zshrc
   source ~/.zshrc
   ```

When the cookie expires (e.g. after logging out of Substack), find the `SUBSTACK_SID` line in `~/.zshrc` and replace the value, then run `source ~/.zshrc` again.

> **Never paste the cookie value into chat** (including to Claude). Both claude.ai and the Claude Code terminal send conversation content to Anthropic's servers, so the cookie would leave your machine. Always run commands directly in your terminal.

## Commands

```bash
python scraper.py sync        # fetch latest activity + comments
python dashboard.py           # generate dashboard.html and open it
python check.py               # run sanity checks after any code changes
```

## Configuration

- User config (USER_ID, HANDLE, OWN_PUBS) lives in `config.py` — gitignored, never committed
- Data stored in `replies.db` (local SQLite, gitignored)

## How it works

1. Hits Substack's internal API (unofficial, no public docs) authenticated via session cookie
2. Fetches activity feed (note replies, comment replies) + comments on your own posts
3. Stores everything in a local SQLite database
4. `dashboard.py` generates a self-contained HTML file you open in your browser

## When starting a new session

`SUBSTACK_SID` should already be set via `~/.zshrc`. If it's missing or expired:
1. Get the new `substack.sid` cookie from browser DevTools (see Setup above)
2. Update the value in `~/.zshrc` and run `source ~/.zshrc` — **do not ask the user to paste the value into chat**
3. Then run whichever command they need
