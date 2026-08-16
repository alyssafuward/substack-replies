# Substack Replies — Product Requirements

Status key: ✅ Done | ⚠️ Partial or bug | ❌ Not built

---

## 1. Data Sync

### 1.1 Activity feed sync
**What:** Fetch replies and other activity from Substack's activity feed API, newest-first, and store in the DB.
**Status:** ✅
**Where:** `scraper.py` → `sync_activity_feed()`

### 1.2 Stop immediately on rate limit
**What:** On a 429 response, stop the sync and tell the user to try again in a few minutes. No retries, no wait loops.
**Status:** ✅
**Where:** `scraper.py` → `get()` raises `RATE_LIMITED` on first 429; `main()` catches it and prints message

### 1.3 Forward sync stops at last sync point
**What:** On each sync, only fetch activity newer than the last successful sync. Don't re-fetch everything every time.
**Status:** ✅
**Where:** `scraper.py` → `sync_activity_feed()` — stops when `item_ts <= last_synced_at`

### 1.4 Backfill fills in history missed by interrupted syncs
**What:** If a sync was rate-limited or stopped mid-run, the next sync should resume from where it left off and recover missed pages.
**Status:** ❌ Bug
**Where:** `scraper.py` → `main()` Step 3
**Problem:** The backfill cursor is reconstructed from `MIN(created_at)` in the DB, but the activity feed API paginates by `updated_at`. These are different fields. The backfill ends up at the end of the feed and returns nothing. Pages missed by interrupted syncs can't be recovered without starting fresh.
**Fix needed:** Persist the actual `after` cursor value (based on `updated_at`) to `sync_state` after each page commit, and resume from there.

### 1.5 Post comments sync
**What:** Fetch comments on your own publication posts and store them.
**Status:** ✅
**Where:** `scraper.py` → `load_posts_to_target()`, `refresh_post_comments()`

### 1.6 Only one sync runs at a time
**What:** Starting a sync while one is already running should show an error, not start a second.
**Status:** ✅
**Where:** `app.py` → `_sync_lock` / `_try_start_sync()`

### 1.7 User can stop a running sync
**What:** A Stop button terminates the sync subprocess.
**Status:** ✅
**Where:** `app.py` → `POST /sync/stop` kills `_sync_proc`

### 1.8 Streaming progress log
**What:** Sync output streams to the browser in real time, line by line.
**Status:** ✅
**Where:** `app.py` → SSE via `_stream()`, browser JS `EventSource`

### 1.9 Last sync log persists across page loads
**What:** The log from the most recent sync is saved and can be viewed after a reload.
**Status:** ✅
**Where:** `dashboard.py` render → localStorage in browser JS

---

## 2. Classification

Every activity item must be classified into exactly one bucket: **Responded**, **Liked only**, or **Unanswered**.

### 2.1 Responded = you replied or recheck confirmed a response
**What:** An item is responded if `is_responded=1` (set by recheck) OR a reply comment from you exists in the DB.
**Status:** ⚠️ Gap
**Where:** `dashboard.py` → `load_data()` (checks both); `dashboard.py` → `load_responded_data()` (checks `is_responded=1` only)
**Problem:** Items where a reply IS found in the DB (via comment search) are correctly excluded from the unanswered/liked queue, but they are NOT included in the responded section because `load_responded_data()` only queries `is_responded=1`. Those items are invisible — not in any section.
**Fix needed:** When `load_data()` finds a reply in the DB, it should also set `is_responded=1` so `load_responded_data()` picks it up. Or `load_responded_data()` should also query by reply-in-DB.

### 2.2 Liked only = you liked the reply but have not replied
**What:** Items where the comment has a reaction from you, but no reply from you.
**Status:** ⚠️ Bug (liked + replied case)
**Where:** `dashboard.py` → `load_data()` sets `liked = bool(raw.get("reaction"))`
**Problem:** If you liked a reply AND also replied, the item should be in Responded, not Liked only. But this is not always detected. See requirement 2.3.

### 2.3 Liked + replied → classified as Responded
**What:** If you both liked a reply and replied to it, it must show as Responded, not Liked only.
**Status:** ✅
**Where:** `scraper.py` → `sync_activity_feed()` inline check — runs for both `note_reply` and `comment_reply` when first stored and a reaction is present. `note_reply` uses the reader/replies API; `comment_reply` fetches the post thread via `fetch_post_comments()`.

### 2.4 Liked = acknowledged (intentional design decision)
**What:** Liking a reply means you saw it and acknowledged it. Liked-only items do not need a response and are excluded from the main unanswered queue. Recheck does not re-examine liked items.
**Status:** ✅ Intentional
**Where:** Documented in `CLAUDE.md` and `scraper.py` comments

### 2.5 post_reply type surfaced in dashboard
**What:** `post_reply` items from the activity feed (someone replied to a post, not a comment) should appear in the replies queue.
**Status:** ❌ Not built
**Where:** `REPLY_TYPES` in `scraper.py` does not include `post_reply`; `load_data()` queries only `note_reply` and `comment_reply`
**Note:** Unknown how many items this affects. Low priority until volume is understood.

---

## 3. Recheck

Recheck runs at the start of every sync. It re-examines items previously marked unresponded to see if you've since replied or liked them.

### 3.1 Recheck comment_reply items
**What:** For each unresponded `comment_reply`, fetch the post thread and check if you've since replied.
**Status:** ✅
**Where:** `scraper.py` → `recheck_unresponded()`

### 3.2 Recheck note_reply items
**What:** For each unresponded `note_reply`, fetch the reader API and check if you've since liked or replied.
**Status:** ✅
**Where:** `scraper.py` → `recheck_note_replies()`

### 3.3 Recheck does not re-examine liked items
**What:** Items with a reaction are skipped by recheck — they're already acknowledged.
**Status:** ✅ Intentional
**Note:** This is correct for liked-only items, but it means liked+replied items can't be caught by recheck. That case must be caught at sync time (requirement 2.3).

### 3.4 Rate limiting across recheck phases
**What:** A 3s pause between comment recheck and note recheck prevents back-to-back API bursts. Note recheck sleeps 2.5s per item.
**Status:** ✅
**Where:** `scraper.py` → `main()` `time.sleep(3)` between calls; `recheck_note_replies()` `time.sleep(2.5)`

---

## 4. Dashboard — Replies Tab

### 4.1 Unanswered queue, newest first, first 10 shown
**What:** Main list of replies needing a response. Sorted newest first. First 10 visible, rest collapsed.
**Status:** ✅
**Where:** `dashboard.py` → `render_html()`

### 4.2 Filter by commenter name or @handle
**What:** Text input filters all three sections simultaneously. Sections with matches auto-expand.
**Status:** ✅
**Where:** `dashboard.py` → `filterByName()` JS, `data-who` attribute on cards

### 4.3 Stats bar shows unanswered / liked / responded counts + last sync time
**What:** Header shows actionable counts for each bucket and when the last sync ran.
**Status:** ⚠️ Partial
**Where:** `dashboard.py` → `load_stats()` returns raw DB row counts (activity_items, comments, posts), not per-bucket counts
**Problem:** Stats bar shows total DB counts, not the classified unanswered/liked/responded counts the user actually cares about.
**Fix needed:** `load_stats()` should return counts derived from the same classification logic as `load_data()`.

### 4.4 Cards show commenter, body, post link, comment link, date
**Status:** ✅
**Where:** `dashboard.py` → `render_card()`

### 4.5 Liked only section (collapsed)
**Status:** ✅

### 4.6 Responded section (collapsed, no cap)
**Status:** ✅ (cap was removed)
**Where:** `dashboard.py` → `load_responded_data()`

---

## 5. Dashboard — Post Comments Tab

### 5.1 Per-publication tabs
**Status:** ✅

### 5.2 Load-to-target button
**What:** Fetch posts one by one until N unanswered comments are loaded.
**Status:** ✅
**Where:** `scraper.py` → `load_posts_to_target()`

### 5.3 Unanswered / liked split within each post
**Status:** ✅

### 5.4 Sync lock (no concurrent syncs)
**Status:** ✅

---

## 6. Insights Page (/insights)

### 6.1 Engagement type breakdown
**Status:** ✅
**Where:** `insights.py` → `load_all()`

### 6.2 Top commenters list
**Status:** ✅
**Where:** `insights.py` → `load_all()`

### 6.3 Commenter profile search
**What:** Search by name or @handle, see their comment history with responded/liked/unanswered badges.
**Status:** ✅ (but flagged for further work — not fully polished)
**Where:** `insights.py` → `search_commenter()`

### 6.4 Commenter search on home page
**What:** Same search available on the main Replies tab, filtering the existing card views in place.
**Status:** ❌ Not built
**Note:** Currently only on /insights. Discussed but deferred.

---

## 7. Tests

### 7.1 Unit tests for classification logic
**What:** Tests for `load_data()`, `load_responded_data()`, and the liked/responded/unanswered split using fixture data — so regressions are caught before they reach the app.
**Status:** ❌ Not built

---

## 8. Subscriber Tracking

### 8.1 Separate subscriber DB
**What:** Track the Substack subscriber list (email, plan, signup date, active/expiry status) in its own SQLite DB, kept apart from `replies.db` since comments and subscribers are different entities with no shared key (subscriber CSV exports have no display name).
**Status:** ✅
**Where:** `subscribers.py` → `subscribers.db` (gitignored, local only, same pattern as `replies.db`)

### 8.2 Import full CSV export
**What:** Import Substack's subscriber CSV export (Settings → Subscribers → export) — email, active_subscription, expiry, plan, email_disabled, created_at, first_payment_at.
**Status:** ✅
**Where:** `subscribers.py` → `import_csv()`; run as `python subscribers.py <path-to-csv>`

### 8.3 Top up from screenshots between exports
**What:** Add or update subscriber rows from data Claude reads off a screenshot of the Substack subscriber dashboard (email, plan tag, star/quality rating, signup date — no expiry or first_payment_at, since the dashboard view doesn't show those).
**Status:** ✅
**Where:** `subscribers.py` → `import_screenshot_rows()`

### 8.4 Merge, don't overwrite, on upsert
**What:** Upserting by (email, publication) only overwrites a field when the new value is non-empty and different, so a partial screenshot row never blanks out richer CSV fields (expiry, first_payment_at), and a later CSV re-import never erases a `quality_stars` value that only ever came from a screenshot.
**Status:** ✅
**Where:** `subscribers.py` → `upsert()`

### 8.5 Track multiple publications and dedupe across them
**What:** Alyssa runs three Substacks (alyssafuward, thehartstudio, createwithalyssa) with overlapping subscribers. Each row is keyed by (email, publication), so the same person subscribed to two publications gets two rows. `python subscribers.py --summary` prints per-publication counts, the deduped unique total across all publications, and pairwise/all-publication overlap counts.
**Status:** ✅
**Where:** `subscribers.py` → `dedupe_summary()`, `print_dedupe_summary()`; publication is inferred from the CSV filename (`email_list.<publication>.csv`)

---

## Open bugs summary

| ID | Description | Severity |
|----|-------------|----------|
| 1.4 | Backfill cursor uses wrong field (`created_at` vs `updated_at`) — missed pages can't be recovered | High |
| 2.1 | Items responded via DB reply search are invisible (not in responded section) | Medium |
| ~~2.3~~ | ~~`comment_reply` liked+replied not detected at sync time~~ | Fixed |
| 4.3 | Stats bar shows raw DB counts, not classified bucket counts | Low |
| 2.5 | `post_reply` type not shown in dashboard | Low |

## Not yet built

| ID | Description |
|----|-------------|
| 6.4 | Commenter search on home page |
| 7.1 | Unit tests |
