# =============================================================================
# Build the Quantum TechHub Python sandbox image.
#
# Windows / WSL usage (PowerShell):
#   .\scripts\build_sandbox_image.ps1
#   .\scripts\build_sandbox_image.ps1 -Distro Ubuntu
#
# Linux / macOS usage:
#   ./scripts/build_sandbox_image.sh
#
# The script prefers Docker running inside WSL (works with Docker Desktop and
# with a native dockerd installed in a WSL distro). If a Docker binary is
# available on the Windows PATH directly it will use that instead.
# =============================================================================

param(
    [string]$Distro = "",
    [string]$Image = "quantumm/python-ds:3.12"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dockerfile = Join-Path $projectRoot "Dockerfile.python-ds"

if (-not (Test-Path $dockerfile)) {
    Write-Error "Dockerfile not found at $dockerfile"
    exit 1
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if (Test-Command "docker") {
    Write-Host "Building with native Docker binary..." -ForegroundColor Cyan
    & docker build -f $dockerfile -t $Image $projectRoot
    exit $LASTEXITCODE
}

if (Test-Command "wsl") {
    Write-Host "Native docker not found; building via WSL..." -ForegroundColor Yellow
    # Convert the Windows path to a WSL path (C:\a\b -> /mnt/c/a/b).
    $wslRoot = (& wsl -e wslpath -a $projectRoot) 2>$null
    if (-not $wslRoot) {
        Write-Error "Could not translate project path into WSL. Is a distro installed? Run 'wsl --list'."
        exit 1
    }
    $wslDockerfile = "$wslRoot/Dockerfile.python-ds"
    $wslImage = $Image

    $wslArgs = @()
    if ($Distro) { $wslArgs += @("-d", $Distro) }
    $wslArgs += @("--", "docker", "build", "-f", $wslDockerfile, "-t", $wslImage, $wslRoot)

    & wsl @wslArgs
    exit $LASTEXITCODE
}

Write-Error "Neither 'docker' nor 'wsl' was found. Install Docker Desktop with the WSL 2 backend, or install Docker inside a WSL distro."
exit 1
