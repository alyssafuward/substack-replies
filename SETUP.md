# Setting Up Substack Replies

## What you'll need

- A Mac or PC
- A Substack account
- Claude Code installed — [claude.ai/code](https://claude.ai/code)

---

## Steps

### 1. Open Terminal and start Claude Code

**On Mac:** Press Cmd+Space, type "Terminal", hit Enter. Then type:

```
claude
```

### 2. Tell Claude to set up Substack Replies

Paste this into the Claude conversation:

> I want to set up this Substack replies tool: https://github.com/alyssafuward/substack-replies
>
> Can you clone it, install anything that's needed, and walk me through the setup?

Claude will handle the rest — cloning the repo, installing dependencies, setting up your Substack config, and running your first sync.

### 3. Get your Substack session cookie

When Claude asks for your session cookie:

1. Open [substack.com](https://substack.com) logged in
2. Press **Cmd+Option+I** → **Application** tab → **Cookies** → **https://substack.com**
3. Find `substack.sid` and copy the value

Follow Claude's instructions for where to put it. **Do not paste the cookie value into the chat** — run the command Claude gives you directly in Terminal instead.

---

## Ongoing use

Open Terminal, type `claude`, then say: *"sync my Substack replies and open the dashboard."*

---

## Privacy

- Your data stays on your computer — nothing is sent to any server
- The tool only reads from Substack, it never posts or modifies anything on your behalf
- If your dashboard stops working, your session cookie may have expired — get a fresh one from your browser using the same steps above
