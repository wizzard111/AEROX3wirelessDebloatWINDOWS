# Aerox Lite installer for Windows (started by "Install Aerox Lite.bat").
# Per-user install, no administrator rights: %LOCALAPPDATA%\Programs\AeroxLite,
# Start menu (and optional desktop) shortcut, entry in Settings > Apps for uninstalling.
# Uses the ready-made program folder next to this script (release download) or builds it from source.
param(
    [switch]$Yes,
    [switch]$NoLaunch,
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\AeroxLite",
    [string]$StartMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string]$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AeroxLite",
    [string]$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$isRelease = Test-Path (Join-Path $here "AeroxLite\AeroxLite.exe")
$root = if ($isRelease) { (Resolve-Path (Join-Path $here "..")).Path } else { (Resolve-Path (Join-Path $here "..\..")).Path }
$log = Join-Path $root "install.log"
try { Start-Transcript -Path $log -Force | Out-Null } catch { }

function Step([string]$text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Ask([string]$question) {
    if ($Yes) { return $true }
    $a = Read-Host "$question [Y/n]"
    return (-not $a) -or ($a -match '^[Yy]')
}
function Fail([string]$text) {
    Write-Host ""; Write-Host "Installation failed: $text" -ForegroundColor Red
    Write-Host "Full log: $log"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

Write-Host "================================================"
Write-Host "  Aerox Lite installer"
Write-Host ("  " + (Get-CimInstance Win32_OperatingSystem).Caption + ", " + $env:PROCESSOR_ARCHITECTURE)
Write-Host "================================================"

# ---------------------------------------------------------------- 1. SteelSeries GG
$gg = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "SteelSeriesGG*" -or $_.ProcessName -like "SteelSeriesEngine*" }
if ($gg) {
    Step "SteelSeries GG is running"
    Write-Host "It overwrites the mouse settings and lighting while it runs."
    if (Ask "Quit SteelSeries GG now?") {
        $gg | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Host "Done. To stop it from starting with Windows: Task Manager > Startup apps > SteelSeries GG > Disable."
    }
}

# ---------------------------------------------------------------- 2. the program
. (Join-Path $here "build.ps1")
if ($isRelease) {
    $exe = Join-Path $here "AeroxLite\AeroxLite.exe"
    Step "Using the ready-made program from this download"
} else {
    $exe = Join-Path $root "build\dist\AeroxLite\AeroxLite.exe"
    if (Test-AeroxExe $exe) {
        Step "Using the program built earlier ($exe)"
    } else {
        Step "Looking for Python 3.10 - 3.14 with Tcl/Tk"
        $py = Find-Python
        if ($py) {
            Write-Host "Found Python $($py.Version): $($py.Path)"
        } else {
            Write-Host "No suitable Python found. The official installer from python.org (about 30 MB) is needed once."
            if (-not (Ask "Download and install it now (for your user only, no admin rights)?")) { Fail "Python is required." }
            Step "Finding the latest Python 3.14 release"
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $listing = (Invoke-WebRequest -UseBasicParsing "https://www.python.org/ftp/python/").Content
            $versions = [regex]::Matches($listing, 'href="(3\.14\.\d+)/"') | ForEach-Object { [version]$_.Groups[1].Value } | Sort-Object -Descending
            $url = $null
            foreach ($v in $versions) {
                $candidate = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
                try { Invoke-WebRequest -UseBasicParsing -Method Head $candidate | Out-Null; $url = $candidate; break } catch { }
            }
            if (-not $url) { Fail "could not find the Python installer. Install Python from https://www.python.org/downloads/windows/ and run this again." }
            $setup = Join-Path $env:TEMP "python-setup-aerox.exe"
            Step "Downloading $url"
            Invoke-WebRequest -UseBasicParsing $url -OutFile $setup
            Step "Installing Python (this takes a minute)"
            $p = Start-Process $setup -ArgumentList "/quiet InstallAllUsers=0 InstallLauncherAllUsers=0 Include_tcltk=1 Include_launcher=1 Include_test=0 PrependPath=0" -Wait -PassThru
            Remove-Item $setup -ErrorAction SilentlyContinue
            if ($p.ExitCode -ne 0) { Fail "the Python installer returned code $($p.ExitCode)" }
            $py = Find-Python
            if (-not $py) { Fail "Python was installed but could not be found. See $log" }
            Write-Host "Python $($py.Version) is ready."
        }
        Step "Building Aerox Lite (takes a few minutes the first time)"
        try { $exe = @(Invoke-AeroxBuild $root $py.Path)[-1] } catch { Fail "$_" }
    }
}
if (-not (Test-AeroxExe $exe)) { Fail "the program failed its self-test" }

# ---------------------------------------------------------------- 3. install for this user
Step "Installing to $InstallDir"
# Close the copy being replaced (only the one running from the install folder, not a portable copy elsewhere).
Get-Process AeroxLite -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500
# The program is a folder (AeroxLite.exe + _internal). Replace the previous version completely.
if (Test-Path $InstallDir) {
    Get-ChildItem $InstallDir -Force | Where-Object { $_.Name -ne "uninstall.ps1" } | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item (Join-Path (Split-Path $exe) "*") $InstallDir -Recurse -Force
$target = Join-Path $InstallDir "AeroxLite.exe"
Copy-Item (Join-Path $here "uninstall.ps1") (Join-Path $InstallDir "uninstall.ps1") -Force
# Downloaded files carry "from the internet": SmartScreen would ask on every start.
Get-ChildItem $InstallDir -Recurse -File | Unblock-File

Step "Creating shortcuts"
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $target; $s.WorkingDirectory = $InstallDir; $s.IconLocation = "$target,0"
    $s.Description = "SteelSeries Aerox 3 Wireless settings"
    $s.Save()
}
New-Item -ItemType Directory -Force $StartMenuDir | Out-Null
New-Shortcut (Join-Path $StartMenuDir "Aerox Lite.lnk")
Write-Host "Start menu: Aerox Lite"
if (Ask "Also put a shortcut on the desktop?") {
    try {
        New-Item -ItemType Directory -Force $DesktopDir | Out-Null
        New-Shortcut (Join-Path $DesktopDir "Aerox Lite.lnk"); Write-Host "Desktop: Aerox Lite"
    } catch { Write-Host "Could not create the desktop shortcut ($_); the Start menu entry works." }
}

Step "Registering in Settings > Apps (for uninstalling)"
$uninstall = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $InstallDir "uninstall.ps1") + '"'
New-Item -Force $UninstallKey | Out-Null
$props = @{
    DisplayName = "Aerox Lite"; DisplayVersion = "5.0.1"; Publisher = "reflex"
    DisplayIcon = $target; InstallLocation = $InstallDir; UninstallString = $uninstall
    URLInfoAbout = "https://github.com/wizzard111/AEROX3wirelessDebloatWINDOWS"
}
foreach ($k in $props.Keys) { New-ItemProperty -Path $UninstallKey -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
foreach ($k in "NoModify", "NoRepair") { New-ItemProperty -Path $UninstallKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
$kb = [int]((Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
New-ItemProperty -Path $UninstallKey -Name EstimatedSize -Value $kb -PropertyType DWord -Force | Out-Null

# "Start with Windows" from an older copy (e.g. in Downloads) should now start the installed one.
$run = Get-ItemProperty -Path $RunKey -Name AeroxLite -ErrorAction SilentlyContinue
if ($run) {
    Set-ItemProperty -Path $RunKey -Name AeroxLite -Value ('"' + $target + '" --tray')
    Write-Host "Autostart now points to the installed program."
}

# ---------------------------------------------------------------- 4. start
if (-not $NoLaunch) {
    Step "Starting Aerox Lite"
    Start-Process $target -WorkingDirectory $InstallDir
}
Write-Host ""
Write-Host "Aerox Lite is installed. Open it from the Start menu: Aerox Lite."
Write-Host "  * Tick 'Start with Windows' in the app to start it automatically."
Write-Host "  * Click 'SAVE TO MOUSE' after changing settings."
Write-Host "  * To remove it: Settings > Apps > Aerox Lite > Uninstall (or 'Uninstall Aerox Lite.bat')."
try { Stop-Transcript | Out-Null } catch { }
