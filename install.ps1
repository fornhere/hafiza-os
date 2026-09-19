param([string]$Agent, [string]$Vault, [switch]$SkipObsidian, [switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
$pythonPrefix = @('-3')
if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue; $pythonPrefix = @() }
if (-not $pythonCommand) { throw 'Python 3.10+ kurup aynı komutu tekrar çalıştırın: https://www.python.org/downloads/' }
& $pythonCommand.Source @pythonPrefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Çalışan Python 3.10+ gerekli.' }
$hafizaTemporary = Join-Path ([IO.Path]::GetTempPath()) ('hafiza-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $hafizaTemporary | Out-Null
try {
  $revision = (Invoke-RestMethod 'https://api.github.com/repos/fornhere/hafiza-os/commits/main').sha
  if ($revision -notmatch '^[a-f0-9]{40}$') { throw 'Geçersiz kaynak sürümü.' }
  $scriptPath = Join-Path $hafizaTemporary 'baslat.py'
  Invoke-WebRequest "https://raw.githubusercontent.com/fornhere/hafiza-os/$revision/baslat.py" -OutFile $scriptPath -UseBasicParsing
  $installerArgs = @($scriptPath, '--revision', $revision)
  if ($Agent) { $installerArgs += @('--agent', $Agent) }
  if ($Vault) { $installerArgs += @('--vault', $Vault) }
  if ($SkipObsidian) { $installerArgs += '--skip-obsidian' }
  if ($NonInteractive) { $installerArgs += '--non-interactive' }
  & $pythonCommand.Source @pythonPrefix @installerArgs
  if ($LASTEXITCODE -ne 0) { throw 'Kurulum tamamlanmadı.' }
} finally { Remove-Item -Recurse -Force $hafizaTemporary }
