# substack-replies

A personal tool for Substack writers who want one place to see what still needs a response — across notes, comments, and your own posts.

This is not a managed service. It runs locally on your computer, stores your data in a local database, and talks to Substack directly using your own session. Nothing is hosted anywhere.

> **Note:** This uses Substack's internal API, which is unofficial, undocumented, and intended for personal use only. It works as of writing but could break if Substack changes things. The API is rate-limited — if you hit the limit, the app will stop and ask you to try again in a few minutes.

---

## What you get

**Replies tab** — replies to your Substack Notes, and replies to comments you've left on other people's posts and Notes. Shows what still needs a response. Use **Sync** to pull in new activity. You can set how many new replies to fetch at a time — the app rechecks your existing unresponded items first, then pulls in the most recent new replies up to your limit, then fills in older history if there's still room.

**Publication tabs** — one tab per publication you own. Shows comments on your own posts. Use **Load posts** to pull in posts and their comments for the first time; use **Sync** to check for new activity — only posts where the comment count changed are re-fetched.

**Search** — filter by name, keyword, or phrase across all tabs simultaneously. Match counts appear in each tab label.

**Liked toggle** — if you ❤️ a reply on Substack, the app can treat that as "seen and acknowledged" and move it to a collapsed section on both the Replies and Publications tabs. Use the toggle below the search bar to turn this off — liked items will stay in the main queue until you respond or archive them.

**Archive** — dismiss a reply without responding to it. Useful for spam, drive-bys, or things you've read but don't want cluttering your queue. Available on the Replies tab only; Publications comments can't be archived yet.

**Co-authored & guest posts** — replies from posts you've written for other publications show up in a separate collapsed section in the Replies tab, since they need a different kind of attention.

**Responded** — once you've replied to something, it moves to a collapsed Responded section so you can focus on what's still open.

**Your data** — everything lives in a local SQLite database. No cloud sync, no sharing. Data persists across page refreshes.

---

## Requirements

**The one thing you need to install yourself:**

- **Claude Code** — this is how you'll interact with the app, run setup, and customize things later. [Download here.](https://claude.ai/code) Claude Code runs inside Terminal on your Mac.

**Everything else, Claude will help you set up:**

- **Python 3** — to run the app
- **GitHub account** — only needed if you want to customize the code and save your changes
- **The code itself** — Claude will help you get a copy onto your machine

---

## Getting started

**[Download the setup skill](https://raw.githubusercontent.com/alyssafuward/substack-replies/main/setup-skill/SKILL.md)** — right-click and Save As, or click Raw and use your browser's save option. Drop it in your Downloads folder. Then open Claude Code and say:

> "Install the setup skill from my Downloads folder"

Claude will walk you through everything: installing Python if needed, getting a copy of the code, setting up a GitHub account if you want one, getting your Substack credentials, configuring the app, and verifying it all works before you run it for the first time.

**A note on Terminal.** Claude Code runs inside Terminal. If you haven't used it before — on a Mac, press `Cmd+Space`, type "Terminal", and hit enter. One thing that trips people up: Terminal is keyboard-only. You can't click to reposition your cursor inside a command the way you would in a text editor. Use the arrow keys to move around and edit. Claude will give you exact commands to run, so mostly you'll just be pasting (`Cmd+V`) and hitting enter.

---

## Security

To fetch your data, the app uses your Substack session cookie — the same credential your browser uses when you're logged in. Claude will help you find it, copy it, and store it safely on your machine.

A few things worth knowing:

- The session cookie is a live credential. If you think it's been exposed, log out of Substack to invalidate it and run setup again with a fresh one.
- **Never paste your session cookie into chat** — including to Claude. Conversation content is sent to Anthropic's servers.

---

Questions? Find me on Substack: [alyssafuward.substack.com](https://alyssafuward.substack.com)
