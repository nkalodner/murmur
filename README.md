# Murmur

Local push-to-talk dictation for macOS and Windows. Hold a key, talk, release, and the words land wherever your cursor is. It replaces a Wispr Flow subscription with speech models running entirely on your machine (NVIDIA's Parakeet by default; Whisper and Canary are a settings pick away): free, offline, and nothing you say leaves your computer. MIT licensed.

I develop Murmur inside my personal site's monorepo, and every change is auto-published to [github.com/nkalodner/murmur](https://github.com/nkalodner/murmur), so the public code always matches what I run.

## How it works

- A small tray app watches one global hotkey (Right Ctrl by default).
- Hold the key and speak. Release, and Murmur transcribes on the machine and pastes the text into whatever app has focus.
- Quick-tap the key instead to record hands-free, then tap again to finish. Esc cancels a recording.
- Transcription runs on your CPU, by default with the int8 ONNX build of `parakeet-tdt-0.6b-v2`; Whisper, Canary, and other models are one settings change away (see [Choosing a model](#choosing-a-model)). A ten second sentence takes about a second on a modern laptop with the default, punctuation and capitalization included.
- A local settings page (tray menu, or `murmur --settings`) handles the hotkey, the mic, a personal dictionary, and everything else. See [Settings](#settings).

## Install

You need [uv](https://docs.astral.sh/uv/), which installs and manages Python for you, and git.

Install uv on macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or on Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then, in a fresh terminal on either platform, clone this repo and install it:

```bash
git clone https://github.com/nkalodner/murmur.git
uv tool install ./murmur
murmur
```

Notes:

- If `murmur` is not found after install, run `uv tool update-shell` and open a fresh terminal.
- To update later: `git -C murmur pull`, then `uv tool install --reinstall ./murmur`.
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
- **Model**: pick from the menu (Parakeet v2/v3, Whisper base, Canary 1B v2) or enter any onnx-asr name / Hugging Face repo id via Custom, plus precision and a language code for the models that read one. A new model downloads on first use and loads on the next dictation. See [Choosing a model](#choosing-a-model).
- **Startup**: Open Murmur at login (Windows and macOS). See [below](#do-i-need-to-keep-the-terminal-open-start-at-login).
- **Recent transcripts**: the last few dictations, newest first, for testing dictionary entries.

### The dictionary

Two mechanisms, both applied to every transcript before it is pasted:

- **Vocabulary**: words and phrases spelled and cased exactly how you want them typed. Transcripts that come out close snap to your spelling, so "wisper" becomes "Wispr" and "photo globe" becomes "Photoglobe". Ordinary spoken words are left alone, so a short name like "Andi" never rewrites "and" or "and I", and very short entries only snap on a near-exact match. Match sensitivity (`vocab_threshold`) sets how close a word must sound before it snaps; add proper nouns and jargon.
- **Replacements**: exact heard-to-typed pairs for things the model reliably mishears the same way, like "cloud code" becoming "Claude Code". Matched case-insensitively on word boundaries.

Built a dictionary on one machine and setting up another? **Export dictionary** on the settings page writes every word and replacement to a small JSON file; **Import dictionary** on the other device folds it in. Imports merge: duplicates are skipped and the importing device's own entries always win, so it is safe to run in either direction (and it accepts a whole `config.json` too, if that is what you have). The same works from the terminal:

```
murmur --export-dictionary               # writes murmur-dictionary.json here
murmur --import-dictionary murmur-dictionary.json
```

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
murmur --export-dictionary   # write your dictionary to a file for another device
murmur --import-dictionary murmur-dictionary.json
```

### Choosing a model

The settings page offers four directly; all run fully local through [onnx-asr](https://github.com/istupakov/onnx-asr):

| Model | Languages | Download | Why pick it |
| --- | --- | --- | --- |
| `nemo-parakeet-tdt-0.6b-v2` | English | ~700 MB | The default. Best accuracy for its speed on a CPU. |
| `nemo-parakeet-tdt-0.6b-v3` | 25 European languages | ~700 MB | Same family and speed as v2, auto-detects the language. |
| `whisper-base` | 99 languages | ~80 MB | Lightest and quickest to try, widest language list, noticeably softer accuracy. Set a language code if it guesses wrong. |
| `nemo-canary-1b-v2` | 25 European languages | ~1 GB | The most accurate multilingual option, with a longer pause after speaking on CPU. |

The Custom field takes anything else onnx-asr can load: its other aliases (the GigaAM and FastConformer families for Russian, `nemo-parakeet-ctc-0.6b`, and so on) or any Hugging Face repo id with a slash, like `onnx-community/whisper-large-v3-turbo` for Whisper's strongest open model. Two notes on custom repos: not all of them ship int8 files, so switch quantization to full precision if the load fails, and bigger Whisper models get slow on a CPU. The `language` setting (two letters, like `en`) is read by Whisper and Canary; Parakeet ignores it.

## Do I need to keep the terminal open? Start at login

No. Turn on **Open Murmur at login** in the settings page (Startup section) and Murmur starts by itself, in the tray, with no terminal window. The same switch is available from the command line:

```
murmur --enable-autostart     # start at login from now on
murmur --disable-autostart    # stop
```

A `murmur` you start in a terminal is tied to that window, so closing it quits. The startup toggle avoids that by launching Murmur from the system, with no terminal involved.

- **Windows**: the install also created `murmurw`, a windowless launcher. Run `murmurw` yourself any time to start Murmur with no console window, then close the terminal and it stays in the tray.
- **macOS**: `murmurw` and `murmur` are the same command, so use the login toggle to run without a terminal. To start the background copy right now without logging out, run `launchctl kickstart -k gui/$(id -u)/com.murmur.dictation`. Open the settings from the menu bar or with `murmur --settings` (it attaches to the running copy) rather than launching `murmur` again, which would start a second instance.

- **Windows**: the toggle places a shortcut to `murmurw.exe` in your Startup folder (falling back to a registry Run entry if the folder is blocked). Nothing shows on screen but the tray icon.
- **macOS**: the toggle installs a LaunchAgent and loads it. One caveat: launched this way, macOS sees a new launcher, so it asks once more for Microphone, Input Monitoring, and Accessibility. Grant them and you are set.

Every computer is its own setup. The toggle only touches the machine you run it on, so if you use Murmur on both a Mac and a Windows PC, turn it on once on each. Enabling it on one does nothing for the other.

## Troubleshooting

- **`uv tool install` fails with "Permission denied" on `~/.cache`** (macOS/Linux): the cache directory is owned by root, usually left behind by an earlier `sudo`. Take it back with `sudo chown -R "$(whoami)" ~/.cache` (and `~/.local` if that one complains too), then reinstall.
- **Hotkey does nothing (macOS)**: Input Monitoring permission is missing. `murmur --doctor` confirms it; grant it to your terminal and restart Murmur.
- **Nothing pastes (macOS)**: same story with the Accessibility permission.
- **The hotkey or pasting stops after an update (macOS)**: macOS ties Input Monitoring and Accessibility to the exact program, and `uv tool install --reinstall` can reset them. Re-grant in System Settings > Privacy & Security; `murmur --doctor` shows what is missing.
- **A key you rebound to does nothing (macOS)**: some top-row F-keys are media keys (volume, brightness) that Murmur cannot see. Hold Fn while pressing it, enable "Use F1, F2, etc. keys as standard function keys" in System Settings, or pick a bare modifier like `cmd_r`.
- **An app rejects the paste** (some terminals, password fields): set `"paste": false` to type the text instead.
- **Clipboard contents vanished**: Murmur restores text clipboards after pasting, but images and files are lost. Set `restore_clipboard_ms` to `-1` if you would rather keep the transcript on the clipboard.
- **It does not start at login (Windows)**: run `murmur --enable-autostart` and confirm it prints "Murmur will start at login." Startup is per-machine, so enabling it on your Mac never sets up Windows. Murmur should then appear under Task Manager > Startup Apps; if that list shows it as *Disabled*, right-click and choose Enable, since Windows keeps its own on/off flag that can override the entry. If the command reports it cannot find `murmur` on PATH, run `uv tool update-shell`, open a fresh terminal, and try again. After a `uv tool` reinstall or upgrade that moves the command, run the enable line once more to refresh the path it points at.
- **Enabling reports that Windows removed the startup entry**: some antivirus and "startup manager" tools revert startup changes made by apps they do not recognize. On Windows, Murmur starts by placing a shortcut in your Startup folder (these tools usually leave it alone), and only falls back to a registry entry if the folder is blocked too. If it reports both were removed, allow Murmur (`murmurw.exe`) in that tool, or add the shortcut yourself: press Win+R, run `shell:startup`, and drop a shortcut to `murmurw.exe` in the folder that opens.
- **Model download failed midway**: rerun `murmur --download`; it resumes.
- **Wrong mic**: pick it in the settings page, or `murmur --list-devices` and set `device` to a name substring.
- **A word keeps coming out wrong**: add it to the vocabulary (settings page), or add an exact replacement if the model mishears it the same way every time.

## Development

```bash
cd murmur
uv run murmur -v --no-tray   # run from source, terminal only
uv run murmur --doctor
uv run pytest                # run the test suite
```

The tests cover the pure logic (spoken-form formatting, the dictionary,
audio chunking, config, sound cues) and the recording pill, and skip the
display-dependent hotkey checks when there is no X server. They also run in
CI on every change under `murmur/`.

## Credits

Speech recognition defaults to [NVIDIA Parakeet TDT 0.6b](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0) and runs through [onnx-asr](https://github.com/istupakov/onnx-asr) and its ONNX exports by Ilya Stupakov, which also power the Whisper, Canary, and other model options. If you ever want a packaged installer with the same idea instead of a Python tool, [Handy](https://handy.computer) is a solid open source option.
