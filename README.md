# Murmur

Local push-to-talk dictation for macOS and Windows. Hold a key, talk, release, and the words land wherever your cursor is. Speech models run entirely on your machine (NVIDIA's Parakeet by default; Whisper and Canary are a settings pick away): free, offline, and nothing you say leaves your computer. MIT licensed.

I develop Murmur inside my personal site's monorepo, and every change is auto-published to [github.com/nkalodner/murmur](https://github.com/nkalodner/murmur), so the public code always matches what I run.

## How it works

- A small tray app watches up to two global hotkeys (Right Ctrl by default), either of which can be a key combination, and either of which can be switched off.
- Only one copy runs at a time. Starting a second one exits with a note instead, since two would type every dictation twice.
- Hold the key and speak. Release, and Murmur transcribes on the machine and pastes the text into whatever app has focus.
- Quick-tap the key instead to record hands-free, then tap again to finish. Esc cancels a recording.
- Transcription runs on your CPU, by default with the int8 ONNX build of `parakeet-tdt-0.6b-v2`; Whisper, Canary, and other models are one settings change away (see [Choosing a model](#choosing-a-model)). A ten second sentence takes about a second on a modern laptop with the default, punctuation and capitalization included.
- A local settings page (tray menu, or `murmur --settings`) handles the hotkey, the mic, a personal dictionary, and everything else. See [Settings](#settings).

## Install

You need [uv](https://docs.astral.sh/uv/), which installs and manages Python for you, and git.

**1. Install uv** (once per computer). On macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or on Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**2. Open a new terminal window.** Close the one you just used and open a fresh one; only a new window knows where uv landed, so the next step is typed there.

**3. Clone this repo, install it, and run it** (either platform):

```bash
git clone https://github.com/nkalodner/murmur.git
uv tool install ./murmur
murmur
```

Notes:

- If `murmur` is not found after install, run `uv tool update-shell` and open a fresh terminal.
- To update later: quit Murmur first so its files are not locked, then `git -C murmur pull` and `uv tool install --reinstall ./murmur`. Relaunch when it finishes. [What's new](#whats-new) lists what changed in each version; if the reinstall errors out, see [Troubleshooting](#troubleshooting).
- To remove: `uv tool uninstall murmur-dictation`, then delete `~/.murmur` and the model in `~/.cache/huggingface`.

### First run

- The model downloads once from Hugging Face (about 700 MB) into your user cache. `murmur --download` grabs it ahead of time if you prefer.
- macOS asks for three permissions, all granted to your terminal app (Terminal, iTerm, and so on), since that is what runs Murmur:
  - **Microphone**: prompted automatically at launch.
  - **Input Monitoring**: lets Murmur see the hotkey. The prompt appears at launch; approve it and restart Murmur. The hotkey only attaches when Murmur starts, so a grant made while it is running does nothing until you quit and reopen it. The terminal and the settings page both tell you when that restart is the one step left.
  - **Accessibility**: lets Murmur paste. System Settings > Privacy & Security > Accessibility > enable your terminal.
  - **When all three are granted, restart your computer once.** Every permission applies cleanly at the next launch, and the key just works from then on.
- Windows needs no special permissions. To dictate into apps running as administrator, launch Murmur from an administrator terminal too.

`murmur --doctor` checks mic, model cache, permissions, and clipboard in one pass, and the settings page shows a banner whenever a permission still stands between you and a working hotkey.

### What Murmur sends

Nothing you say, ever. Transcription is entirely local, and there is no telemetry or analytics of any kind.

The one exception is the update check: once a day Murmur fetches a version number from this repo so it can tell you when a newer release exists. It is a plain download that sends no transcript, no settings, and nothing identifying you. Turn it off with **Check for updates** on the App tab, or `"update_check": false` in the config, and Murmur makes no network requests at all after the model has downloaded.

## What's new

Not sure which version you have? Run `murmur --version`, or look at the top of the settings page. Updating is the one line in [Install](#install) above.

### 0.11.0

- **The menu bar icon grew a real menu.** Switch the microphone right from the tray (a submenu with a checkmark on the live pick, updating the moment you change it), paste the last transcript again, pause dictation entirely, and toggle Start at login. A row appears when an update exists. Settings and Quit are where they always were.
- **The icon is a microphone now.** The same mark as Murmur's favicon instead of a plain dot, wearing the same state colors: gray idle, red recording, amber transcribing, dimmed while the model loads or dictation is paused.

### 0.10.1

- **The settings page got quieter.** Roughly half the words: every setting is one hairline row with its name on the left and its control on the right, toggles included, and each description was cut to the fact you need to decide.

### 0.10.0

- **The settings page became tabs.** Seven of them (Hotkeys, Recording, Typing, Sounds, Dictionary, Model, App) instead of one long scroll, with the address bar remembering which tab you are on. The old Behavior grab-bag is gone: recording things live with the mic, typing things live together, sounds live with sounds. Recent transcripts moved next to the dictionary they exist to test, the chime volume slider got its Play button on the same row, and Export and Import got proper icons.
- **The mic test reads like a result now.** The meter is zoned (red silent, amber faint, green good) on a decibel scale, so the bar always lands in the zone the verdict describes, a sweep animation shows while it listens, and a "Test complete" line names the device it heard. Cmd/Ctrl+S saves from anywhere on the page, the vocabulary and replacement lists show counts and say something useful when empty, and on a Mac the recording-pill toggle now explains itself instead of silently doing nothing.

### 0.9.1

- **The chime stopped ending up in your transcript.** The start cue sounds while the mic is already recording, so it was landing in the audio and the model typed it as "mm" or "mmhmm". Murmur now silences the microphone for exactly as long as the cue plays, so the take begins with your voice and nothing else. Nothing is lost from what you say: the muted stretch is the chime, which is over before you start talking.
- **Chime volume is yours to set.** A slider under Behavior, from 100% down to 0%. 0% silences the cues without turning the chimes off, so the timing (and the mic muting that goes with it) stays exactly as it was. The Play button previews the level you are dragging to, before you save.

### 0.9.0

- **Letters spelled out loud join into an acronym.** Say the letters and "W S A" types as `WSA`, "T F T" as `TFT`, "A R A M" as `ARAM`. Only runs of bare capital letters join, so "Plan A and Plan B" is safe, and the model's own punctuation breaks a run, so "A, B, or C" keeps its commas.
- **Spoken years and clock times come out as numbers, am/pm or not.** "twenty twenty six" types as `2026`, "nineteen ninety nine" as `1999`, "four thirty" as `4:30`, "three oh five" as `3:05`. Counting runs ("eighteen nineteen twenty") and quantities ("nineteen twenty years ago") are left as spoken. All of it sits under the existing **Auto-format speech** toggle, so one switch turns it off.
- **Setup says when it will actually work.** On a Mac, the settings page now shows a live banner while a permission is missing, and the moment you grant Input Monitoring it flips to the one remaining step: quit Murmur and open it again, because the hotkey only attaches at launch. The terminal says the same thing the moment the grant lands. The install instructions now spell out the new-terminal step and recommend one computer restart after granting the permissions, which makes everything stick.
- **The start chime is clean on the Mac.** The cue used to play through the app's own audio pipeline while the microphone stream was open, and those two competing is what left a little static in it no matter how the buffers were tuned. Chimes on macOS now go through the system's own sound player instead, the same path a notification sound takes, so the mic stream can no longer scratch them up. Windows keeps the path it already had.

### 0.8.0

- **Filler words get dropped.** "um" and "uh" no longer make it into what gets typed. Deliberately narrow: only sounds that are never real English words, so "umbrella", "uh-huh", and "the sum of" are all safe. On by default, under Behavior; add your own words to `filler_words` in `~/.murmur/config.json` if you want a heavier hand.
- **Murmur tells you when there is a new version.** It asks GitHub once a day and shows a banner in the settings page when a newer version exists, with the update command right there. **This is the only network request Murmur makes.** It sends no transcript, no config, and nothing that identifies you, and one toggle under Behavior turns it off. Your speech still never leaves the machine. Also `murmur --check-update`.

### 0.7.0

- **Only one copy runs at a time.** Starting Murmur while it is already running now exits with a note pointing at the copy you have. Two copies each transcribed and pasted the same speech, so everything got typed twice. Most common when Murmur starts at login and you also launch it in a terminal.
- **A second hotkey, and hotkeys can be combinations.** Two independent bindings, either of which starts dictation. Each can be one key or two or three held together, like `cmd+shift`. **Either can also be switched off**, so if you want only a combination and no bare key, turn the first one off. One has to stay on. See [Settings](#settings).
- **Quiet other audio while you talk.** Optional: the system volume drops while you are recording and returns to the exact level afterward, so dictating over a video does not fight the speaker. Off by default, under Behavior. macOS and Windows.

### 0.6.0

- **A real model menu.** Pick Parakeet v2 (the default), Parakeet v3 for 25 languages, Whisper base (80 MB, 99 languages), or Canary 1B v2, or type any other onnx-asr name or Hugging Face repo id. A bad name is now caught when you save it. See [Choosing a model](#choosing-a-model).
- **Your dictionary moves between machines.** Export it to a small file on one computer and import it on another; merges skip duplicates and never overwrite the entries already there. Also `murmur --export-dictionary` / `--import-dictionary`.

### 0.5.x

- **Auto-format speech** (0.5.0): spoken times, dates, percents, and dollars come out written, so "one pm" types as `1:00 PM`. Deliberately conservative about anything ambiguous.
- **A slimmer, smoother recording pill** on Windows and Linux (0.5.6, 0.5.7): just the bars that move with your voice, with properly rounded edges.
- **Start-at-login got more reliable on Windows** (0.5.8, 0.5.9): it now leads with a Startup-folder shortcut, which the antivirus and "startup manager" tools that quietly revert registry entries tend to leave alone.
- **macOS fixes**: changing the hotkey no longer quits the app (0.5.1), no stray Dock icon (0.5.2), the start chime stopped crackling (0.5.4), and both permission prompts now appear so you can grant them from the dialog instead of hunting for the binary (0.5.5).
- **Copying while Murmur pasted no longer lost your clipboard** (0.5.3).

### 0.4.0

- **The recording pill**: a small always-on-top overlay with live level bars while you talk (Windows and Linux).
- **The dictionary stopped over-reaching**: a short name like "Andi" no longer rewrites every "and" and "and I".

### 0.3.0

- **Start at login**, with a windowless launcher (`murmurw`) so Murmur runs from the tray with no terminal open.
- **Test mic** in the settings page, and a softer start chime.

### 0.2.0

- **The local settings page** (tray menu or `murmur --settings`) and the **personal dictionary**: vocabulary that snaps close-sounding transcripts to your spelling, plus exact heard-to-typed replacements.

## Using it

| Action | What happens |
| --- | --- |
| Hold Right Ctrl, speak, release | Transcribes and pastes at your cursor |
| Hold your second hotkey (if set) | Exactly the same, from whichever key or combination you bound |
| Quick-tap Right Ctrl | Starts hands-free recording; tap again to finish |
| Esc while recording | Cancels, nothing is pasted |

The menu bar icon is a small microphone that wears the state: gray idle, red recording, amber transcribing, dimmed while loading or paused. Its menu covers the day-to-day without opening the settings page: switch the microphone, paste the last transcript, pause dictation, toggle Start at login, and quit. Short chimes confirm ready, start, stop, and cancel.

Recordings stop automatically after 2 minutes (`max_seconds`). Longer stretches of audio are split at pauses and transcribed piece by piece. Every transcript is also appended to `~/.murmur/history.jsonl`, so pasting into the wrong window never loses your words.

## Settings

`murmur --settings` opens the settings page, starting Murmur first if it needs to. It is also in the tray menu, and double-clicking the tray icon opens it on Windows. The page is served by Murmur itself on `127.0.0.1` only; nothing leaves your machine. Changes apply immediately, including the hotkey, and persist to `~/.murmur/config.json`. Since 0.10.0 the page is organized as seven tabs instead of one long scroll:

- **Hotkeys**: two independent bindings, and either one starts dictation. Each can be a single key or two or three held together (`cmd+shift`); press the combination while changing to record it. Esc stays reserved for canceling a recording.
  - **Either one can be switched off**, so long as one is left. Want only a two-key combination and no bare key? Switch the first one off. Murmur refuses to leave you with both off, since there would be no way to dictate.
  - The two cannot overlap: if one is contained in the other (`ctrl_r` and `ctrl_r+space`), the shorter one always fires first, so Murmur rejects that pair instead of leaving you with a hotkey that never works.
- **Recording**: pick a microphone or leave it on the system default, and Test mic listens for about a second and shows where your voice lands on a zoned meter (red silent, amber faint, green good), with a clear "Test complete" line naming the device it heard. The same tab holds the recording pill (a small always-on-top overlay with bars that move to your voice; Windows and Linux, since macOS shows the menu-bar mic instead), the max recording length, and the tap-lock window.
- **Typing**: everything about what lands at your cursor. **Auto-format speech**: spoken times, dates, numbers, and spelled-out acronyms come out written, so "one pm" types as `1:00 PM`, "four thirty" as `4:30`, "twenty twenty six" as `2026`, "fifty percent" as `50%`, and letters said one at a time join up, "W S A" as `WSA`; grammar the model itself writes is trusted, so "which one am I" is never mangled and "A, B, or C" keeps its commas. **Drop filler words**: "um" and "uh" never get typed, and only sounds that are never real words are on the list (`filler_words` in the config takes additions). Plus trailing space, paste versus type-it-out, and the clipboard restore delay.
- **Sounds**: chimes on or off, with **Chime volume** and its Play preview on the same row (0% is silent without switching chimes off). Murmur mutes the mic for exactly the length of the start cue, so the chime can never be recorded and transcribed as "mm". **Quiet other audio** turns the system volume down while you talk and puts it back at the exact level afterward (off by default; macOS and Windows; the slider sets how far down).
- **Dictionary**: see below. Recent transcripts sit on the same tab, newest first, so testing an entry is dictate, refresh, check, and the keep-history toggle is right beside the list it feeds.
- **Model**: pick from the menu (Parakeet v2/v3, Whisper base, Canary 1B v2) or enter any onnx-asr name / Hugging Face repo id via Custom, plus precision and a language code for the models that read one. A new model downloads on first use and loads on the next dictation. See [Choosing a model](#choosing-a-model).
- **App**: Open Murmur at login (Windows and macOS; see [below](#do-i-need-to-keep-the-terminal-open-start-at-login)) and the daily update check, which is the only network request Murmur makes and sends nothing about you.

### The dictionary

Two mechanisms, both applied to every transcript before it is pasted:

- **Vocabulary**: words and phrases spelled and cased exactly how you want them typed. Transcripts that come out close snap to your spelling, so "pie torch" becomes "PyTorch" and "photo globe" becomes "Photoglobe". Ordinary spoken words are left alone, so a short name like "Andi" never rewrites "and" or "and I", and very short entries only snap on a near-exact match. Match sensitivity (`vocab_threshold`) sets how close a word must sound before it snaps; add proper nouns and jargon.
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
| `hotkey` | `"ctrl_r"` | The push-to-talk key (pynput names); `null` switches it off |
| `hotkey2` | `null` | A second binding that also starts dictation; join keys with `+` (`"cmd+shift"`) |
| `model` | `"nemo-parakeet-tdt-0.6b-v2"` | Any onnx-asr model name |
| `quantization` | `"int8"` | `null` for full precision (bigger, slower on CPU) |
| `language` | `null` | Only read by whisper/canary models; Parakeet v3 auto-detects |
| `device` | `null` | Mic name substring; `null` uses the system default |
| `sounds` | `true` | Audio cues on state changes |
| `sound_volume` | `100` | How loud the cues are, 0-100; `0` is silent |
| `paste` | `true` | `false` types character by character instead of pasting |
| `restore_clipboard_ms` | `600` | Delay before restoring your previous clipboard; `-1` never restores |
| `tap_lock_ms` | `350` | Presses shorter than this lock hands-free recording |
| `max_seconds` | `120` | Auto-stop for a single recording |
| `trailing_space` | `true` | Append a space so back-to-back dictations flow |
| `history` | `true` | Log transcripts to `~/.murmur/history.jsonl` |
| `pill` | `true` | Floating recording overlay (Windows/Linux) |
| `formatting` | `true` | Spoken times/dates/numbers/acronyms become written forms (4:30, 2026, WSA) |
| `remove_fillers` | `true` | Drop filler words from transcripts before they are typed |
| `filler_words` | `["um","uh","erm","uhm"]` | The words removed. Add your own for a more aggressive pass |
| `update_check` | `true` | Ask GitHub once a day whether a newer Murmur exists |
| `duck_audio` | `false` | Turn other audio down while recording, then restore it (macOS/Windows) |
| `duck_percent` | `20` | Output volume to drop to while recording, as a percentage |
| `vocabulary` | `[]` | Dictionary words/phrases, spelled how they should be typed |
| `replacements` | `[]` | Exact fixes: `{"from": "heard", "to": "typed"}` |
| `vocab_threshold` | `0.82` | How close a word must sound to snap to vocabulary (lower catches more) |

Hotkey names come from pynput: `ctrl_r`, `alt_r`, `cmd_r`, `f8`, `pause`, and friends. Join two or three with `+` for a combination (`cmd+shift`). Set either binding to `null` to switch it off; at least one has to stay on. Pick a key that types nothing on its own; bare modifiers work best. On international Windows layouts `alt_r` is AltGr, so prefer `ctrl_r` there.

CLI flags override the config for one run, and a few act and exit:

```
murmur --hotkey f8 --model nemo-parakeet-tdt-0.6b-v3 --type --no-sounds --no-tray -v
murmur --hotkey2 cmd+shift   # a second hotkey that also starts dictation
murmur --settings            # open the settings page
murmur --enable-autostart    # start at login (also --disable-autostart)
murmur --list-devices        # list input devices
murmur --doctor              # check mic, model, permissions, clipboard
murmur --check-update        # ask GitHub whether a newer version exists
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
- **A reinstall fails with "Invalid environment ... missing Python executable", or "Access is denied" on Windows**: uv cannot repair the tool's environment in place, either because it was left half-written (the managed Python it used moved) or because Murmur is still running and Windows has its files locked. Quit Murmur completely first: right-click the tray or menu-bar icon and choose Quit (if it starts at login it may be running on its own). Then remove it and install fresh:
  - Any platform: `uv tool uninstall murmur-dictation`, then run your install line again (`uv tool install ./murmur`, or the archive URL if that is how you installed).
  - Windows, if the uninstall still reports "Access is denied": a copy is still holding the files. Stop it and clear the folder in PowerShell, then install again:
    ```powershell
    Get-Process murmur*,python*,pythonw* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*uv\tools\murmur-dictation*" } | Stop-Process -Force
    Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\murmur-dictation"
    ```
    If it still will not delete, reboot and run those lines before opening anything else. Your settings (`~/.murmur`) and the downloaded model are untouched.
- **Hotkey does nothing (macOS)**: Input Monitoring permission is missing, or it was granted while Murmur was already running. The hotkey only attaches at launch, so the fix is always the same: grant it to your terminal (`murmur --doctor` and the settings page both confirm which state you are in), then quit Murmur and open it again. Granted it and it still does nothing? Restart the computer once; that clears every cached permission state.
- **Nothing pastes (macOS)**: same story with the Accessibility permission.
- **The hotkey or pasting stops after an update (macOS)**: macOS ties Input Monitoring and Accessibility to the exact program, and `uv tool install --reinstall` can reset them. Re-grant in System Settings > Privacy & Security; `murmur --doctor` shows what is missing.
- **A key you rebound to does nothing (macOS)**: some top-row F-keys are media keys (volume, brightness) that Murmur cannot see. Hold Fn while pressing it, enable "Use F1, F2, etc. keys as standard function keys" in System Settings, or pick a bare modifier like `cmd_r`.
- **An app rejects the paste** (some terminals, password fields): set `"paste": false` to type the text instead.
- **Clipboard contents vanished**: Murmur restores text clipboards after pasting, but images and files are lost. Set `restore_clipboard_ms` to `-1` if you would rather keep the transcript on the clipboard.
- **It does not start at login (Windows)**: run `murmur --enable-autostart` and confirm it prints "Murmur will start at login." Startup is per-machine, so enabling it on your Mac never sets up Windows. Murmur should then appear under Task Manager > Startup Apps; if that list shows it as *Disabled*, right-click and choose Enable, since Windows keeps its own on/off flag that can override the entry. If the command reports it cannot find `murmur` on PATH, run `uv tool update-shell`, open a fresh terminal, and try again. After a `uv tool` reinstall or upgrade that moves the command, run the enable line once more to refresh the path it points at.
- **Enabling reports that Windows removed the startup entry**: some antivirus and "startup manager" tools revert startup changes made by apps they do not recognize. On Windows, Murmur starts by placing a shortcut in your Startup folder (these tools usually leave it alone), and only falls back to a registry entry if the folder is blocked too. If it reports both were removed, allow Murmur (`murmurw.exe`) in that tool, or add the shortcut yourself: press Win+R, run `shell:startup`, and drop a shortcut to `murmurw.exe` in the folder that opens.
- **"Murmur is already running, so this copy will not start"**: exactly what it says, and it is a guard, not an error. Only one copy runs at a time, because two would each transcribe and paste the same speech, typing everything twice. Use the copy already running (its tray or menu-bar icon, or `murmur --settings`), or quit that one first if you want a fresh start. This is the common surprise when Murmur starts at login and you also launch it in a terminal.
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
