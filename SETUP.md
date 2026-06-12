# Setting Up Substack Replies

Substack Replies is a local tool that pulls all your Substack replies and comments into a single dashboard so you can track which ones need a response. This guide walks you through getting it running on your computer. You don't need to be a developer — Claude Code will handle the technical parts for you.

---

## What you'll need

- A Mac or PC
- A Substack account
- About 10–15 minutes

---

## Step 1: Install Claude Code

Claude Code is an AI assistant that runs in your Terminal. It will set up and run this tool for you — you just tell it what you want in plain language.

Follow the official installation instructions at: **[claude.ai/code](https://claude.ai/code)**

---

## Step 2: Open Terminal and start Claude Code

Terminal is a text-based interface that lets you run commands on your computer. Claude Code runs inside Terminal and issues commands on your behalf. Before running anything, it will show you what it's about to do and ask for your permission.

**To open Terminal on a Mac:**
1. Press **Cmd+Space** to open Spotlight
2. Type "Terminal" and press Enter

Then type the following and press Enter:

```
claude
```

> **If you're not a developer:** tell Claude at the start: *"I'm not a developer — please explain what you're doing and ask before running anything."* If Claude asks to do something you don't understand or that seems unrelated to setting up this tool, say no and ask it to explain first.

---

## Step 3: Tell Claude to set up Substack Replies

Paste this into the Claude conversation:

> I want to set up this Substack replies tool: https://github.com/alyssafuward/substack-replies — can you clone it, install what's needed, and walk me through the setup?

Claude will ask whether you want to just try the app as-is, or create your own copy on GitHub so you can customize it later. Either way, it will handle the download, dependencies, and configuration for you.

---

## Step 4: Get your Substack session cookie

At some point Claude will ask for your Substack session cookie. This is the credential the app uses to fetch your data from Substack on your behalf.

**Treat your session cookie like a password.** Do not paste it into the Claude chat — Claude will tell you how to store it safely on your machine instead.

To find your cookie:
1. Open [substack.com](https://substack.com) in your browser, logged in
2. Open Developer Tools: **Cmd+Option+I** on Mac, **F12** on Windows
3. Click the **Application** tab (Chrome) or **Storage** tab (Firefox)
4. In the left sidebar: **Cookies** → **https://substack.com**
5. Find the row named `substack.sid` and copy its value

Claude will give you a command to store it securely — paste the command into Terminal, not the cookie value into chat.

Once the cookie is set, Claude will run your first sync and open the dashboard. Building the database for the first time can take several minutes — this is normal. Subsequent syncs are much faster.

---

## Questions?

Find me on Substack: [alyssafuward.substack.com](https://alyssafuward.substack.com)
