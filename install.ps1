# Murmur, in one line (Windows PowerShell):
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/nkalodner/murmur/main/install.ps1 | iex"
#
# Installs uv if it is missing, then installs Murmur from the published
# archive. The archive rather than a git clone, so this needs no git and
# leaves no checkout to keep track of; `murmur --update` uses the same source.
#
# The thing this exists to fix: installing uv puts it somewhere the PowerShell
# window you are typing in does not know about yet, which is the "murmur is
# not recognized" everyone hits. This refreshes PATH for its own run and then
# tells you exactly where the command landed.

$ErrorActionPreference = "Stop"
$VersionSource = "https://raw.githubusercontent.com/nkalodner/murmur/main/src/murmur/__init__.py"
try {
    $VersionFile = Invoke-RestMethod $VersionSource
} catch {
    Write-Error "Could not determine the latest Murmur release."
    exit 1
}
if ($VersionFile -notmatch '__version__\s*=\s*["'']([^"'']+)["'']') {
    Write-Error "The published Murmur version is invalid."
    exit 1
}
$Archive = "https://github.com/nkalodner/murmur/archive/refs/tags/v$($Matches[1]).zip"

function Refresh-Path {
    # uv writes to the user PATH; this process still has the old copy.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = @($machine, $user, "$env:USERPROFILE\.local\bin") -join ";"
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "uv is already installed."
} else {
    Write-Host "Installing uv, which installs and manages Python for you..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Error "Could not install uv. See https://docs.astral.sh/uv/ and try again."
        exit 1
    }
    Refresh-Path
}

$PythonVersion = "3.12"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Refresh-Path
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv installed but is not on PATH. Open a new PowerShell window and run this again."
    exit 1
}

Write-Host ""
Write-Host "Installing Murmur (this pulls a Python and builds it; give it a minute)..."
# Pin a uv-managed Python rather than letting uv reuse whatever is on the box.
# The Microsoft Store python is the trap: its environments carry reparse points
# uv cannot delete, so a later update dies with os error 4395 and the launcher
# stops resolving. `uv python install` can fail on the symlink it makes last
# while still having installed a working interpreter, so the find comes after
# and decides on its own.
# uv reports progress on stderr, and under $ErrorActionPreference = "Stop"
# PowerShell 5.1 turns redirected native stderr into a terminating error.
# Relax it for these two lines only; their exit status is decided below.
$Prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
uv python install $PythonVersion *> $null
$Python = (uv python find $PythonVersion 2> $null | Select-Object -First 1)
$ErrorActionPreference = $Prev
if ($Python) {
    uv tool install --force --reinstall --python $Python $Archive
} else {
    Write-Host "Could not place a managed Python; using whatever uv picks."
    uv tool install --force --reinstall $Archive
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "uv could not install Murmur. Troubleshooting: https://github.com/nkalodner/murmur#troubleshooting"
    exit $LASTEXITCODE
}

Refresh-Path
Write-Host ""
Write-Host "Murmur is installed."
Write-Host ""
Write-Host "Start it by opening a NEW PowerShell window and running:  murmur"
Write-Host "(Only a new window knows where the command landed.)"
Write-Host ""
Write-Host "Windows needs no special permissions. To dictate into apps running as"
Write-Host "administrator, start Murmur from an administrator terminal too."
Write-Host ""
Write-Host "The model downloads once on first use (about 700 MB). Hold Right Ctrl,"
Write-Host "talk, let go. Settings open on the first run; 'murmur --settings' after."
Write-Host "Murmur opens at login from now on; the App tab has the switch."
