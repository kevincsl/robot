param(
    [Parameter(Position = 0)]
    [ValidateSet("start-bg", "shutdown", "status")]
    [string]$Action = "status",
    [int]$WaitSeconds = 2
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startScript = Join-Path $repoRoot "start_robot.bat"
$stdoutLog = Join-Path $repoRoot "robot.bg.stdout.log"
$stderrLog = Join-Path $repoRoot "robot.bg.stderr.log"

function Get-RobotProcesses {
    $escapedRoot = [Regex]::Escape($repoRoot)
    try {
        $viaCim = Get-CimInstance Win32_Process | Where-Object {
            ($_.Name -match "^(teleapp|python|py)(\.exe)?$") -and
            ($_.CommandLine -match $escapedRoot) -and
            ($_.CommandLine -match "robot\.py|teleapp\.exe")
        } | Sort-Object ProcessId
        if ($viaCim) {
            return $viaCim
        }
    } catch {
    }

    $venvPython = (Join-Path $repoRoot ".venv\Scripts\python.exe").ToLowerInvariant()
    $venvTeleapp = (Join-Path $repoRoot ".venv\Scripts\teleapp.exe").ToLowerInvariant()
    $fallback = Get-Process -Name teleapp, python, py -ErrorAction SilentlyContinue | ForEach-Object {
        $path = ""
        if ($_.Path) {
            $path = $_.Path.ToLowerInvariant()
        }
        [pscustomobject]@{
            ProcessId       = $_.Id
            ParentProcessId = 0
            Name            = "$($_.ProcessName).exe"
            CommandLine     = $path
        }
    }
    $fallback | Where-Object {
        $_.CommandLine -eq $venvPython -or $_.CommandLine -eq $venvTeleapp
    } | Sort-Object ProcessId
}

switch ($Action) {
    "start-bg" {
        if (-not (Test-Path -LiteralPath $startScript)) {
            Write-Output "[robot] missing start script: $startScript"
            exit 1
        }
        if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".venv\Scripts\python.exe"))) {
            Write-Output "[robot] missing venv python. run bootstrap_robot.bat first."
            exit 1
        }

        $existing = Get-RobotProcesses
        if ($existing) {
            $pids = ($existing | Select-Object -ExpandProperty ProcessId) -join ","
            Write-Output "[robot] already running. pids=$pids"
            exit 0
        }

        Start-Process `
            -FilePath "cmd.exe" `
            -ArgumentList "/c", "start_robot.bat" `
            -WorkingDirectory $repoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog | Out-Null

        if ($WaitSeconds -gt 0) {
            Start-Sleep -Seconds $WaitSeconds
        }

        $running = Get-RobotProcesses
        if ($running) {
            $pids = ($running | Select-Object -ExpandProperty ProcessId) -join ","
            Write-Output "[robot] started in background. pids=$pids"
            Write-Output "[robot] logs: $stderrLog"
            exit 0
        }

        Write-Output "[robot] start requested but process not detected."
        Write-Output "[robot] check logs: $stderrLog"
        exit 2
    }

    "shutdown" {
        $targets = Get-RobotProcesses | Sort-Object ProcessId -Descending
        if (-not $targets) {
            Write-Output "[robot] no robot process found."
            exit 0
        }

        $pids = ($targets | Select-Object -ExpandProperty ProcessId) -join ","
        Write-Output "[robot] stopping pids=$pids"
        foreach ($proc in $targets) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1

        $remain = Get-RobotProcesses
        if ($remain) {
            $remainPids = ($remain | Select-Object -ExpandProperty ProcessId) -join ","
            Write-Output "[robot] some processes are still alive: $remainPids"
            exit 3
        }

        Write-Output "[robot] shutdown complete."
        exit 0
    }

    "status" {
        $running = Get-RobotProcesses
        if (-not $running) {
            Write-Output "[robot] not running."
            exit 0
        }

        Write-Output "[robot] running processes:"
        $running | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-Table -AutoSize | Out-String | Write-Output
        exit 0
    }
}
