<#
.SYNOPSIS
    提交前的本地检查：外面来的文件（基线的模型）齐不齐，身体和仿真（在容器里）的格式、代码规则、测试，
    报告和代码是不是对得上，网页的代码规则、类型、测试、打包。
.EXAMPLE
    .\scripts\check.ps1
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Results = New-Object System.Collections.Generic.List[object]

$View = Join-Path $Root 'view'

function Invoke-Step([string]$Name, [scriptblock]$Command) {
    Write-Host ''
    Write-Host "▶ $Name" -ForegroundColor Cyan
    $started = Get-Date
    Push-Location $Root
    # docker 把进度写到 stderr。Windows PowerShell 会把那些行当成错误，遇到 Stop 就停下，
    # 所以在这一步里先继续往下走，成不成功只看退出码。
    $ErrorActionPreference = 'Continue'
    try {
        & $Command 2>&1 | ForEach-Object { Write-Host "  $_" }
        $passed = ($LASTEXITCODE -eq 0)
    } catch {
        Write-Host "  $_" -ForegroundColor Red
        $passed = $false
    } finally {
        Pop-Location
    }
    $seconds = [int]((Get-Date) - $started).TotalSeconds
    $Results.Add([pscustomobject]@{ 步骤 = $Name; 结果 = $(if ($passed) { '通过' } else { '没通过' }); '用时（秒）' = $seconds })
}

# 基线的模型不提交进仓库。已经下载过就只核对一遍（不连网）；没有的、不对的才下载。
Invoke-Step '外面来的文件：基线的模型和清单一样（没有就下载）' {
    docker compose run --rm --build body python -m nova_body.third_party
}
Invoke-Step '身体和仿真：格式、代码规则、测试（容器）' {
    docker compose run --rm body sh -c 'ruff format --check . && ruff check . && pytest -q'
}
# 报告是程序生成的。改了假设或代码却忘了重新生成，这一步就会不通过。
Invoke-Step '身体：质量闭环的报告和代码对得上' {
    docker compose run --rm body sh -c 'python -m nova_body.mass_report --output /tmp/mass-report.md > /dev/null && cmp /tmp/mass-report.md /docs/报告/质量闭环.md'
}
Invoke-Step '身体：身体模型的报告、图和代码对得上' {
    docker compose run --rm body sh -c 'python -m nova_body.model_report --output /tmp/body-model.md > /dev/null && cmp /tmp/body-model.md /docs/报告/身体模型.md && cmp /tmp/body-model.svg /docs/报告/身体模型.svg'
}
Invoke-Step '身体：基线的报告、图和代码对得上' {
    docker compose run --rm body sh -c 'python -m nova_body.baseline_report --output /tmp/baseline.md > /dev/null && cmp /tmp/baseline.md /docs/报告/基线身体.md && cmp /tmp/baseline.svg /docs/报告/基线身体.svg'
}
# 力量的报告要把全部的动作在两个身体上各做一遍（几个进程一起算），要两三分钟。
Invoke-Step '身体：力量的报告和代码对得上' {
    docker compose run --rm body sh -c 'python -m nova_body.strength_report --output /tmp/strength.md > /dev/null && cmp /tmp/strength.md /docs/报告/力量.md'
}
# 驱动器的报告要让 Nova 做一遍全部的动作、算一轮家务的热，一两分钟。
Invoke-Step '身体：驱动器的报告和代码对得上' {
    docker compose run --rm body sh -c 'python -m nova_body.drive_report --output /tmp/drives.md > /dev/null && cmp /tmp/drives.md /docs/报告/驱动器.md'
}
# 网页在这台电脑上直接跑（不在容器里）。依赖已经装好的话，这一步很快。
Invoke-Step '网页：依赖装好了' {
    npm --prefix $View install --prefer-offline --no-audit --no-fund
}
# 类型是照规约生成的。改了规约却忘了重新生成，这一步就会不通过。
Invoke-Step '网页：照规约生成的类型是最新的' {
    npm --prefix $View run contracts
    if ($LASTEXITCODE -eq 0) { git diff --exit-code -- view/src/generated }
}
Invoke-Step '网页：代码规则（ESLint）' { npm --prefix $View run lint }
Invoke-Step '网页：类型检查、打包' { npm --prefix $View run build }
Invoke-Step '网页：测试（Vitest）' { npm --prefix $View run test }

Write-Host ''
$Results | Format-Table -AutoSize | Out-String | Write-Host
if ($Results.结果 -contains '没通过') {
    Write-Host '  有步骤没通过。请看上面的输出。' -ForegroundColor Red
    exit 1
}
Write-Host '  全部通过。' -ForegroundColor Green
