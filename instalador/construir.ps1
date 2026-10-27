# Gera o executavel (PyInstaller) e o instalador (Inno Setup).
#   powershell -ExecutionPolicy Bypass -File instalador\construir.ps1
# Resultado: saida\Setup_PonteMTI773_<versao>.exe
$ErrorActionPreference = 'Stop'
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz

$versao = (Select-String -Path 'ponte\__init__.py' -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
"Versao $versao"

# 1) Icone do programa
python ferramentas\gerar_icone.py instalador\ponte.ico
if ($LASTEXITCODE) { throw 'falha ao gerar o icone' }

# 2) Executavel (pasta build\dist\MTI773Ponte, sem console)
python -m PyInstaller --noconfirm --clean --windowed --onedir --name MTI773Ponte `
    --icon "$raiz\instalador\ponte.ico" --distpath build\dist --workpath build\tmp --specpath build `
    MTI773Ponte.pyw
if ($LASTEXITCODE) { throw 'falha no PyInstaller' }

# 3) Instalador
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 nao encontrado' }
& $iscc "/DVersao=$versao" instalador\MTI773Ponte.iss
if ($LASTEXITCODE) { throw 'falha no Inno Setup' }
"OK: saida\Setup_PonteMTI773_$versao.exe"
