# Murmur

Local push-to-talk dictation for macOS and Windows. Hold a key, talk, release, and the words land wherever your cursor is. It replaces a Wispr Flow subscription with NVIDIA's Parakeet speech model running entirely on your machine: free, offline, and nothing you say leaves your computer. MIT licensed.

I develop Murmur inside my personal site's monorepo, and every change is auto-published to [github.com/nkalodner/murmur](https://github.com/nkalodner/murmur), so the public code always matches what I run.

## How it works

- A small tray app watches one global hotkey (Right Ctrl by default).
- Hold the key and speak. Release, and Murmur transcribes with Parakeet and pastes the text into whatever app has focus.
- Quick-tap the key instead to record hands-free, then tap again to finish. Esc cancels a recording.
- Transcription runs on your CPU with the int8 ONNX build of `parakeet-tdt-0.6b-v2`. A ten second sentence takes about a second on a modern laptop, with punctuation and capitalization included.
- A local settings page (tray menu, or `murmur --settings`) handles the hotkey, the mic, a personal dictionary, and everything else. See [Settings](#settings).

## Install

Both platforms use [uv](https://docs.astral.sh/uv/), which installs and manages Python for you. No git, no other setup: install uv, then install Murmur from the hosted wheel.

### macOS

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install https://noahkalodner.com/downloads/murmur_dictation-0.5.0-py3-none-any.whl
murmur
```

(Run the uv line first, then open a fresh terminal so `uv` is on your PATH.)

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install https://noahkalodner.com/downloads/murmur_dictation-0.5.0-py3-none-any.whl
murmur
```

### From source

Clone this repo and install the folder that holds `pyproject.toml`:

```bash
git clone https://github.com/nkalodner/murmur.git
uv tool install ./murmur
```

Notes:

- If `murmur` is not found after install, run `uv tool update-shell` and open a fresh terminal.
- To update later: rerun the `uv tool install` line above with `--reinstall` (the wheel URL always points at the current version).
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

## Settings

`murmur --settings` opens the settings page, starting Murmur first if it needs to. It is also in the tray menu, and double-clicking the tray icon opens it on Windows. The page is served by Murmur itself on `127.0.0.1` only; nothing leaves your machine. Changes apply immediately, including the hotkey, and persist to `~/.murmur/config.json`.

- **Hotkey**: click Change key and press the one you want. Esc stays reserved for canceling a recording.
- **Microphone**: pick a specific input, or leave it on the system default. Test mic records about a second and shows the level, so you can confirm it hears you before saving.
- **Dictionary**: see below.
- **Behavior**: chimes, paste versus type, trailing space, history, the recording pill, max recording length, tap-lock window, clipboard restore delay. The start-recording cue is a soft low tone; the Play button next to it previews it.
- **Recording pill**: a small always-on-top overlay near the bottom of the screen while you talk, just a status dot and bars that move to your voice, no text (Windows and Linux; macOS shows the tray dot instead, since Tk can't share the menu-bar thread). Toggle it under Behavior.
- **Auto-format speech**: spoken times, dates, and numbers come out written. "one pm" types as `1:00 PM`, "three oh five p.m." as `3:05 PM`, "july third" as `July 3rd`, "fifty percent" as `50%`, "twenty dollars" as `$20`, "twenty five" as `25`. Deliberately conservative: anything ambiguous ("five thirty" with no am/pm) stays as spoken, and "which one am I" is never mangled. Toggle under Behavior.
- **Model**: switch models or precision. A new model downloads on first use and loads on the next dictation.
- **Startup**: Open Murmur at login (Windows and macOS). See [below](#do-i-need-to-keep-the-terminal-open-start-at-login).
- **Recent transcripts**: the last few dictations, newest first, for testing dictionary entries.

### The dictionary

Two mechanisms, both applied to every transcript before it is pasted:

- **Vocabulary**: words and phrases spelled and cased exactly how you want them typed. Transcripts that come out close snap to your spelling, so "wisper" becomes "Wispr" and "photo globe" becomes "Photoglobe". Ordinary spoken words are left alone, so a short name like "Andi" never rewrites "and" or "and I", and very short entries only snap on a near-exact match. Match sensitivity (`vocab_threshold`) sets how close a word must sound before it snaps; add proper nouns and jargon.
- **Replacements**: exact heard-to-typed pairs for things the model reliably mishears the same way, like "cloud code" becoming "Claude Code". Matched case-insensitively on word boundaries.

## Configuration

`~/.murmur/config.json` is created on first run. The settings page edits all of it; the file is there for hand edits and backups:

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
| `pill` | `true` | Floating recording overlay (Windows/Linux) |
| `formatting` | `true` | Spoken times/dates/numbers become written forms (1:00 PM, July 3rd, 50%) |
| `vocabulary` | `[]` | Dictionary words/phrases, spelled how they should be typed |
| `replacements` | `[]` | Exact fixes: `{"from": "heard", "to": "typed"}` |
| `vocab_threshold` | `0.82` | How close a word must sound to snap to vocabulary (lower catches more) |

Hotkey names come from pynput: `ctrl_r`, `alt_r`, `cmd_r`, `f8`, `pause`, and friends. Pick a key that types nothing on its own; bare modifiers work best. On international Windows layouts `alt_r` is AltGr, so prefer `ctrl_r` there.

CLI flags override the config for one run, and a few act and exit:

```
murmur --hotkey f8 --model nemo-parakeet-tdt-0.6b-v3 --type --no-sounds --no-tray -v
murmur --settings            # open the settings page
murmur --enable-autostart    # start at login (also --disable-autostart)
murmur --list-devices        # list input devices
murmur --doctor              # check mic, model, permissions, clipboard
```

### Other models

`nemo-parakeet-tdt-0.6b-v2` is English only and currently the best quality per CPU cycle. `nemo-parakeet-tdt-0.6b-v3` is the multilingual version (25 European languages). Any model [onnx-asr](https://github.com/istupakov/onnx-asr) supports will work, including `whisper-base`.

## Do I need to keep the terminal open? Start at login

No. Turn on **Open Murmur at login** in the settings page (Startup section) and Murmur starts by itself, in the tray, with no terminal window. The same switch is available from the command line:

```
murmur --enable-autostart     # start at login from now on
murmur --disable-autostart    # stop
```

Behind the scenes this uses a windowless launcher, `murmurw`, that the install created alongside `murmur`. You can also run `murmurw` yourself any time to launch Murmur without a console window, then close the terminal; it keeps running in the tray. (Plain `murmur` from a terminal ties the app to that window, so closing it quits Murmur.)

- **Windows**: the toggle writes a per-user startup entry pointing at `murmurw.exe`. Nothing shows on screen but the tray icon.
- **macOS**: the toggle installs a LaunchAgent and loads it. One caveat: launched this way, macOS sees a new launcher, so it asks once more for Microphone, Input Monitoring, and Accessibility. Grant them and you are set.

## Troubleshooting

- **Hotkey does nothing (macOS)**: Input Monitoring permission is missing. `murmur --doctor` confirms it; grant it to your terminal and restart Murmur.
- **Nothing pastes (macOS)**: same story with the Accessibility permission.
- **An app rejects the paste** (some terminals, password fields): set `"paste": false` to type the text instead.
- **Clipboard contents vanished**: Murmur restores text clipboards after pasting, but images and files are lost. Set `restore_clipboard_ms` to `-1` if you would rather keep the transcript on the clipboard.
- **Model download failed midway**: rerun `murmur --download`; it resumes.
- **Wrong mic**: pick it in the settings page, or `murmur --list-devices` and set `device` to a name substring.
- **A word keeps coming out wrong**: add it to the vocabulary (settings page), or add an exact replacement if the model mishears it the same way every time.

## Development

```bash
cd murmur
uv run murmur -v --no-tray   # run from source, terminal only
uv run murmur --doctor
```

## Credits

Speech recognition is [NVIDIA Parakeet TDT 0.6b](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0) via [onnx-asr](https://github.com/istupakov/onnx-asr) and its ONNX exports by Ilya Stupakov. If you ever want a packaged installer with the same idea instead of a Python tool, [Handy](https://handy.computer) is a solid open source option.
