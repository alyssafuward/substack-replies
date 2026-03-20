# Setting Up Substack Replies

This guide walks you through getting Substack Replies running on your computer. You don't need to be a developer — Claude Code will handle the technical parts for you.

---

## What you'll need

- A Mac or PC
- A Substack account
- About 10-15 minutes

---

## Step 1: Install Claude Code

Claude Code is an AI assistant that runs in your Terminal and can set up and run tools like this one for you.

Follow the official installation instructions at: **[claude.ai/code](https://claude.ai/code)**

---

## Step 2: Open Terminal and start Claude

**On Mac:** Press Cmd+Space, type "Terminal", hit Enter.

Type the following and press Enter:

```
claude
```

You're now talking to Claude. Everything from here you can do by just telling Claude what you want in plain language.

---

## Step 3: Tell Claude to set up Substack Replies

Paste this into the Claude conversation:

> I want to set up this Substack replies tool: https://github.com/alyssafuward/substack-replies
>
> Can you clone it, install anything that's needed, and walk me through the setup?

Claude will:
- Clone the repo to your computer
- Install Python and Git if you don't have them
- Walk you through getting your Substack session cookie
- Set up your personal config
- Run your first sync and open the dashboard

---

## Step 4: Get your Substack session cookie

At some point Claude will ask you to get your session cookie. This is how the tool authenticates with Substack on your behalf.

**Important:** Claude will tell you to run a command in Terminal — do that, don't paste the cookie value into the chat window. The cookie is a live credential and chat messages are sent to Anthropic's servers.

To get your cookie:
1. Open [substack.com](https://substack.com) in your browser and make sure you're logged in
2. Press **Cmd+Option+I** (Mac) to open Developer Tools
3. Click the **Application** tab
4. In the left sidebar, click **Cookies** → **https://substack.com**
5. Find the row named `substack.sid` and copy the value in the Value column

Then follow Claude's instructions for where to put it.

---

## Ongoing use

Once set up, whenever you want to check your replies:

1. Open Terminal
2. Type `claude` and press Enter
3. Say: *"sync my Substack replies and open the dashboard"*

Claude will fetch the latest replies and open your dashboard in the browser.

---

## Troubleshooting

If anything goes wrong, just tell Claude what happened. It can diagnose and fix most issues.

If your dashboard stops working after a while, your session cookie may have expired. You'll know because syncing will fail with an authentication error. Just get a fresh cookie from your browser (same steps as above) and tell Claude to update it.

---

## Privacy and security

- Your data never leaves your computer
- The session cookie is stored locally in your terminal config (`~/.zshrc`) — never in the repo or sent anywhere
- The replies database is stored locally and is never committed to git
- This tool only reads from Substack — it never posts, likes, or modifies anything on your behalf
