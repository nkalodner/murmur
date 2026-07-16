# Murmur

Local push-to-talk dictation for macOS and Windows. Hold a key, talk, release, and the words land wherever your cursor is. It replaces a Wispr Flow subscription with NVIDIA's Parakeet speech model running entirely on your machine: free, offline, and nothing you say leaves your computer.

This folder is a standalone Python app. It shares a repo with noahkalodner.com but has no connection to the site build.

## How it works

- A small tray app watches one global hotkey (Right Ctrl by default).
- Hold the key and speak. Release, and Murmur transcribes with Parakeet and pastes the text into whatever app has focus.
- Quick-tap the key instead to record hands-free, then tap again to finish. Esc cancels a recording.
- Transcription runs on your CPU with the int8 ONNX build of `parakeet-tdt-0.6b-v2`. A ten second sentence takes about a second on a modern laptop, with punctuation and capitalization included.

## Install

Both platforms use [uv](https://docs.astral.sh/uv/), which installs and manages Python for you.

### macOS

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/nkalodner/noahkalodner-personal-site.git
uv tool install ./noahkalodner-personal-site/murmur
murmur
```

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
git clone https://github.com/nkalodner/noahkalodner-personal-site.git
uv tool install .\noahkalodner-personal-site\murmur
murmur
```

Notes:

- No git? Download the repo as a zip from GitHub and point `uv tool install` at the unzipped `murmur` folder.
- If `murmur` is not found after install, run `uv tool update-shell` and open a fresh terminal.
- To update later: pull the repo, then `uv tool install --reinstall ./noahkalodner-personal-site/murmur`.
- To remove: `uv tool uninstall murmur-dictation`, then delete `~/.murmur` and the model in `~/.cache/huggingface`.

### First run

- The model downloads once from Hugging Face (about 700 MB) into your user cache. `murmur --download` grabs it ahead of time if you prefer.
- macOS asks for three permissions, all granted to your terminal app (Terminal, iTerm, and so on), since that is what runs Murmur:
  - **Microphone**: prompted automatically at launch.
  - **Input Monitoring**: lets Murmur see the hotkey. The prompt appears at launch; approve it and restart Murmur.
  - **Accessibility**: lets Murmur paste. System Settings > Privacy & Security > Accessibility > enable your terminal.
- Windows needs no special permissions. To dictate into apps running as administrator, launch Murmur from an administrator terminal too.

`murmur --doctor` checks mic, model cache, permissions, and clipboard in one pass.

## Using it

| Action | What happens |
| --- | --- |
| Hold Right Ctrl, speak, release | Transcribes and pastes at your cursor |
| Quick-tap Right Ctrl | Starts hands-free recording; tap again to finish |
| Esc while recording | Cancels, nothing is pasted |

The tray icon shows state: gray is idle, red is recording, amber is transcribing. Short chimes confirm ready, start, stop, and cancel.

Recordings stop automatically after 2 minutes (`max_seconds`). Longer stretches of audio are split at pauses and transcribed piece by piece. Every transcript is also appended to `~/.murmur/history.jsonl`, so pasting into the wrong window never loses your words.

## Configuration

`~/.murmur/config.json` is created on first run:

| Key | Default | Meaning |
| --- | --- | --- |
| `hotkey` | `"ctrl_r"` | The push-to-talk key (pynput names) |
| `model` | `"nemo-parakeet-tdt-0.6b-v2"` | Any onnx-asr model name |
| `quantization` | `"int8"` | `null` for full precision (bigger, slower on CPU) |
| `language` | `null` | Only read by whisper/canary models; Parakeet v3 auto-detects |
| `device` | `null` | Mic name substring; `null` uses the system default |
| `sounds` | `true` | Audio cues on state changes |
| `paste` | `true` | `false` types character by character instead of pasting |
| `restore_clipboard_ms` | `600` | Delay before restoring your previous clipboard; `-1` never restores |
| `tap_lock_ms` | `350` | Presses shorter than this lock hands-free recording |
| `max_seconds` | `120` | Auto-stop for a single recording |
| `trailing_space` | `true` | Append a space so back-to-back dictations flow |
| `history` | `true` | Log transcripts to `~/.murmur/history.jsonl` |

Hotkey names come from pynput: `ctrl_r`, `alt_r`, `cmd_r`, `f8`, `pause`, and friends. Pick a key that types nothing on its own; bare modifiers work best. On international Windows layouts `alt_r` is AltGr, so prefer `ctrl_r` there.

CLI flags override the config for one run:

```
murmur --hotkey f8 --model nemo-parakeet-tdt-0.6b-v3 --type --no-sounds --no-tray -v
```

### Other models

`nemo-parakeet-tdt-0.6b-v2` is English only and currently the best quality per CPU cycle. `nemo-parakeet-tdt-0.6b-v3` is the multilingual version (25 European languages). Any model [onnx-asr](https://github.com/istupakov/onnx-asr) supports will work, including `whisper-base`.

## Start at login

**macOS**: save this as `~/Library/LaunchAgents/com.noah.murmur.plist` (fix the username in the path), then run `launchctl load ~/Library/LaunchAgents/com.noah.murmur.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.noah.murmur</string>
  <key>ProgramArguments</key><array><string>/Users/YOU/.local/bin/murmur</string></array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/murmur.log</string>
  <key>StandardErrorPath</key><string>/tmp/murmur.log</string>
</dict></plist>
```

Heads up: launched this way, macOS attributes the permission prompts to `python` instead of your terminal, so expect to grant Microphone, Input Monitoring, and Accessibility once more. Keeping Murmur in a terminal tab is the simpler routine.

**Windows**: press Win+R, run `shell:startup`, and drop in a shortcut to `%USERPROFILE%\.local\bin\murmur.exe`. Set the shortcut to run minimized if the console window bothers you.

## Troubleshooting

- **Hotkey does nothing (macOS)**: Input Monitoring permission is missing. `murmur --doctor` confirms it; grant it to your terminal and restart Murmur.
- **Nothing pastes (macOS)**: same story with the Accessibility permission.
- **An app rejects the paste** (some terminals, password fields): set `"paste": false` to type the text instead.
- **Clipboard contents vanished**: Murmur restores text clipboards after pasting, but images and files are lost. Set `restore_clipboard_ms` to `-1` if you would rather keep the transcript on the clipboard.
- **Model download failed midway**: rerun `murmur --download`; it resumes.
- **Wrong mic**: `murmur --list-devices`, then set `device` to a name substring.

## Development

```bash
cd murmur
uv run murmur -v --no-tray   # run from source, terminal only
uv run murmur --doctor
```

## Credits

Speech recognition is [NVIDIA Parakeet TDT 0.6b](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0) via [onnx-asr](https://github.com/istupakov/onnx-asr) and its ONNX exports by Ilya Stupakov. If you ever want a packaged installer with the same idea instead of a Python tool, [Handy](https://handy.computer) is a solid open source option.
