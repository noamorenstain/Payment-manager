# Payment Manager - installer (ASCII-only file; Hebrew text is built from code points).
#   * Finds Python 3.12/3.13 installed from python.org
#   * Creates an isolated environment in %LOCALAPPDATA%\PaymentManager\venv (outside OneDrive)
#   * Installs the pinned libraries (internet needed only for this step)
#   * Creates the data folder %USERPROFILE%\PaymentManagerData (only missing folders; never
#     touches existing data)
#   * Creates (or refreshes) a desktop shortcut
#
# Safe to run any number of times: an existing healthy environment is reused, existing data
# is never modified, and the shortcut is simply replaced with an up-to-date one.
param(
    [switch]$NoShortcut,
    [switch]$Dev,
    # For testing only: create the shortcut in this folder instead of the Desktop.
    [string]$ShortcutDir
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppHome = Join-Path $env:LOCALAPPDATA 'PaymentManager'
$VenvDir = Join-Path $AppHome 'venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$IconPath = Join-Path $ProjectRoot 'app\static\img\icon.ico'

# "Payment Manager" in Hebrew, and an ASCII fallback name.
$HebrewName = -join ([char[]](0x05DE,0x05E0,0x05D4,0x05DC,0x0020,0x05EA,0x05E9,0x05DC,0x05D5,0x05DE,0x05D9,0x05DD))
$AsciiName = 'Payment Manager'
$TempLinkName = 'PaymentManager.install-tmp.lnk'

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "    WARNING: $text" -ForegroundColor Yellow }

function Find-Python {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($v in '3.13', '3.12') {
            try {
                $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
            } catch { }
        }
    }
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike '*WindowsApps*') {
        $ok = & $candidate.Source -c "import sys; print(int(sys.version_info >= (3, 12)))" 2>$null
        if ($ok -eq '1') { return $candidate.Source }
    }
    return $null
}

function Test-VenvHealthy {
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }
    try {
        $out = & $VenvPython -c "import sys; print(int(sys.version_info >= (3, 12)))" 2>$null
        return ($LASTEXITCODE -eq 0 -and $out -eq '1')
    } catch { return $false }
}

function Get-DesktopDir {
    # The real Desktop, including OneDrive-redirected desktops (read from the user's
    # Known Folder settings, not assumed to be %USERPROFILE%\Desktop).
    $candidates = @(
        [Environment]::GetFolderPath('Desktop'),
        (New-Object -ComObject WScript.Shell).SpecialFolders.Item('Desktop')
    )
    foreach ($dir in $candidates) {
        if ($dir -and (Test-Path -LiteralPath $dir -PathType Container)) { return $dir }
    }
    return $null
}

function Get-LinkInfo([string]$Dir, [string]$FileName) {
    # Shell.Application is Unicode-aware (WScript.Shell is not), so it can read Hebrew names.
    $folder = (New-Object -ComObject Shell.Application).Namespace($Dir)
    if (-not $folder) { return $null }
    $item = $folder.ParseName($FileName)
    if (-not $item -or -not $item.IsLink) { return $null }
    return $item.GetLink
}

function New-AppShortcut([string]$Dir) {
    # WScript.Shell converts file names to the legacy ANSI code page, so a Hebrew name turns
    # into "????" (illegal characters) and Save() fails. Therefore: save under an ASCII
    # temporary name, then rename with the Unicode-safe PowerShell file APIs.
    foreach ($required in @($VenvPython, $ProjectRoot, $IconPath)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required path is missing: $required" }
    }

    $tempPath = Join-Path $Dir $TempLinkName
    if (Test-Path -LiteralPath $tempPath) { Remove-Item -LiteralPath $tempPath -Force }

    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($tempPath)
    $link.TargetPath = $VenvPython
    $link.Arguments = '-m app'
    $link.WorkingDirectory = $ProjectRoot
    $link.IconLocation = "$IconPath,0"
    $link.WindowStyle = 7   # start minimized
    $link.Description = 'Payment Manager'
    $link.Save()

    $finalName = $null
    foreach ($name in @($HebrewName, $AsciiName)) {
        try {
            Move-Item -LiteralPath $tempPath -Destination (Join-Path $Dir "$name.lnk") -Force
            $finalName = "$name.lnk"
            break
        } catch {
            Write-Warn "Could not use the name '$name': $($_.Exception.Message)"
        }
    }
    if (-not $finalName) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        throw 'Could not save the shortcut under any name.'
    }

    # Keep exactly one shortcut: if the Hebrew one succeeded, remove an ASCII one left by an
    # older install (only if it is ours, i.e. it points at this environment).
    if ($finalName -eq "$HebrewName.lnk") {
        $old = Get-LinkInfo $Dir "$AsciiName.lnk"
        if ($old -and $old.Path -eq $VenvPython) {
            Remove-Item -LiteralPath (Join-Path $Dir "$AsciiName.lnk") -Force
        }
    }

    # Verify what was written.
    $info = Get-LinkInfo $Dir $finalName
    if (-not $info) { throw "Shortcut was not created: $(Join-Path $Dir $finalName)" }
    if ($info.Path -ne $VenvPython -or $info.Arguments -ne '-m app' -or $info.WorkingDirectory -ne $ProjectRoot) {
        throw "Shortcut verification failed (target='$($info.Path)', args='$($info.Arguments)', dir='$($info.WorkingDirectory)')."
    }
    return (Join-Path $Dir $finalName)
}

# ---------------------------------------------------------------- 1. Python
Write-Step 'Looking for Python 3.12 or 3.13'
$Python = Find-Python
if (-not $Python) {
    Write-Host ''
    Write-Host 'Python 3.12 or newer was not found.' -ForegroundColor Red
    Write-Host 'Install it (free) from https://www.python.org/downloads/windows/'
    Write-Host 'and tick "Add python.exe to PATH" and "py launcher", then run install.bat again.'
    exit 1
}
Write-Host "    Using $Python"

# ---------------------------------------------------------------- 2. Environment
if (Test-VenvHealthy) {
    Write-Step 'Environment already exists - reusing it'
} else {
    if (Test-Path -LiteralPath $VenvDir) {
        # Only the program environment is rebuilt; it never contains user data.
        Write-Step "Environment is damaged or outdated - rebuilding $VenvDir"
        & $Python -m venv --clear $VenvDir
    } else {
        Write-Step "Creating environment in $VenvDir"
        New-Item -ItemType Directory -Force -Path $AppHome | Out-Null
        & $Python -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-VenvHealthy)) { throw 'Creating the Python environment failed.' }
}

# ---------------------------------------------------------------- 3. Libraries
$req = if ($Dev) { 'requirements-dev.txt' } else { 'requirements.txt' }
$reqPath = Join-Path $ProjectRoot $req
& $VenvPython (Join-Path $PSScriptRoot 'check_requirements.py') $reqPath | Out-Null
if ($LASTEXITCODE -eq 0) {
    # Re-runs work offline and leave a complete environment untouched.
    Write-Step "Libraries from $req are already installed - skipping"
} else {
    Write-Step "Installing libraries from $req (one-time internet access)"
    & $VenvPython -m pip install --disable-pip-version-check --quiet -r $reqPath
    if ($LASTEXITCODE -ne 0) { throw 'Installing libraries failed. Check the internet connection and try again.' }
}

# ---------------------------------------------------------------- 4. Data folder
Write-Step 'Preparing the data folder (existing data is never changed)'
Push-Location $ProjectRoot
try {
    & $VenvPython -m app --init-only
    if ($LASTEXITCODE -ne 0) { throw 'Preparing the data folder failed.' }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------- 5. Shortcut
$shortcutOk = $true
if (-not $NoShortcut) {
    Write-Step 'Creating desktop shortcut'
    $targetDir = if ($ShortcutDir) { $ShortcutDir } else { Get-DesktopDir }
    if (-not $targetDir -or -not (Test-Path -LiteralPath $targetDir -PathType Container)) {
        Write-Warn 'The Desktop folder could not be found.'
        $shortcutOk = $false
    } else {
        try {
            $created = New-AppShortcut $targetDir
            Write-Host "    $created"
        } catch {
            Write-Warn "The shortcut could not be created: $($_.Exception.Message)"
            $shortcutOk = $false
        }
    }
}

Write-Host ''
if ($shortcutOk) {
    Write-Host 'Installation complete. Start Payment Manager from the desktop shortcut or start.bat.' -ForegroundColor Green
} else {
    Write-Host 'Installation complete, but without a desktop shortcut.' -ForegroundColor Yellow
    Write-Host "Start Payment Manager by double-clicking start.bat in: $ProjectRoot" -ForegroundColor Yellow
}
exit 0
