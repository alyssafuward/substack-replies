# Setting Up Substack Replies

Substack Replies is a local tool that pulls all your Substack replies and comments into a single dashboard so you can track which ones need a response. This guide walks you through getting it running on your computer. You don't need to be a developer — Claude Code will handle the technical parts for you.

---

## What you'll need

- A Mac or PC
- A Substack account
- About 10-15 minutes

---

## Step 1: Install Claude Code

Claude Code is an AI assistant that runs in your Terminal. It will set up and run this tool for you — you just tell it what you want in plain language.

Follow the official installation instructions at: **[claude.ai/code](https://claude.ai/code)**

---

## Step 2: Open Terminal and start Claude Code

Terminal is a text-based interface that lets you interact directly with your computer by running commands. Commands in Terminal can make real changes to your computer — installing software, creating files, and so on.

Claude Code runs inside Terminal and issues these commands on your behalf. Before running anything, it should show you what it's about to do and ask for your permission.

> **Safety tips:**
> - If you aren't a developer, tell Claude at the start: *"I'm not a developer — please explain what you're doing and ask before running anything"*
> - If Claude asks to do something you don't understand or that seems unrelated to setting up this tool, say no and ask it to explain first

**To open Terminal on a Mac:**
1. Press **Cmd+Space** to open Spotlight search
2. Type "Terminal" and press Enter
3. A window will open with a text prompt — this is Terminal

Then type the following and press Enter:

```
claude
```

You're now talking to Claude. Everything from here you can do in plain language.

---

## Step 3: Tell Claude to set up Substack Replies

Paste this into the Claude conversation:

> I want to set up this Substack replies tool: https://github.com/alyssafuward/substack-replies
>
> Can you clone it, install anything that's needed, and walk me through the setup?

Claude will:
- Download the tool to your computer
- Install anything that's missing
- Walk you through getting your Substack session cookie
- Set up your personal Substack config (a small file that tells the tool your Substack handle and publications)
- Run your first sync and open the dashboard

---

## Step 4: Get your Substack session cookie

When Claude asks for your session cookie, this is how the tool authenticates with Substack on your behalf.

1. Open [substack.com](https://substack.com) logged in
2. Press **Cmd+Option+I** → **Application** tab → **Cookies** → **https://substack.com**
3. Find `substack.sid` and copy the value

**Important:** Claude will give you a command to run in Terminal — run that, don't paste the cookie value into the chat. The cookie is a live credential and chat messages are sent to Anthropic's servers.

---

## Ongoing use

Once set up, whenever you want to check your replies:

1. Open Terminal
2. Type `claude` and press Enter
3. Say: *"sync my Substack replies and open the dashboard"*

---

## Troubleshooting

If anything goes wrong, just tell Claude what happened — it can diagnose and fix most issues.

If your dashboard stops working after a while, your session cookie may have expired. Get a fresh one from your browser using the same steps above and tell Claude to update it.

---

## Privacy

- Your data never leaves your computer
- The session cookie is stored locally — never in the repo or sent anywhere
- This tool only reads from Substack — it never posts, likes, or modifies anything on your behalf
