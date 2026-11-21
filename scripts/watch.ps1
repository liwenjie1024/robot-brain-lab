<#
.SYNOPSIS
    在浏览器里看练出来的策略（mjlab 的网页播放器 viser）：找最新的一次训练、它最新的存档，开容器，开浏览器。
    播放器右边面板的 Checkpoints 里可以换成同一次训练的早一些的存档，看机器人是怎么一步步学会的。
    看完运行 docker stop nova-watch。播放器用显卡，训练的时候不要开（显卡的内存不够两个一起用）。
.PARAMETER Run
    看哪一次训练：results/train/g1_velocity 下面的文件夹名（比如 2026-11-20_11-21-16_g1-stairs）。不给就用最新的那一次。
.PARAMETER NoBrowser
    只开播放器，不打开浏览器。
.EXAMPLE
    .\scripts\watch.ps1
.EXAMPLE
    .\scripts\watch.ps1 -Run 2026-11-18_12-11-09_g1-flat
#>
param([string]$Run, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Runs = Join-Path $Root 'results/train/g1_velocity'
$Address = 'http://127.0.0.1:8080'
$Container = 'nova-watch'
$WaitSeconds = 120
# 训练的文件夹名的结尾（train/README.md 里训练时的 --agent.run-name）→ 那一次练的任务。
$TaskOfRunSuffix = [ordered]@{
    'g1-flat'   = 'Mjlab-Velocity-Flat-Unitree-G1'
    'g1-stairs' = 'Nova-Velocity-Stairs-Unitree-G1'
}

function Get-CheckpointStep([System.IO.FileInfo]$File) {
    return [int]($File.BaseName -replace '^model_', '')
}

function Find-Run([string]$Name) {
    $withCheckpoints = Get-ChildItem $Runs -Directory | Where-Object { Get-ChildItem $_.FullName -Filter 'model_*.pt' }
    if ($Name) {
        $chosen = $withCheckpoints | Where-Object Name -eq $Name
        if (-not $chosen) { throw "results/train/g1_velocity 里没有存档的训练里找不到 $Name" }
        return $chosen
    }
    $latest = $withCheckpoints | Sort-Object Name | Select-Object -Last 1
    if (-not $latest) { throw 'results/train/g1_velocity 里还没有练出来的存档。' }
    return $latest
}

function Find-Task([string]$RunName) {
    foreach ($suffix in $TaskOfRunSuffix.Keys) {
        if ($RunName.EndsWith($suffix)) { return $TaskOfRunSuffix[$suffix] }
    }
    throw "不知道 $RunName 练的是哪个任务（文件夹名要以 $($TaskOfRunSuffix.Keys -join ' 或 ') 结尾）"
}

Push-Location $Root
try {
    $runDir = Find-Run $Run
    $task = Find-Task $runDir.Name
    $checkpoint = Get-ChildItem $runDir.FullName -Filter 'model_*.pt' |
        Sort-Object { Get-CheckpointStep $_ } | Select-Object -Last 1
    Write-Host "▶ 训练：$($runDir.Name)（任务 $task），最新的存档 $($checkpoint.Name)" -ForegroundColor Cyan

    # docker 把进度写到 stderr；Windows PowerShell 会把那些行当成错误，所以成不成功只看退出码。
    $ErrorActionPreference = 'Continue'
    docker rm -f $Container 2>&1 | Out-Null
    $env:MSYS_NO_PATHCONV = '1'
    docker compose run -d --rm --name $Container -p 127.0.0.1:8080:8080 train `
        python -m nova_train.play $task `
        --checkpoint-file "/results/train/g1_velocity/$($runDir.Name)/$($checkpoint.Name)" --viewer viser 2>&1 |
        ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { throw '播放器没有启动起来。Docker Desktop 开着吗？' }
    $ErrorActionPreference = 'Stop'

    Write-Host '▶ 等播放器准备好（第一次要编译显卡的程序，可能要一两分钟）' -ForegroundColor Cyan
    $ready = $false
    foreach ($second in 1..$WaitSeconds) {
        try {
            Invoke-WebRequest -Uri $Address -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) { throw "等了 $WaitSeconds 秒播放器还没准备好。看一下它的日志：docker logs $Container" }

    Write-Host "▶ 播放器在 $Address" -ForegroundColor Cyan
    Write-Host '  看到机器人：右边面板 Controls → Scene → Camera，勾上 Track camera，再把鼠标滚轮往上滚（拉近）。'
    Write-Host '  让它走：Commands → Twist，勾上 Enable，改 lin_vel_x（往前的速度，m/s）、ang_vel_z（转弯）。'
    Write-Host '  看它怎么学会的：Checkpoints 里换成早一些的存档（model_0 是还没学的时候）。'
    Write-Host "  看完：docker stop $Container"
    if (-not $NoBrowser) { Start-Process $Address }
} finally {
    Pop-Location
}
