# Twitch Wheel Vote Bot (Local Python App)

A local desktop app that connects to Twitch chat, counts phrase votes in real time, and displays a weighted Wheel-of-Fortune-style spinner.

## Features

- Connects to Twitch IRC and reads live chat from a configured channel.
- 2-minute vote window using **startvote**.
- Editable segment table (add, remove, and inline edit phrase/vote counts).
- Export/import buttons for saving and reloading wheel segment data (including user-vote associations) as text files.
- Wheel/table display only the top **N** most common phrases (N = input field).
- Similar/contained phrases are automatically merged into an existing phrase bucket to reduce duplicate near-matches.
- Wheel slices are weighted by vote count and update instantly.
- Separate wheel render window with continuous spin and a live green label showing the slice under the pointer.
- Wheel display also shows a smaller green `voted by:` line under the current phrase; as the pointer moves, it resolves to an individual voter within that phrase slice.
- Wheel window scales responsively and keeps a fixed square aspect ratio during resize.
- Connection status/error area plus live chat feed.

## Setup

1. Install Python 3.10+.
2. Configure `config.json`:
   - `channel`: Twitch channel to monitor (default: `itskxtlyn`)
   - `nickname`: Twitch bot username
   - `oauth_token`: Twitch IRC token in form `oauth:...`

### Getting a Twitch OAuth token

Use Twitch Chat OAuth token tools or your own OAuth flow and paste the token into `config.json`.

## Run locally

```bash
python main.py
```

## How the voting works

- Press **startvote** to begin a 120-second voting period.
- Press **stopvote** to end the voting period early.
- Every chat message becomes a normalized phrase (`lowercase`, trimmed spaces).
- Phrase count increments as messages arrive, and near-duplicate messages map to existing phrase entries when similar enough.
- Each username is limited to one active vote at a time.
- If a user sends a different phrase later, their previous vote is removed and replaced with the new vote (re-voting).
- **Top phrases on wheel** sets how many highest-vote phrases are shown on the wheel/table; lower-ranked phrases are ignored in the display/spin until they move into the top set.
- Edit the table at any time; wheel updates immediately.
- Pressing **spinwheel** adds momentum even if the wheel is already spinning.

## Build as a Windows EXE (PyInstaller)

From a Windows terminal in this project folder:

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name twitch-wheel-bot main.py
```

Output EXE:

- `dist/twitch-wheel-bot.exe`

### Include config.json next to EXE

Copy `config.json` into the same folder as the EXE, then edit it there.

### Optional icon

```bash
pyinstaller --noconfirm --onefile --windowed --name twitch-wheel-bot --icon app.ico main.py
```

## Notes

- Twitch may throttle or disconnect malformed/unauthorized sessions; check connection status line and chat pane for debug messages.
- If token/nickname is not configured, app starts but shows config error until fixed.
