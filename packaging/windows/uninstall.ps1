# Removes Aerox Lite installed by install.ps1, then asks whether to keep the settings and the download
# folder, or remove everything (including the installer and the uninstaller).
# Exit code 10 asks "Uninstall Aerox Lite.bat" to delete the download folder after this script ends
# (a running .bat cannot delete its own folder earlier).
# Non-interactive: -AppOnly (keep settings and folder), -All (remove everything), -Purge (= -All).
param(
    [switch]$AppOnly,
    [switch]$All,
    [switch]$Purge,
    [string]$PackageDir = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\AeroxLite",
    [string]$StartMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string]$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AeroxLite",
    [string]$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    [string]$SettingsDir = "$env:APPDATA\AeroxLite"
)
$ErrorActionPreference = "Continue"

# Only a folder that is clearly the Aerox Lite download may be deleted as a whole.
$pkg = $null
if ($PackageDir) {
    try { $p = (Resolve-Path $PackageDir).Path.TrimEnd('\') } catch { $p = $null }
    if ($p -and (Test-Path (Join-Path $p "Install Aerox Lite.bat")) -and
        ((Test-Path (Join-Path $p "app")) -or (Test-Path (Join-Path $p "src")) -or (Test-Path (Join-Path $p "packaging"))) -and
        ($p -ne $env:USERPROFILE) -and ($p.Length -gt 3)) { $pkg = $p }
}

Write-Host "================================================"
Write-Host "  Aerox Lite uninstaller"
Write-Host "================================================"
if ($AppOnly) { $choice = "1" }
elseif ($All -or $Purge) { $choice = "2" }
else {
    Write-Host "What should be removed?"
    Write-Host "  1) Only the app            (your settings and this folder stay)"
    if ($pkg) {
        Write-Host "  2) Everything              (the app, its settings and this folder:"
        Write-Host "                              $pkg"
        Write-Host "                              including the installer and this uninstaller)"
    } else {
        Write-Host "  2) The app and its settings"
    }
    $choice = Read-Host "Choose [1/2]"
    Write-Host ""
}

Write-Host "Removing Aerox Lite..."
# Close the installed copy (only the one running from the install folder, not a portable copy elsewhere).
Get-Process AeroxLite -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

$run = Get-ItemProperty -Path $RunKey -Name AeroxLite -ErrorAction SilentlyContinue
if ($run) { Remove-ItemProperty -Path $RunKey -Name AeroxLite -ErrorAction SilentlyContinue; Write-Host "Autostart removed." }
foreach ($lnk in (Join-Path $StartMenuDir "Aerox Lite.lnk"), (Join-Path $DesktopDir "Aerox Lite.lnk")) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Removed $lnk" }
}
if (Test-Path $UninstallKey) { Remove-Item $UninstallKey -Recurse -Force; Write-Host "Removed from Settings > Apps." }

if (Test-Path $InstallDir) {
    $self = $PSCommandPath
    if ($self -and $self.StartsWith((Resolve-Path $InstallDir).Path, [StringComparison]::OrdinalIgnoreCase)) {
        # This script runs from the folder it deletes: finish the deletion after it exits.
        Start-Process cmd.exe -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$InstallDir`"" -WindowStyle Hidden
    } else {
        Remove-Item $InstallDir -Recurse -Force
    }
    Write-Host "Removed $InstallDir"
}

if ($choice -eq "2") {
    if (Test-Path $SettingsDir) { Remove-Item $SettingsDir -Recurse -Force; Write-Host "Settings removed." }
    if ($pkg) {
        Write-Host "The folder $pkg will be deleted when you close this window."
        Write-Host "Done."
        exit 10
    }
} else {
    Write-Host "Settings kept in $SettingsDir"
}
Write-Host "Done."
exit 0
