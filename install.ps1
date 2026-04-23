$ErrorActionPreference = "Stop"

$RepoSlug = if ($env:OMNI_INSTALL_REPO) { $env:OMNI_INSTALL_REPO } else { "sxrubyo/omnisync" }
$RepoZipUrl = if ($env:OMNI_INSTALL_SOURCE_ARCHIVE) { $env:OMNI_INSTALL_SOURCE_ARCHIVE } else { "https://github.com/$RepoSlug/archive/refs/heads/main.zip" }
$LocalRepo = if ($env:OMNI_INSTALL_LOCAL_REPO) { $env:OMNI_INSTALL_LOCAL_REPO } else { "" }
$OmniHome = if ($env:OMNI_INSTALL_HOME) { $env:OMNI_INSTALL_HOME } else { (Join-Path $env:USERPROFILE ".omni") }
$RepoDir = Join-Path $OmniHome "repo"
$RuntimeDir = if ($env:OMNI_RUNTIME_DIR) { $env:OMNI_RUNTIME_DIR } else { (Join-Path $OmniHome "runtime") }
$BinDir = if ($env:OMNI_BIN_DIR) { $env:OMNI_BIN_DIR } else { (Join-Path $env:USERPROFILE ".local\bin") }
$WrapperCmd = if ($env:OMNI_WRAPPER_PATH) { $env:OMNI_WRAPPER_PATH } else { (Join-Path $BinDir "omni.cmd") }
$SkipBootstrap = if ($env:OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP) { $env:OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP } else { "0" }
$AssumeYes = if ($env:OMNI_INSTALL_ASSUME_YES) { $env:OMNI_INSTALL_ASSUME_YES } else { "0" }

function Write-Banner {
    Write-Host "OmniSync installer" -ForegroundColor Cyan
    Write-Host "portable migration bootstrap" -ForegroundColor DarkGray
}

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "  OK  $Message" -ForegroundColor Green
}

function Fail([string]$Message) {
    Write-Host "  ERR $Message" -ForegroundColor Red
    exit 1
}

function Confirm-RuntimeDependencies {
    if ($SkipBootstrap -eq "1") { return }
    Write-Step "Preparing runtime dependencies"
    Write-Host "  INFO Paramiko habilita conexiones SSH por contraseña y transferencias SFTP en omni connect." -ForegroundColor DarkCyan
    Write-Host "  INFO También se instalarán rich, tqdm y prompt_toolkit para la interfaz del CLI." -ForegroundColor DarkCyan

    if ($AssumeYes -eq "1" -or [Console]::IsInputRedirected -or [Console]::IsOutputRedirected) {
        Write-Ok "Runtime dependency bootstrap accepted automatically"
        return
    }

    $Reply = Read-Host "Instalar dependencias runtime ahora? [Y/n]"
    if ($Reply -match '^(n|no)$') {
        Fail "Installation cancelled before runtime dependency bootstrap"
    }
    Write-Ok "Runtime dependency bootstrap accepted"
}

function Resolve-Python {
    foreach ($candidate in @("py", "python", "python3")) {
        try {
            if ($candidate -eq "py") {
                & py -3 -c "import sys; print(sys.executable)" | Out-Null
                if ($LASTEXITCODE -eq 0) { return "py -3" }
            } else {
                & $candidate -c "import sys; print(sys.executable)" | Out-Null
                if ($LASTEXITCODE -eq 0) { return $candidate }
            }
        } catch {}
    }
    return $null
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][string]$PythonCommand,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    if ($PythonCommand -eq "py -3") {
        & py -3 @Arguments
    } else {
        & $PythonCommand @Arguments
    }
}

function Sync-RepoTree {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$TargetDir,
        [Parameter(Mandatory = $true)][string]$PythonCommand
    )

    $script = @'
from pathlib import Path
import shutil
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
exclude = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".env",
    "runtime",
    "logs",
    "data",
    "backups",
    "home_snapshot",
    "home_private_snapshot",
}

if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True, exist_ok=True)

for child in source.iterdir():
    if child.name in exclude:
        continue
    destination = target / child.name
    if child.is_dir():
        shutil.copytree(child, destination, ignore=shutil.ignore_patterns(*exclude))
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, destination)
'@

    Invoke-Python -PythonCommand $PythonCommand -Arguments @("-c", $script, $SourceDir, $TargetDir)
}

function Stage-RepoArchive {
    param(
        [Parameter(Mandatory = $true)][string]$ZipFile,
        [Parameter(Mandatory = $true)][string]$TargetDir,
        [Parameter(Mandatory = $true)][string]$PythonCommand
    )

    $script = @'
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

zip_path = Path(sys.argv[1])
target = Path(sys.argv[2])
exclude_roots = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".env",
    "runtime",
    "logs",
    "data",
    "backups",
    "home_snapshot",
    "home_private_snapshot",
}
exclude_paths = {
    "config/repos.json",
    "config/servers.json",
    "config/system_manifest.json",
    "config/omni_agent.json",
    "config/omni_agent_activation.txt",
}

if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True, exist_ok=True)

found_entrypoint = False
with zipfile.ZipFile(zip_path) as archive:
    for info in archive.infolist():
        raw_name = str(info.filename or "").replace("\\", "/")
        if not raw_name or raw_name.endswith("/"):
            continue
        parts = PurePosixPath(raw_name).parts
        if len(parts) < 2:
            continue
        rel_parts = parts[1:]
        if not rel_parts:
            continue
        rel_path = PurePosixPath(*rel_parts)
        rel_str = rel_path.as_posix()
        if any(not part.strip() for part in rel_parts):
            continue
        if any(part != part.rstrip(" .") for part in rel_parts):
            continue
        if rel_parts[0] in exclude_roots:
            continue
        if rel_str in exclude_paths:
            continue
        if ".pytest_cache" in rel_parts or "__pycache__" in rel_parts:
            continue
        destination = target.joinpath(*rel_parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)
        if rel_str == "src/omni_core.py":
            found_entrypoint = True

if not found_entrypoint:
    raise SystemExit("Downloaded archive does not contain src/omni_core.py")
'@

    Invoke-Python -PythonCommand $PythonCommand -Arguments @("-c", $script, $ZipFile, $TargetDir)
}

$Python = Resolve-Python
if (-not $Python) {
    Fail "Python 3 no está disponible. Instálalo y vuelve a intentar."
}

$PythonExecutable = if ($Python -eq "py -3") {
    & py -3 -c "import sys; print(sys.executable)"
} else {
    & $Python -c "import sys; print(sys.executable)"
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("omni-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
$ZipPath = Join-Path $TempRoot "omnisync.zip"

Write-Banner
Write-Step "Preparing OmniSync directories"
New-Item -ItemType Directory -Force -Path $OmniHome | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

if (-not [string]::IsNullOrWhiteSpace($LocalRepo)) {
    Write-Step "Staging OmniSync from local repository"
    if (-not (Test-Path (Join-Path $LocalRepo "src\omni_core.py"))) {
        Fail "Local repo override no contiene src\\omni_core.py: $LocalRepo"
    }
    Sync-RepoTree -SourceDir $LocalRepo -TargetDir $RepoDir -PythonCommand $Python
    Write-Ok "Repository staged in $RepoDir"
} else {
    Write-Step "Downloading OmniSync"
    Invoke-WebRequest -UseBasicParsing -Uri $RepoZipUrl -OutFile $ZipPath
    Write-Ok "Archive downloaded"

    Write-Step "Extracting OmniSync"
    Stage-RepoArchive -ZipFile $ZipPath -TargetDir $RepoDir -PythonCommand $Python
    Write-Ok "Repository staged in $RepoDir"
}

Write-Step "Bootstrapping isolated runtime"
Invoke-Python -PythonCommand $Python -Arguments @("-m", "venv", $RuntimeDir)
$RuntimePython = Join-Path $RuntimeDir "Scripts\python.exe"
if (-not (Test-Path $RuntimePython)) {
    Fail "Python runtime not found at $RuntimePython"
}
if ($SkipBootstrap -ne "1") {
    Confirm-RuntimeDependencies
    & $RuntimePython -m pip install --disable-pip-version-check --upgrade pip | Out-Null
    & $RuntimePython -m pip install --disable-pip-version-check rich tqdm prompt_toolkit paramiko | Out-Null
}
Write-Ok "Runtime ready at $RuntimeDir"

Write-Step "Creating CLI wrapper"
$WrapperBody = @"
@echo off
setlocal
set OMNI_CONFIG_DIR=
set OMNI_STATE_DIR=
set OMNI_BACKUP_DIR=
set OMNI_BUNDLE_DIR=
set OMNI_AUTO_BUNDLE_DIR=
set OMNI_LOG_DIR=
set OMNI_WATCH_STATE_FILE=
set OMNI_ENV_FILE=
set OMNI_AGENT_CONFIG_FILE=
set OMNI_TASKS_FILE=
set OMNI_REPOS_FILE=
set OMNI_SERVERS_FILE=
set OMNI_MANIFEST_FILE=
set "OMNI_HOME=$OmniHome"
"$RuntimePython" "$RepoDir\src\omni_core.py" %*
"@
$WrapperBody | Set-Content -Path $WrapperCmd -Encoding ascii
Write-Ok "CLI wrapper created at $WrapperCmd"

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $UserPath) { $UserPath = "" }
$PathParts = $UserPath -split ";" | Where-Object { $_ }
if (-not ($PathParts | Where-Object { $_ -eq $BinDir })) {
    $NewPath = if ([string]::IsNullOrWhiteSpace($UserPath)) { $BinDir } else { "$UserPath;$BinDir" }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Ok "User PATH updated"
}
$env:Path = "$BinDir;$env:Path"

Write-Step "Validating OmniSync"
& $WrapperCmd init | Out-Null
& $WrapperCmd help | Out-Null
& $WrapperCmd commands | Out-Null
$ResolvedOmni = (Get-Command omni -ErrorAction Stop).Source
if ($ResolvedOmni -ne $WrapperCmd) {
    Fail "PowerShell resolves omni to $ResolvedOmni instead of $WrapperCmd"
}
Write-Ok "Omni CLI is ready"

Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "OmniSync installed." -ForegroundColor White
Write-Host "Open a new terminal if PATH changes are not visible yet." -ForegroundColor DarkGray
Write-Host "Commands:" -ForegroundColor White
Write-Host "  omni" -ForegroundColor Gray
Write-Host "  omni guide" -ForegroundColor Gray
Write-Host "  omni connect --host <ip|fqdn> --user <user>" -ForegroundColor Gray
