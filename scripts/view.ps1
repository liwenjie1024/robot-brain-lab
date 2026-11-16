<#
.SYNOPSIS
    打开 Nova 的网页：启动实时的仿真（容器），启动网页的服务，再用浏览器打开。
    看完以后在这个窗口里按 Ctrl+C 停掉网页的服务。仿真的容器留着；要停就运行 docker compose stop sim。
.PARAMETER NoBrowser
    只启动仿真和网页的服务，不打开浏览器。
.EXAMPLE
    .\scripts\view.ps1
#>
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$View = Join-Path $Root 'view'
$Address = 'http://127.0.0.1:5280'
$SimHealth = 'http://127.0.0.1:8870/health'
$WaitSeconds = 30

Push-Location $Root
try {
    Write-Host '▶ 启动仿真（容器）' -ForegroundColor Cyan
    # docker 把进度写到 stderr；Windows PowerShell 会把那些行当成错误，所以成不成功只看退出码。
    $ErrorActionPreference = 'Continue'
    docker compose up -d sim 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { throw '仿真没有启动起来。Docker Desktop 开着吗？' }
    $ErrorActionPreference = 'Stop'

    Write-Host '▶ 等仿真准备好' -ForegroundColor Cyan
    $ready = $false
    foreach ($second in 1..$WaitSeconds) {
        try {
            Invoke-WebRequest -Uri $SimHealth -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) { throw "等了 $WaitSeconds 秒仿真还没准备好。看一下它的日志：docker compose logs sim" }

    if (-not (Test-Path (Join-Path $View 'node_modules'))) {
        Write-Host '▶ 第一次用：安装网页要的库（要几分钟）' -ForegroundColor Cyan
        npm --prefix $View install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw '网页要的库没有装好。' }
    }

    Write-Host "▶ 网页在 $Address （按 Ctrl+C 停掉）" -ForegroundColor Cyan
    if (-not $NoBrowser) { Start-Process $Address }
    # 直接用 node 启动，不经过 npm：经过 npm 的话，停掉以后下面的进程会留着，一直占着端口。
    node (Join-Path $View 'node_modules/vite/bin/vite.js') $View --port 5280 --strictPort --host 127.0.0.1
} finally {
    Pop-Location
}
