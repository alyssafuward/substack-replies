# substack-replies — Claude Instructions

## Before starting any work

1. Read `REQUIREMENTS.md` — living spec with requirement IDs and status
2. Check open GitHub issues (`gh issue list`) — this is the task tracker; don't duplicate task state anywhere else
3. Run `python check.py` before committing — 9-point integrity check

## How to run

```
python app.py
```

## Key files

| File | Purpose |
|------|---------|
| `scraper.py` | All sync / recheck / backfill logic, rate limiting |
| `dashboard.py` | HTML rendering for home / responded / liked pages |
| `app.py` | Flask routes and SSE streaming |
| `insights.py` | Insights page rendering |
| `check.py` | Pre-commit integrity check |
| `REQUIREMENTS.md` | Living product spec (committed) |
| `NOTES.md` | Local scratchpad — gitignored, don't commit |

## Design decisions — do not change without explicit instruction

**"Liked = acknowledged"**: A ❤ reaction on a note reply means Alyssa considered it handled, even without writing a text reply. This is intentional — it is not a bug.

**Rate limiting — stop immediately**: When Substack returns a 429, sync stops and tells the user to try again. Do not add retry loops, exponential backoff, or waiting. Alyssa explicitly wants the hard stop.

**SSE uses temp file, not pipe**: The subprocess writes output to a temp file; Flask tails it and streams to the browser. This replaced a pipe-based approach that froze when the browser disconnected (e.g., computer sleep). Do not revert to pipes.

## Substack API

- Note thread: `https://substack.com/api/v1/reader/comment/{id}`
- Thread replies: `https://substack.com/api/v1/reader/comment/{id}/replies`
- Activity feed paginates by `updated_at` (not `created_at`)
- Note URLs: `https://substack.com/@{handle}/note/c-{id}`

## Git workflow

Follow global rules: create a GitHub issue, create a feature branch tied to that issue, open a PR to merge to main. Never commit directly to main.
