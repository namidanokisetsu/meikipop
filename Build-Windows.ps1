param(
    [string]$Python = "$PSScriptRoot\.venv-desktop\Scripts\python.exe",
    [string]$ISCC = "",
    [switch]$SkipBundle
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $SkipBundle) {
        & $Python -m PyInstaller --noconfirm meikipop.desktop.win.spec
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    }
    if (-not $ISCC) {
        $ISCC = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
            Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $ISCC) { throw 'Install Inno Setup 6 or pass -ISCC <path>' }
    $version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read app version' }
    & $ISCC "/DAppVersion=$version" packaging/meikipop.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
    $installer = Get-Item -LiteralPath "dist/Meikipop-$version-windows-x64-setup.exe"
    $hash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($installer.Name)" | Set-Content -Encoding ascii -LiteralPath "$($installer.FullName).sha256"
    Write-Output $installer.FullName
} finally { Pop-Location }
