param(
    [Parameter(Mandatory = $true)]
    [string]$TargetHost,

    [string]$User = "ubuntu",

    [int]$Port = 22,

    [string]$RepoUrl = "git@github.com:sxrubyo/omni-core.git",

    [string]$Destination = "/opt/omni-core",

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

Assert-CommandExists -Name "ssh"

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
