import json
import asyncio
import os
from datetime import datetime
import httpx
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from gpt4o_config import build_system_prompt, postprocess_text
from db import init_db
from memory import (
    add_global_memory,
    count_messages,
    create_conversation,
    delete_conversation,
    delete_conversation_summary,
    export_conversation_to_file,
    get_conversation_summary,
    import_transcript_text,
    list_conversation_summaries,
    list_conversations,
    list_global_memories,
    load_all_messages,
    load_recent_messages,
    recent_summary_texts,
    rename_conversation,
    save_conversation_summary,
    save_message,
    seed_summary_text,
)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUMMARY_MODEL = os.getenv("GPT4O_SUMMARY_MODEL", "openai/gpt-4o-mini")
RECENT_SUMMARIES_LIMIT = 5
SUMMARY_SOURCE_MESSAGES_LIMIT = 90
SUMMARY_SOURCE_CHARS_LIMIT = 40000
app = FastAPI(title="GPT-4o Local")
SEED_ARMED = False
STATIC_DIR = "static" if os.path.isdir("static") else None
INDEX_FILE = "static/index.html" if os.path.exists("static/index.html") else "index.html"
if STATIC_DIR:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
init_db()
class ChatIn(BaseModel):
    conversation_id: str
    user_text: str
    model: str | None = None
    image_data_url: str | None = None
class PinIn(BaseModel):
    conversation_id: str
    text: str
class RenameIn(BaseModel):
    conversation_id: str
    name: str
class SummaryBuildIn(BaseModel):
    conversation_id: str
    model: str | None = None
    save: bool = True
class SummaryDeleteIn(BaseModel):
    summary_id: int
class NewConvIn(BaseModel):
    name: str | None = None
def is_direct_openai_model(model: str | None) -> bool:
    model = (model or "").strip()
    return model.startswith("openai-direct/")
def direct_openai_model_id(model: str | None) -> str:
    model = (model or "").strip()
    if model.startswith("openai-direct/"):
        return model.split("/", 1)[1]
    return model
async def call_openrouter(messages: list[dict], model: str, max_tokens: int = 1200):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://localhost",
        "X-Title": "GPT-4o Local",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "top_p": 0.85,
        "frequency_penalty": 0.15,
        "presence_penalty": 0.1,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        real_model = data.get("model") or model
        return text, real_model, data
async def call_openai(messages: list[dict], model: str, max_tokens: int = 1200):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    def to_responses_input(items: list[dict]) -> list[dict]:
        out = []
        for item in items:
            role = item.get("role", "user")
            content = item.get("content", "")
            text_type = "output_text" if role == "assistant" else "input_text"
            if isinstance(content, str):
                out.append({
                    "role": role,
                    "content": [{"type": text_type, "text": content}],
                })
                continue
            if isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({
                            "type": text_type,
                            "text": part.get("text", ""),
                        })
                    elif part.get("type") == "image_url":
                        image_url = (part.get("image_url") or {}).get("url")
                        if image_url and role != "assistant":
                            parts.append({
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": "auto",
                            })
                if parts:
                    out.append({"role": role, "content": parts})
                continue
            out.append({
                "role": role,
                "content": [{"type": text_type, "text": str(content)}],
            })
        return out
    body = {
        "model": direct_openai_model_id(model),
        "input": to_responses_input(messages),
        "max_output_tokens": max_tokens,
    }
    last_exc = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0),
                http2=False,
                limits=httpx.Limits(max_keepalive_connections=0, max_connections=10),
            ) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("output_text") or ""
                if not text:
                    output = data.get("output", [])
                    chunks = []
                    for item in output:
                        for part in item.get("content", []):
                            if part.get("type") in {"output_text", "text"}:
                                txt = part.get("text") or ""
                                if txt:
                                    chunks.append(txt)
                    text = "\n".join(chunks).strip()
                real_model = data.get("model") or direct_openai_model_id(model)
                return text, real_model, data
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
            last_exc = e
            if attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            raise
    raise last_exc
def build_summary_messages(
    conversation_id: str,
    max_messages: int = SUMMARY_SOURCE_MESSAGES_LIMIT,
    max_chars: int = SUMMARY_SOURCE_CHARS_LIMIT,
):
    full_messages = load_all_messages(conversation_id)
    if max_messages and len(full_messages) > max_messages:
        full_messages = full_messages[-max_messages:]
    transcript_lines = []
    total_chars = 0
    for item in reversed(full_messages):
        speaker = "User" if item["role"] == "user" else "Assistant"
        line = f"{speaker}: {item['content']}".strip()
        # Build from the end to keep the newest messages within the character limit.
        extra = len(line) + 2
        if max_chars and (total_chars + extra) > max_chars:
            break
        transcript_lines.append(line)
        total_chars += extra
    transcript_lines.reverse()
    transcript = "\n\n".join(transcript_lines).strip()
    instruction = """
Write a short conversation summary for cross-chat memory.
Format:
- Topics:
- Important facts:
- User preferences or constraints:
- Useful continuity notes:
Rules:
- Be concise but specific.
- Do not invent anything that was not in the conversation.
- Save only what can help continue the conversation later.
- Do not copy long quotes.
- If a section has nothing relevant, write a short neutral note.
""".strip()
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": transcript or "The conversation is empty."},
    ]
@app.get("/", response_class=HTMLResponse)
def index():
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return f.read()
@app.post("/pin")
def pin_memory(pin: PinIn):
    add_global_memory(pin.text.strip())
    return {"ok": True}
@app.get("/history")
def history(conversation_id: str):
    conv_id = conversation_id.strip()
    msgs = load_recent_messages(conv_id, limit=2000)
    return {"messages": msgs}
@app.get("/export")
def export(conversation_id: str):
    conv_id = conversation_id.strip()
    data = export_conversation_to_file(conv_id)
    filename = data["saved_as"].split("/")[-1]
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
@app.get("/conversations")
def conversations():
    return {"conversations": list_conversations()}
@app.get("/global_memory")
def get_global_memory():
    return {"items": list_global_memories()}
@app.post("/conversations")
def new_conversation(payload: NewConvIn):
    name = (payload.name or "").strip() or "Conversation"
    conv_id = create_conversation(name)
    return {"id": conv_id, "name": name}
@app.post("/import")
async def import_file(name: str = "Import", file: UploadFile = File(...)):
    b = await file.read()
    try:
        text = b.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        text = b.decode("cp1251", errors="replace")
    conv_id = import_transcript_text(name, text)
    return JSONResponse({"ok": True, "conversation_id": conv_id})
@app.post("/rename_conversation")
def rename_conv(payload: RenameIn):
    rename_conversation(payload.conversation_id, payload.name)
    return {"ok": True}
@app.post("/delete_conversation")
def delete_conv(conversation_id: str):
    delete_conversation(conversation_id)
    return {"ok": True}
@app.get("/conversation_summaries")
def get_conversation_summaries(limit: int = RECENT_SUMMARIES_LIMIT, exclude_conversation_id: str | None = None):
    return {
        "items": list_conversation_summaries(
            limit=limit,
            exclude_conversation_id=exclude_conversation_id,
        )
    }
@app.get("/conversation_summary")
def get_conversation_summary_endpoint(conversation_id: str):
    item = get_conversation_summary(conversation_id.strip())
    return {"item": item}
@app.post("/conversation_summary")
async def build_conversation_summary(payload: SummaryBuildIn):
    if not OPENROUTER_API_KEY:
        return {"ok": False, "error": "OPENROUTER_API_KEY is not set. Set it and restart the server."}
    conv_id = payload.conversation_id.strip()
    message_count = count_messages(conv_id)
    if message_count == 0:
        return {"ok": False, "error": "Conversation is empty."}
    messages = build_summary_messages(conv_id)
    selected_model = SUMMARY_MODEL.strip()
    try:
        summary_text, real_model, _ = await call_openrouter(
            messages,
            selected_model,
            max_tokens=500
        )
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        return {
            "ok": False,
            "error": f"OpenRouter returned HTTP {status_code} while building the bridge. Try again later."
        }
    except httpx.ReadTimeout:
        return {
            "ok": False,
            "error": "OpenRouter did not respond in time while building the bridge. Try again."
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Could not build the bridge: {str(e)}"
        }
    
    summary_text = postprocess_text(summary_text)
    summary_id = None
    if payload.save:
        summary_id = save_conversation_summary(
            conversation_id=conv_id,
            summary_text=summary_text,
            source_message_count=message_count,
        )
    else:
        summary_id = None
    existing = get_conversation_summary(conv_id)
    return {
        "ok": True,
        "conversation_id": conv_id,
        "summary_id": summary_id or (existing["id"] if existing else None),
        "summary_text": summary_text,
        "model_used": real_model,
        "created_at_local": existing["created_at_local"] if existing else None,
    }
@app.post("/conversation_summary/delete")
def delete_conversation_summary_endpoint(payload: SummaryDeleteIn):
    delete_conversation_summary(payload.summary_id)
    return {"ok": True}
@app.post("/chat")
async def chat(payload: ChatIn):
    selected_model = (payload.model or "openai/gpt-4o-2024-11-20").strip()
    if is_direct_openai_model(selected_model):
        if not OPENAI_API_KEY:
            return {"error": "OPENAI_API_KEY is not set. Set it and restart the server."}
    else:
        if not OPENROUTER_API_KEY:
            return {"error": "OPENROUTER_API_KEY is not set. Set it and restart the server."}
    conv_id = payload.conversation_id.strip()
    user_text = payload.user_text.strip()
    global_mem = list_global_memories()
    recent = load_recent_messages(conv_id, limit=70)
    recent_for_model = [{"role": m["role"], "content": m["content"]} for m in recent]
    bridge_summaries = recent_summary_texts(
        limit=RECENT_SUMMARIES_LIMIT,
        exclude_conversation_id=conv_id,
    )
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M")
    if payload.image_data_url:
        stored_user_content = json.dumps(
            {"text": user_text, "image_data_url": payload.image_data_url},
            ensure_ascii=False,
        )
    else:
        stored_user_content = user_text
    save_message(
        conv_id,
        "user",
        stored_user_content,
        model_used="user",
        created_at_local=now_local,
    )
    global SEED_ARMED
    seed_sum = seed_summary_text() if SEED_ARMED else None
    SEED_ARMED = False
    system_prompt = build_system_prompt(
        pinned_memories=global_mem,
        seed_summary=seed_sum,
        recent_summaries=bridge_summaries,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(recent_for_model)
    if payload.image_data_url:
        user_content = []
        if user_text:
            user_content.append({"type": "text", "text": user_text})
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": payload.image_data_url},
            }
        )
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_text})
    try:
        if is_direct_openai_model(selected_model):
            assistant_text, real_model, _ = await call_openai(messages, selected_model, max_tokens=1200)
        else:
            assistant_text, real_model, _ = await call_openrouter(messages, selected_model, max_tokens=1200)
    except httpx.ReadTimeout:
        return {
            "error": "The model provider did not respond in time. Try again; the conversation was saved."
        }
    except httpx.RemoteProtocolError as e:
        return {
            "error": f"The provider connection closed before a response was received: {e}"
        }
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        status = e.response.status_code if e.response is not None else "unknown"
        return {
            "error": f"Model request failed ({status}): {detail}"
        }
    except Exception as e:
        return {
            "error": f"Model request failed: {e}"
        }
    assistant_text = postprocess_text(assistant_text)
    assistant_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_message(
        conv_id,
        "assistant",
        assistant_text,
        model_used=real_model,
        created_at_local=assistant_time,
    )
    return {
        "reply": assistant_text,
        "model_used": real_model,
        "created_at_local": assistant_time,
    }
@app.get("/models")
async def get_models():
    if not OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY is not set. Set it and restart the server."}
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://localhost",
        "X-Title": "GPT-4o Local",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
        r.raise_for_status()
        return r.json()
@app.post("/seed")
def arm_seed():
    global SEED_ARMED
    text = seed_summary_text()
    if not text:
        return {"ok": False, "text": None}
    SEED_ARMED = True
    return {"ok": True}
@app.post("/create_conversation")
def create_conversation_endpoint(payload: dict):
    name = payload.get("name", "Conversation")
    conv_id = create_conversation(name)
    return {"conversation_id": conv_id}
