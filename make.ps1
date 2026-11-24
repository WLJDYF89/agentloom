# make.ps1 —— Makefile 的 Windows 等价入口
#
# 本机（以及多数 Windows 环境）没有 GNU make。这个脚本提供与 Makefile
# 一一对应的目标，保证「make lint / make test 能跑通」这条验收标准
# 在 Windows 上同样成立。
#
#   powershell -ExecutionPolicy Bypass -File make.ps1 lint
#   powershell -ExecutionPolicy Bypass -File make.ps1 test
#   powershell -ExecutionPolicy Bypass -File make.ps1 check
#   powershell -ExecutionPolicy Bypass -File make.ps1 up
#
# 更短的写法见同目录 make.cmd：make lint / make test / make up
#
# 注意：本文件必须以 UTF-8 with BOM 保存。Windows PowerShell 5.1 在没有 BOM
# 时按当前 ANSI 代码页解析脚本，中文注释会被解成乱码进而引发语法错误。
# 改完本文件请复核首字节：`Format-Hex make.ps1 -Count 3` 应为 EF BB BF。

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
$ComposeFile = 'deploy/docker-compose.yml'

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

# 统一的 docker 调用出口：检查命令存在、定位到仓库根、检查退出码。
# 所有 compose 操作都从这里走，避免每处各写一遍参数与错误处理。
function Invoke-Docker {
    param([string[]]$Arguments)
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw '找不到 docker 命令。请确认 Docker Desktop 已安装并在 PATH 中'
    }
    Push-Location $RepoRoot
    try {
        & $docker.Source @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "命令失败（exit $LASTEXITCODE）：docker $($Arguments -join ' ')"
        }
    }
    finally { Pop-Location }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    Invoke-Docker (@('compose', '-f', $ComposeFile) + $Arguments)
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

# ---- Docker Compose ----
# 这些目标故意不进 check 的依赖链：CI 环境通常没有 Docker 守护进程，
# 放进去会让 make check 无辜失败。

function Get-HealthUrl {
    $port = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { '8000' }
    return "http://localhost:$port/health"
}

function Task-Up {
    Write-Step '启动全栈并等待健康检查通过'
    # --wait 是关键：不加它 up -d 会立刻返回 0，哪怕容器两秒后就崩了。
    # 加了它，命令返回 0 就等于所有 healthcheck 都过了。
    Invoke-Compose @('up', '-d', '--wait')
    Write-Host "全栈就绪：$(Get-HealthUrl)" -ForegroundColor Green
}

function Task-UpBuild {
    Write-Step '重建镜像后启动全栈（等待健康）'
    Invoke-Compose @('up', '-d', '--build', '--wait')
    Write-Host "全栈就绪（已重建镜像）：$(Get-HealthUrl)" -ForegroundColor Green
}

function Task-Down {
    Write-Step '停止容器（保留数据卷）'
    Invoke-Compose @('down')
    Write-Host '已停止' -ForegroundColor Green
}

function Task-Logs {
    Write-Step '跟随日志（Ctrl+C 退出）'
    Invoke-Compose @('logs', '-f')
}

function Task-Ps {
    Invoke-Compose @('ps')
}

# ---- 数据库迁移 ----
# 迁移才是正规路径：deploy/postgres/init/ 下的 SQL 只在空数据卷的第一次启动跑一次。

function Task-Migrate {
    Write-Step '迁移到最新版本'
    Invoke-Py @('-m', 'alembic', 'upgrade', 'head')
    Write-Host '迁移完成' -ForegroundColor Green
}

function Task-MigrateDown {
    Write-Step '回退一个版本'
    Invoke-Py @('-m', 'alembic', 'downgrade', '-1')
    Write-Host '已回退' -ForegroundColor Green
}

function Task-MigrateHistory {
    Invoke-Py @('-m', 'alembic', 'history', '--verbose')
    Invoke-Py @('-m', 'alembic', 'current')
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
  up          起全栈（postgres + backend）并等到健康
  up-build    重建镜像后再起
  down        停容器（保留数据卷）
  logs        跟随全栈日志
  ps          查看容器与健康状态
  migrate     数据库迁移到最新版本
  migrate-down 回退一个版本
  migrate-history 查看迁移历史与当前版本
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
    'up' { Task-Up }
    'up-build' { Task-UpBuild }
    'down' { Task-Down }
    'logs' { Task-Logs }
    'ps' { Task-Ps }
    'migrate' { Task-Migrate }
    'migrate-down' { Task-MigrateDown }
    'migrate-history' { Task-MigrateHistory }
    'clean' { Task-Clean }
    default {
        Write-Host "未知目标：$Target。运行 make help 查看可用目标。" -ForegroundColor Red
        exit 1
    }
}
