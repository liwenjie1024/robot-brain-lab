<#
.SYNOPSIS
    커밋 전 로컬 점검: 몸(sim)·ROS 2(ros) 린트·형식·시험(컨테이너), 화면(bench) 린트·형식·시험·빌드, 공용·두뇌 린트·형식·시험.
.EXAMPLE
    .\scripts\check.ps1
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Results = New-Object System.Collections.Generic.List[object]

function Invoke-Step([string]$Name, [string]$Directory, [scriptblock]$Command) {
    Write-Host ''
    Write-Host "▶ $Name" -ForegroundColor Cyan
    $started = Get-Date
    Push-Location $Directory
    # docker·npm은 진행 상황을 stderr에 쓴다. Windows PowerShell은 그 줄을 오류로 바꿔 Stop이면 멈추므로,
    # 단계 안에서는 계속 진행하고 성공 여부는 종료 코드로만 본다.
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
    $Results.Add([pscustomobject]@{ 단계 = $Name; 결과 = $(if ($passed) { '통과' } else { '실패' }); '걸린 시간(초)' = $seconds })
}

Invoke-Step '몸: 형식·린트·시험 (컨테이너)' $Root {
    docker compose run --rm --build sim sh -c 'ruff format --check . && ruff check . && pytest -q'
}
# ROS 2 쪽 몸: 이미지를 만들고 그 안에서 시험한다. 형식·린트는 몸 이미지의 Ruff로 (ROS 이미지에 pip를 쓰지 않으려고)
Invoke-Step 'ROS 2: 빌드·시험 (컨테이너)' $Root {
    docker compose build ros
    if ($LASTEXITCODE -eq 0) {
        docker compose run --rm --no-deps ros bash -c 'source install/setup.bash && cd src/bl01_driver && python3 -m pytest -q test'
    }
}
Invoke-Step 'ROS 2: 형식·린트 (Ruff)' $Root {
    docker compose run --rm --no-deps -v "$(Join-Path $Root 'ros'):/ros" sim sh -c 'cd /ros && ruff format --check . && ruff check .'
}
Invoke-Step '화면: 코드 규칙 (ESLint)' (Join-Path $Root 'bench') { npx eslint . }
Invoke-Step '화면: 형식 검사 (TypeScript)' (Join-Path $Root 'bench') { npx vue-tsc --noEmit }
Invoke-Step '화면: 시험 (Vitest)' (Join-Path $Root 'bench') { npx vitest run }
Invoke-Step '화면: 빌드' (Join-Path $Root 'bench') { npx vite build }
# 공용 코드는 두뇌와 같은 코드 규칙을 쓴다 (공용에는 따로 ESLint 설정이 없다)
Invoke-Step '공용: 코드 규칙·형식·시험' (Join-Path $Root 'shared') {
    npx eslint --config ../brain/eslint.config.js src; if ($LASTEXITCODE -eq 0) { npx tsc --noEmit }; if ($LASTEXITCODE -eq 0) { npx vitest run }
}
Invoke-Step '두뇌: 코드 규칙·형식·시험' (Join-Path $Root 'brain') {
    npx eslint .; if ($LASTEXITCODE -eq 0) { npx tsc --noEmit }; if ($LASTEXITCODE -eq 0) { npx vitest run }
}

Write-Host ''
$Results | Format-Table -AutoSize | Out-String | Write-Host
if ($Results.결과 -contains '실패') {
    Write-Host '  실패한 단계가 있습니다. 위의 출력을 확인해 주세요.' -ForegroundColor Red
    exit 1
}
Write-Host '  모든 점검을 통과했습니다.' -ForegroundColor Green
