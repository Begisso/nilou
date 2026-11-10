# Builds dist\Nilou.exe - one portable file, no installer.
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install --quiet --upgrade pip pillow pyinstaller

Write-Host 'Rendering icon...'
& $py tools\make_icon.py

Write-Host 'Running tests...'
& $py -m unittest discover tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }

Write-Host 'Building Nilou.exe...'
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name Nilou `
    --icon assets\nilou.ico `
    --version-file tools\version_info.txt `
    --add-data 'assets;assets' `
    --add-data 'extension;extension' `
    --exclude-module unittest --exclude-module pydoc --exclude-module test `
    Nilou.pyw
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$exe = Get-Item dist\Nilou.exe
Write-Host ("Built {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB))
