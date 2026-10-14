# Rebuild the embedded OpenCL GPU stress binary.
#
# Requires an NVIDIA CUDA toolkit (for CL/cl.h and OpenCL.lib) plus a
# mingw-w64 g++ with OpenCL support. Output: junkcleaner/assets/gpu_stress.exe
#
# Why a separate native binary: the packaged EXE must be able to stress the
# GPU on any PC without requiring the user to install Python + CUDA PyTorch.
# This program only depends on the OpenCL runtime shipped with NVIDIA drivers.

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$src = Join-Path $PSScriptRoot 'gpu_stress.c'
$out = Join-Path $root 'junkcleaner\assets\gpu_stress.exe'

$cudaRoot = Get-ChildItem 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA' `
    -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $cudaRoot) {
    throw 'CUDA toolkit not found (needed for CL/cl.h and OpenCL.lib)'
}
$inc = Join-Path $cudaRoot.FullName 'include'
$lib = Join-Path $cudaRoot.FullName 'lib\x64'

$gxx = (Get-Command g++ -ErrorAction SilentlyContinue).Source
if (-not $gxx) { throw 'g++ not found on PATH' }

Write-Host "compiling $src -> $out"
& $gxx $src -o $out -I"$inc" -L"$lib" -lOpenCL -O2
if ($LASTEXITCODE -ne 0) { throw "build failed: $LASTEXITCODE" }
Get-Item -LiteralPath $out | Select-Object FullName,Length,LastWriteTime
