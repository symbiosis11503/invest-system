"""Send web push notification to all subscribers.

Usage:
    python push_notify.py "標題" "內容" [url] [tag]

Or as module:
    from push_notify import send_push
    send_push("標題", "內容", url="/debate", tag="debate")
"""
import requests
import sys


def send_push(title, body="", url="/", tag="invest-notification"):
    """Send push notification via webapp API (localhost only)."""
    try:
        resp = requests.post("http://localhost:18900/api/push/send", json={
            "title": title,
            "body": body,
            "url": url,
            "tag": tag
        }, timeout=10)
        result = resp.json()
        print(f"Push: sent={result.get('sent',0)} failed={result.get('failed',0)}")
        return result
    except Exception as e:
        print(f"Push failed: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python push_notify.py <title> [body] [url] [tag]")
        sys.exit(1)
    title = sys.argv[1]
    body = sys.argv[2] if len(sys.argv) > 2 else ""
    url = sys.argv[3] if len(sys.argv) > 3 else "/"
    tag = sys.argv[4] if len(sys.argv) > 4 else "invest-notification"
    send_push(title, body, url, tag)
