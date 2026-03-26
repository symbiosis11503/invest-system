"""
Telegram Userbot 群組監聽模組

首次使用：
  1. 在 ~/.config/ai-hub/shared/.env 加入 TG_API_ID 和 TG_API_HASH
  2. python tg_monitor.py --login   （需要手機驗證碼，互動式輸入）
  3. python tg_monitor.py --groups  （列出所有已加入群組）
  4. python tg_monitor.py --listen GROUP_ID1,GROUP_ID2  （開始監聽）
"""

import argparse
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

from config import load_env, DB_PATH, BASE_DIR

# ── 環境變數 ──────────────────────────────────────────────
load_env()

import os

TG_API_ID = os.environ.get("TG_API_ID")
TG_API_HASH = os.environ.get("TG_API_HASH")
SESSION_PATH = str(BASE_DIR / "tg_session")

# ── SQLite ────────────────────────────────────────────────

def init_db():
    """建立 tg_messages 表（如不存在）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL,
            group_name  TEXT,
            sender_id   INTEGER,
            sender_name TEXT,
            message_text TEXT,
            ts          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tg_messages_group_ts
        ON tg_messages (group_id, ts)
    """)
    conn.commit()
    conn.close()


def save_message(group_id, group_name, sender_id, sender_name, message_text, ts):
    """將訊息存入 SQLite"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO tg_messages
           (group_id, group_name, sender_id, sender_name, message_text, ts)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (group_id, group_name, sender_id, sender_name, message_text, ts),
    )
    conn.commit()
    conn.close()


# ── AI 分析（預留介面）────────────────────────────────────

def analyze_message(text: str, group_name: str = '', msg_id: int = 0) -> dict | None:
    """
    即時 AI 分析 TG 訊息。
    財經相關群組的訊息自動導入 news_intelligence 並分析。
    """
    # 只分析有意義的訊息（>20字，來自財經相關群組）
    finance_keywords = ['財經', '投資', '郭哲榮', '慢报', '捕手']
    is_finance = any(k in group_name for k in finance_keywords)

    if not is_finance or len(text) < 20:
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        url = f"tg://{msg_id}"
        exists = conn.execute("SELECT 1 FROM news_intelligence WHERE url=?", (url,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT OR IGNORE INTO news_intelligence (title, summary, url, source, published_at) VALUES (?,?,?,?,?)",
                (text[:100], text, url, f"telegram:{group_name}",
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
        conn.close()
    except Exception as e:
        logging.debug("tg_monitor save_message fail: %s", e)
        pass

    return None


# ── Telegram Client ───────────────────────────────────────

def get_client() -> TelegramClient:
    """建立 Telegram client，api_id/hash 從環境變數讀取"""
    if not TG_API_ID or not TG_API_HASH:
        raise RuntimeError(
            "缺少 TG_API_ID 或 TG_API_HASH，請在 ~/.config/ai-hub/shared/.env 設定"
        )
    return TelegramClient(SESSION_PATH, int(TG_API_ID), TG_API_HASH)


# ── 指令：登入 ────────────────────────────────────────────

async def cmd_login():
    """互動式登入，首次需要手機驗證碼"""
    client = get_client()
    await client.start()
    me = await client.get_me()
    print(f"登入成功: {me.first_name} ({me.phone})")
    await client.disconnect()


# ── 指令：列出群組 ────────────────────────────────────────

async def cmd_groups():
    """列出所有已加入的群組/頻道"""
    client = get_client()
    await client.start()

    print(f"{'ID':<16} {'類型':<6} 名稱")
    print("-" * 60)

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            kind = "頻道" if getattr(entity, "broadcast", False) else "群組"
            print(f"{dialog.id:<16} {kind:<6} {dialog.name}")

    await client.disconnect()


# ── 指令：監聽 ────────────────────────────────────────────

async def cmd_listen(target: str):
    """
    監聽指定群組的新訊息並存入 SQLite。
    target: 'all' 或逗號分隔的 group_id 列表
    """
    init_db()
    client = get_client()
    await client.start()

    # 解析目標群組
    listen_all = target.strip().lower() == "all"
    target_ids: set[int] = set()

    if not listen_all:
        for gid in target.split(","):
            gid = gid.strip()
            if gid.lstrip("-").isdigit():
                target_ids.add(int(gid))
            else:
                print(f"忽略無效 ID: {gid}")

    # 建立 group_id → name 對照表
    group_names: dict[int, str] = {}
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            group_names[dialog.id] = dialog.name

    # 顯示監聽清單
    if listen_all:
        print(f"監聽所有群組 ({len(group_names)} 個)")
    else:
        for gid in target_ids:
            name = group_names.get(gid, "未知")
            print(f"監聽: {gid} ({name})")

    print("開始監聽... Ctrl+C 停止\n")

    @client.on(events.NewMessage)
    async def handler(event):
        chat = await event.get_chat()
        chat_id = event.chat_id

        # 判斷訊息類型
        is_group = isinstance(chat, (Channel, Chat))
        is_private = isinstance(chat, User)

        if is_group:
            if not listen_all and chat_id not in target_ids:
                return
        elif is_private:
            pass  # 個人訊息全部收
        else:
            return

        # 取得發送者
        sender = await event.get_sender()
        sender_id = sender.id if sender else None
        if isinstance(sender, User):
            sender_name = " ".join(
                filter(None, [sender.first_name, sender.last_name])
            )
        else:
            sender_name = getattr(sender, "title", None) or str(sender_id)

        if is_private:
            chat_name = f"私訊:{sender_name}"
        else:
            chat_name = group_names.get(chat_id) or getattr(chat, "title", str(chat_id))
        text = event.raw_text or ""
        ts = datetime.now(timezone.utc).isoformat()

        # 存入 SQLite
        save_message(chat_id, chat_name, sender_id, sender_name, text, ts)

        # 即時分析（財經群組自動導入 intelligence）
        analyze_message(text, chat_name, event.id)

        # 簡易 log
        short = text[:60].replace("\n", " ")
        print(f"[{chat_name}] {sender_name}: {short}")

    await client.run_until_disconnected()


# ── CLI 入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Telegram 群組監聽模組")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--login", action="store_true", help="首次登入（需驗證碼）")
    group.add_argument("--groups", action="store_true", help="列出已加入群組")
    group.add_argument("--listen", type=str, metavar="IDS",
                       help="監聽群組，'all' 或逗號分隔 ID")

    args = parser.parse_args()

    if args.login:
        asyncio.run(cmd_login())
    elif args.groups:
        asyncio.run(cmd_groups())
    elif args.listen:
        asyncio.run(cmd_listen(args.listen))


if __name__ == "__main__":
    main()
