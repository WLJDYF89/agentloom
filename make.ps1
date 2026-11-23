# make.ps1 —— Makefile 的 Windows 等价入口
#
# 本机（以及多数 Windows 环境）没有 GNU make。这个脚本提供与 Makefile
# 一一对应的目标，保证「make lint / make test 能跑通」这条验收标准
# 在 Windows 上同样成立。
#
#   powershell -ExecutionPolicy Bypass -File make.ps1 lint
#   powershell -ExecutionPolicy Bypass -File make.ps1 test
#   powershell -ExecutionPolicy Bypass -File make.ps1 check
#
# 更短的写法见同目录 make.cmd：make lint / make test / make check
#
# 注意：本文件必须以 UTF-8 with BOM 保存。Windows PowerShell 5.1 在没有 BOM
# 时按当前 ANSI 代码页解析脚本，中文注释会被解成乱码进而引发语法错误。

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = 'help',

    # 建 venv 用的解释器；不传则自动探测
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $RepoRoot 'backend'
$VenvDir = Join-Path $Backend '.venv'
$VenvPy = Join-Path $VenvDir 'Scripts\python.exe'

function Write-Step([string]$Message) {
    Write-Host "> $Message" -ForegroundColor Cyan
}

function Resolve-Python {
    if ($Python) { return $Python }
    # 优先 3.12，其次任意 python
    foreach ($candidate in @('py -3.12', 'python3.12', 'python')) {
        $parts = $candidate.Split(' ')
        $exe = Get-Command $parts[0] -ErrorAction SilentlyContinue
        if ($exe) {
            $probe = & $exe.Source @($parts[1..($parts.Count - 1)]) --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$probe" -match '3\.12') {
                return $candidate
            }
        }
    }
    throw '找不到 Python 3.12，请用 -Python 指定解释器路径'
}

function Invoke-Py {
    param([string[]]$Arguments)
    if (-not (Test-Path $VenvPy)) {
        throw '虚拟环境不存在：先运行 make setup'
    }
    Push-Location $Backend
    try {
        & $VenvPy @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "命令失败（exit $LASTEXITCODE）：python $($Arguments -join ' ')"
        }
    }
    finally { Pop-Location }
}

function Task-Venv {
    if (Test-Path $VenvPy) {
        Write-Step "虚拟环境已存在：$VenvDir"
        return
    }
    $py = Resolve-Python
    Write-Step "创建虚拟环境（$py）"
    $parts = $py.Split(' ')
    Push-Location $RepoRoot
    try {
        & $parts[0] @($parts[1..($parts.Count - 1)]) -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
    }
    finally { Pop-Location }
}

function Task-Deps {
    if (-not (Test-Path $VenvPy)) { Task-Venv }
    Write-Step '升级 pip'
    & $VenvPy -m pip install -q --upgrade pip
    Write-Step '安装依赖（含 dev）'
    & $VenvPy -m pip install -q -e "$Backend[dev]"
    if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
}

function Task-Lint {
    Write-Step 'ruff check'
    Invoke-Py @('-m', 'ruff', 'check', '.')
    Write-Step 'ruff format --check'
    Invoke-Py @('-m', 'ruff', 'format', '--check', '.')
}

function Task-Format {
    Write-Step 'ruff check --fix'
    Invoke-Py @('-m', 'ruff', 'check', '--fix', '.')
    Write-Step 'ruff format'
    Invoke-Py @('-m', 'ruff', 'format', '.')
}

function Task-Typecheck {
    Write-Step 'mypy'
    Invoke-Py @('-m', 'mypy')
}

function Task-Test {
    Write-Step 'pytest'
    Invoke-Py @('-m', 'pytest')
}

function Task-TestCov {
    Write-Step 'pytest --cov'
    Invoke-Py @('-m', 'pytest', '--cov=app', '--cov-report=term-missing')
}

function Task-Clean {
    Write-Step '清理缓存'
    foreach ($p in @('.pytest_cache', '.mypy_cache', '.ruff_cache', '.coverage', 'htmlcov')) {
        $full = Join-Path $Backend $p
        if (Test-Path $full) { Remove-Item -Recurse -Force $full }
    }
    Get-ChildItem -Path $Backend -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host '已清理' -ForegroundColor Green
}

function Show-Help {
    @'
  setup       一键初始化（建 venv + 装依赖）
  venv        创建虚拟环境
  deps        安装依赖（含 dev）
  lint        ruff 检查（不修改文件）
  format      ruff 自动修复 + 格式化
  typecheck   mypy 严格模式
  test        跑测试
  test-cov    跑测试 + 覆盖率
  check       lint + typecheck + test
  run         本地启动开发服务器
  clean       清理缓存产物
'@ | Write-Host
}

switch ($Target) {
    'help' { Show-Help }
    'venv' { Task-Venv }
    'deps' { Task-Deps }
    'setup' {
        Task-Venv
        Task-Deps
        Write-Host '环境就绪' -ForegroundColor Green
    }
    'lint' { Task-Lint }
    'format' { Task-Format }
    'typecheck' { Task-Typecheck }
    'test' { Task-Test }
    'test-cov' { Task-TestCov }
    'check' {
        Task-Lint
        Task-Typecheck
        Task-Test
        Write-Host '全部通过' -ForegroundColor Green
    }
    'run' {
        Write-Step '启动开发服务器'
        Invoke-Py @('-m', 'app')
    }
    'clean' { Task-Clean }
    default {
        Write-Host "未知目标：$Target。运行 make help 查看可用目标。" -ForegroundColor Red
        exit 1
    }
}
