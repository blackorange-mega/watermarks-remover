<#
.SYNOPSIS
  Port a Windows de setup_ctrlregen.sh.

.DESCRIPTION
  Bootstrap del checkout externo noai-watermark para el backend opcional de
  eliminacion en dominio de pixel (CtrlRegen).

  El proyecto upstream (https://github.com/mertizci/noai-watermark) no incluye
  fichero LICENSE, asi que su codigo se trata como all-rights-reserved y NO se
  empaqueta en este repositorio. Este script lo clona en local e instala solo
  las dependencias que necesita clean_ctrlregen.py.

  Diferencia con la version .sh: el venv de Windows vive en .venv\Scripts\
  en vez de .venv/bin/, y si el indice de torch para tu version de CUDA no
  existe se cae al torch por defecto en vez de abortar.

.PARAMETER Dir
  Directorio del checkout (por defecto: $env:NOAI_WATERMARK_DIR o ~\noai-watermark)

.PARAMETER Ref
  Commit a usar (por defecto: el SHA fijado; no apuntes a una rama movil)

.PARAMETER Python
  Interprete usado para crear el venv (por defecto: python)
#>
[CmdletBinding()]
param(
    [string]$Dir,
    [string]$Ref = 'b642ae45d20eded52c96d570985eb4e3e427aac8',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-Checked {
    param([string]$What, [scriptblock]$Block)
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What fallo (codigo $LASTEXITCODE)" }
}

if (-not $Dir) {
    if ($env:NOAI_WATERMARK_DIR) { $Dir = $env:NOAI_WATERMARK_DIR }
    else { $Dir = Join-Path $HOME 'noai-watermark' }
}
$parent = Split-Path -Parent $Dir
if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Force -Path $Dir | Out-Null }
$Dir = (Resolve-Path $Dir).Path

if (-not (Test-Path (Join-Path $Dir '.git'))) {
    Write-Host "Clonando noai-watermark en $Dir (ref fijado: $Ref)"
    Invoke-Checked 'git clone' { git clone --depth 1 --filter=blob:none --sparse https://github.com/mertizci/noai-watermark.git $Dir }
    Invoke-Checked 'git fetch' { git -C $Dir fetch --depth 1 origin $Ref }
    Invoke-Checked 'git checkout' { git -C $Dir checkout --detach $Ref }
    Invoke-Checked 'sparse-checkout' { git -C $Dir sparse-checkout set --no-cone '/src/' }
    $head = (git -C $Dir rev-parse HEAD).Trim()
    if ($head -ne $Ref) { throw "error: se esperaba el ref fijado $Ref, se obtuvo $head" }
} else {
    Write-Host "Usando checkout existente: $Dir"
}

$venvPython = Join-Path $Dir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Creando venv en $Dir\.venv"
    Invoke-Checked 'crear venv' { & $Python -m venv (Join-Path $Dir '.venv') }
}

Write-Host 'Instalando dependencias de Python'
# pip fijado (un --upgrade pip sin pin es un punto de deriva de cadena de suministro).
Invoke-Checked 'pip install pip' { & $venvPython -m pip install --upgrade 'pip==26.2.1' }

# torch con el indice de plataforma correcto antes que el resto de pines.
#
# OJO: nvidia-smi reporta la CUDA MAXIMA QUE SOPORTA EL DRIVER, no la que hay
# que instalar; el driver es retrocompatible, asi que un wheel cu126 corre sin
# problema sobre un driver 13.0. Derivar el tag del wheel de esa cifra -como
# hace la version .sh- es incorrecto en general, y rompe de verdad en GPUs
# antiguas: los wheels cu128+ y CUDA 13 eliminaron Maxwell/Pascal/Volta, asi
# que en una Pascal (sm_61) instalarian un torch sin kernels para la tarjeta y
# fallaria en ejecucion con "no kernel image is available for execution".
# Por eso mandamos la compute capability, no la version del driver.
$cuda = $null
$cc = $null
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $smi = (& nvidia-smi | Out-String)
    if ($smi -match 'CUDA Version:\s*([0-9]+\.[0-9]+)') { $cuda = $Matches[1] }
    $capRaw = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($capRaw -and ($capRaw.Trim() -match '^[0-9]+\.[0-9]+$')) { $cc = [double]$capRaw.Trim() }
}

$torchOk = $false
if ($cuda) {
    if ($cc -and $cc -lt 7.5) {
        # Ultimo indice cuyos wheels aun traen kernels de Maxwell/Pascal/Volta.
        $tag = 'cu126'
        Write-Host "GPU NVIDIA compute capability $cc (anterior a Turing): forzando $tag,"
        Write-Host "porque los wheels cu128+ / CUDA 13 ya no incluyen kernels para esta tarjeta."
    } else {
        $tag = 'cu' + ($cuda -replace '\.', '')
        Write-Host "GPU NVIDIA detectada (driver soporta CUDA $cuda); usando $tag"
    }
    $index = "https://download.pytorch.org/whl/$tag"
    & $venvPython -m pip install torch --index-url $index
    if ($LASTEXITCODE -eq 0) { $torchOk = $true }
    else { Write-Warning "el indice $index fallo; se cae al torch por defecto" }
} else {
    Write-Host 'Sin GPU NVIDIA detectada; instalando torch por defecto (CPU)'
}

if (-not $torchOk) {
    Invoke-Checked 'pip install torch' { & $venvPython -m pip install torch }
}

# Comprobacion decisiva: que el torch instalado traiga kernels para ESTA GPU.
if ($cc) {
    $smTarget = 'sm_' + ($cc -replace '\.', '')
    $archs = (& $venvPython -c "import torch; print(' '.join(torch.cuda.get_arch_list()))" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $archs) {
        if ($archs -match [regex]::Escape($smTarget)) {
            Write-Host "OK: torch incluye $smTarget (archs: $archs)"
        } else {
            Write-Warning "el torch instalado NO incluye $smTarget - CtrlRegen fallara en GPU."
            Write-Warning "archs disponibles: $archs"
            Write-Warning "reinstala con un indice mas antiguo, p.ej.:"
            Write-Warning "  & '$venvPython' -m pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cu126"
        }
    }
}

Invoke-Checked 'pip install requirements' { & $venvPython -m pip install -r (Join-Path $ScriptDir 'requirements-ctrlregen.txt') }

Write-Host ''
Write-Host 'Listo. Para quitar una marca:'
Write-Host ''
Write-Host "  `$env:NOAI_WATERMARK_DIR = '$Dir'"
Write-Host "  & '$venvPython' '$ScriptDir\clean_ctrlregen.py' IMAGEN -o SALIDA"
