# Builds build\dist\AeroxLite\AeroxLite.exe (folder build): venv, dependencies, tests, PyInstaller, self-test.
# Run directly (build.bat) or dot-source it to use Find-Python / Invoke-AeroxBuild (install.ps1 does).
param([string]$Python = "")

function Test-AeroxPython([string]$exe) {
    $ErrorActionPreference = "Continue"  # probing tools write to stderr; that is not a failure
    # Returns the version string when $exe is Python 3.10-3.14 with Tk, otherwise $null.
    try {
        # No double quotes inside: Windows PowerShell 5.1 strips them from native-command arguments.
        $code = "import sys, tkinter; v = sys.version_info; ok = (3, 10) <= v[:2] <= (3, 14) and tkinter.TkVersion >= 8.6; print('.'.join(map(str, v[:3])) if ok else '')"
        $v = & $exe -c $code 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return "$v".Trim() }
    } catch { }
    return $null
}

function Find-Python {
    $ErrorActionPreference = "Continue"  # probing tools write to stderr; that is not a failure
    # Python 3.10-3.14 with Tk: py launcher first, then the usual install folders, then PATH.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($minor in 14, 13, 12, 11, 10) {
            $p = & py "-3.$minor" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidates += "$p".Trim() }
        }
    }
    foreach ($minor in 14, 13, 12, 11, 10) {
        $candidates += "$env:LOCALAPPDATA\Programs\Python\Python3$minor\python.exe"
        $candidates += "$env:ProgramFiles\Python3$minor\python.exe"
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c) -and ($c -notlike "*WindowsApps*")) {
            $v = Test-AeroxPython $c
            if ($v) { return @{ Path = $c; Version = $v } }
        }
    }
    return $null
}

function Test-AeroxExe([string]$exe) {
    $ErrorActionPreference = "Continue"  # probing tools write to stderr; that is not a failure
    # The built program loads all modules and native libraries and exits (no window).
    if (-not (Test-Path $exe)) { return $false }
    $p = Start-Process -FilePath $exe -ArgumentList "--self-test" -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit(60000)) { $p.Kill(); return $false }
    return $p.ExitCode -eq 0
}

function Invoke-AeroxBuild([string]$root, [string]$py) {
    # Tools print progress to stderr; with "Stop" Windows PowerShell would treat that as a failure.
    # Failures are detected from exit codes instead.
    $ErrorActionPreference = "Continue"
    Push-Location $root
    try {
        $venvPy = Join-Path $root ".venv\Scripts\python.exe"
        if (Test-Path $venvPy) {
            $a = & $venvPy -c "import sys; print(sys.version)" 2>$null
            $b = & $py -c "import sys; print(sys.version)"
            if ("$a" -ne "$b") { Write-Host "Removing an old build environment made with another Python."; Remove-Item -Recurse -Force (Join-Path $root ".venv") }
        }
        if (-not (Test-Path $venvPy)) {
            Write-Host "Creating the build environment (.venv)"
            & $py -m venv .venv | Out-Host; if ($LASTEXITCODE) { throw "python -m venv failed" }
        }
        # Native output goes to the screen (Out-Host), not into this function's return value.
        Write-Host "Installing dependencies"
        & $venvPy -m pip install --disable-pip-version-check -q -r packaging\requirements.txt -r packaging\requirements-build.txt | Out-Host
        if ($LASTEXITCODE) { throw "pip install failed" }
        Write-Host "Running the tests"
        & $venvPy -X utf8 -m unittest discover -s tests 2>&1 | ForEach-Object { "$_" } | Out-Host
        if ($LASTEXITCODE) { throw "the tests failed" }
        Write-Host "Building AeroxLite.exe"
        & $venvPy -X utf8 -m PyInstaller --clean --noconfirm --log-level WARN --distpath build\dist --workpath build\work packaging\windows\AeroxLite.spec 2>&1 | ForEach-Object { "$_" } | Out-Host
        if ($LASTEXITCODE) { throw "PyInstaller failed" }
        $exe = Join-Path $root "build\dist\AeroxLite\AeroxLite.exe"
        if (-not (Test-AeroxExe $exe)) { throw "the built program failed its self-test" }
        Write-Host "Built and self-tested: $exe"
        return $exe
    } finally { Pop-Location }
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference = "Stop"
    $root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    if (-not $Python) {
        $found = Find-Python
        if (-not $found) { Write-Host "Python 3.10-3.14 with Tcl/Tk was not found. Install it from https://www.python.org/downloads/windows/"; exit 1 }
        $Python = $found.Path
    }
    try { Invoke-AeroxBuild $root $Python | Out-Null } catch { Write-Host "Build failed: $_"; exit 1 }
}
