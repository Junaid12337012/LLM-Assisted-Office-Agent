param(
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
$python = Join-Path $repoRoot '.tools\python311\runtime\python.exe'
$backend = Join-Path $repoRoot 'desktop_backend.py'
$desktopScript = Join-Path $repoRoot 'desktop_app.ps1'

if (-not (Test-Path $python)) {
    throw "Portable Python runtime not found at $python"
}
if (-not (Test-Path $backend)) {
    throw "Desktop backend not found at $backend"
}
if (-not (Test-Path $desktopScript)) {
    throw "Desktop app script not found at $desktopScript"
}

function Invoke-BackendJson {
    param(
        [string[]]$Arguments
    )

    $output = & $python $backend @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ([string]::Join([Environment]::NewLine, ($output | ForEach-Object { $_.ToString() })))
    }

    $raw = [string]::Join([Environment]::NewLine, ($output | ForEach-Object { $_.ToString() }))
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

$commandCache = Invoke-BackendJson -Arguments @('list-commands')
$knownCommands = @{}
foreach ($command in $commandCache.commands) {
    $knownCommands[$command.name] = $command
}

$safeMode = $true
$confirmRisky = $false

function Get-TodayIsoDate {
    return (Get-Date).ToString('yyyy-MM-dd')
}

function Quote-AgentValue {
    param(
        [string]$Value
    )

    if ($null -eq $Value) {
        return '""'
    }

    $sanitized = $Value.Replace('"', "'")
    if ([string]::IsNullOrWhiteSpace($sanitized)) {
        return '""'
    }
    if ($sanitized -match '[\s=]') {
        return '"' + $sanitized + '"'
    }
    return $sanitized
}

function Parse-AgentCommand {
    param(
        [string]$RawCommand
    )

    $trimmed = $RawCommand.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        return $null
    }

    if ($trimmed.StartsWith('run ')) {
        $trimmed = $trimmed.Substring(4).Trim()
    }

    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        return $null
    }

    $spaceIndex = $trimmed.IndexOf(' ')
    if ($spaceIndex -lt 0) {
        $commandName = $trimmed
        $argumentsText = ''
    }
    else {
        $commandName = $trimmed.Substring(0, $spaceIndex)
        $argumentsText = $trimmed.Substring($spaceIndex + 1)
    }

    $values = @{}
    $pattern = '(?<key>[A-Za-z_][A-Za-z0-9_]*)=(?<value>"[^"]*"|''[^'']*''|\S+)'
    foreach ($match in [regex]::Matches($argumentsText, $pattern)) {
        $key = $match.Groups['key'].Value
        $value = $match.Groups['value'].Value
        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$key] = $value
    }

    return @{
        command_name = $commandName
        values = $values
    }
}

function Build-AgentCommand {
    param(
        [string]$CommandName,
        [hashtable]$Values,
        [object]$Metadata
    )

    $parts = @('run', $CommandName)
    $usedKeys = @{}

    foreach ($parameter in $Metadata.parameters) {
        if ($Values.ContainsKey($parameter.name)) {
            $parts += ('{0}={1}' -f $parameter.name, (Quote-AgentValue -Value ([string]$Values[$parameter.name])))
            $usedKeys[$parameter.name] = $true
        }
    }

    foreach ($key in ($Values.Keys | Sort-Object)) {
        if (-not $usedKeys.ContainsKey($key)) {
            $parts += ('{0}={1}' -f $key, (Quote-AgentValue -Value ([string]$Values[$key])))
        }
    }

    return $parts -join ' '
}

function Get-ParameterDefault {
    param(
        [string]$CommandName,
        [string]$ParameterName,
        [hashtable]$ExistingValues
    )

    $today = if ($ExistingValues.ContainsKey('run_date') -and -not [string]::IsNullOrWhiteSpace([string]$ExistingValues['run_date'])) {
        [string]$ExistingValues['run_date']
    }
    else {
        Get-TodayIsoDate
    }

    switch ("$CommandName::$ParameterName") {
        'mvp.start_day::run_date' { return $today }
        'mvp.start_day::note_path' { return "data/evidence/notes/start_day_$today.md" }
        'mvp.note::run_date' { return $today }
        'mvp.note::note_title' { return 'Quick Note' }
        'mvp.note::note_path' { return "data/evidence/notes/quick_note_$today.txt" }
        'mvp.download_report::run_date' { return $today }
        'mvp.download_report::download_dir' { return 'data/evidence/exports' }
        'mvp.download_report::export_dir' { return 'data/evidence/exports' }
        'browser.download_daily_report::download_dir' { return 'data/evidence/exports' }
        'browser.download_daily_report::export_dir' { return 'data/evidence/exports' }
        'browser.download_daily_report::run_date' { return $today }
        'reports.end_of_day_summary::run_date' { return $today }
        'reports.end_of_day_summary::export_path' { return "data/evidence/exports/summary_$today.json" }
        'mvp.end_day::run_date' { return $today }
        'mvp.end_day::summary_output' { return "data/evidence/exports/end_of_day_$today.json" }
        'portal.upload_latest_file::source_dir' { return 'data/evidence/exports' }
        default { return $null }
    }
}

function Resolve-AgentShortcut {
    param(
        [string]$InputText
    )

    $trimmed = $InputText.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        return $null
    }

    $normalized = ($trimmed -replace '\s+', ' ').Trim().ToLowerInvariant()
    switch ($normalized) {
        'paint' { return 'run desktop.demo_paint' }
        'open paint' { return 'run desktop.demo_paint' }
        'notepad' { return 'run desktop.demo_notepad' }
        'open notepad' { return 'run desktop.demo_notepad' }
        'workspace' { return 'run workspace.open_all' }
        'open workspace' { return 'run workspace.open_all' }
        'start day' { return 'run mvp.start_day' }
        'begin day' { return 'run mvp.start_day' }
        'download report' { return 'run mvp.download_report' }
        'daily report' { return 'run mvp.download_report' }
        'end day' { return 'run mvp.end_day' }
        'finish day' { return 'run mvp.end_day' }
        'summary today' { return 'run mvp.end_day' }
        'today summary' { return 'run mvp.end_day' }
        default { }
    }

    if ($trimmed -match '^(?:note|quick note)\s+(.+)$') {
        $noteText = $Matches[1].Trim()
        return ('run mvp.note note_text={0}' -f (Quote-AgentValue -Value $noteText))
    }

    return $trimmed
}

function Complete-AgentCommand {
    param(
        [string]$InputText,
        [switch]$Quiet
    )

    $resolved = Resolve-AgentShortcut -InputText $InputText
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        return $null
    }

    $parsed = Parse-AgentCommand -RawCommand $resolved
    if ($null -eq $parsed) {
        return $resolved
    }

    $commandName = [string]$parsed.command_name
    if (-not $knownCommands.ContainsKey($commandName)) {
        if ($resolved.StartsWith('run ')) {
            return $resolved
        }
        return $resolved
    }

    $metadata = $knownCommands[$commandName]
    $values = @{}
    foreach ($key in $parsed.values.Keys) {
        $values[$key] = [string]$parsed.values[$key]
    }

    $appliedDefaults = @()
    foreach ($parameter in $metadata.parameters) {
        if ($values.ContainsKey($parameter.name)) {
            continue
        }

        $default = Get-ParameterDefault -CommandName $commandName -ParameterName $parameter.name -ExistingValues $values
        if (-not [string]::IsNullOrWhiteSpace([string]$default)) {
            $values[$parameter.name] = [string]$default
            $appliedDefaults += ('{0}={1}' -f $parameter.name, $default)
            continue
        }

        if ($parameter.required) {
            $prompt = '{0} ({1})' -f $parameter.name, $parameter.type
            if ($parameter.enum -and $parameter.enum.Count -gt 0) {
                $prompt = '{0} [{1}]' -f $prompt, ($parameter.enum -join ', ')
            }
            $inputValue = Read-Host $prompt
            if ([string]::IsNullOrWhiteSpace($inputValue)) {
                throw "Missing required parameter '$($parameter.name)' for '$commandName'."
            }
            $values[$parameter.name] = $inputValue.Trim()
        }
    }

    if (-not $Quiet -and $appliedDefaults.Count -gt 0) {
        Write-Host ('Using defaults: {0}' -f ($appliedDefaults -join ', ')) -ForegroundColor DarkGray
    }

    return Build-AgentCommand -CommandName $commandName -Values $values -Metadata $metadata
}

function Show-Banner {
    Write-Host ''
    Write-Host 'Office Automation Agent - Phase 1 MVP' -ForegroundColor Cyan
    Write-Host 'Type a command and the workflow engine will run it for you.' -ForegroundColor DarkGray
    Write-Host 'Try: start day, note Finish invoices, download report, end day, paint' -ForegroundColor DarkGray
    Write-Host 'Built-ins: help, commands, shortcuts, examples, runs, show <id>, safe on/off, confirm on/off, desktop, clear, exit' -ForegroundColor DarkGray
    Write-Host ''
}

function Show-Settings {
    $safeText = if ($safeMode) { 'ON' } else { 'OFF' }
    $confirmText = if ($confirmRisky) { 'ON' } else { 'OFF' }
    Write-Host ("safe_mode=$safeText confirm_risky=$confirmText") -ForegroundColor Yellow
}

function Show-Help {
    Write-Host ''
    Write-Host 'How to use the agent:' -ForegroundColor Green
    Write-Host '  1. Type a shortcut like start day or note Finish invoices' -ForegroundColor Gray
    Write-Host '  2. Or run a named workflow like mvp.download_report or desktop.demo_paint' -ForegroundColor Gray
    Write-Host '  3. Missing values are filled with sensible defaults or prompted for when needed' -ForegroundColor Gray
    Write-Host '  4. Use runs to see history and show <id> to inspect step logs' -ForegroundColor Gray
    Write-Host ''
    Write-Host 'Built-in console commands:' -ForegroundColor Green
    Write-Host '  help           Show this help text' -ForegroundColor Gray
    Write-Host '  commands       List available workflow commands' -ForegroundColor Gray
    Write-Host '  shortcuts      Show plain-English shortcuts' -ForegroundColor Gray
    Write-Host '  examples       Show example command lines' -ForegroundColor Gray
    Write-Host '  runs [n]       Show recent run history' -ForegroundColor Gray
    Write-Host '  show <id>      Show one run and its step logs' -ForegroundColor Gray
    Write-Host '  safe on/off    Toggle safe mode' -ForegroundColor Gray
    Write-Host '  confirm on/off Toggle auto-approval for risky actions' -ForegroundColor Gray
    Write-Host '  desktop        Open the desktop GUI window' -ForegroundColor Gray
    Write-Host '  clear          Clear the console' -ForegroundColor Gray
    Write-Host '  exit           Close the agent console' -ForegroundColor Gray
    Write-Host ''
}

function Show-Shortcuts {
    Write-Host ''
    Write-Host 'Shortcut commands:' -ForegroundColor Green
    Write-Host '  start day                 Create a daily note, open the workspace page, and open the exports folder' -ForegroundColor Gray
    Write-Host '  note Finish invoices      Save a quick note and open it in Notepad' -ForegroundColor Gray
    Write-Host '  download report           Download the sample daily report into exports' -ForegroundColor Gray
    Write-Host '  end day                   Export a day summary and open it in Notepad' -ForegroundColor Gray
    Write-Host '  paint                     Launch Microsoft Paint' -ForegroundColor Gray
    Write-Host '  notepad                   Launch the demo Notepad note' -ForegroundColor Gray
    Write-Host '  workspace                 Open the workspace browser page and exports folder' -ForegroundColor Gray
    Write-Host ''
}

function Show-Commands {
    Write-Host ''
    Write-Host 'Available workflow commands:' -ForegroundColor Green
    foreach ($command in ($commandCache.commands | Sort-Object name)) {
        $risk = $command.risk.ToUpper()
        Write-Host ("  {0,-30}  [{1}]  {2}" -f $command.name, $risk, $command.description) -ForegroundColor Gray
    }
    Write-Host ''
}

function Show-Examples {
    Write-Host ''
    Write-Host 'Recommended MVP commands:' -ForegroundColor Green
    Write-Host '  start day' -ForegroundColor Gray
    Write-Host '  note Call vendor before 3 PM' -ForegroundColor Gray
    Write-Host '  download report' -ForegroundColor Gray
    Write-Host '  end day' -ForegroundColor Gray
    Write-Host '  paint' -ForegroundColor Gray
    Write-Host ''
    Write-Host 'Advanced command lines:' -ForegroundColor Green
    foreach ($command in ($commandCache.commands | Sort-Object name)) {
        Write-Host ("  {0}" -f $command.example) -ForegroundColor Gray
    }
    Write-Host ''
}

function Show-Runs {
    param(
        [int]$Limit = 10
    )

    $payload = Invoke-BackendJson -Arguments @('list-runs', '--limit', [string]$Limit)
    Write-Host ''
    if (-not $payload.runs -or $payload.runs.Count -eq 0) {
        Write-Host 'No runs found yet.' -ForegroundColor DarkGray
        Write-Host ''
        return
    }

    Write-Host 'Recent runs:' -ForegroundColor Green
    foreach ($run in $payload.runs) {
        Write-Host ("  #{0,-4} {1,-28} {2,-10} {3}" -f $run.id, $run.command_name, $run.status, $run.started_at) -ForegroundColor Gray
    }
    Write-Host ''
}

function Show-RunDetails {
    param(
        [int]$RunId
    )

    $payload = Invoke-BackendJson -Arguments @('run-details', '--run-id', [string]$RunId)
    Write-Host ''
    Write-Host ("Run #{0} - {1}" -f $payload.run.id, $payload.run.command_name) -ForegroundColor Green
    Write-Host ("Status: {0}" -f $payload.run.status) -ForegroundColor Gray
    Write-Host ("Started: {0}" -f $payload.run.started_at) -ForegroundColor Gray
    if ($payload.run.finished_at) {
        Write-Host ("Finished: {0}" -f $payload.run.finished_at) -ForegroundColor Gray
    }
    Write-Host 'Summary:' -ForegroundColor Gray
    Write-Host (($payload.run.summary | ConvertTo-Json -Depth 10)) -ForegroundColor DarkGray
    Write-Host 'Steps:' -ForegroundColor Gray
    foreach ($step in $payload.steps) {
        Write-Host ("  - {0,-20} {1,-18} {2}" -f $step.step_id, $step.status, $step.message) -ForegroundColor Gray
    }
    Write-Host ''
}

function Invoke-AgentRun {
    param(
        [string]$RawInput
    )

    try {
        $resolved = Complete-AgentCommand -InputText $RawInput
        if (-not $resolved) {
            return
        }
    }
    catch {
        Write-Host ("Command failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
        Write-Host ''
        return
    }

    $arguments = @('run-command', '--raw-command', $resolved)
    if ($safeMode) {
        $arguments += '--safe-mode'
    }
    if ($confirmRisky) {
        $arguments += '--confirm-risky'
    }

    Write-Host ''
    Write-Host ("> {0}" -f $resolved) -ForegroundColor Cyan
    try {
        $payload = Invoke-BackendJson -Arguments $arguments
        $outcome = $payload.outcome
        if ($outcome.status -eq 'completed') {
            Write-Host ("Completed run #{0}" -f $outcome.run_id) -ForegroundColor Green
        }
        elseif ($outcome.status -eq 'failed') {
            Write-Host ("Run #{0} failed" -f $outcome.run_id) -ForegroundColor Red
        }
        else {
            Write-Host ("Run #{0} status: {1}" -f $outcome.run_id, $outcome.status) -ForegroundColor Yellow
        }
        Write-Host ("Workflow: {0}" -f $payload.run.workflow_id) -ForegroundColor Gray
        Write-Host ("Steps: {0}" -f (($outcome.completed_steps -join ', '))) -ForegroundColor Gray
        if ($outcome.last_error) {
            Write-Host ("Error: {0}" -f $outcome.last_error) -ForegroundColor Red
        }
        Write-Host 'Summary:' -ForegroundColor Gray
        Write-Host (($outcome.summary | ConvertTo-Json -Depth 10)) -ForegroundColor DarkGray
        Write-Host ''
    }
    catch {
        Write-Host ("Command failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
        Write-Host ''
    }
}

if ($SelfTest) {
    $startDay = Complete-AgentCommand -InputText 'start day' -Quiet
    $quickNote = Complete-AgentCommand -InputText 'note finish invoices' -Quiet
    $downloadReport = Complete-AgentCommand -InputText 'download report' -Quiet
    $endDay = Complete-AgentCommand -InputText 'end day' -Quiet

    if ($startDay -notmatch '^run mvp\.start_day run_date=\d{4}-\d{2}-\d{2} note_path=') {
        throw 'start day shortcut resolution failed.'
    }
    if ($quickNote -notmatch '^run mvp\.note run_date=\d{4}-\d{2}-\d{2} note_text="finish invoices" note_title="Quick Note" note_path=') {
        throw 'note shortcut resolution failed.'
    }
    if ($downloadReport -notmatch '^run mvp\.download_report run_date=\d{4}-\d{2}-\d{2} download_dir=data/evidence/exports export_dir=data/evidence/exports$') {
        throw 'download report shortcut resolution failed.'
    }
    if ($endDay -notmatch '^run mvp\.end_day run_date=\d{4}-\d{2}-\d{2} summary_output=data/evidence/exports/end_of_day_\d{4}-\d{2}-\d{2}\.json$') {
        throw 'end day shortcut resolution failed.'
    }

    Write-Output 'agent-console-selftest-ok'
    exit 0
}

Show-Banner
Show-Settings

while ($true) {
    $inputText = Read-Host 'agent'
    if ($null -eq $inputText) {
        break
    }

    $trimmed = $inputText.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        continue
    }

    switch -Regex ($trimmed) {
        '^(exit|quit)$' {
            break
        }
        '^help$' {
            Show-Help
            continue
        }
        '^commands$' {
            Show-Commands
            continue
        }
        '^shortcuts$' {
            Show-Shortcuts
            continue
        }
        '^examples$' {
            Show-Examples
            continue
        }
        '^runs(\s+\d+)?$' {
            $parts = $trimmed -split '\s+'
            if ($parts.Length -gt 1) {
                Show-Runs -Limit ([int]$parts[1])
            }
            else {
                Show-Runs -Limit 10
            }
            continue
        }
        '^show\s+\d+$' {
            $runId = [int](($trimmed -split '\s+')[1])
            try {
                Show-RunDetails -RunId $runId
            }
            catch {
                Write-Host $_.Exception.Message -ForegroundColor Red
                Write-Host ''
            }
            continue
        }
        '^safe\s+on$' {
            $safeMode = $true
            Show-Settings
            continue
        }
        '^safe\s+off$' {
            $safeMode = $false
            Show-Settings
            continue
        }
        '^confirm\s+on$' {
            $confirmRisky = $true
            Show-Settings
            continue
        }
        '^confirm\s+off$' {
            $confirmRisky = $false
            Show-Settings
            continue
        }
        '^desktop$' {
            powershell -ExecutionPolicy Bypass -File $desktopScript
            continue
        }
        '^clear$' {
            Clear-Host
            Show-Banner
            Show-Settings
            continue
        }
        default {
            Invoke-AgentRun -RawInput $trimmed
        }
    }
}

Write-Host ''
Write-Host 'Agent console closed.' -ForegroundColor DarkGray
