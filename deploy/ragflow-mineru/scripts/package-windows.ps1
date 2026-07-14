[CmdletBinding()]
param(
    [string]$RagflowRef = "v0.26.4",
    [string]$MineruRef = "master",
    [string]$OutputRoot = "",
    [string]$PackageName = "",
    [ValidateSet("elasticsearch", "infinity", "opensearch", "oceanbase", "seekdb")]
    [string]$DocEngine = "infinity",
    [ValidateSet("cpu", "gpu")]
    [string]$Device = "gpu",
    [string]$RagflowImage = "",
    [string]$MineruImage = "mineru:latest",
    [string]$MdConvertImage = "md-convert:latest",
    [string]$GatewayImage = "nginx:1.27-alpine",
    [string]$KrokiImage = "yuzutech/kroki:latest",
    [string]$KrokiMermaidImage = "yuzutech/kroki-mermaid:latest",
    [string]$ComposeProfiles = "",
    [switch]$BuildMineru,
    [switch]$SkipMdConvertBuild,
    [switch]$SkipPull,
    [switch]$SkipImageSave,
    [string]$EnvOverridePath = "",
    [string[]]$ExtraImages = @(),
    [switch]$NoArchive
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StackDir = Resolve-Path (Join-Path $ScriptDir "..")
$RepoRoot = Resolve-Path (Join-Path $StackDir "..\..")

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $RepoRoot "dist"
}

if ([string]::IsNullOrWhiteSpace($PackageName)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $safeRef = $RagflowRef -replace "[^A-Za-z0-9_.-]", "-"
    $PackageName = "ragflow-mineru-airgap-$safeRef-$stamp"
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    $display = "$FilePath $($Arguments -join ' ')"
    if ($WorkingDirectory) {
        Write-Host "[$WorkingDirectory] $display"
        Push-Location $WorkingDirectory
        try {
            & $FilePath @Arguments 2>&1 | Write-Host
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host $display
        & $FilePath @Arguments 2>&1 | Write-Host
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $display"
    }
}

function Copy-DirectoryFresh {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (Test-Path $Destination) {
        Remove-Item -Recurse -Force $Destination
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Write-Host
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed while copying '$Source' to '$Destination' with exit code $LASTEXITCODE."
    }
    $global:LASTEXITCODE = 0
}

function ConvertTo-SafeImageFileName {
    param([string]$Image)
    return (($Image -replace "[/:@]", "_") -replace "[^A-Za-z0-9_.-]", "_") + ".tar"
}

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content -Path $Path)
    }

    $pattern = "^\s*#?\s*" + [regex]::Escape($Key) + "\s*="
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "$Key=$Value"
            $found = $true
            break
        }
    }

    if (-not $found) {
        $lines += "$Key=$Value"
    }

    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

function Apply-EnvOverrideFile {
    param(
        [string]$TargetPath,
        [string]$OverridePath
    )

    if ([string]::IsNullOrWhiteSpace($OverridePath)) {
        return
    }
    if (-not (Test-Path $OverridePath)) {
        throw "Override env file does not exist: $OverridePath"
    }

    foreach ($line in Get-Content -Path $OverridePath) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            throw "Invalid env override line: $line"
        }

        $key = $parts[0].Trim()
        $value = $parts[1]
        if ($key -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Invalid env override key: $key"
        }

        Set-EnvValue -Path $TargetPath -Key $key -Value $value
    }
}

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Key
    )

    if (-not (Test-Path $Path)) {
        return ""
    }

    $pattern = "^\s*" + [regex]::Escape($Key) + "\s*="
    $line = Get-Content -Path $Path | Where-Object { $_ -match $pattern } | Select-Object -Last 1
    if (-not $line) {
        return ""
    }
    return ($line -split "=", 2)[1].Trim()
}

function Ensure-EnvListValues {
    param(
        [string]$Path,
        [string]$Key,
        [string[]]$RequiredValues
    )

    $current = Get-EnvValue -Path $Path -Key $Key
    $values = @()
    if (-not [string]::IsNullOrWhiteSpace($current)) {
        $values = @($current -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }

    foreach ($required in $RequiredValues) {
        if ($values -notcontains $required) {
            $values += $required
        }
    }

    Set-EnvValue -Path $Path -Key $Key -Value ($values -join ",")
}

function Clone-Repo {
    param(
        [string]$Url,
        [string]$Ref,
        [string]$Destination
    )

    if (Test-Path $Destination) {
        return
    }

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Invoke-Checked -FilePath "git" -Arguments @("clone", "--depth", "1", "--branch", $Ref, $Url, $Destination)
}

function Get-ComposeImages {
    param([string]$ComposeDirectory)

    Push-Location $ComposeDirectory
    try {
        $composeArgs = @(
            "compose",
            "--env-file", ".env",
            "-f", "docker-compose.yml",
            "-f", "docker-compose.mineru.yml",
            "-f", "docker-compose.md-convert.yml",
            "-f", "docker-compose.gateway.yml",
            "config",
            "--images"
        )
        $output = & docker @composeArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            $output | ForEach-Object { Write-Host $_ }
            throw "docker compose config --images failed."
        }

        return @(
            $output |
                Where-Object { $_ -and $_.Trim().Length -gt 0 } |
                ForEach-Object { $_.Trim() } |
                Sort-Object -Unique
        )
    }
    finally {
        Pop-Location
    }
}

Require-Command "git"
Require-Command "docker"
Require-Command "robocopy"
Invoke-Checked -FilePath "docker" -Arguments @("compose", "version")

$outputRootFull = [System.IO.Path]::GetFullPath($OutputRoot)
$packageDir = Join-Path $outputRootFull $PackageName
$cacheDir = Join-Path $outputRootFull "_cache"
$imagesDir = Join-Path $packageDir "images"
$packageScriptsDir = Join-Path $packageDir "scripts"
$packageRagflowDir = Join-Path $packageDir "ragflow"
$packageDockerDir = Join-Path $packageRagflowDir "docker"

New-Item -ItemType Directory -Force -Path $outputRootFull, $cacheDir, $packageDir, $imagesDir, $packageScriptsDir | Out-Null

$ragflowCache = Join-Path $cacheDir ("ragflow-" + ($RagflowRef -replace "[^A-Za-z0-9_.-]", "-"))
Clone-Repo -Url "https://github.com/infiniflow/ragflow.git" -Ref $RagflowRef -Destination $ragflowCache

Copy-DirectoryFresh -Source (Join-Path $ragflowCache "docker") -Destination $packageDockerDir
Copy-Item -Force -Path (Join-Path $StackDir "docker-compose.mineru.yml") -Destination (Join-Path $packageDockerDir "docker-compose.mineru.yml")
Copy-Item -Force -Path (Join-Path $StackDir "docker-compose.md-convert.yml") -Destination (Join-Path $packageDockerDir "docker-compose.md-convert.yml")
Copy-Item -Force -Path (Join-Path $StackDir "docker-compose.gateway.yml") -Destination (Join-Path $packageDockerDir "docker-compose.gateway.yml")
Copy-DirectoryFresh -Source (Join-Path $StackDir "gateway") -Destination (Join-Path $packageDockerDir "gateway")
Copy-DirectoryFresh -Source (Join-Path $RepoRoot "services\md-convert") -Destination (Join-Path $packageDir "md-convert-source")
Copy-Item -Force -Path (Join-Path $StackDir "README.md") -Destination (Join-Path $packageDir "README.md")
Copy-Item -Force -Path (Join-Path $ScriptDir "deploy-linux.sh") -Destination $packageScriptsDir
Copy-Item -Force -Path (Join-Path $ScriptDir "verify-linux.sh") -Destination $packageScriptsDir

New-Item -ItemType Directory -Force -Path `
    (Join-Path $packageDockerDir "ragflow-logs"), `
    (Join-Path $packageDockerDir "mineru-input"), `
    (Join-Path $packageDockerDir "mineru-output"), `
    (Join-Path $packageDockerDir "md-convert-data") | Out-Null

if ([string]::IsNullOrWhiteSpace($RagflowImage)) {
    $RagflowImage = "infiniflow/ragflow:$RagflowRef"
}

if ([string]::IsNullOrWhiteSpace($ComposeProfiles)) {
    $ComposeProfiles = "$DocEngine,$Device,mineru,md-convert,gateway"
}

$envPath = Join-Path $packageDockerDir ".env"
Set-EnvValue -Path $envPath -Key "DOC_ENGINE" -Value $DocEngine
Set-EnvValue -Path $envPath -Key "DEVICE" -Value $Device
Set-EnvValue -Path $envPath -Key "COMPOSE_PROFILES" -Value $ComposeProfiles
Set-EnvValue -Path $envPath -Key "RAGFLOW_IMAGE" -Value $RagflowImage
Set-EnvValue -Path $envPath -Key "MINERU_IMAGE" -Value $MineruImage
Set-EnvValue -Path $envPath -Key "MD_CONVERT_IMAGE" -Value $MdConvertImage
Set-EnvValue -Path $envPath -Key "GATEWAY_IMAGE" -Value $GatewayImage
Set-EnvValue -Path $envPath -Key "KROKI_IMAGE" -Value $KrokiImage
Set-EnvValue -Path $envPath -Key "KROKI_MERMAID_IMAGE" -Value $KrokiMermaidImage
Set-EnvValue -Path $envPath -Key "PUBLIC_PORT" -Value "18080"
Set-EnvValue -Path $envPath -Key "RAGFLOW_WEB_UPSTREAM" -Value $(if ($Device -eq "cpu") { "ragflow-cpu:80" } else { "ragflow-gpu:80" })
Set-EnvValue -Path $envPath -Key "GATEWAY_MAX_BODY_SIZE" -Value "1024m"
Set-EnvValue -Path $envPath -Key "GATEWAY_PROXY_READ_TIMEOUT" -Value "3600s"
Set-EnvValue -Path $envPath -Key "MD_CONVERT_REDIS_DB" -Value "1"
Set-EnvValue -Path $envPath -Key "MD_CONVERT_QUEUE" -Value "md-convert"
Set-EnvValue -Path $envPath -Key "MD_CONVERT_MAX_UPLOAD_BYTES" -Value "52428800"
Set-EnvValue -Path $envPath -Key "MERMAID_OUTPUT_FORMAT" -Value "svg"
Set-EnvValue -Path $envPath -Key "MINERU_MODEL_SOURCE" -Value "local"
Set-EnvValue -Path $envPath -Key "MINERU_BACKEND" -Value "pipeline"
Set-EnvValue -Path $envPath -Key "MINERU_DELETE_OUTPUT" -Value "0"
Set-EnvValue -Path $envPath -Key "MINERU_ROUTER_PORT" -Value "8002"
Set-EnvValue -Path $envPath -Key "MINERU_GRADIO_PORT" -Value "7860"
Set-EnvValue -Path $envPath -Key "MINERU_LOCAL_GPUS" -Value "auto"
Set-EnvValue -Path $envPath -Key "MINERU_NVIDIA_VISIBLE_DEVICES" -Value "all"
Set-EnvValue -Path $envPath -Key "MINERU_CUDA_VISIBLE_DEVICES" -Value "0"
Set-EnvValue -Path $envPath -Key "MINERU_SHM_SIZE" -Value "32g"
Set-EnvValue -Path $envPath -Key "USE_DOCLING" -Value "false"
Apply-EnvOverrideFile -TargetPath $envPath -OverridePath $EnvOverridePath
Ensure-EnvListValues -Path $envPath -Key "COMPOSE_PROFILES" -RequiredValues @("md-convert", "gateway")

if ($BuildMineru) {
    $mineruCache = Join-Path $cacheDir ("MinerU-" + ($MineruRef -replace "[^A-Za-z0-9_.-]", "-"))
    Clone-Repo -Url "https://github.com/opendatalab/MinerU.git" -Ref $MineruRef -Destination $mineruCache
    Invoke-Checked -FilePath "docker" -Arguments @("build", "-t", $MineruImage, "-f", "docker/global/Dockerfile", ".") -WorkingDirectory $mineruCache
}

if (-not $SkipMdConvertBuild) {
    $mdConvertSource = Join-Path $RepoRoot "services\md-convert"
    Invoke-Checked -FilePath "docker" -Arguments @("build", "-t", $MdConvertImage, ".") -WorkingDirectory $mdConvertSource
}

$images = @(Get-ComposeImages -ComposeDirectory $packageDockerDir)
$images += $ExtraImages
$images = @($images | Where-Object { $_ -and $_.Trim().Length -gt 0 } | ForEach-Object { $_.Trim() } | Sort-Object -Unique)

if (-not $SkipPull) {
    foreach ($image in $images) {
        Write-Host "Checking image $image"
        & docker image inspect $image *> $null
        if ($LASTEXITCODE -eq 0) {
            continue
        }

        if ($image -eq $MineruImage -and -not $BuildMineru) {
            throw "MinerU image '$MineruImage' is not present locally. Re-run with -BuildMineru or build/pull it before packaging."
        }

        if ($image -eq $MdConvertImage -and $SkipMdConvertBuild) {
            throw "Markdown convert image '$MdConvertImage' is not present locally. Re-run without -SkipMdConvertBuild or build it before packaging."
        }

        Invoke-Checked -FilePath "docker" -Arguments @("pull", $image)
    }
}

$manifestImages = @()
if (-not $SkipImageSave) {
    foreach ($image in $images) {
        & docker image inspect $image *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Image '$image' is missing locally. Cannot save offline bundle."
        }

        $fileName = ConvertTo-SafeImageFileName -Image $image
        $tarPath = Join-Path $imagesDir $fileName
        Invoke-Checked -FilePath "docker" -Arguments @("save", "-o", $tarPath, $image)
        $manifestImages += [ordered]@{
            image = $image
            file = "images/$fileName"
        }
    }
}

$manifest = [ordered]@{
    createdAt = (Get-Date).ToString("o")
    ragflowRef = $RagflowRef
    mineruRef = $MineruRef
    docEngine = $DocEngine
    device = $Device
    composeProfiles = $ComposeProfiles
    mdConvertImage = $MdConvertImage
    gatewayImage = $GatewayImage
    krokiImage = $KrokiImage
    krokiMermaidImage = $KrokiMermaidImage
    packageName = $PackageName
    images = $manifestImages
}

$manifest | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $packageDir "manifest.json") -Encoding UTF8

if (-not $NoArchive) {
    $zipPath = Join-Path $outputRootFull "$PackageName.zip"
    if (Test-Path $zipPath) {
        Remove-Item -Force $zipPath
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($packageDir, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Write-Host "Archive written: $zipPath"
}

Write-Host "Package directory: $packageDir"
Write-Host "Copy the package to Linux, unzip if needed, then run: sudo bash scripts/deploy-linux.sh --package-dir <package-dir>"
