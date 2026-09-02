# Yvaine Astra AI - Python 后端启动脚本
$ErrorActionPreference = "Stop"

Write-Host "🌟 Yvaine Astra AI 后端启动器" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

# 检查虚拟环境
if (-not (Test-Path "./venv")) {
    Write-Host "📦 虚拟环境不存在，正在创建..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 虚拟环境创建失败" -ForegroundColor Red
        exit 1
    }
}

# 激活虚拟环境
Write-Host "🔌 激活虚拟环境..." -ForegroundColor Green
& ./venv/Scripts/Activate.ps1

# 检查依赖
Write-Host "📥 检查依赖..." -ForegroundColor Green
$pipList = pip list --format=freeze
$requirements = Get-Content ./backend/requirements.txt

$missingDeps = @()
foreach ($line in $requirements) {
    if ($line -match '^([a-zA-Z0-9_-]+)==') {
        $pkgName = $Matches[1].ToLower()
        if (-not ($pipList | Where-Object { $_ -match "^$pkgName==" })) {
            $missingDeps += $line
        }
    }
}

if ($missingDeps.Count -gt 0) {
    Write-Host "📦 安装缺失的依赖..." -ForegroundColor Yellow
    pip install -r ./backend/requirements.txt
}

# 检查 .env 文件
if (-not (Test-Path "./backend/.env")) {
    Write-Host "⚠️ 未找到 .env 文件，从示例创建..." -ForegroundColor Yellow
    Copy-Item ./backend/.env.example ./backend/.env
    Write-Host "📝 请编辑 backend/.env 文件，填入你的 API Key" -ForegroundColor Cyan
}

# 启动后端
Write-Host ""
Write-Host "🚀 启动 Yvaine 后端服务..." -ForegroundColor Green
Write-Host "   地址: http://127.0.0.1:8000" -ForegroundColor Gray
Write-Host "   WebSocket: ws://127.0.0.1:8000/ws/chat" -ForegroundColor Gray
Write-Host ""
Set-Location ./backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload