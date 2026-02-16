# Decision Engine Browser Extension

Chrome/Edge extension (Manifest V3) that logs Claude AI chat activity to the Decision Engine recorder.

## Features

- Automatically detects user messages and Claude assistant responses on claude.ai
- Buffers messages until both prompt and response are available
- Sends events to local Decision Engine recorder at `http://localhost:8000`
- Stores session ID per browser session
- Detects human selection patterns (e.g., "I picked option 1")
- Status popup shows last recorded event and any errors

## Installation (Edge/Chrome)

1. **Start the Decision Engine recorder**:
   ```powershell
   cd C:\Users\samly\Documents\decision-engine
   uvicorn app.main:app --reload
   ```
   Ensure it's running on `http://localhost:8000`

2. **Open Edge Extensions page**:
   - Open Edge browser
   - Navigate to `edge://extensions/` (or `chrome://extensions/` for Chrome)

3. **Enable Developer Mode**:
   - Toggle "Developer mode" switch in the top-right corner

4. **Load the extension**:
   - Click "Load unpacked"
   - Navigate to `C:\Users\samly\Documents\decision-engine\browser_extension`
   - Select the folder and click "Select Folder"

5. **Verify installation**:
   - The extension icon should appear in your browser toolbar
   - Click the icon to see the popup (should show "No events recorded yet" initially)

## Usage

1. **Navigate to Claude AI**:
   - Go to `https://claude.ai` or `https://*.claude.ai`
   - The extension automatically activates on these domains

2. **Start chatting**:
   - Send a message to Claude
   - Wait for Claude's response
   - The extension detects both messages and sends an event to the recorder

3. **Check status**:
   - Click the extension icon to see:
     - Last recorded event ID
     - Last event timestamp
     - Current session ID
     - Any errors (if recorder is unreachable)

## How It Works

- **Content Script** (`content.js`):
  - Runs on claude.ai pages
  - Uses `MutationObserver` to watch for new messages
  - Extracts user prompts and assistant responses from the DOM
  - Detects human selection patterns (e.g., "I picked option 1")
  - Computes SHA-256 hash of `user_prompt + "\n---\n" + assistant_response`
  - Sends POST request to `/events/record` endpoint

- **Background Service Worker** (`background.js`):
  - Manages extension lifecycle
  - Handles session ID storage

- **Popup** (`popup.html/js`):
  - Displays last recorded event ID and timestamp
  - Shows current session ID
  - Displays errors if recorder is unreachable

## Event Format

Each turn (user message + Claude response) generates one event:

```json
{
  "event_type": "AI_DECISION_TURN",
  "actor_id": "sam",
  "session_id": "<uuid-per-browser-session>",
  "source_system": "claude-web",
  "payload_hash": "sha256:<hex>",
  "system_suggestion": "<Claude's response text>",
  "options_presented": null,
  "human_selection": "<option X>" or null,
  "occurred_at_utc": "<ISO timestamp>"
}
```

## Troubleshooting

**Extension not detecting messages**:
- Claude's DOM structure may have changed
- Check browser console (F12) for `[Decision Engine]` logs
- The extension uses fallback text extraction if DOM selectors fail

**Events not being recorded**:
- Ensure Decision Engine recorder is running: `uvicorn app.main:app --reload`
- Check popup for error messages
- Verify `http://localhost:8000` is accessible
- Check browser console for fetch errors

**Session ID not persisting**:
- Edge/Chrome may clear session storage on browser restart
- This is expected behavior; each browser session gets a new session ID

## Files

- `manifest.json` - Extension configuration (Manifest V3)
- `content.js` - Main script that detects messages and sends events
- `background.js` - Service worker for extension lifecycle
- `popup.html` - Status popup UI
- `popup.js` - Popup logic
- `README.md` - This file

## Notes

- The extension only runs on `https://claude.ai/*` and `https://*.claude.ai/*`
- Session ID is stored in `chrome.storage.session` (cleared on browser close)
- Last event info is stored in `chrome.storage.local` (persists)
- The extension uses `window.crypto.subtle.digest` for SHA-256 hashing
- DOM selectors are Claude-specific and may need updates if Claude changes their UI
