# Executa script Python com saida em tempo real no console e append no log.
param(
    [string]$PythonExe = 'python',
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$LogFile,
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$ScriptArgLine = ''
)

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $WorkingDirectory

$ScriptArgs = @()
if (-not [string]::IsNullOrWhiteSpace($ScriptArgLine)) {
    $ScriptArgs = $ScriptArgLine.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
}

$escapedArgs = @('-u', $Script) + $ScriptArgs | ForEach-Object {
    if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PythonExe
$psi.Arguments = ($escapedArgs -join ' ')
$psi.WorkingDirectory = $WorkingDirectory
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
$psi.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
$psi.CreateNoWindow = $true

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi

$emit = {
    param([string]$Line)
    if ([string]::IsNullOrEmpty($Line)) { return }
    $stamp = Get-Date -Format 'HH:mm:ss'
    $formatted = "[$stamp] $Line"
    Write-Host $formatted
    Add-Content -LiteralPath $LogFile -Value $formatted -Encoding utf8
}

$null = $proc.Start()
while (-not $proc.StandardOutput.EndOfStream) {
    $line = $proc.StandardOutput.ReadLine()
    if ($null -ne $line) { & $emit $line }
}
while (-not $proc.StandardError.EndOfStream) {
    $line = $proc.StandardError.ReadLine()
    if ($null -ne $line) { & $emit $line }
}
$proc.WaitForExit()
exit $proc.ExitCode
