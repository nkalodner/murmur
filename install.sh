#!/bin/sh
# Murmur, in one line (macOS and Linux):
#
#   curl -LsSf https://raw.githubusercontent.com/nkalodner/murmur/main/install.sh | sh
#
# Installs uv if it is missing, then installs Murmur from the published
# archive. The archive rather than a git clone, so this needs no git and
# leaves no checkout to keep track of; `murmur --update` uses the same source.
#
# Two things this exists to fix. Installing uv puts it somewhere the shell you
# are typing in does not know about yet, which is the "murmur: command not
# found" everyone hits, so this adds it to PATH for its own run and then tells
# you exactly where the command landed. And nothing here prompts: stdin is the
# script itself when it arrives through a pipe, so a read would eat the rest
# of the file.
set -eu

say() { printf '%s\n' "$*"; }
die() { printf 'Install failed: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl is needed and is not installed."

VERSION_SOURCE="https://raw.githubusercontent.com/nkalodner/murmur/main/src/murmur/__init__.py"
VERSION="$(curl -LsSf "$VERSION_SOURCE" | sed -n 's/^__version__ = ["'\'']\([^"'\'']*\)["'\'']/\1/p')"
[ -n "$VERSION" ] || die "could not determine the latest Murmur release."
ARCHIVE="https://github.com/nkalodner/murmur/archive/refs/tags/v${VERSION}.zip"


if command -v uv >/dev/null 2>&1; then
  say "uv is already installed."
else
  say "Installing uv, which installs and manages Python for you..."
  curl -LsSf https://astral.sh/uv/install.sh | sh \
    || die "could not install uv. See https://docs.astral.sh/uv/ and try again."
fi

# uv drops its binary in one of these. Add whichever exists to PATH for this
# script, so a fresh install works in the same breath instead of needing a new
# terminal first.
for dir in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
  if [ -d "$dir" ]; then
    case ":$PATH:" in
      *":$dir:"*) ;;
      *) PATH="$dir:$PATH" ;;
    esac
  fi
done
export PATH

command -v uv >/dev/null 2>&1 \
  || die "uv installed but is not on PATH. Open a new terminal and run this again."

PYTHON_VERSION="3.12"

say ""
say "Installing Murmur (this pulls a Python and builds it; give it a minute)..."
# Pin a uv-managed Python rather than reusing whatever is on the machine, so a
# system Python that later moves or disappears cannot strand the install. (The
# Windows installer does the same for a sharper reason: see install.ps1.)
uv python install "$PYTHON_VERSION" >/dev/null 2>&1 || true
PYTHON="$(uv python find "$PYTHON_VERSION" 2>/dev/null | head -n 1 || true)"
if [ -n "$PYTHON" ]; then
  uv tool install --force --reinstall --python "$PYTHON" "$ARCHIVE" \
  || die "uv could not install Murmur. Troubleshooting: https://github.com/nkalodner/murmur#troubleshooting"
else
  uv tool install --force --reinstall "$ARCHIVE" \
  || die "uv could not install Murmur. Troubleshooting: https://github.com/nkalodner/murmur#troubleshooting"
fi

MURMUR="$(command -v murmur || true)"
say ""
say "Murmur is installed."
say ""
if [ -n "$MURMUR" ]; then
  say "Start it with:  murmur"
  say "(If your terminal says 'command not found', open a new terminal window"
  say " first. Only a new one knows where the command landed.)"
else
  say "Start it by opening a NEW terminal window and running:  murmur"
fi
say ""
if [ "$(uname -s)" = "Darwin" ]; then
  say "The first launch asks for three macOS permissions, all granted to your"
  say "terminal app, since that is what runs Murmur: Microphone, Input"
  say "Monitoring (for the hotkey), and Accessibility (for pasting). Grant all"
  say "three, then restart your computer once and the hotkey just works."
  say ""
fi
say "The model downloads once on first use (about 700 MB). Hold Right Ctrl,"
say "talk, let go. Settings open on the first run; 'murmur --settings' after."
say "Murmur opens at login from now on; the App tab has the switch."
