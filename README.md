# GPT-4o Local

GPT-4o Local is a small local chat interface with SQLite-based memory, conversation management, image paste support, and optional cross-conversation summary bridges.

This repository is a neutral GitHub-ready version. It contains no personal prompt, no private database, and no API keys.

## Current memory architecture

The current version uses three local layers:

1. **Current conversation history** — a tail of the active conversation.
2. **Global pinned memory** — user-pinned notes stored locally in SQLite.
3. **Conversation summaries** — manually saved summary bridges from previous conversations that can be injected into new chats.

The old cross-dialog working buffer is disabled in this version. Conversation continuity now comes from saved summary bridges instead.

## Features

- Local SQLite storage for conversations and messages.
- Conversation list with rename and delete actions.
- OpenRouter chat completion support.
- Optional direct OpenAI Responses API support for `openai-direct/...` model entries.
- Per-conversation model selection stored in browser localStorage.
- Message metadata: model used and local timestamp.
- Global pinned memory.
- Transcript import from text/Markdown/JSON files.
- Conversation export to JSON.
- One-shot seed loading for the next reply.
- Manual conversation summary bridges.
- Image paste support with preview and local history display.

## Model options included in the UI

The default interface includes:

- `openai/gpt-4o-2024-11-20` through OpenRouter.
- `openai/gpt-5.1-chat` through OpenRouter.
- `openai/gpt-5.2-chat` through OpenRouter.
- `openai-direct/gpt-5.2-chat-latest` through the OpenAI Responses API.

Availability depends on your provider account and the current model catalog.

## Project structure

- `app.py` — FastAPI server and endpoints.
- `memory.py` — conversation, memory, summary, import, and export helpers.
- `db.py` — SQLite initialization and soft migrations.
- `gpt4o_config.py` — system prompt builder and output post-processing.
- `index.html` — single-file browser UI.
- `start_gpt4o_local.ps1` — Windows PowerShell launcher.
- `start_gpt4o_local.bat` — Windows batch launcher wrapper.
- `.env.example` — example environment variables.
- `.gitignore` — excludes local databases, virtual environments, secrets, and exports.

Runtime folders are created automatically as needed:

- `memories/exports/` — exported conversations.
- `memories/seed/` — optional seed file.
- `memories/pinned/` — reserved for pinned-memory related files.

## Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure API keys

Set environment variables before starting the server.

Required for OpenRouter models:

```powershell
$env:OPENROUTER_API_KEY = "your-openrouter-key"
```

Required only for `openai-direct/...` models:

```powershell
$env:OPENAI_API_KEY = "your-openai-key"
```

Optional summary model override:

```powershell
$env:GPT4O_SUMMARY_MODEL = "openai/gpt-4o-mini"
```

You can also copy `.env.example` to `.env` for your own local use, but do not commit `.env`.

### 4. Start the server

```powershell
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

On Windows, you can also run:

```powershell
.\start_gpt4o_local.ps1
```

## Memory details

### Current conversation history

The active conversation tail is sent with each new message.

In `app.py`:

```python
recent = load_recent_messages(conv_id, limit=70)
```

Change `limit` to tune context size. Smaller values are cheaper and faster; larger values provide more continuity.

### Global pinned memory

Pinned memory is stored in the `global_memories` table inside `gpt4o_local.db`.

The UI can:

- add pinned memory through the bottom input field;
- show existing pinned memory through the `Memory` button.

### Conversation summary bridges

A bridge is a short summary saved for one conversation. When a new message is sent, the app loads the latest saved bridges from other conversations and adds them to the system prompt as background continuity.

The number of recent bridges is controlled in `app.py`:

```python
RECENT_SUMMARIES_LIMIT = 5
```

Each conversation keeps one current bridge. Rebuilding a bridge replaces the old one for that conversation.

### Seed

Seed is optional and one-shot. If `memories/seed/seed.json` exists and contains a `summary` field, pressing `Load seed once` injects it only into the next response.

Example:

```json
{
  "summary": "The assistant should use a concise and friendly tone."
}
```

## Main endpoints

### Chat and history

- `POST /chat` — send a message.
- `GET /history?conversation_id=...` — load conversation history.
- `GET /models` — fetch OpenRouter model catalog.

### Conversations

- `GET /conversations` — list conversations.
- `POST /conversations` — create a conversation.
- `POST /create_conversation` — legacy-compatible create endpoint for the UI.
- `POST /rename_conversation` — rename a conversation.
- `POST /delete_conversation?conversation_id=...` — delete a conversation.

### Memory

- `POST /pin` — add a global pinned memory item.
- `GET /global_memory` — list global pinned memory.

### Summaries

- `GET /conversation_summaries` — list recent summaries.
- `GET /conversation_summary?conversation_id=...` — get the summary for one conversation.
- `POST /conversation_summary` — build and save a summary bridge.
- `POST /conversation_summary/delete` — delete a summary bridge.

### Import and export

- `POST /import` — import a transcript file.
- `GET /export?conversation_id=...` — export a conversation as JSON.

## Transcript import format

The importer recognizes common markers such as:

- `You said:`
- `User:`
- `Human:`
- `ChatGPT said:`
- `Assistant said:`
- `Assistant:`
- `GPT-4o:`
- `[1]` for user messages
- `[2]` for assistant messages

If no explicit role is detected at the beginning, the first block is treated as a user message.

## Security notes

- Do not commit API keys.
- Do not commit `.env`.
- Do not commit local SQLite databases.
- The included launcher reads keys from the current environment or from an optional local `.env` file.

The uploaded working version contained local runtime data and hard-coded API keys in the launcher. Those items are intentionally removed from this GitHub package.

## GitHub-ready changes in this version

- Renamed the project to GPT-4o Local.
- Replaced the personal prompt with a neutral assistant prompt.
- Converted UI text, README text, and code comments to English.
- Changed local database name to `gpt4o_local.db`.
- Renamed the prompt configuration module to `gpt4o_config.py`.
- Removed hard-coded API keys from startup scripts.
- Kept all memory local in SQLite.
- Kept manual summary bridges between conversations.
- Kept GPT-5.1 and GPT-5.2 model choices in the UI.
- Removed old cross-dialog working-buffer injection from the active chat path.
