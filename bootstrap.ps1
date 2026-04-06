param(
    [Parameter(Mandatory = $true)]
    [string]$TargetHost,

    [string]$User = "ubuntu",

    [int]$Port = 22,

    [string]$RepoUrl = "git@github.com:sxrubyo/omni-core.git",

    [string]$Destination = "",

    [string]$Branch = "main",

    [string]$IdentityFile,

    [switch]$InstallTimer,

    [string]$TimerOnCalendar = "daily"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ConvertTo-BashSingleQuoted {
    param(
        [AllowNull()]
        [string]$Value
    )

    if ($null -eq $Value) {
        return "''"
    }

    if ($Value.Length -eq 0) {
        return "''"
    }

    return "'" + ($Value -replace "'", "'\"'\"'") + "'"
}

function Assert-CommandExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No se encontró el comando requerido: $Name"
    }
}

function Get-RemoteInstallCandidates {
    $scanScript = @'
python3 - <<'"'"'PY'"'"'
import json
import os
import shutil

user = os.environ.get("TARGET_USER", "ubuntu")
candidates = [
    ("/opt/omni-core", "Recomendado para software de sistema y servidores limpios."),
    (f"/home/{user}/omni-core", "Más simple si trabajas dentro del home del usuario."),
    ("/srv/omni-core", "Útil si manejas servicios y datos bajo /srv."),
]

result = []
for path, note in candidates:
    parent = os.path.dirname(path.rstrip("/")) or "/"
    existing = os.path.exists(path)
    parent_exists = os.path.exists(parent)
    free_bytes = 0
    free_gb = 0.0
    if parent_exists:
        usage = shutil.disk_usage(parent)
        free_bytes = usage.free
        free_gb = round(usage.free / (1024 ** 3), 1)
    writable = os.access(path if existing else parent, os.W_OK) if parent_exists else False
    result.append({
        "path": path,
        "note": note,
        "existing": existing,
        "parent": parent,
        "parent_exists": parent_exists,
        "writable": writable,
        "free_gb": free_gb,
    })

recommended = "/opt/omni-core"
if not any(item["path"] == recommended and item["parent_exists"] for item in result):
    recommended = f"/home/{user}/omni-core"

print(json.dumps({"recommended": recommended, "candidates": result}))
PY
'@

    $cmdArgs = @()
    if ($IdentityFile) {
        $cmdArgs += @("-i", $IdentityFile)
    }
    $cmdArgs += @("-p", "$Port")
    $cmdArgs += @("$User@$TargetHost")
    $cmdArgs += @("env", "TARGET_USER=$User", "bash", "-lc", $scanScript)
    $raw = & ssh @cmdArgs
    if (-not $raw) {
        throw "No se pudo escanear el host remoto para proponer ubicaciones."
    }
    return $raw | ConvertFrom-Json
}

function Select-InstallDestination {
    param(
        [Parameter(Mandatory = $true)]
        $Scan
    )

    $recommended = [string]$Scan.recommended
    Write-Host ""
    Write-Host "  Omni detectó estas ubicaciones en el host remoto:" -ForegroundColor Cyan
    Write-Host ""
    $index = 1
    foreach ($candidate in $Scan.candidates) {
        $path = [string]$candidate.path
        $note = [string]$candidate.note
        $free = [string]$candidate.free_gb + " GB libres"
        $extra = if ($path -eq $recommended) { "  (recomendada)" } else { "" }
        Write-Host ("    {0}. {1}{2}" -f $index, $path, $extra) -ForegroundColor White
        Write-Host ("       {0} · {1}" -f $note, $free) -ForegroundColor DarkGray
        $index += 1
    }
    Write-Host ("    {0}. Personalizada" -f $index) -ForegroundColor White
    Write-Host "       Escribe cualquier ruta absoluta del host remoto." -ForegroundColor DarkGray
    Write-Host ""

    while ($true) {
        $choice = Read-Host "  → Elige una ubicación (Enter = recomendada)"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            return $recommended
        }
        if ($choice -match '^\d+$') {
            $numeric = [int]$choice
            if ($numeric -ge 1 -and $numeric -le $Scan.candidates.Count) {
                return [string]$Scan.candidates[$numeric - 1].path
            }
            if ($numeric -eq ($Scan.candidates.Count + 1)) {
                while ($true) {
                    $custom = Read-Host "  ? Ruta personalizada en el host remoto"
                    if ($custom -match '^/') {
                        return $custom.Trim()
                    }
                    Write-Host "  ! Debe ser una ruta absoluta Linux, por ejemplo /home/ubuntu/omni-core" -ForegroundColor Yellow
                }
            }
        }
        Write-Host "  ! Escribe el número de la opción o Enter para usar la recomendada." -ForegroundColor Yellow
    }
}

Assert-CommandExists -Name "ssh"

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $scan = Get-RemoteInstallCandidates
    $Destination = Select-InstallDestination -Scan $scan
}

$repoArg = ConvertTo-BashSingleQuoted $RepoUrl
$destArg = ConvertTo-BashSingleQuoted $Destination
$branchArg = ConvertTo-BashSingleQuoted $Branch
$timerArg = ConvertTo-BashSingleQuoted $TimerOnCalendar
$installTimerFlag = if ($InstallTimer) { "1" } else { "0" }

$remoteScript = @'
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

REPO_URL=${REPO_URL:?}
DEST_DIR=${DEST_DIR:?}
REF_NAME=${REF_NAME:-main}
INSTALL_TIMER=${INSTALL_TIMER:-0}
TIMER_ON_CALENDAR=${TIMER_ON_CALENDAR:-daily}

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git rsync openssh-client ca-certificates curl docker.io docker-compose-plugin
fi

if [ -d "$DEST_DIR/.git" ]; then
  git -C "$DEST_DIR" fetch --all --prune
  git -C "$DEST_DIR" checkout "$REF_NAME"
  git -C "$DEST_DIR" pull --ff-only origin "$REF_NAME"
else
  git clone --branch "$REF_NAME" "$REPO_URL" "$DEST_DIR"
fi

cd "$DEST_DIR"
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync

if [ "$INSTALL_TIMER" = "1" ]; then
  "$DEST_DIR/bin/omni" timer-install --service-name omni-update --on-calendar "$TIMER_ON_CALENDAR"
fi

echo "Bootstrap remoto completado en $DEST_DIR"
'@

$sshArgs = @()
if ($IdentityFile) {
    $sshArgs += @("-i", $IdentityFile)
}
$sshArgs += @("-p", "$Port")
$sshArgs += @("$User@$TargetHost")
$sshArgs += @("env", "REPO_URL=$repoArg", "DEST_DIR=$destArg", "REF_NAME=$branchArg", "INSTALL_TIMER=$installTimerFlag", "TIMER_ON_CALENDAR=$timerArg", "bash", "-s")

$remoteScript | & ssh @sshArgs
