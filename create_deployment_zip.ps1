# Script para crear ZIP del proyecto listo para cPanel
# Excluye archivos que no deben ir al servidor

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Crear ZIP para Deployment a cPanel" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$zipName = "fisichecker_deploy.zip"
$tempDir = "fisichecker"

# Verificar que estamos en el directorio correcto
if (-not (Test-Path "manage.py")) {
    Write-Host "❌ Error: Ejecuta este script desde el directorio Back/" -ForegroundColor Red
    exit 1
}

Write-Host "📦 Preparando archivos para deployment..." -ForegroundColor Yellow
Write-Host ""

# Crear directorio temporal
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}
New-Item -ItemType Directory -Path $tempDir | Out-Null

# Copiar archivos importantes
Write-Host "📋 Copiando archivos del proyecto..." -ForegroundColor Green

$includePatterns = @(
    "*.py",
    "*.txt",
    "*.md",
    "*.json",
    ".htaccess",
    "FisiChecker",
    "audits"
)

$excludePatterns = @(
    ".venv",
    "venv",
    "__pycache__",
    "*.pyc",
    "*.log",
    "db.sqlite3",
    ".env",
    "staticfiles",
    "media",
    ".git",
    ".pytest_cache",
    "tmp",
    "*.zip"
)

# Copiar todo excepto excluidos
Get-ChildItem -Path . -Recurse | Where-Object {
    $item = $_
    $shouldExclude = $false
    
    foreach ($pattern in $excludePatterns) {
        if ($item.FullName -like "*$pattern*") {
            $shouldExclude = $true
            break
        }
    }
    
    -not $shouldExclude
} | ForEach-Object {
    $relativePath = $_.FullName.Substring((Get-Location).Path.Length + 1)
    $destPath = Join-Path $tempDir $relativePath
    $destDir = Split-Path $destPath -Parent
    
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    
    if (-not $_.PSIsContainer) {
        Copy-Item $_.FullName -Destination $destPath -Force
    }
}

Write-Host "✅ Archivos copiados" -ForegroundColor Green
Write-Host ""

# Crear archivo .env.example en el ZIP (recordatorio)
$envReminder = @"
# RECORDATORIO: Crear archivo .env en el servidor con:
# - SECRET_KEY generada
# - Credenciales de MySQL
# - ALLOWED_HOSTS correcto
# Copia .env.example y completa con valores reales
"@

Set-Content -Path "$tempDir\.env.RECORDATORIO" -Value $envReminder

# Comprimir
Write-Host "🗜️  Comprimiendo archivos a $zipName..." -ForegroundColor Yellow

if (Test-Path $zipName) {
    Remove-Item $zipName -Force
}

Compress-Archive -Path "$tempDir\*" -DestinationPath $zipName -CompressionLevel Optimal

# Limpiar directorio temporal
Remove-Item -Recurse -Force $tempDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✅ ZIP CREADO EXITOSAMENTE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Archivo: $zipName" -ForegroundColor Cyan
$zipSize = (Get-Item $zipName).Length / 1MB
Write-Host "Tamaño: $([math]::Round($zipSize, 2)) MB" -ForegroundColor Cyan
Write-Host ""
Write-Host "📤 Siguiente paso:" -ForegroundColor Yellow
Write-Host "  1. Ve a cPanel File Manager" -ForegroundColor White
Write-Host "  2. Navega a /home/taw/" -ForegroundColor White
Write-Host "  3. Sube $zipName" -ForegroundColor White
Write-Host "  4. Click derecho → Extract (Extraer)" -ForegroundColor White
Write-Host "  5. Renombra la carpeta extraída a 'fisichecker'" -ForegroundColor White
Write-Host ""
