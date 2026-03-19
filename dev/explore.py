#!/usr/bin/env python3
"""
Substack API Explorer — dev/reference tool used to reverse-engineer the API shape.
Not needed for normal use. Run from the repo root after setting up config.py.

Usage:
  export SUBSTACK_SID="your-cookie-value"
  python dev/explore.py
"""

import os
import sys
import json
import requests
from pathlib import Path

# Allow imports from repo root (for config.py)
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from config import USER_ID, HANDLE, OWN_PUBS
except ImportError:
    print("Error: config.py not found. Copy config.example.py to config.py and fill in your values.")
    sys.exit(1)

BASE_URL = "https://substack.com"

# Pick the first pub ID from your config as the default for exploration
PUB_ID = next(iter(OWN_PUBS.values()), None)

# Replace with a real post ID from your publication to test post-level endpoints
POST_ID = None  # e.g. a post ID from your publication


def get_headers():
    from urllib.parse import unquote
    cookie = os.environ.get("SUBSTACK_SID")
    if not cookie:
        print("ERROR: Set SUBSTACK_SID environment variable to your substack.sid cookie value.")
        exit(1)
    # URL-decode the cookie value (browser stores it encoded)
    cookie_decoded = unquote(cookie)
    return {
        "Cookie": f"substack.sid={cookie_decoded}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://substack.com/",
    }

def probe(label, url, save_as=None):
    print(f"\n{'='*60}")
    print(f"ENDPOINT: {label}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    try:
        resp = requests.get(url, headers=get_headers(), timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2)[:4000])
            if len(json.dumps(data)) > 4000:
                print("... (truncated)")
            if save_as:
                with open(save_as, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"\n(Full response saved to {save_as})")
            return data
        else:
            print(resp.text[:500])
    except Exception as e:
        print(f"Error: {e}")
    return None

def probe_raw(label, url):
    """Print raw response text (not JSON parsed)."""
    print(f"\n{'='*60}")
    print(f"ENDPOINT: {label}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    try:
        resp = requests.get(url, headers=get_headers(), timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")
        print(f"Body (raw): {repr(resp.text[:500])}")
    except Exception as e:
        print(f"Error: {e}")

def main():
    print(f"Probing Substack API for handle: {HANDLE}\n")

    # Deep-inspect the two 200-but-empty endpoints
    for url in [
        "https://reader.substack.com/api/v1/comment_activity",
        "https://reader.substack.com/api/v1/notification_list",
    ]:
        print(f"\n{'='*60}")
        print(f"DEEP INSPECT: {url}")
        resp = requests.get(url, headers=get_headers(), timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Headers: {dict(resp.headers)}")
        print(f"Body length: {len(resp.text)}")
        print(f"Body repr: {repr(resp.text[:200])}")

    # Try with no query params (maybe limit param breaks it)
    probe("Comment activity (no params)", "https://reader.substack.com/api/v1/comment_activity", save_as="comment_activity.json")
    probe("Notification list (no params)", "https://reader.substack.com/api/v1/notification_list", save_as="notification_list.json")

    # Try with connect.sid (alternative session cookie name)
    print("\n\n--- Trying connect.sid cookie name ---")
    from urllib.parse import unquote
    cookie_val = unquote(os.environ.get("SUBSTACK_SID", ""))
    alt_headers = {**get_headers(), "Cookie": f"connect.sid={cookie_val}"}
    resp = requests.get("https://substack.com/api/v1/subscriber", headers=alt_headers, timeout=10)
    print(f"connect.sid auth check: {resp.status_code} {resp.text[:100]}")

if __name__ == "__main__":
    main()
