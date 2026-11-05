# Genio 실행: Docker 확인 → .env 준비 → 컨테이너 기동 → 준비 확인 → 브라우저 열기
# 사용: start_genio.bat           (평소 실행)
#       start_genio.bat -Rebuild  (화면·서버 코드를 고친 뒤 다시 빌드)
param([switch]$Rebuild, [switch]$NoBrowser)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot

$LocalUrl = "http://127.0.0.1:5190"
$ShareUrl = "https://genio.tail6bd481.ts.net"

# docker는 진행 상황을 오류 출력(stderr)으로 내보낸다. Windows PowerShell 5.1은 "Stop" 상태에서 그 줄을
# 치명적 오류로 보고 스크립트를 끝내 버리므로, docker를 부를 때만 "Continue"로 바꾸고 종료 코드로 판단한다.
function Native([scriptblock]$Block) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Block } finally { $ErrorActionPreference = $prev }
}

function Step($msg) { Write-Host ""; Write-Host "▶ $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Fail($msg, $hint) {
    Write-Host "  ✗ $msg" -ForegroundColor Red
    if ($hint) { Write-Host "    → $hint" -ForegroundColor Yellow }
    exit 1
}

# 1) Docker
Step "Docker 확인"
$dockerOk = $false
try { docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; $dockerOk = ($LASTEXITCODE -eq 0) } catch { $dockerOk = $false }
if (-not $dockerOk) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    )
    $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) { Fail "Docker Desktop을 찾지 못했어요." "Docker Desktop을 설치한 뒤 다시 실행하세요." }
    Write-Host "  Docker Desktop을 켜는 중… (최대 3분)"
    Start-Process -FilePath $exe | Out-Null
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        try { docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break } } catch {}
    }
    if (-not $dockerOk) { Fail "Docker가 켜지지 않았어요." "Docker Desktop 창에서 오류를 확인한 뒤 다시 실행하세요." }
}
Ok "Docker 준비됨"

# 2) .env
Step "설정 파일(.env) 확인"
if (-not (Test-Path ".env")) {
    $secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $fernet = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
    (Get-Content ".env.example" -Encoding UTF8) `
        -replace "^GENIO_SECRET_KEY=.*", "GENIO_SECRET_KEY=$secret" `
        -replace "^GENIO_FERNET_KEY=.*", "GENIO_FERNET_KEY=$fernet" `
        -replace "^GENIO_PUBLIC_WEB_URL=.*", "GENIO_PUBLIC_WEB_URL=$ShareUrl" |
        Set-Content ".env" -Encoding UTF8
    Ok ".env를 새로 만들었어요(키 자동 생성)"
} else {
    Ok ".env 있음"
}

# 3) 컨테이너
Step "컨테이너 실행 (web · api · worker · postgres · redis · tailscale)"
if ($Rebuild) { Native { docker compose up -d --build } } else { Native { docker compose up -d } }
if ($LASTEXITCODE -ne 0) { Fail "컨테이너를 띄우지 못했어요." "docker compose logs 로 오류를 확인하세요." }
Ok "컨테이너 실행됨"
# tailscale은 web의 네트워크를 같이 쓰므로, web이 새로 만들어졌으면 다시 붙여야 한다
Native { docker compose up -d --force-recreate tailscale 2>&1 | Out-Null }

# 4) 준비 확인
Step "서버 준비 기다리는 중"
$ready = $false
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "$LocalUrl/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) { Fail "서버가 3분 안에 준비되지 않았어요." "docker compose logs api 로 오류를 확인하세요." }
Ok "서버 준비됨"

# Tailscale genio 기기 로그인 확인(처음 한 번 승인 필요)
$login = Native { docker compose logs tailscale 2>&1 } | Select-String -Pattern "https://login\.tailscale\.com/a/\S+" | Select-Object -Last 1
$tsStatus = Native { docker compose exec -T tailscale tailscale status 2>&1 }
if (-not ($tsStatus -match "genio") -and $login) {
    Write-Host ""
    Write-Host "  ! 공유 주소를 쓰려면 아래 링크에서 Tailscale 승인을 한 번 해 주세요:" -ForegroundColor Yellow
    Write-Host "    $($login.Matches[0].Value)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  Genio 실행 완료" -ForegroundColor Green
Write-Host "  이 PC      : $LocalUrl"
Write-Host "  공유 주소  : $ShareUrl"
Write-Host "  데모 로그인: owner@example.com / genio1234!"
Write-Host "  끄기       : docker compose down"
Write-Host "==============================================" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $LocalUrl }
