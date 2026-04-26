import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from db import DB_PATH

MEM_ROOT = Path("memories")
SEED_FILE = MEM_ROOT / "seed" / "seed.json"
WORKING_FILE = MEM_ROOT / "working" / "buffer.json"


def _ensure_dirs():
    (MEM_ROOT / "seed").mkdir(parents=True, exist_ok=True)
    (MEM_ROOT / "exports").mkdir(parents=True, exist_ok=True)
    (MEM_ROOT / "pinned").mkdir(parents=True, exist_ok=True)


def _clean_text(text: str | None) -> str:
    return (text or "").strip()


def _parse_message_payload(content: str) -> dict:
    raw = _clean_text(content)
    if not raw:
        return {
            "text": "",
            "image_data_url": None,
            "display_content": "",
        }

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "text": raw,
            "image_data_url": None,
            "display_content": raw,
        }

    if isinstance(data, dict):
        text = _clean_text(data.get("text"))
        image_data_url = data.get("image_data_url") or None
        if text and image_data_url:
            display_content = f"{text}\n[image attached]"
        elif text:
            display_content = text
        elif image_data_url:
            display_content = "[image attached]"
        else:
            display_content = ""
        return {
            "text": text,
            "image_data_url": image_data_url,
            "display_content": display_content,
        }

    return {
        "text": raw,
        "image_data_url": None,
        "display_content": raw,
    }


def _maybe_parse_message_content(content: str) -> str:
    return _parse_message_payload(content)["display_content"]


def save_message(
    conversation_id: str,
    role: str,
    content: str,
    model_used: str | None = None,
    created_at_local: str | None = None,
):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO messages (conversation_id, role, content, model_used, created_at_local)
        VALUES (?, ?, ?, ?, ?)
        """,
        (conversation_id, role, content, model_used, created_at_local),
    )
    con.commit()
    con.close()



def load_recent_messages(conversation_id: str, limit: int = 48):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content, model_used, created_at_local, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()

    rows = list(reversed(rows))
    items = []
    for (role, content, model_used, created_at_local, created_at) in rows:
        parsed = _parse_message_payload(content)
        items.append(
            {
                "role": role,
                "content": parsed["display_content"],
                "image_data_url": parsed["image_data_url"],
                "model_used": model_used,
                "created_at_local": created_at_local or created_at,
            }
        )
    return items



def load_all_messages(conversation_id: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conversation_id,),
    )
    rows = cur.fetchall()
    con.close()
    return [{"role": role, "content": _maybe_parse_message_content(content)} for (role, content) in rows]



def count_messages(conversation_id: str) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    )
    row = cur.fetchone()
    con.close()
    return int(row[0] or 0)



def add_pinned_memory(conversation_id: str, content: str):
    content = _clean_text(content)
    if not content:
        return
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO pinned_memories (conversation_id, content) VALUES (?, ?)",
        (conversation_id, content),
    )
    con.commit()
    con.close()



def list_pinned_memories(conversation_id: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT content FROM pinned_memories
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conversation_id,),
    )
    rows = cur.fetchall()
    con.close()
    return [r[0] for r in rows]



def add_global_memory(content: str):
    content = _clean_text(content)
    if not content:
        return
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO global_memories (content) VALUES (?)",
        (content,),
    )
    con.commit()
    con.close()



def list_global_memories():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT content FROM global_memories
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    con.close()
    return [r[0] for r in rows]



def save_conversation_summary(
    conversation_id: str,
    summary_text: str,
    source_message_count: int | None = None,
) -> int | None:
    summary_text = _clean_text(summary_text)
    if not summary_text:
        return None

    created_at_local = datetime.now().strftime("%Y-%m-%d %H:%M")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "DELETE FROM conversation_summaries WHERE conversation_id = ?",
        (conversation_id,),
    )
    cur.execute(
        """
        INSERT INTO conversation_summaries (conversation_id, summary_text, source_message_count, created_at_local)
        VALUES (?, ?, ?, ?)
        """,
        (conversation_id, summary_text, int(source_message_count or 0), created_at_local),
    )
    summary_id = cur.lastrowid
    con.commit()
    con.close()
    return summary_id



def list_conversation_summaries(limit: int = 5, exclude_conversation_id: str | None = None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    if exclude_conversation_id:
        cur.execute(
            """
            SELECT id, conversation_id, summary_text, source_message_count, created_at, created_at_local
            FROM conversation_summaries
            WHERE conversation_id != ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (exclude_conversation_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT id, conversation_id, summary_text, source_message_count, created_at, created_at_local
            FROM conversation_summaries
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )

    rows = cur.fetchall()
    con.close()
    return [
        {
            "id": row[0],
            "conversation_id": row[1],
            "summary_text": row[2],
            "source_message_count": row[3],
            "created_at": row[4],
            "created_at_local": row[5] or row[4],
        }
        for row in rows
    ]



def get_conversation_summary(conversation_id: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, conversation_id, summary_text, source_message_count, created_at, created_at_local
        FROM conversation_summaries
        WHERE conversation_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 1
        """,
        (conversation_id,),
    )
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    return {
        "id": row[0],
        "conversation_id": row[1],
        "summary_text": row[2],
        "source_message_count": row[3],
        "created_at": row[4],
        "created_at_local": row[5] or row[4],
    }



def delete_conversation_summary(summary_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM conversation_summaries WHERE id = ?", (summary_id,))
    con.commit()
    con.close()



def recent_summary_texts(limit: int = 5, exclude_conversation_id: str | None = None) -> list[str]:
    items = list_conversation_summaries(
        limit=limit,
        exclude_conversation_id=exclude_conversation_id,
    )
    return [item["summary_text"] for item in items if _clean_text(item["summary_text"])]



def load_seed() -> dict | None:
    _ensure_dirs()
    if not SEED_FILE.exists():
        return None

    try:
        raw = SEED_FILE.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        raw = SEED_FILE.read_text(encoding="cp1251").strip()
        SEED_FILE.write_text(raw, encoding="utf-8")

    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None



def save_seed(seed: dict):
    _ensure_dirs()
    SEED_FILE.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")



def seed_summary_text() -> str | None:
    seed = load_seed()
    if not seed:
        return None
    return seed.get("summary") or None



def load_working_background(max_items: int = 12) -> str | None:
    _ensure_dirs()
    if not WORKING_FILE.exists():
        return None
    try:
        raw = WORKING_FILE.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = WORKING_FILE.read_text(encoding="cp1251")
        WORKING_FILE.write_text(raw, encoding="utf-8")

    data = json.loads(raw)
    if max_items <= 0:
        return None

    items = data.get("items", [])[-max_items:]
    if not items:
        return None

    lines = []
    for item in items:
        who = "User" if item.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {item.get('content', '')}".strip())
    return "\n".join(lines).strip()



def append_working(role: str, content: str, max_keep: int = 24):
    _ensure_dirs()
    data = {"items": []}
    if WORKING_FILE.exists():
        data = json.loads(WORKING_FILE.read_text(encoding="utf-8"))
    items = data.get("items", [])
    items.append({"role": role, "content": content})
    data["items"] = items[-max_keep:]
    WORKING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")



def export_conversation_to_file(conversation_id: str) -> dict:
    _ensure_dirs()

    messages = load_all_messages(conversation_id)
    pinned = list_pinned_memories(conversation_id)
    summary = get_conversation_summary(conversation_id)

    payload = {
        "schema": "gpt4o-local.conversation.v1",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "conversation_id": conversation_id,
        "pinned_memories": pinned,
        "summary": summary["summary_text"] if summary else None,
        "messages": messages,
    }

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    short = conversation_id[:8]
    out = MEM_ROOT / "exports" / f"{ts}_{short}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    payload["saved_as"] = str(out)
    return payload



def create_conversation(name: str) -> str:
    conv_id = str(uuid.uuid4())
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO conversations (id, name) VALUES (?, ?)",
        (conv_id, _clean_text(name) or "Conversation"),
    )
    con.commit()
    con.close()
    return conv_id



def list_conversations():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, created_at
        FROM conversations
        ORDER BY datetime(created_at) DESC
        """
    )
    rows = cur.fetchall()
    con.close()
    return [{"id": row[0], "name": row[1], "created_at": row[2]} for row in rows]



def _decode_bytes(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1251", errors="replace")



def _parse_transcript(text: str):
    """Parse simple exported transcripts into user/assistant messages.

    Supported markers include:
    - You said: / User: / [1]
    - ChatGPT said: / Assistant said: / Assistant: / GPT-4o: / [2]
    Markers can appear on a separate line or before text.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def flush(buf_role, buf):
        content = "\n".join(buf).strip()
        if content:
            out.append({"role": buf_role, "content": content})

    out = []
    role = None
    buf = []

    you_mark = re.compile(r"^\s*(You said:|User:|Human:|\[1\])\s*$", re.IGNORECASE)
    gpt_mark = re.compile(r"^\s*(ChatGPT said:|Assistant said:|Assistant:|GPT-4o:|\[2\])\s*$", re.IGNORECASE)

    for ln in lines:
        s = ln.rstrip()

        if you_mark.match(s):
            if role:
                flush(role, buf)
            role, buf = "user", []
            continue

        if gpt_mark.match(s):
            if role:
                flush(role, buf)
            role, buf = "assistant", []
            continue

        if role is None and not s.strip():
            continue

        if role is None:
            role = "user"
        buf.append(s)

    if role:
        flush(role, buf)

    return out



def import_transcript_text(name: str, raw_text: str) -> str:
    msgs = _parse_transcript(raw_text)
    conv_id = create_conversation(name)

    for message in msgs:
        save_message(conv_id, message["role"], message["content"])

    return conv_id



def rename_conversation(conv_id: str, new_name: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "UPDATE conversations SET name = ? WHERE id = ?",
        (_clean_text(new_name), conv_id),
    )
    con.commit()
    con.close()



def delete_conversation(conv_id: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    cur.execute("DELETE FROM pinned_memories WHERE conversation_id = ?", (conv_id,))
    cur.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (conv_id,))
    cur.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    con.commit()
    con.close()
