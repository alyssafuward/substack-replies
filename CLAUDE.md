# Substack Replies

A personal tool that scrapes Substack replies and displays them in a local HTML report, so you can track which ones need a response.

## Setup (required before running anything)

You need your `substack.sid` session cookie. To get it:

1. Open [substack.com](https://substack.com) in your browser and make sure you're logged in
2. Open DevTools: **Cmd+Option+I** (Mac) → go to **Application** tab → **Cookies** → `https://substack.com`
3. Find the cookie named `substack.sid` and copy its value
4. Add it permanently to your shell profile so it's available in every terminal session (including when Claude runs commands):
   ```
   echo 'export SUBSTACK_SID="paste-your-value-here"' >> ~/.zshrc
   source ~/.zshrc
   ```

This writes the cookie to `~/.zshrc` on disk — it stays local to your machine and is never committed to git. When the cookie expires (e.g. after logging out of Substack), find the `SUBSTACK_SID` line in `~/.zshrc` and replace the value, then run `source ~/.zshrc` again.

> **Never paste the cookie value into chat** (including to Claude). Both claude.ai and the Claude Code terminal send conversation content to Anthropic's servers, so the cookie would leave your machine. Always run commands directly in your terminal.

## Commands

```bash
python scraper.py sync        # fetch latest activity + comments
python report.py              # generate report.html and open it
```

## Configuration

- `USER_ID = 118913109` (alyssafuward)
- Publications: `alyssafuward` and `createwithalyssa`
- Data stored in `replies.db` (local SQLite, not committed to git)

## How it works

1. Hits Substack's internal API (unofficial, no public docs) authenticated via session cookie
2. Fetches activity feed (note replies, comment replies) + comments on your own posts
3. Stores everything in a local SQLite database
4. `report.py` generates a self-contained HTML file you open in your browser

## When starting a new session

`SUBSTACK_SID` should already be set via `~/.zshrc`. If it's missing or expired:
1. Get the new `substack.sid` cookie from browser DevTools (see Setup above)
2. Update the value in `~/.zshrc` and run `source ~/.zshrc` — **do not ask the user to paste the value into chat**
3. Then run whichever command they need
