param(
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
$python = Join-Path $repoRoot '.tools\python311\runtime\python.exe'
$backend = Join-Path $repoRoot 'desktop_backend.py'
$trainingScript = Join-Path $repoRoot 'training_mode.ps1'

if (-not (Test-Path $python)) { throw "Portable Python runtime not found at $python" }
if (-not (Test-Path $backend)) { throw "Desktop backend not found at $backend" }
if (-not (Test-Path $trainingScript)) { throw "Training mode script not found at $trainingScript" }

function Invoke-BackendJson {
    param([string[]]$Arguments)
    $output = & $python $backend @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ([string]::Join([Environment]::NewLine, ($output | ForEach-Object { $_.ToString() })))
    }
    $raw = [string]::Join([Environment]::NewLine, ($output | ForEach-Object { $_.ToString() }))
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    return $raw | ConvertFrom-Json
}

function Get-TodayIsoDate { (Get-Date).ToString('yyyy-MM-dd') }

function Quote-AgentValue {
    param([string]$Value)
    if ($null -eq $Value) { return '""' }
    $sanitized = $Value.Replace('"', "'")
    if ([string]::IsNullOrWhiteSpace($sanitized)) { return '""' }
    if ($sanitized -match '[\s=]') { return '"' + $sanitized + '"' }
    return $sanitized
}

function Parse-AgentCommand {
    param([string]$RawCommand)
    $trimmed = $RawCommand.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) { return $null }
    if ($trimmed.StartsWith('run ')) { $trimmed = $trimmed.Substring(4).Trim() }
    if ([string]::IsNullOrWhiteSpace($trimmed)) { return $null }
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
    return @{ command_name = $commandName; values = $values }
}

function Build-AgentCommand {
    param([string]$CommandName, [hashtable]$Values, [object]$Metadata)
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
    param([string]$CommandName, [string]$ParameterName, [hashtable]$ExistingValues)
    $today = if ($ExistingValues.ContainsKey('run_date') -and -not [string]::IsNullOrWhiteSpace([string]$ExistingValues['run_date'])) { [string]$ExistingValues['run_date'] } else { Get-TodayIsoDate }
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
        'desktop.print_today_vouchers::app_name' { return 'voucher_app' }
        'desktop.print_today_vouchers::date_from' { return 'today' }
        'desktop.print_today_vouchers::date_to' { return 'today' }
        default { return $null }
    }
}

function Resolve-AgentShortcut {
    param([string]$InputText)
    $trimmed = $InputText.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) { return $null }
    $normalized = ($trimmed -replace '\s+', ' ').Trim().ToLowerInvariant()
    switch ($normalized) {
        'paint' { return 'run desktop.demo_paint' }
        'notepad' { return 'run desktop.demo_notepad' }
        'workspace' { return 'run workspace.open_all' }
        'start day' { return 'run mvp.start_day' }
        'download report' { return 'run mvp.download_report' }
        'end day' { return 'run mvp.end_day' }
        'print all today voucher' { return 'run desktop.print_today_vouchers app_name=voucher_app date_from=today date_to=today' }
        default { }
    }
    if ($trimmed -match '^(?:note|quick note)\s+(.+)$') {
        return ('run mvp.note note_text={0}' -f (Quote-AgentValue -Value $Matches[1].Trim()))
    }
    return $trimmed
}

$commandsPayload = Invoke-BackendJson -Arguments @('list-commands')
$script:commandLookup = @{}
$script:commandListData = @()
foreach ($command in $commandsPayload.commands) {
    $script:commandLookup[[string]$command.name] = $command
    $script:commandListData += $command
}

function Complete-AgentCommand {
    param([string]$InputText)
    $resolved = Resolve-AgentShortcut -InputText $InputText
    if ([string]::IsNullOrWhiteSpace($resolved)) { return $null }
    $parsed = Parse-AgentCommand -RawCommand $resolved
    if ($null -eq $parsed) { return $resolved }
    $commandName = [string]$parsed.command_name
    if (-not $script:commandLookup.ContainsKey($commandName)) { return $resolved }
    $metadata = $script:commandLookup[$commandName]
    $values = @{}
    foreach ($key in $parsed.values.Keys) { $values[$key] = [string]$parsed.values[$key] }
    $missing = @()
    foreach ($parameter in $metadata.parameters) {
        if ($values.ContainsKey($parameter.name)) { continue }
        $default = Get-ParameterDefault -CommandName $commandName -ParameterName $parameter.name -ExistingValues $values
        if (-not [string]::IsNullOrWhiteSpace([string]$default)) { $values[$parameter.name] = [string]$default }
        elseif ($parameter.required) { $missing += $parameter.name }
    }
    if ($missing.Count -gt 0) { throw "Fill these fields before running: $($missing -join ', ')" }
    return Build-AgentCommand -CommandName $commandName -Values $values -Metadata $metadata
}

function Get-AssistantPlanPayload {
    param([string]$Instruction)
    if ([string]::IsNullOrWhiteSpace($Instruction)) { return $null }
    $arguments = @('plan-instruction', '--instruction', $Instruction)
    if ($null -ne $script:localModelCheckbox -and $script:localModelCheckbox.Checked) {
        $arguments += '--local-model'
        if ($null -ne $script:screenContextCheckbox -and $script:screenContextCheckbox.Checked) {
            $arguments += '--with-screen'
        }
    }
    return Invoke-BackendJson -Arguments $arguments
}

function Format-AssistantPlanText {
    param([object]$Plan)
    if ($null -eq $Plan) { return '' }
    $lines = @(
        "Assistant Plan"
        "Status: $($Plan.status)"
        "Confidence: $([math]::Round([double]$Plan.confidence, 2))"
        "Source: $($Plan.source)"
        "Explanation: $($Plan.explanation)"
    )
    if ($Plan.missing_parameters.Count -gt 0) {
        $lines += ''
        $lines += "Missing: $($Plan.missing_parameters -join ', ')"
    }
    if ($Plan.warnings.Count -gt 0) {
        $lines += ''
        $lines += 'Warnings:'
        foreach ($warning in $Plan.warnings) { $lines += "- $warning" }
    }
    if ($Plan.commands.Count -gt 0) {
        $lines += ''
        $lines += 'Commands:'
        $index = 1
        foreach ($command in $Plan.commands) {
            $lines += "$index. $($command.command_name) [$($command.risk)]"
            $lines += "   $($command.reason)"
            $lines += "   $($command.raw_command)"
            $index += 1
        }
    }
    return ($lines -join "`r`n")
}

if ($SelfTest) {
    if ((Complete-AgentCommand -InputText 'start day') -notmatch '^run mvp\.start_day run_date=\d{4}-\d{2}-\d{2} note_path=') { throw 'start day resolution failed.' }
    if ((Complete-AgentCommand -InputText 'note finish invoices') -notmatch '^run mvp\.note run_date=\d{4}-\d{2}-\d{2} note_text="finish invoices" note_title="Quick Note" note_path=') { throw 'note resolution failed.' }
    if ((Complete-AgentCommand -InputText 'download report') -notmatch '^run mvp\.download_report run_date=\d{4}-\d{2}-\d{2} download_dir=data/evidence/exports export_dir=data/evidence/exports$') { throw 'download report resolution failed.' }
    if ((Complete-AgentCommand -InputText 'end day') -notmatch '^run mvp\.end_day run_date=\d{4}-\d{2}-\d{2} summary_output=data/evidence/exports/end_of_day_\d{4}-\d{2}-\d{2}\.json$') { throw 'end day resolution failed.' }
    $trainingTemplates = Invoke-BackendJson -Arguments @('training-list-templates')
    if ($null -eq $trainingTemplates) { throw 'training backend unavailable.' }
    $assistantPlan = Get-AssistantPlanPayload -Instruction "start today's office work"
    if ($assistantPlan.plan.commands.Count -lt 3) { throw 'assistant planning failed.' }
    $operatorSession = Invoke-BackendJson -Arguments @('operator-create-session', '--instruction', "start today's office work")
    if ($operatorSession.tasks.Count -lt 3) { throw 'operator session creation failed.' }
    Write-Output 'desktop-ui-selftest-ok'
    exit 0
}

$theme = @{
    Window = [System.Drawing.Color]::FromArgb(243, 238, 229)
    Sidebar = [System.Drawing.Color]::FromArgb(249, 245, 237)
    Card = [System.Drawing.Color]::FromArgb(255, 252, 247)
    CardAlt = [System.Drawing.Color]::FromArgb(247, 241, 232)
    Hero = [System.Drawing.Color]::FromArgb(34, 63, 58)
    Accent = [System.Drawing.Color]::FromArgb(191, 108, 68)
    AccentSoft = [System.Drawing.Color]::FromArgb(243, 226, 212)
    Border = [System.Drawing.Color]::FromArgb(221, 210, 197)
    Text = [System.Drawing.Color]::FromArgb(34, 35, 36)
    Muted = [System.Drawing.Color]::FromArgb(104, 97, 90)
    Success = [System.Drawing.Color]::FromArgb(47, 111, 82)
    Warning = [System.Drawing.Color]::FromArgb(203, 133, 39)
    Danger = [System.Drawing.Color]::FromArgb(168, 63, 49)
    Input = [System.Drawing.Color]::FromArgb(255, 253, 249)
}

$fonts = @{
    Hero = New-Object System.Drawing.Font('Bahnschrift SemiBold', 22)
    Title = New-Object System.Drawing.Font('Segoe UI Semibold', 16)
    Section = New-Object System.Drawing.Font('Segoe UI Semibold', 11)
    Label = New-Object System.Drawing.Font('Segoe UI Semibold', 9.5)
    Body = New-Object System.Drawing.Font('Segoe UI', 9.5)
    Small = New-Object System.Drawing.Font('Segoe UI', 8.5)
    Mono = New-Object System.Drawing.Font('Consolas', 10)
}

$screenBounds = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$script:isCompactLayout = ($screenBounds.Width -le 1366 -or $screenBounds.Height -le 728)
if ($script:isCompactLayout) {
    $fonts.Hero = New-Object System.Drawing.Font('Bahnschrift SemiBold', 18)
    $fonts.Title = New-Object System.Drawing.Font('Segoe UI Semibold', 13.5)
    $fonts.Section = New-Object System.Drawing.Font('Segoe UI Semibold', 10.5)
    $fonts.Label = New-Object System.Drawing.Font('Segoe UI Semibold', 9)
    $fonts.Body = New-Object System.Drawing.Font('Segoe UI', 9)
    $fonts.Small = New-Object System.Drawing.Font('Segoe UI', 8)
    $fonts.Mono = New-Object System.Drawing.Font('Consolas', 9)
}

$layout = @{
    FormPadding = if ($script:isCompactLayout) { 8 } else { 14 }
    RootSidebarWidth = if ($script:isCompactLayout) { 280 } else { 340 }
    FormMinWidth = if ($script:isCompactLayout) { 1080 } else { 1240 }
    FormMinHeight = if ($script:isCompactLayout) { 660 } else { 820 }
    SidebarBrandHeight = if ($script:isCompactLayout) { 138 } else { 175 }
    SidebarQuickHeight = if ($script:isCompactLayout) { 196 } else { 245 }
    RightHeroHeight = if ($script:isCompactLayout) { 92 } else { 126 }
    CardPadding = if ($script:isCompactLayout) { 14 } else { 18 }
    BrandPadding = if ($script:isCompactLayout) { 16 } else { 20 }
    HeroPadding = if ($script:isCompactLayout) { 16 } else { 22 }
    OuterGap = if ($script:isCompactLayout) { 10 } else { 14 }
    MetricWidth = if ($script:isCompactLayout) { 104 } else { 132 }
    MetricHeight = if ($script:isCompactLayout) { 60 } else { 72 }
    MetricPadding = if ($script:isCompactLayout) { 10 } else { 12 }
    MetricMarginRight = if ($script:isCompactLayout) { 8 } else { 12 }
    MetricMarginBottom = if ($script:isCompactLayout) { 8 } else { 0 }
    CommandRowTitle = if ($script:isCompactLayout) { 44 } else { 52 }
    CommandRowInput = if ($script:isCompactLayout) { 38 } else { 44 }
    CommandRowButtons = if ($script:isCompactLayout) { 36 } else { 46 }
    CommandRowMode = if ($script:isCompactLayout) { 24 } else { 34 }
    CommandRowShortcuts = if ($script:isCompactLayout) { 38 } else { 64 }
    GuidedHeaderHeight = if ($script:isCompactLayout) { 54 } else { 64 }
    GuidedFooterHeight = if ($script:isCompactLayout) { 34 } else { 42 }
    SummaryHeight = if ($script:isCompactLayout) { 82 } else { 96 }
    ActivityHeaderHeight = if ($script:isCompactLayout) { 38 } else { 42 }
    RunsFilterHeight = if ($script:isCompactLayout) { 34 } else { 38 }
    ArtifactRowHeight = if ($script:isCompactLayout) { 34 } else { 38 }
    CommandListHeight = if ($script:isCompactLayout) { 250 } else { 330 }
    ParameterMinWidth = if ($script:isCompactLayout) { 208 } else { 240 }
    QuickButtonWidth = if ($script:isCompactLayout) { 112 } else { 248 }
    QuickButtonHeight = if ($script:isCompactLayout) { 28 } else { 32 }
    QuickButtonMinWidth = if ($script:isCompactLayout) { 104 } else { 236 }
}

function Set-CardStyle {
    param($Control, [System.Drawing.Color]$BackColor)
    $Control.BackColor = $BackColor
    $Control.BorderStyle = 'FixedSingle'
}

function Set-PrimaryButtonStyle {
    param($Button)
    $Button.BackColor = $theme.Accent
    $Button.ForeColor = [System.Drawing.Color]::White
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderSize = 0
    $Button.Font = $fonts.Label
    $Button.Cursor = 'Hand'
}

function Set-SecondaryButtonStyle {
    param($Button)
    $Button.BackColor = $theme.CardAlt
    $Button.ForeColor = $theme.Text
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderSize = 1
    $Button.FlatAppearance.BorderColor = $theme.Border
    $Button.Font = $fonts.Body
    $Button.Cursor = 'Hand'
}

function Set-ChipButtonStyle {
    param($Button)
    $Button.BackColor = $theme.AccentSoft
    $Button.ForeColor = $theme.Hero
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderSize = 0
    $Button.Font = $fonts.Small
    $Button.Cursor = 'Hand'
}

function Set-TextSurfaceStyle {
    param($TextBox, [switch]$Mono)
    $TextBox.BackColor = $theme.Input
    $TextBox.ForeColor = $theme.Text
    $TextBox.BorderStyle = 'FixedSingle'
    $TextBox.Font = if ($Mono) { $fonts.Mono } else { $fonts.Body }
}

function Set-ListViewStyle {
    param($ListView)
    $ListView.BackColor = $theme.Input
    $ListView.ForeColor = $theme.Text
    $ListView.BorderStyle = 'FixedSingle'
    $ListView.FullRowSelect = $true
    $ListView.GridLines = $true
    $ListView.HideSelection = $false
    $ListView.View = 'Details'
    $ListView.Font = $fonts.Body
}

function New-MetricCard {
    param([string]$Caption, [string]$Value)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Size = New-Object System.Drawing.Size($layout.MetricWidth, $layout.MetricHeight)
    $panel.Padding = New-Object System.Windows.Forms.Padding($layout.MetricPadding)
    $panel.Margin = New-Object System.Windows.Forms.Padding(0, 0, $layout.MetricMarginRight, $layout.MetricMarginBottom)
    $panel.BackColor = [System.Drawing.Color]::FromArgb(255, 252, 247)

    $valueLabel = New-Object System.Windows.Forms.Label
    $valueLabel.Text = $Value
    $valueLabel.Font = if ($script:isCompactLayout) { $fonts.Section } else { $fonts.Title }
    $valueLabel.ForeColor = $theme.Hero
    $valueLabel.AutoSize = $true
    $valueLabel.Location = New-Object System.Drawing.Point(10, 10)
    [void]$panel.Controls.Add($valueLabel)

    $captionLabel = New-Object System.Windows.Forms.Label
    $captionLabel.Text = $Caption
    $captionLabel.Font = $fonts.Small
    $captionLabel.ForeColor = $theme.Muted
    $captionLabel.AutoSize = $true
    $captionLabel.Location = New-Object System.Drawing.Point(10, 44)
    [void]$panel.Controls.Add($captionLabel)

    return [pscustomobject]@{
        Panel = $panel
        ValueLabel = $valueLabel
        CaptionLabel = $captionLabel
    }
}
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Office Automation Agent'
$form.StartPosition = 'Manual'
$form.Width = [Math]::Min(1520, [Math]::Max(1180, $screenBounds.Width - 8))
$form.Height = [Math]::Min(960, [Math]::Max(660, $screenBounds.Height - 8))
$form.Location = New-Object System.Drawing.Point -ArgumentList @(([int]$screenBounds.Left + 4), ([int]$screenBounds.Top + 4))
$form.MinimumSize = New-Object System.Drawing.Size($layout.FormMinWidth, $layout.FormMinHeight)
$form.BackColor = $theme.Window
$form.Padding = New-Object System.Windows.Forms.Padding($layout.FormPadding)
$form.AutoScaleMode = 'Dpi'
$form.Font = $fonts.Body
try {
    $property = $form.GetType().GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]'NonPublic,Instance')
    if ($property) { $property.SetValue($form, $true, $null) }
}
catch { }

$rootSplit = New-Object System.Windows.Forms.SplitContainer
$rootSplit.Dock = 'Fill'
$rootSplit.SplitterWidth = 8
$rootSplit.SplitterDistance = $layout.RootSidebarWidth
$rootSplit.FixedPanel = 'Panel1'
$rootSplit.BackColor = $theme.Window
[void]$form.Controls.Add($rootSplit)

$sidebarLayout = New-Object System.Windows.Forms.TableLayoutPanel
$sidebarLayout.Dock = 'Fill'
$sidebarLayout.ColumnCount = 1
$sidebarLayout.RowCount = 3
[void]$sidebarLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.SidebarBrandHeight)))
[void]$sidebarLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.SidebarQuickHeight)))
[void]$sidebarLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$rootSplit.Panel1.BackColor = $theme.Sidebar
[void]$rootSplit.Panel1.Controls.Add($sidebarLayout)

$brandCard = New-Object System.Windows.Forms.Panel
$brandCard.Dock = 'Fill'
$brandCard.Padding = New-Object System.Windows.Forms.Padding($layout.BrandPadding)
$brandCard.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, $layout.OuterGap)
$brandCard.BackColor = $theme.Hero
[void]$sidebarLayout.Controls.Add($brandCard, 0, 0)

$brandBadge = New-Object System.Windows.Forms.Label
$brandBadge.Text = if ($script:isCompactLayout) { 'Desktop Phase 1' } else { 'Desktop-ready Phase 1' }
$brandBadge.Font = $fonts.Small
$brandBadge.ForeColor = [System.Drawing.Color]::FromArgb(227, 232, 229)
$brandBadge.AutoSize = $true
$brandBadge.Location = New-Object System.Drawing.Point(20, 18)
[void]$brandCard.Controls.Add($brandBadge)

$brandTitle = New-Object System.Windows.Forms.Label
$brandTitle.Text = 'Office Automation Agent'
$brandTitle.Font = $fonts.Title
$brandTitle.ForeColor = [System.Drawing.Color]::White
$brandTitle.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 220 } else { 270 }), 0)
$brandTitle.AutoSize = $true
$brandTitle.Location = New-Object System.Drawing.Point($(if ($script:isCompactLayout) { 16 } else { 18 }), $(if ($script:isCompactLayout) { 42 } else { 44 }))
[void]$brandCard.Controls.Add($brandTitle)

$brandSubtitle = New-Object System.Windows.Forms.Label
$brandSubtitle.Text = if ($script:isCompactLayout) { 'Desktop workflows and run history in one place.' } else { 'A polished desktop shell for command-driven automation, guided workflows, and run tracking.' }
$brandSubtitle.Font = $fonts.Body
$brandSubtitle.ForeColor = [System.Drawing.Color]::FromArgb(233, 236, 234)
$brandSubtitle.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 224 } else { 270 }), 0)
$brandSubtitle.AutoSize = $true
$brandSubtitle.Location = New-Object System.Drawing.Point($(if ($script:isCompactLayout) { 18 } else { 20 }), $(if ($script:isCompactLayout) { 82 } else { 84 }))
[void]$brandCard.Controls.Add($brandSubtitle)

$brandFooter = New-Object System.Windows.Forms.Label
$brandFooter.Text = if ($script:isCompactLayout) { 'Quick actions on the left. Editing and run history on the right.' } else { 'Quick actions on the left. Command bar and workflow editor on the right.' }
$brandFooter.Font = $fonts.Small
$brandFooter.ForeColor = [System.Drawing.Color]::FromArgb(206, 215, 211)
$brandFooter.MaximumSize = New-Object System.Drawing.Size(270, 0)
$brandFooter.AutoSize = $true
$brandFooter.Location = New-Object System.Drawing.Point(20, 132)
$brandFooter.Visible = (-not $script:isCompactLayout)
[void]$brandCard.Controls.Add($brandFooter)

$quickCard = New-Object System.Windows.Forms.Panel
$quickCard.Dock = 'Fill'
$quickCard.Padding = New-Object System.Windows.Forms.Padding($layout.CardPadding)
$quickCard.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, $layout.OuterGap)
Set-CardStyle -Control $quickCard -BackColor $theme.Card
[void]$sidebarLayout.Controls.Add($quickCard, 0, 1)

$quickHeader = New-Object System.Windows.Forms.Label
$quickHeader.Text = 'Quick Actions'
$quickHeader.Font = $fonts.Section
$quickHeader.ForeColor = $theme.Text
$quickHeader.AutoSize = $true
$quickHeader.Location = New-Object System.Drawing.Point(18, 16)
[void]$quickCard.Controls.Add($quickHeader)

$quickHint = New-Object System.Windows.Forms.Label
$quickHint.Text = if ($script:isCompactLayout) { 'Tap a shortcut to load a workflow.' } else { 'One-click shortcuts for the tasks you will reach for most often.' }
$quickHint.Font = $fonts.Small
$quickHint.ForeColor = $theme.Muted
$quickHint.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 228 } else { 260 }), 0)
$quickHint.AutoSize = $true
$quickHint.Location = New-Object System.Drawing.Point(18, 40)
[void]$quickCard.Controls.Add($quickHint)

$quickButtonsHost = New-Object System.Windows.Forms.TableLayoutPanel
$quickButtonsHost.Location = New-Object System.Drawing.Point(16, $(if ($script:isCompactLayout) { 68 } else { 74 }))
$quickButtonsHost.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 244 } else { 260 }), $(if ($script:isCompactLayout) { 116 } else { 132 }))
$quickButtonsHost.Anchor = 'Top,Bottom,Left,Right'
$quickButtonsHost.ColumnCount = if ($script:isCompactLayout) { 2 } else { 1 }
$quickButtonsHost.RowCount = if ($script:isCompactLayout) { 3 } else { 6 }
$quickButtonsHost.AutoScroll = $false
$quickButtonsHost.Padding = New-Object System.Windows.Forms.Padding(0)
$quickButtonsHost.BackColor = $theme.Card
[void]$quickButtonsHost.ColumnStyles.Clear()
if ($script:isCompactLayout) {
    [void]$quickButtonsHost.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 50)))
    [void]$quickButtonsHost.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 50)))
}
else {
    [void]$quickButtonsHost.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
}
[void]$quickButtonsHost.RowStyles.Clear()
for ($quickRow = 0; $quickRow -lt $quickButtonsHost.RowCount; $quickRow++) {
    [void]$quickButtonsHost.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, ($layout.QuickButtonHeight + 8))))
}
[void]$quickCard.Controls.Add($quickButtonsHost)

$catalogCard = New-Object System.Windows.Forms.Panel
$catalogCard.Dock = 'Fill'
$catalogCard.Padding = New-Object System.Windows.Forms.Padding($layout.CardPadding)
Set-CardStyle -Control $catalogCard -BackColor $theme.Card
[void]$sidebarLayout.Controls.Add($catalogCard, 0, 2)

$catalogHeader = New-Object System.Windows.Forms.Label
$catalogHeader.Text = 'Workflow Catalog'
$catalogHeader.Font = $fonts.Section
$catalogHeader.ForeColor = $theme.Text
$catalogHeader.AutoSize = $true
$catalogHeader.Location = New-Object System.Drawing.Point(18, 16)
[void]$catalogCard.Controls.Add($catalogHeader)

$catalogCountLabel = New-Object System.Windows.Forms.Label
$catalogCountLabel.Text = ''
$catalogCountLabel.Font = $fonts.Small
$catalogCountLabel.ForeColor = $theme.Muted
$catalogCountLabel.AutoSize = $true
$catalogCountLabel.Location = New-Object System.Drawing.Point(18, 40)
[void]$catalogCard.Controls.Add($catalogCountLabel)

$catalogSearchBox = New-Object System.Windows.Forms.TextBox
$catalogSearchBox.Location = New-Object System.Drawing.Point(18, 66)
$catalogSearchBox.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 244 } else { 262 }), 28)
$catalogSearchBox.Anchor = 'Top,Left,Right'
Set-TextSurfaceStyle -TextBox $catalogSearchBox
[void]$catalogCard.Controls.Add($catalogSearchBox)

$catalogHint = New-Object System.Windows.Forms.Label
$catalogHint.Text = if ($script:isCompactLayout) { 'Filter workflows.' } else { 'Filter by workflow name or description.' }
$catalogHint.Font = $fonts.Small
$catalogHint.ForeColor = $theme.Muted
$catalogHint.AutoSize = $true
$catalogHint.Location = New-Object System.Drawing.Point(18, 100)
[void]$catalogCard.Controls.Add($catalogHint)

$commandList = New-Object System.Windows.Forms.ListBox
$commandList.Location = New-Object System.Drawing.Point(18, 126)
$commandList.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 244 } else { 262 }), $layout.CommandListHeight)
$commandList.Anchor = 'Top,Bottom,Left,Right'
$commandList.Font = $fonts.Body
$commandList.BackColor = $theme.Input
$commandList.ForeColor = $theme.Text
$commandList.BorderStyle = 'FixedSingle'
[void]$catalogCard.Controls.Add($commandList)

$rightLayout = New-Object System.Windows.Forms.TableLayoutPanel
$rightLayout.Dock = 'Fill'
$rightLayout.ColumnCount = 1
$rightLayout.RowCount = 3
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.RightHeroHeight)))
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 46)))
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 54)))
[void]$rootSplit.Panel2.Controls.Add($rightLayout)

$heroCard = New-Object System.Windows.Forms.Panel
$heroCard.Dock = 'Fill'
$heroCard.Padding = New-Object System.Windows.Forms.Padding($layout.HeroPadding)
$heroCard.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, $layout.OuterGap)
$heroCard.BackColor = $theme.Hero
[void]$rightLayout.Controls.Add($heroCard, 0, 0)

$heroLayout = New-Object System.Windows.Forms.TableLayoutPanel
$heroLayout.Dock = 'Fill'
$heroLayout.ColumnCount = 2
$heroLayout.RowCount = 1
[void]$heroLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 58)))
[void]$heroLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 42)))
[void]$heroCard.Controls.Add($heroLayout)

$heroTextPanel = New-Object System.Windows.Forms.Panel
$heroTextPanel.Dock = 'Fill'
[void]$heroLayout.Controls.Add($heroTextPanel, 0, 0)

$heroTitle = New-Object System.Windows.Forms.Label
$heroTitle.Text = if ($script:isCompactLayout) { 'Desktop Control Center' } else { 'Polished Desktop Control Center' }
$heroTitle.Font = $fonts.Title
$heroTitle.ForeColor = [System.Drawing.Color]::White
$heroTitle.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 430 } else { 560 }), 0)
$heroTitle.AutoSize = $true
$heroTitle.Location = New-Object System.Drawing.Point(0, 6)
[void]$heroTextPanel.Controls.Add($heroTitle)

$heroSubtitle = New-Object System.Windows.Forms.Label
$heroSubtitle.Text = if ($script:isCompactLayout) { 'Shortcuts, guided workflows, and run history.' } else { 'Use shortcuts, guided workflows, and live run history from a desktop window that scales cleanly across desktop sizes.' }
$heroSubtitle.Font = $fonts.Body
$heroSubtitle.ForeColor = [System.Drawing.Color]::FromArgb(229, 235, 232)
$heroSubtitle.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 430 } else { 560 }), 0)
$heroSubtitle.AutoSize = $true
$heroSubtitle.Location = New-Object System.Drawing.Point(0, $(if ($script:isCompactLayout) { 34 } else { 40 }))
[void]$heroTextPanel.Controls.Add($heroSubtitle)

$heroModeLabel = New-Object System.Windows.Forms.Label
$heroModeLabel.Text = ''
$heroModeLabel.Font = $fonts.Small
$heroModeLabel.ForeColor = [System.Drawing.Color]::FromArgb(223, 232, 228)
$heroModeLabel.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 430 } else { 560 }), 0)
$heroModeLabel.AutoSize = $true
$heroModeLabel.Location = New-Object System.Drawing.Point(0, $(if ($script:isCompactLayout) { 56 } else { 82 }))
[void]$heroTextPanel.Controls.Add($heroModeLabel)

$heroMetricsFlow = New-Object System.Windows.Forms.FlowLayoutPanel
$heroMetricsFlow.Dock = 'Fill'
$heroMetricsFlow.WrapContents = $true
$heroMetricsFlow.FlowDirection = 'LeftToRight'
$heroMetricsFlow.BackColor = $theme.Hero
$heroMetricsFlow.AutoScroll = $false
$heroMetricsFlow.Padding = New-Object System.Windows.Forms.Padding(0, $(if ($script:isCompactLayout) { 6 } else { 10 }), 0, 0)
[void]$heroLayout.Controls.Add($heroMetricsFlow, 1, 0)

$workflowMetric = New-MetricCard -Caption 'Registered workflows' -Value ([string]$script:commandListData.Count)
$runMetric = New-MetricCard -Caption 'Recent runs shown' -Value '0'
$statusMetric = New-MetricCard -Caption 'Last status' -Value 'Ready'
[void]$heroMetricsFlow.Controls.Add($workflowMetric.Panel)
[void]$heroMetricsFlow.Controls.Add($runMetric.Panel)
[void]$heroMetricsFlow.Controls.Add($statusMetric.Panel)

$upperSplit = New-Object System.Windows.Forms.SplitContainer
$upperSplit.Dock = 'Fill'
$upperSplit.SplitterDistance = 455
$upperSplit.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, $layout.OuterGap)
$upperSplit.BackColor = $theme.Window
[void]$rightLayout.Controls.Add($upperSplit, 0, 1)

$commandCard = New-Object System.Windows.Forms.Panel
$commandCard.Dock = 'Fill'
$commandCard.Padding = New-Object System.Windows.Forms.Padding($layout.CardPadding)
Set-CardStyle -Control $commandCard -BackColor $theme.Card
[void]$upperSplit.Panel1.Controls.Add($commandCard)

$guidedCard = New-Object System.Windows.Forms.Panel
$guidedCard.Dock = 'Fill'
$guidedCard.Padding = New-Object System.Windows.Forms.Padding($layout.CardPadding)
Set-CardStyle -Control $guidedCard -BackColor $theme.Card
[void]$upperSplit.Panel2.Controls.Add($guidedCard)

$activitySplit = New-Object System.Windows.Forms.SplitContainer
$activitySplit.Dock = 'Fill'
$activitySplit.SplitterDistance = 420
$activitySplit.BackColor = $theme.Window
[void]$rightLayout.Controls.Add($activitySplit, 0, 2)

$runsCard = New-Object System.Windows.Forms.Panel
$runsCard.Dock = 'Fill'
$runsCard.Padding = New-Object System.Windows.Forms.Padding($layout.CardPadding)
Set-CardStyle -Control $runsCard -BackColor $theme.Card
[void]$activitySplit.Panel1.Controls.Add($runsCard)

$logsCard = New-Object System.Windows.Forms.Panel
$logsCard.Dock = 'Fill'
$logsCard.Padding = New-Object System.Windows.Forms.Padding($layout.CardPadding)
Set-CardStyle -Control $logsCard -BackColor $theme.Card
[void]$activitySplit.Panel2.Controls.Add($logsCard)
$commandLayout = New-Object System.Windows.Forms.TableLayoutPanel
$commandLayout.Dock = 'Fill'
$commandLayout.ColumnCount = 1
$commandLayout.RowCount = 6
[void]$commandLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.CommandRowTitle)))
[void]$commandLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.CommandRowInput)))
[void]$commandLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.CommandRowButtons)))
[void]$commandLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.CommandRowMode)))
[void]$commandLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.CommandRowShortcuts)))
[void]$commandLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$commandCard.Controls.Add($commandLayout)

$commandTitle = New-Object System.Windows.Forms.Label
$commandTitle.Text = 'Command Bar'
$commandTitle.Font = $fonts.Section
$commandTitle.ForeColor = $theme.Text
$commandTitle.AutoSize = $true
$commandTitle.Location = New-Object System.Drawing.Point(0, 0)
[void]$commandLayout.Controls.Add($commandTitle, 0, 0)

$commandHint = New-Object System.Windows.Forms.Label
$commandHint.Text = if ($script:isCompactLayout) { 'Type a request or command, then press Enter.' } else { 'Type a natural request or a direct command. Press Enter to run immediately.' }
$commandHint.Font = $fonts.Small
$commandHint.ForeColor = $theme.Muted
$commandHint.AutoSize = $true
$commandHint.Location = New-Object System.Drawing.Point(0, 24)
[void]$commandLayout.Controls.Add($commandHint, 0, 0)

$agentInputBox = New-Object System.Windows.Forms.TextBox
$agentInputBox.Dock = 'Fill'
Set-TextSurfaceStyle -TextBox $agentInputBox
[void]$commandLayout.Controls.Add($agentInputBox, 0, 1)

$buttonFlow = New-Object System.Windows.Forms.TableLayoutPanel
$buttonFlow.Dock = 'Fill'
$buttonFlow.ColumnCount = 4
$buttonFlow.RowCount = 1
$buttonFlow.AutoScroll = $false
$buttonFlow.BackColor = $theme.Card
[void]$buttonFlow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, $(if ($script:isCompactLayout) { 31 } else { 32 }))))
[void]$buttonFlow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, $(if ($script:isCompactLayout) { 24 } else { 24 }))))
[void]$buttonFlow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, $(if ($script:isCompactLayout) { 27 } else { 28 }))))
[void]$buttonFlow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, $(if ($script:isCompactLayout) { 18 } else { 16 }))))
[void]$buttonFlow.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$commandLayout.Controls.Add($buttonFlow, 0, 2)

$runInputButton = New-Object System.Windows.Forms.Button
$runInputButton.Text = if ($script:isCompactLayout) { 'Run' } else { 'Run Typed Command' }
$runInputButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 124 } else { 160 }), 32)
$runInputButton.Margin = New-Object System.Windows.Forms.Padding(0, 0, 6, 0)
$runInputButton.Dock = 'Fill'
Set-PrimaryButtonStyle -Button $runInputButton
[void]$buttonFlow.Controls.Add($runInputButton, 0, 0)

$usePreviewButton = New-Object System.Windows.Forms.Button
$usePreviewButton.Text = if ($script:isCompactLayout) { 'Plan' } else { 'Preview Plan' }
$usePreviewButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 116 } else { 142 }), 32)
$usePreviewButton.Margin = New-Object System.Windows.Forms.Padding(0, 0, 6, 0)
$usePreviewButton.Dock = 'Fill'
Set-SecondaryButtonStyle -Button $usePreviewButton
[void]$buttonFlow.Controls.Add($usePreviewButton, 1, 0)

$approveTrainingButton = New-Object System.Windows.Forms.Button
$approveTrainingButton.Text = if ($script:isCompactLayout) { 'Save' } else { 'Approve + Save' }
$approveTrainingButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 108 } else { 132 }), 32)
$approveTrainingButton.Margin = New-Object System.Windows.Forms.Padding(0, 0, 6, 0)
$approveTrainingButton.Dock = 'Fill'
$approveTrainingButton.Enabled = $false
Set-SecondaryButtonStyle -Button $approveTrainingButton
[void]$buttonFlow.Controls.Add($approveTrainingButton, 2, 0)

$clearInputButton = New-Object System.Windows.Forms.Button
$clearInputButton.Text = if ($script:isCompactLayout) { 'Clr' } else { 'Clear' }
$clearInputButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 58 } else { 72 }), 32)
$clearInputButton.Margin = New-Object System.Windows.Forms.Padding(0)
$clearInputButton.Dock = 'Fill'
Set-SecondaryButtonStyle -Button $clearInputButton
[void]$buttonFlow.Controls.Add($clearInputButton, 3, 0)

$modeFlow = New-Object System.Windows.Forms.FlowLayoutPanel
$modeFlow.Dock = 'Fill'
$modeFlow.FlowDirection = 'LeftToRight'
$modeFlow.WrapContents = $false
$modeFlow.BackColor = $theme.Card
[void]$commandLayout.Controls.Add($modeFlow, 0, 3)

$safeModeCheckbox = New-Object System.Windows.Forms.CheckBox
$safeModeCheckbox.Text = if ($script:isCompactLayout) { 'Safe' } else { 'Safe mode' }
$safeModeCheckbox.Checked = $true
$safeModeCheckbox.AutoSize = $true
$safeModeCheckbox.Font = $fonts.Small
$safeModeCheckbox.ForeColor = $theme.Text
$safeModeCheckbox.Margin = New-Object System.Windows.Forms.Padding(0, 4, 12, 0)
[void]$modeFlow.Controls.Add($safeModeCheckbox)

$confirmRiskCheckbox = New-Object System.Windows.Forms.CheckBox
$confirmRiskCheckbox.Text = if ($script:isCompactLayout) { 'Allow risk' } else { 'Approve risky actions' }
$confirmRiskCheckbox.Checked = $false
$confirmRiskCheckbox.AutoSize = $true
$confirmRiskCheckbox.Font = $fonts.Small
$confirmRiskCheckbox.ForeColor = $theme.Text
$confirmRiskCheckbox.Margin = New-Object System.Windows.Forms.Padding(0, 4, 0, 0)
[void]$modeFlow.Controls.Add($confirmRiskCheckbox)

$localModelCheckbox = New-Object System.Windows.Forms.CheckBox
$localModelCheckbox.Text = if ($script:isCompactLayout) { 'Local' } else { 'Local model' }
$localModelCheckbox.Checked = $true
$localModelCheckbox.AutoSize = $true
$localModelCheckbox.Font = $fonts.Small
$localModelCheckbox.ForeColor = $theme.Text
$localModelCheckbox.Margin = New-Object System.Windows.Forms.Padding(12, 4, 0, 0)
[void]$modeFlow.Controls.Add($localModelCheckbox)

$screenContextCheckbox = New-Object System.Windows.Forms.CheckBox
$screenContextCheckbox.Text = if ($script:isCompactLayout) { 'Screen' } else { 'Read screen' }
$screenContextCheckbox.Checked = $true
$screenContextCheckbox.AutoSize = $true
$screenContextCheckbox.Font = $fonts.Small
$screenContextCheckbox.ForeColor = $theme.Text
$screenContextCheckbox.Margin = New-Object System.Windows.Forms.Padding(12, 4, 0, 0)
[void]$modeFlow.Controls.Add($screenContextCheckbox)

$shortcutFlow = New-Object System.Windows.Forms.FlowLayoutPanel
$shortcutFlow.Dock = 'Fill'
$shortcutFlow.FlowDirection = 'LeftToRight'
$shortcutFlow.WrapContents = $true
$shortcutFlow.AutoScroll = $false
$shortcutFlow.BackColor = $theme.Card
$shortcutFlow.Padding = New-Object System.Windows.Forms.Padding(0, 2, 0, 0)
[void]$commandLayout.Controls.Add($shortcutFlow, 0, 4)

$shortcutHint = New-Object System.Windows.Forms.Label
$shortcutHint.Text = if ($script:isCompactLayout) { 'Shortcuts:' } else { 'Popular shortcuts:' }
$shortcutHint.Font = $fonts.Small
$shortcutHint.ForeColor = $theme.Muted
$shortcutHint.AutoSize = $true
$shortcutHint.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 0)
[void]$shortcutFlow.Controls.Add($shortcutHint)

$commandFooter = New-Object System.Windows.Forms.Panel
$commandFooter.Dock = 'Fill'
$commandFooter.Padding = New-Object System.Windows.Forms.Padding(14)
$commandFooter.BackColor = $theme.CardAlt
$commandFooter.BorderStyle = 'FixedSingle'
[void]$commandLayout.Controls.Add($commandFooter, 0, 5)

$commandFooterTitle = New-Object System.Windows.Forms.Label
$commandFooterTitle.Text = 'Ready for fast desktop use'
$commandFooterTitle.Font = $fonts.Label
$commandFooterTitle.ForeColor = $theme.Text
$commandFooterTitle.AutoSize = $true
$commandFooterTitle.Location = New-Object System.Drawing.Point(12, 10)
[void]$commandFooter.Controls.Add($commandFooterTitle)

$commandFooterText = New-Object System.Windows.Forms.Label
$commandFooterText.Text = 'Natural requests plan safely, guided forms fill defaults, and every run is written to history with step logs.'
$commandFooterText.Font = $fonts.Small
$commandFooterText.ForeColor = $theme.Muted
$commandFooterText.MaximumSize = New-Object System.Drawing.Size(380, 0)
$commandFooterText.AutoSize = $true
$commandFooterText.Location = New-Object System.Drawing.Point(12, 34)
[void]$commandFooter.Controls.Add($commandFooterText)

$guidedLayout = New-Object System.Windows.Forms.TableLayoutPanel
$guidedLayout.Dock = 'Fill'
$guidedLayout.ColumnCount = 1
$guidedLayout.RowCount = 3
[void]$guidedLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.GuidedHeaderHeight)))
[void]$guidedLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$guidedLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.GuidedFooterHeight)))
[void]$guidedCard.Controls.Add($guidedLayout)

$selectedCommandLabel = New-Object System.Windows.Forms.Label
$selectedCommandLabel.Text = 'Select a workflow from the catalog'
$selectedCommandLabel.Font = $fonts.Section
$selectedCommandLabel.ForeColor = $theme.Text
$selectedCommandLabel.AutoSize = $true
$selectedCommandLabel.Location = New-Object System.Drawing.Point(0, 0)
[void]$guidedLayout.Controls.Add($selectedCommandLabel, 0, 0)

$selectedCommandDescription = New-Object System.Windows.Forms.Label
$selectedCommandDescription.Text = 'The workflow editor updates the command preview as you type.'
$selectedCommandDescription.Font = $fonts.Small
$selectedCommandDescription.ForeColor = $theme.Muted
$selectedCommandDescription.MaximumSize = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 460 } else { 560 }), 0)
$selectedCommandDescription.AutoSize = $true
$selectedCommandDescription.Location = New-Object System.Drawing.Point(0, 28)
[void]$guidedLayout.Controls.Add($selectedCommandDescription, 0, 0)

$guidedInnerSplit = New-Object System.Windows.Forms.SplitContainer
$guidedInnerSplit.Dock = 'Fill'
$guidedInnerSplit.SplitterDistance = if ($script:isCompactLayout) { 260 } else { 310 }
$guidedInnerSplit.BackColor = $theme.Card
[void]$guidedLayout.Controls.Add($guidedInnerSplit, 0, 1)

$parameterCard = New-Object System.Windows.Forms.Panel
$parameterCard.Dock = 'Fill'
$parameterCard.Padding = New-Object System.Windows.Forms.Padding(12)
$parameterCard.BackColor = $theme.CardAlt
$parameterCard.BorderStyle = 'FixedSingle'
[void]$guidedInnerSplit.Panel1.Controls.Add($parameterCard)

$parameterLayout = New-Object System.Windows.Forms.TableLayoutPanel
$parameterLayout.Dock = 'Fill'
$parameterLayout.ColumnCount = 1
$parameterLayout.RowCount = 3
[void]$parameterLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 26)))
[void]$parameterLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 36)))
[void]$parameterLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$parameterCard.Controls.Add($parameterLayout)

$parameterHeader = New-Object System.Windows.Forms.Label
$parameterHeader.Text = if ($script:isCompactLayout) { 'Fields' } else { 'Workflow fields' }
$parameterHeader.Font = $fonts.Label
$parameterHeader.ForeColor = $theme.Text
$parameterHeader.AutoSize = $true
$parameterHeader.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 0)
[void]$parameterLayout.Controls.Add($parameterHeader, 0, 0)

$parameterHint = New-Object System.Windows.Forms.Label
$parameterHint.Text = if ($script:isCompactLayout) { 'Fill required fields to complete the preview.' } else { 'Required fields stay highlighted in the preview until they are filled.' }
$parameterHint.Font = $fonts.Small
$parameterHint.ForeColor = $theme.Muted
$parameterHint.MaximumSize = New-Object System.Drawing.Size(280, 0)
$parameterHint.AutoSize = $true
$parameterHint.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 0)
[void]$parameterLayout.Controls.Add($parameterHint, 0, 1)

$parameterFieldsHost = New-Object System.Windows.Forms.FlowLayoutPanel
$parameterFieldsHost.Dock = 'Fill'
$parameterFieldsHost.FlowDirection = 'TopDown'
$parameterFieldsHost.WrapContents = $false
$parameterFieldsHost.AutoScroll = $true
$parameterFieldsHost.BackColor = $theme.CardAlt
[void]$parameterLayout.Controls.Add($parameterFieldsHost, 0, 2)

$previewCard = New-Object System.Windows.Forms.Panel
$previewCard.Dock = 'Fill'
$previewCard.Padding = New-Object System.Windows.Forms.Padding(12)
$previewCard.BackColor = $theme.CardAlt
$previewCard.BorderStyle = 'FixedSingle'
[void]$guidedInnerSplit.Panel2.Controls.Add($previewCard)

$previewLayout = New-Object System.Windows.Forms.TableLayoutPanel
$previewLayout.Dock = 'Fill'
$previewLayout.ColumnCount = 1
$previewLayout.RowCount = 3
[void]$previewLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 26)))
[void]$previewLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 36)))
[void]$previewLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$previewCard.Controls.Add($previewLayout)

$previewHeader = New-Object System.Windows.Forms.Label
$previewHeader.Text = if ($script:isCompactLayout) { 'Command preview' } else { 'Resolved command preview' }
$previewHeader.Font = $fonts.Label
$previewHeader.ForeColor = $theme.Text
$previewHeader.AutoSize = $true
$previewHeader.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 0)
[void]$previewLayout.Controls.Add($previewHeader, 0, 0)

$previewHint = New-Object System.Windows.Forms.Label
$previewHint.Text = if ($script:isCompactLayout) { 'This is the exact command that will run.' } else { 'This is the exact command the agent will run when you launch the workflow.' }
$previewHint.Font = $fonts.Small
$previewHint.ForeColor = $theme.Muted
$previewHint.MaximumSize = New-Object System.Drawing.Size(280, 0)
$previewHint.AutoSize = $true
$previewHint.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 0)
[void]$previewLayout.Controls.Add($previewHint, 0, 1)

$previewBox = New-Object System.Windows.Forms.TextBox
$previewBox.Dock = 'Fill'
$previewBox.Multiline = $true
$previewBox.ReadOnly = $true
$previewBox.ScrollBars = 'Vertical'
Set-TextSurfaceStyle -TextBox $previewBox -Mono
[void]$previewLayout.Controls.Add($previewBox, 0, 2)

$guidedActionsFlow = New-Object System.Windows.Forms.FlowLayoutPanel
$guidedActionsFlow.Dock = 'Fill'
$guidedActionsFlow.FlowDirection = 'LeftToRight'
$guidedActionsFlow.WrapContents = $true
$guidedActionsFlow.BackColor = $theme.Card
[void]$guidedLayout.Controls.Add($guidedActionsFlow, 0, 2)

$runSelectedButton = New-Object System.Windows.Forms.Button
$runSelectedButton.Text = if ($script:isCompactLayout) { 'Run Workflow' } else { 'Run Selected Workflow' }
$runSelectedButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 148 } else { 170 }), 30)
Set-PrimaryButtonStyle -Button $runSelectedButton
[void]$guidedActionsFlow.Controls.Add($runSelectedButton)

$resetDefaultsButton = New-Object System.Windows.Forms.Button
$resetDefaultsButton.Text = if ($script:isCompactLayout) { 'Defaults' } else { 'Reset Defaults' }
$resetDefaultsButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 104 } else { 118 }), 30)
Set-SecondaryButtonStyle -Button $resetDefaultsButton
[void]$guidedActionsFlow.Controls.Add($resetDefaultsButton)

$guidedActionsNote = New-Object System.Windows.Forms.Label
$guidedActionsNote.Text = 'Pick from the catalog or quick actions to preload this editor.'
$guidedActionsNote.Font = $fonts.Small
$guidedActionsNote.ForeColor = $theme.Muted
$guidedActionsNote.AutoSize = $true
$guidedActionsNote.Margin = New-Object System.Windows.Forms.Padding(12, 8, 0, 0)
[void]$guidedActionsFlow.Controls.Add($guidedActionsNote)

$runsLayout = New-Object System.Windows.Forms.TableLayoutPanel
$runsLayout.Dock = 'Fill'
$runsLayout.ColumnCount = 1
$runsLayout.RowCount = 3
[void]$runsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.ActivityHeaderHeight)))
[void]$runsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.RunsFilterHeight)))
[void]$runsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$runsCard.Controls.Add($runsLayout)

$runsHeaderPanel = New-Object System.Windows.Forms.Panel
$runsHeaderPanel.Dock = 'Fill'
[void]$runsLayout.Controls.Add($runsHeaderPanel, 0, 0)

$runsHeader = New-Object System.Windows.Forms.Label
$runsHeader.Text = 'Recent Runs'
$runsHeader.Font = $fonts.Section
$runsHeader.ForeColor = $theme.Text
$runsHeader.AutoSize = $true
$runsHeader.Location = New-Object System.Drawing.Point(0, 2)
[void]$runsHeaderPanel.Controls.Add($runsHeader)

$runsHint = New-Object System.Windows.Forms.Label
$runsHint.Text = if ($script:isCompactLayout) { 'Select a run for details.' } else { 'Click any run to inspect its summary and step logs.' }
$runsHint.Font = $fonts.Small
$runsHint.ForeColor = $theme.Muted
$runsHint.AutoSize = $true
$runsHint.Location = New-Object System.Drawing.Point(0, 22)
[void]$runsHeaderPanel.Controls.Add($runsHint)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = if ($script:isCompactLayout) { 'Reload' } else { 'Refresh' }
$refreshButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 76 } else { 88 }), 30)
$refreshButton.Location = New-Object System.Drawing.Point($(if ($script:isCompactLayout) { 292 } else { 280 }), 4)
$refreshButton.Anchor = 'Top,Right'
Set-SecondaryButtonStyle -Button $refreshButton
[void]$runsHeaderPanel.Controls.Add($refreshButton)

$reviewQueueButton = New-Object System.Windows.Forms.Button
$reviewQueueButton.Text = if ($script:isCompactLayout) { 'Review' } else { 'Review Queue' }
$reviewQueueButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 82 } else { 98 }), 30)
$reviewQueueButton.Location = New-Object System.Drawing.Point($(if ($script:isCompactLayout) { 202 } else { 170 }), 4)
$reviewQueueButton.Anchor = 'Top,Right'
Set-SecondaryButtonStyle -Button $reviewQueueButton
[void]$runsHeaderPanel.Controls.Add($reviewQueueButton)

$operatorDashboardButton = New-Object System.Windows.Forms.Button
$operatorDashboardButton.Text = if ($script:isCompactLayout) { 'Ops' } else { 'Operator' }
$operatorDashboardButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 72 } else { 82 }), 30)
$operatorDashboardButton.Location = New-Object System.Drawing.Point($(if ($script:isCompactLayout) { 124 } else { 82 }), 4)
$operatorDashboardButton.Anchor = 'Top,Right'
Set-SecondaryButtonStyle -Button $operatorDashboardButton
[void]$runsHeaderPanel.Controls.Add($operatorDashboardButton)

$trainingModeButton = New-Object System.Windows.Forms.Button
$trainingModeButton.Text = if ($script:isCompactLayout) { 'Teach' } else { 'Training' }
$trainingModeButton.Size = New-Object System.Drawing.Size($(if ($script:isCompactLayout) { 72 } else { 78 }), 30)
$trainingModeButton.Location = New-Object System.Drawing.Point($(if ($script:isCompactLayout) { 46 } else { 0 }), 4)
$trainingModeButton.Anchor = 'Top,Right'
Set-SecondaryButtonStyle -Button $trainingModeButton
[void]$runsHeaderPanel.Controls.Add($trainingModeButton)

$runsFilterLayout = New-Object System.Windows.Forms.TableLayoutPanel
$runsFilterLayout.Dock = 'Fill'
$runsFilterLayout.ColumnCount = 3
$runsFilterLayout.RowCount = 1
[void]$runsFilterLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 112)))
[void]$runsFilterLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$runsFilterLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, $(if ($script:isCompactLayout) { 90 } else { 110 }))))
[void]$runsFilterLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$runsLayout.Controls.Add($runsFilterLayout, 0, 1)

$statusFilterBox = New-Object System.Windows.Forms.ComboBox
$statusFilterBox.DropDownStyle = 'DropDownList'
$statusFilterBox.Font = $fonts.Small
$statusFilterBox.Dock = 'Fill'
$statusFilterBox.Margin = New-Object System.Windows.Forms.Padding(0, 0, 8, 0)
[void]$statusFilterBox.Items.AddRange(@('All', 'Completed', 'Failed', 'Running', 'Stopped'))
$statusFilterBox.SelectedIndex = 0
[void]$runsFilterLayout.Controls.Add($statusFilterBox, 0, 0)

$runSearchBox = New-Object System.Windows.Forms.TextBox
$runSearchBox.Dock = 'Fill'
$runSearchBox.Margin = New-Object System.Windows.Forms.Padding(0, 0, 8, 0)
Set-TextSurfaceStyle -TextBox $runSearchBox
[void]$runsFilterLayout.Controls.Add($runSearchBox, 1, 0)

$failureInboxButton = New-Object System.Windows.Forms.Button
$failureInboxButton.Text = if ($script:isCompactLayout) { 'Failures' } else { 'Failure Inbox' }
$failureInboxButton.Dock = 'Fill'
Set-SecondaryButtonStyle -Button $failureInboxButton
[void]$runsFilterLayout.Controls.Add($failureInboxButton, 2, 0)

$runsList = New-Object System.Windows.Forms.ListView
$runsList.Dock = 'Fill'
Set-ListViewStyle -ListView $runsList
[void]$runsList.Columns.Add('ID', 54)
[void]$runsList.Columns.Add('Command', 180)
[void]$runsList.Columns.Add('Status', 84)
[void]$runsList.Columns.Add('Started', 150)
[void]$runsLayout.Controls.Add($runsList, 0, 2)

$logsLayout = New-Object System.Windows.Forms.TableLayoutPanel
$logsLayout.Dock = 'Fill'
$logsLayout.ColumnCount = 1
$logsLayout.RowCount = 4
[void]$logsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.ActivityHeaderHeight)))
[void]$logsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.SummaryHeight)))
[void]$logsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, $layout.ArtifactRowHeight)))
[void]$logsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$logsCard.Controls.Add($logsLayout)

$logsHeader = New-Object System.Windows.Forms.Label
$logsHeader.Text = 'Run Summary and Step Logs'
$logsHeader.Font = $fonts.Section
$logsHeader.ForeColor = $theme.Text
$logsHeader.AutoSize = $true
$logsHeader.Location = New-Object System.Drawing.Point(0, 4)
[void]$logsLayout.Controls.Add($logsHeader, 0, 0)

$detailBox = New-Object System.Windows.Forms.TextBox
$detailBox.Dock = 'Fill'
$detailBox.Multiline = $true
$detailBox.ReadOnly = $true
$detailBox.ScrollBars = 'Vertical'
Set-TextSurfaceStyle -TextBox $detailBox -Mono
[void]$logsLayout.Controls.Add($detailBox, 0, 1)

$artifactLayout = New-Object System.Windows.Forms.TableLayoutPanel
$artifactLayout.Dock = 'Fill'
$artifactLayout.ColumnCount = 4
$artifactLayout.RowCount = 1
[void]$artifactLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, $(if ($script:isCompactLayout) { 58 } else { 74 }))))
[void]$artifactLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$artifactLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, $(if ($script:isCompactLayout) { 56 } else { 74 }))))
[void]$artifactLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, $(if ($script:isCompactLayout) { 54 } else { 66 }))))
[void]$artifactLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$logsLayout.Controls.Add($artifactLayout, 0, 2)

$artifactLabel = New-Object System.Windows.Forms.Label
$artifactLabel.Text = 'Evidence'
$artifactLabel.Font = $fonts.Small
$artifactLabel.ForeColor = $theme.Muted
$artifactLabel.AutoSize = $true
$artifactLabel.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 0)
[void]$artifactLayout.Controls.Add($artifactLabel, 0, 0)

$artifactComboBox = New-Object System.Windows.Forms.ComboBox
$artifactComboBox.DropDownStyle = 'DropDownList'
$artifactComboBox.Font = $fonts.Small
$artifactComboBox.Dock = 'Fill'
$artifactComboBox.Margin = New-Object System.Windows.Forms.Padding(0, 0, 8, 0)
[void]$artifactLayout.Controls.Add($artifactComboBox, 1, 0)

$openArtifactButton = New-Object System.Windows.Forms.Button
$openArtifactButton.Text = if ($script:isCompactLayout) { 'Open' } else { 'Open Path' }
$openArtifactButton.Dock = 'Fill'
$openArtifactButton.Margin = New-Object System.Windows.Forms.Padding(0, 0, 8, 0)
Set-SecondaryButtonStyle -Button $openArtifactButton
[void]$artifactLayout.Controls.Add($openArtifactButton, 2, 0)

$copyArtifactButton = New-Object System.Windows.Forms.Button
$copyArtifactButton.Text = 'Copy'
$copyArtifactButton.Dock = 'Fill'
Set-SecondaryButtonStyle -Button $copyArtifactButton
[void]$artifactLayout.Controls.Add($copyArtifactButton, 3, 0)

$logsList = New-Object System.Windows.Forms.ListView
$logsList.Dock = 'Fill'
Set-ListViewStyle -ListView $logsList
[void]$logsList.Columns.Add('Step', 150)
[void]$logsList.Columns.Add('Status', 96)
[void]$logsList.Columns.Add('Message', 220)
[void]$logsList.Columns.Add('Time', 120)
[void]$logsLayout.Controls.Add($logsList, 0, 3)
$script:visibleCommands = @()
$script:allRuns = @()
$script:currentArtifacts = @()
$script:parameterInputs = @{}
$script:parameterFieldPanels = @()
$script:selectedCommand = $null
$script:lastAssistantInstruction = ''
$script:lastAssistantPlan = $null
$script:lastAssistantScreenContext = @{}
$script:commandList = $commandList
$script:catalogSearchBox = $catalogSearchBox
$script:catalogCountLabel = $catalogCountLabel
$script:parameterFieldsHost = $parameterFieldsHost
$script:previewBox = $previewBox
$script:guidedInnerSplit = $guidedInnerSplit
$script:selectedCommandLabel = $selectedCommandLabel
$script:selectedCommandDescription = $selectedCommandDescription
$script:agentInputBox = $agentInputBox
$script:detailBox = $detailBox
$script:runsList = $runsList
$script:logsList = $logsList
$script:statusFilterBox = $statusFilterBox
$script:runSearchBox = $runSearchBox
$script:failureInboxButton = $failureInboxButton
$script:reviewQueueButton = $reviewQueueButton
$script:artifactComboBox = $artifactComboBox
$script:openArtifactButton = $openArtifactButton
$script:copyArtifactButton = $copyArtifactButton
$script:form = $form
$script:workflowMetric = $workflowMetric
$script:runMetric = $runMetric
$script:statusMetric = $statusMetric
$script:heroModeLabel = $heroModeLabel
$script:approveTrainingButton = $approveTrainingButton
$script:quickCard = $quickCard
$script:quickButtonsHost = $quickButtonsHost
$script:preferencesPath = Join-Path $repoRoot 'data\gui_preferences.json'

function Apply-SplitterConstraints {
    try {
        $rootSplit.Panel1MinSize = if ($script:isCompactLayout) { 280 } else { 300 }
        $rootSplit.Panel2MinSize = if ($script:isCompactLayout) { 720 } else { 820 }
        $upperSplit.Panel1MinSize = if ($script:isCompactLayout) { 330 } else { 380 }
        $upperSplit.Panel2MinSize = if ($script:isCompactLayout) { 360 } else { 420 }
        $activitySplit.Panel1MinSize = if ($script:isCompactLayout) { 300 } else { 330 }
        $activitySplit.Panel2MinSize = if ($script:isCompactLayout) { 360 } else { 430 }
        $guidedInnerSplit.Panel1MinSize = if ($script:isCompactLayout) { 220 } else { 260 }
        $guidedInnerSplit.Panel2MinSize = if ($script:isCompactLayout) { 220 } else { 220 }
    }
    catch { }
}

function Set-SplitterDistanceClamped {
    param(
        [System.Windows.Forms.SplitContainer]$SplitContainer,
        [int]$Target
    )
    try {
        $availableWidth = $SplitContainer.ClientSize.Width
        if ($availableWidth -le 0) { return }
        $maxDistance = [Math]::Max($SplitContainer.Panel1MinSize, $availableWidth - $SplitContainer.Panel2MinSize - $SplitContainer.SplitterWidth)
        $SplitContainer.SplitterDistance = [Math]::Max($SplitContainer.Panel1MinSize, [Math]::Min($Target, $maxDistance))
    }
    catch { }
}

function Update-ResponsiveLayout {
    try {
        $sidebarTarget = if ($script:isCompactLayout) {
            [Math]::Max(256, [Math]::Min(272, [int]($form.ClientSize.Width * 0.21)))
        }
        else {
            [Math]::Max(300, [int]($form.ClientSize.Width * 0.24))
        }
        Set-SplitterDistanceClamped -SplitContainer $rootSplit -Target $sidebarTarget

        if ($script:isCompactLayout) {
            $heroLayout.ColumnStyles[0].Width = 56
            $heroLayout.ColumnStyles[1].Width = 44
        }
        else {
            $heroLayout.ColumnStyles[0].Width = 58
            $heroLayout.ColumnStyles[1].Width = 42
        }

        $contentWidth = $rootSplit.Panel2.ClientSize.Width
        if ($contentWidth -gt 0) {
            $upperTarget = if ($script:isCompactLayout) { [int]($contentWidth * 0.31) } else { [int]($contentWidth * 0.34) }
            $activityTarget = if ($script:isCompactLayout) { [int]($contentWidth * 0.33) } else { [int]($contentWidth * 0.34) }
            Set-SplitterDistanceClamped -SplitContainer $upperSplit -Target $upperTarget
            Set-SplitterDistanceClamped -SplitContainer $activitySplit -Target $activityTarget
        }

        if (-not $guidedInnerSplit.Panel1Collapsed) {
            $guidedTarget = if ($script:isCompactLayout) { [int]($upperSplit.Panel2.ClientSize.Width * 0.37) } else { [int]($upperSplit.Panel2.ClientSize.Width * 0.42) }
            Set-SplitterDistanceClamped -SplitContainer $guidedInnerSplit -Target $guidedTarget
        }
    }
    catch { }
}

function Format-DisplayTimestamp {
    param(
        [string]$Value,
        [string]$CompactPattern = 'MM-dd HH:mm'
    )
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    if (-not $script:isCompactLayout) { return $Value }
    try {
        return ([datetime]$Value).ToLocalTime().ToString($CompactPattern)
    }
    catch {
        return $Value
    }
}

function Resize-QuickButtons {
    if ($null -eq $script:quickButtonsHost -or $null -eq $script:quickCard) { return }
    $leftPadding = 16
    $topPadding = if ($script:isCompactLayout) { 68 } else { 74 }
    $rightPadding = 18
    $bottomPadding = 16
    $script:quickButtonsHost.Location = New-Object System.Drawing.Point($leftPadding, $topPadding)
    $script:quickButtonsHost.Size = New-Object System.Drawing.Size(
        [Math]::Max(170, $script:quickCard.ClientSize.Width - $leftPadding - $rightPadding),
        [Math]::Max(88, $script:quickCard.ClientSize.Height - $topPadding - $bottomPadding)
    )
    if ($script:isCompactLayout) {
        $script:quickButtonsHost.ColumnCount = 2
        $script:quickButtonsHost.RowCount = 3
    }
    else {
        $script:quickButtonsHost.ColumnCount = 1
        $script:quickButtonsHost.RowCount = 6
    }
    foreach ($control in $quickButtonsHost.Controls) {
        if ($control -is [System.Windows.Forms.Button]) {
            $control.Dock = 'Fill'
        }
    }
}

function Resize-CommandBarControls {
    if ($null -eq $buttonFlow) { return }
    if ($script:isCompactLayout) {
        $buttonFlow.ColumnStyles[0].Width = 31
        $buttonFlow.ColumnStyles[1].Width = 24
        $buttonFlow.ColumnStyles[2].Width = 27
        $buttonFlow.ColumnStyles[3].Width = 18
        $runInputButton.Text = 'Run'
        $usePreviewButton.Text = 'Plan'
        $approveTrainingButton.Text = 'Save'
        $clearInputButton.Text = 'Clr'
    }
    else {
        $buttonFlow.ColumnStyles[0].Width = 32
        $buttonFlow.ColumnStyles[1].Width = 24
        $buttonFlow.ColumnStyles[2].Width = 28
        $buttonFlow.ColumnStyles[3].Width = 16
        $runInputButton.Text = 'Run Typed Command'
        $usePreviewButton.Text = 'Preview Plan'
        $approveTrainingButton.Text = 'Approve + Save'
        $clearInputButton.Text = 'Clear'
    }
}

function Load-UiPreferences {
    if (-not (Test-Path $script:preferencesPath)) { return @{} }
    try {
        $raw = Get-Content -Path $script:preferencesPath -Raw -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        $payload = $raw | ConvertFrom-Json -ErrorAction Stop
        $preferences = @{}
        foreach ($property in $payload.PSObject.Properties) {
            $preferences[$property.Name] = $property.Value
        }
        return $preferences
    }
    catch {
        return @{}
    }
}

function Save-UiPreferences {
    try {
        $bounds = if ($script:form.WindowState -eq 'Normal') { $script:form.Bounds } else { $script:form.RestoreBounds }
        $payload = [ordered]@{
            safe_mode = [bool]$safeModeCheckbox.Checked
            confirm_risky = [bool]$confirmRiskCheckbox.Checked
            prefer_local_model = [bool]$localModelCheckbox.Checked
            read_screen_context = [bool]$screenContextCheckbox.Checked
            run_status = [string]$script:statusFilterBox.SelectedItem
            run_search = [string]$script:runSearchBox.Text
            selected_command = if ($script:selectedCommand) { [string]$script:selectedCommand.name } else { '' }
            last_input = [string]$script:agentInputBox.Text
            window_width = [int]$bounds.Width
            window_height = [int]$bounds.Height
        }
        $directory = Split-Path -Parent $script:preferencesPath
        if (-not (Test-Path $directory)) {
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
        }
        $payload | ConvertTo-Json -Depth 5 | Set-Content -Path $script:preferencesPath -Encoding UTF8
    }
    catch { }
}

function Get-FilteredRuns {
    $selectedStatus = [string]$script:statusFilterBox.SelectedItem
    if ([string]::IsNullOrWhiteSpace($selectedStatus)) { $selectedStatus = 'All' }
    $query = [string]$script:runSearchBox.Text
    $filtered = @($script:allRuns)
    if ($selectedStatus -and $selectedStatus -ne 'All') {
        $filtered = @($filtered | Where-Object { ([string]$_.status).Equals($selectedStatus, [System.StringComparison]::OrdinalIgnoreCase) })
    }
    if (-not [string]::IsNullOrWhiteSpace($query)) {
        $needle = $query.Trim().ToLowerInvariant()
        $filtered = @(
            $filtered | Where-Object {
                ([string]$_.command_name).ToLowerInvariant().Contains($needle) -or
                ([string]$_.workflow_id).ToLowerInvariant().Contains($needle) -or
                ([string]$_.status).ToLowerInvariant().Contains($needle)
            }
        )
    }
    return $filtered
}

function Update-FailureInboxButton {
    $failedCount = @($script:allRuns | Where-Object { $_.status -eq 'failed' }).Count
    $label = if ($script:isCompactLayout) { 'Fails' } else { 'Failure Inbox' }
    if ($failedCount -gt 0) {
        $label = if ($script:isCompactLayout) { "Fails ($failedCount)" } else { "Failure Inbox ($failedCount)" }
    }
    $script:failureInboxButton.Text = $label
}

function Refresh-RunListView {
    $selectedRunId = if ($script:runsList.SelectedItems.Count -gt 0) { [int]$script:runsList.SelectedItems[0].Tag.id } else { $null }
    $script:runsList.Items.Clear()
    foreach ($run in (Get-FilteredRuns)) { Add-RunListItem -Run $run }
    $script:runMetric.ValueLabel.Text = [string]$script:runsList.Items.Count
    Resize-RunColumns
    if ($null -ne $selectedRunId) {
        foreach ($item in $script:runsList.Items) {
            if ([int]$item.Tag.id -eq $selectedRunId) {
                $item.Selected = $true
                $item.Focused = $true
                break
            }
        }
    }
}

function Set-ArtifactControls {
    param([object[]]$Artifacts)
    $script:currentArtifacts = @($Artifacts)
    $script:artifactComboBox.Items.Clear()
    foreach ($artifact in $script:currentArtifacts) {
        $display = if ($artifact.exists) { "$($artifact.label) -> $($artifact.path)" } else { "$($artifact.label) -> missing" }
        [void]$script:artifactComboBox.Items.Add($display)
    }
    $enabled = $script:artifactComboBox.Items.Count -gt 0
    $script:artifactComboBox.Enabled = $enabled
    $script:openArtifactButton.Enabled = $enabled
    $script:copyArtifactButton.Enabled = $enabled
    if ($enabled) {
        $script:artifactComboBox.SelectedIndex = 0
    }
}

function Get-SelectedArtifact {
    if ($script:artifactComboBox.SelectedIndex -lt 0) { return $null }
    if ($script:artifactComboBox.SelectedIndex -ge $script:currentArtifacts.Count) { return $null }
    return $script:currentArtifacts[$script:artifactComboBox.SelectedIndex]
}

function Open-SelectedArtifact {
    $artifact = Get-SelectedArtifact
    if ($null -eq $artifact) { return }
    if (-not (Test-Path $artifact.path)) {
        [System.Windows.Forms.MessageBox]::Show("Path not found: $($artifact.path)", 'Missing Artifact', 'OK', 'Warning') | Out-Null
        return
    }
    Start-Process -FilePath $artifact.path | Out-Null
}

function Copy-SelectedArtifactPath {
    $artifact = Get-SelectedArtifact
    if ($null -eq $artifact) { return }
    try {
        Set-Clipboard -Value $artifact.path
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Clipboard Error', 'OK', 'Warning') | Out-Null
    }
}

function Apply-UiPreferences {
    param([hashtable]$Preferences)
    if ($Preferences.ContainsKey('safe_mode')) { $safeModeCheckbox.Checked = [bool]$Preferences['safe_mode'] }
    if ($Preferences.ContainsKey('confirm_risky')) { $confirmRiskCheckbox.Checked = [bool]$Preferences['confirm_risky'] }
    if ($Preferences.ContainsKey('prefer_local_model')) { $localModelCheckbox.Checked = [bool]$Preferences['prefer_local_model'] }
    if ($Preferences.ContainsKey('read_screen_context')) { $screenContextCheckbox.Checked = [bool]$Preferences['read_screen_context'] }
    if ($Preferences.ContainsKey('run_status')) {
        $targetStatus = [string]$Preferences['run_status']
        $index = $script:statusFilterBox.FindStringExact($targetStatus)
        if ($index -ge 0) { $script:statusFilterBox.SelectedIndex = $index }
    }
    if ($Preferences.ContainsKey('run_search')) { $script:runSearchBox.Text = [string]$Preferences['run_search'] }
    if ($Preferences.ContainsKey('selected_command')) {
        $commandName = [string]$Preferences['selected_command']
        if (-not [string]::IsNullOrWhiteSpace($commandName)) {
            Select-CommandByName -CommandName $commandName
        }
    }
    $width = if ($Preferences.ContainsKey('window_width')) { [int]$Preferences['window_width'] } else { 0 }
    $height = if ($Preferences.ContainsKey('window_height')) { [int]$Preferences['window_height'] } else { 0 }
    if ($width -ge $layout.FormMinWidth -and $height -ge $layout.FormMinHeight) {
        $script:form.Size = New-Object System.Drawing.Size($width, $height)
    }
}

function Show-ReviewQueueDialog {
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = 'Review Queue'
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(920, 620)
    $dialog.MinimumSize = New-Object System.Drawing.Size(760, 520)
    $dialog.BackColor = $theme.Window
    $dialog.Font = $fonts.Body

    $dialogLayout = New-Object System.Windows.Forms.TableLayoutPanel
    $dialogLayout.Dock = 'Fill'
    $dialogLayout.ColumnCount = 1
    $dialogLayout.RowCount = 4
    [void]$dialogLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 40)))
    [void]$dialogLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 55)))
    [void]$dialogLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 45)))
    [void]$dialogLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 44)))
    [void]$dialog.Controls.Add($dialogLayout)

    $toolbar = New-Object System.Windows.Forms.TableLayoutPanel
    $toolbar.Dock = 'Fill'
    $toolbar.ColumnCount = 3
    $toolbar.RowCount = 1
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 120)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 96)))
    [void]$toolbar.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$dialogLayout.Controls.Add($toolbar, 0, 0)

    $reviewStatusBox = New-Object System.Windows.Forms.ComboBox
    $reviewStatusBox.DropDownStyle = 'DropDownList'
    $reviewStatusBox.Dock = 'Fill'
    $reviewStatusBox.Margin = New-Object System.Windows.Forms.Padding(0, 6, 8, 6)
    [void]$reviewStatusBox.Items.AddRange(@('pending', 'corrected', 'approved', 'all'))
    $reviewStatusBox.SelectedIndex = 0
    [void]$toolbar.Controls.Add($reviewStatusBox, 0, 0)

    $reviewHintLabel = New-Object System.Windows.Forms.Label
    $reviewHintLabel.Text = 'Approve exact values or correct uncertain OCR outputs before resuming the workflow manually.'
    $reviewHintLabel.Font = $fonts.Small
    $reviewHintLabel.ForeColor = $theme.Muted
    $reviewHintLabel.AutoSize = $true
    $reviewHintLabel.Margin = New-Object System.Windows.Forms.Padding(0, 10, 0, 0)
    [void]$toolbar.Controls.Add($reviewHintLabel, 1, 0)

    $reviewRefreshButton = New-Object System.Windows.Forms.Button
    $reviewRefreshButton.Text = 'Refresh'
    $reviewRefreshButton.Dock = 'Fill'
    $reviewRefreshButton.Margin = New-Object System.Windows.Forms.Padding(8, 4, 0, 4)
    Set-SecondaryButtonStyle -Button $reviewRefreshButton
    [void]$toolbar.Controls.Add($reviewRefreshButton, 2, 0)

    $reviewList = New-Object System.Windows.Forms.ListView
    $reviewList.Dock = 'Fill'
    Set-ListViewStyle -ListView $reviewList
    [void]$reviewList.Columns.Add('ID', 60)
    [void]$reviewList.Columns.Add('Workflow', 150)
    [void]$reviewList.Columns.Add('Step', 140)
    [void]$reviewList.Columns.Add('Status', 90)
    [void]$reviewList.Columns.Add('Suggested', 220)
    [void]$dialogLayout.Controls.Add($reviewList, 0, 1)

    $reviewDetailBox = New-Object System.Windows.Forms.TextBox
    $reviewDetailBox.Dock = 'Fill'
    $reviewDetailBox.Multiline = $true
    $reviewDetailBox.ReadOnly = $true
    $reviewDetailBox.ScrollBars = 'Vertical'
    Set-TextSurfaceStyle -TextBox $reviewDetailBox -Mono
    [void]$dialogLayout.Controls.Add($reviewDetailBox, 0, 2)

    $actionBar = New-Object System.Windows.Forms.TableLayoutPanel
    $actionBar.Dock = 'Fill'
    $actionBar.ColumnCount = 5
    $actionBar.RowCount = 1
    [void]$actionBar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$actionBar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 170)))
    [void]$actionBar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 110)))
    [void]$actionBar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 110)))
    [void]$actionBar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 120)))
    [void]$actionBar.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$dialogLayout.Controls.Add($actionBar, 0, 3)

    $correctedValueBox = New-Object System.Windows.Forms.TextBox
    $correctedValueBox.Dock = 'Fill'
    $correctedValueBox.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 8)
    Set-TextSurfaceStyle -TextBox $correctedValueBox
    [void]$actionBar.Controls.Add($correctedValueBox, 0, 0)

    $openReviewEvidenceButton = New-Object System.Windows.Forms.Button
    $openReviewEvidenceButton.Text = 'Open Evidence'
    $openReviewEvidenceButton.Dock = 'Fill'
    $openReviewEvidenceButton.Margin = New-Object System.Windows.Forms.Padding(0, 6, 8, 6)
    Set-SecondaryButtonStyle -Button $openReviewEvidenceButton
    [void]$actionBar.Controls.Add($openReviewEvidenceButton, 1, 0)

    $approveReviewButton = New-Object System.Windows.Forms.Button
    $approveReviewButton.Text = 'Approve'
    $approveReviewButton.Dock = 'Fill'
    $approveReviewButton.Margin = New-Object System.Windows.Forms.Padding(0, 6, 8, 6)
    Set-SecondaryButtonStyle -Button $approveReviewButton
    [void]$actionBar.Controls.Add($approveReviewButton, 2, 0)

    $correctReviewButton = New-Object System.Windows.Forms.Button
    $correctReviewButton.Text = 'Correct'
    $correctReviewButton.Dock = 'Fill'
    $correctReviewButton.Margin = New-Object System.Windows.Forms.Padding(0, 6, 8, 6)
    Set-PrimaryButtonStyle -Button $correctReviewButton
    [void]$actionBar.Controls.Add($correctReviewButton, 3, 0)

    $closeReviewButton = New-Object System.Windows.Forms.Button
    $closeReviewButton.Text = 'Close'
    $closeReviewButton.Dock = 'Fill'
    $closeReviewButton.Margin = New-Object System.Windows.Forms.Padding(0, 6, 0, 6)
    Set-SecondaryButtonStyle -Button $closeReviewButton
    [void]$actionBar.Controls.Add($closeReviewButton, 4, 0)

    $reviewItems = @()

    function Resize-ReviewColumns {
        $width = [Math]::Max(540, $reviewList.ClientSize.Width - 6)
        $reviewList.Columns[0].Width = 56
        $reviewList.Columns[2].Width = 130
        $reviewList.Columns[3].Width = 90
        $reviewList.Columns[4].Width = 210
        $reviewList.Columns[1].Width = [Math]::Max(120, $width - 56 - 130 - 90 - 210)
    }

    function Get-SelectedReviewItem {
        if ($reviewList.SelectedItems.Count -le 0) { return $null }
        return $reviewList.SelectedItems[0].Tag
    }

    function Show-SelectedReviewItem {
        $item = Get-SelectedReviewItem
        if ($null -eq $item) {
            $reviewDetailBox.Text = ''
            $correctedValueBox.Text = ''
            return
        }
        $metadataJson = $item.metadata | ConvertTo-Json -Depth 8
        $reviewDetailBox.Text = "Review #$($item.id)`r`nWorkflow: $($item.workflow_id)`r`nStep: $($item.step_id)`r`nStatus: $($item.status)`r`nReason: $($item.reason)`r`nSuggested: $($item.suggested_value)`r`nCorrected: $($item.corrected_value)`r`nEvidence: $($item.evidence_path)`r`nMetadata:`r`n$metadataJson"
        $correctedValueBox.Text = if ($item.corrected_value) { [string]$item.corrected_value } else { [string]$item.suggested_value }
    }

    function Load-ReviewItems {
        $reviewList.Items.Clear()
        $payload = Invoke-BackendJson -Arguments @('list-review-items', '--status', ([string]$reviewStatusBox.SelectedItem), '--limit', '50')
        $reviewItems = @($payload.items)
        foreach ($item in $reviewItems) {
            $row = New-Object System.Windows.Forms.ListViewItem([string]$item.id)
            [void]$row.SubItems.Add([string]$item.workflow_id)
            [void]$row.SubItems.Add([string]$item.step_id)
            [void]$row.SubItems.Add([string]$item.status)
            [void]$row.SubItems.Add([string]$item.suggested_value)
            $row.Tag = $item
            [void]$reviewList.Items.Add($row)
        }
        Resize-ReviewColumns
        if ($reviewList.Items.Count -gt 0) {
            $reviewList.Items[0].Selected = $true
        }
    }

    $reviewList.Add_SelectedIndexChanged({ Show-SelectedReviewItem })
    $reviewList.Add_Resize({ Resize-ReviewColumns })
    $reviewStatusBox.Add_SelectedIndexChanged({ Load-ReviewItems })
    $reviewRefreshButton.Add_Click({ Load-ReviewItems })
    $openReviewEvidenceButton.Add_Click({
        $item = Get-SelectedReviewItem
        if ($null -eq $item -or [string]::IsNullOrWhiteSpace([string]$item.evidence_path)) { return }
        if (-not (Test-Path $item.evidence_path)) {
            [System.Windows.Forms.MessageBox]::Show("Evidence not found: $($item.evidence_path)", 'Missing Evidence', 'OK', 'Warning') | Out-Null
            return
        }
        Start-Process -FilePath $item.evidence_path | Out-Null
    })
    $approveReviewButton.Add_Click({
        $item = Get-SelectedReviewItem
        if ($null -eq $item) { return }
        [void](Invoke-BackendJson -Arguments @('resolve-review-item', '--review-id', ([string]$item.id), '--resolution', 'approved', '--corrected-value', [string]$correctedValueBox.Text))
        Load-ReviewItems
    })
    $correctReviewButton.Add_Click({
        $item = Get-SelectedReviewItem
        if ($null -eq $item) { return }
        [void](Invoke-BackendJson -Arguments @('resolve-review-item', '--review-id', ([string]$item.id), '--resolution', 'corrected', '--corrected-value', [string]$correctedValueBox.Text))
        Load-ReviewItems
    })
    $closeReviewButton.Add_Click({ $dialog.Close() })

    Load-ReviewItems
    [void]$dialog.ShowDialog($script:form)
}

function Show-OperatorDashboardDialog {
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = 'Operator Dashboard'
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(1120, 720)
    $dialog.MinimumSize = New-Object System.Drawing.Size(900, 620)
    $dialog.BackColor = $theme.Window
    $dialog.Font = $fonts.Body

    $layoutRoot = New-Object System.Windows.Forms.TableLayoutPanel
    $layoutRoot.Dock = 'Fill'
    $layoutRoot.ColumnCount = 1
    $layoutRoot.RowCount = 2
    [void]$layoutRoot.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 52)))
    [void]$layoutRoot.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$dialog.Controls.Add($layoutRoot)

    $toolbar = New-Object System.Windows.Forms.TableLayoutPanel
    $toolbar.Dock = 'Fill'
    $toolbar.ColumnCount = 6
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 124)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 96)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 104)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 86)))
    [void]$toolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 90)))
    [void]$layoutRoot.Controls.Add($toolbar, 0, 0)

    $sessionInstructionBox = New-Object System.Windows.Forms.TextBox
    $sessionInstructionBox.Dock = 'Fill'
    $sessionInstructionBox.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 8)
    Set-TextSurfaceStyle -TextBox $sessionInstructionBox
    $sessionInstructionBox.Text = if (-not [string]::IsNullOrWhiteSpace($script:agentInputBox.Text)) { [string]$script:agentInputBox.Text } else { "start today's office work" }
    [void]$toolbar.Controls.Add($sessionInstructionBox, 0, 0)

    $createSessionButton = New-Object System.Windows.Forms.Button
    $createSessionButton.Text = 'Create Session'
    $createSessionButton.Dock = 'Fill'
    $createSessionButton.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 8)
    Set-PrimaryButtonStyle -Button $createSessionButton
    [void]$toolbar.Controls.Add($createSessionButton, 1, 0)

    $runNextSessionButton = New-Object System.Windows.Forms.Button
    $runNextSessionButton.Text = 'Run Next'
    $runNextSessionButton.Dock = 'Fill'
    $runNextSessionButton.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 8)
    Set-SecondaryButtonStyle -Button $runNextSessionButton
    [void]$toolbar.Controls.Add($runNextSessionButton, 2, 0)

    $runQueueButton = New-Object System.Windows.Forms.Button
    $runQueueButton.Text = 'Run Queue'
    $runQueueButton.Dock = 'Fill'
    $runQueueButton.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 8)
    Set-SecondaryButtonStyle -Button $runQueueButton
    [void]$toolbar.Controls.Add($runQueueButton, 3, 0)

    $pauseSessionButton = New-Object System.Windows.Forms.Button
    $pauseSessionButton.Text = 'Pause'
    $pauseSessionButton.Dock = 'Fill'
    $pauseSessionButton.Margin = New-Object System.Windows.Forms.Padding(0, 8, 8, 8)
    Set-SecondaryButtonStyle -Button $pauseSessionButton
    [void]$toolbar.Controls.Add($pauseSessionButton, 4, 0)

    $refreshOperatorButton = New-Object System.Windows.Forms.Button
    $refreshOperatorButton.Text = 'Refresh'
    $refreshOperatorButton.Dock = 'Fill'
    $refreshOperatorButton.Margin = New-Object System.Windows.Forms.Padding(0, 8, 0, 8)
    Set-SecondaryButtonStyle -Button $refreshOperatorButton
    [void]$toolbar.Controls.Add($refreshOperatorButton, 5, 0)

    $mainSplit = New-Object System.Windows.Forms.SplitContainer
    $mainSplit.Dock = 'Fill'
    $mainSplit.SplitterDistance = 320
    $mainSplit.BackColor = $theme.Window
    [void]$layoutRoot.Controls.Add($mainSplit, 0, 1)

    $sessionsCard = New-Object System.Windows.Forms.Panel
    $sessionsCard.Dock = 'Fill'
    $sessionsCard.Padding = New-Object System.Windows.Forms.Padding(14)
    Set-CardStyle -Control $sessionsCard -BackColor $theme.Card
    [void]$mainSplit.Panel1.Controls.Add($sessionsCard)

    $sessionsLayout = New-Object System.Windows.Forms.TableLayoutPanel
    $sessionsLayout.Dock = 'Fill'
    $sessionsLayout.ColumnCount = 1
    $sessionsLayout.RowCount = 2
    [void]$sessionsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 38)))
    [void]$sessionsLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$sessionsCard.Controls.Add($sessionsLayout)

    $sessionsHeader = New-Object System.Windows.Forms.Label
    $sessionsHeader.Text = 'Sessions'
    $sessionsHeader.Font = $fonts.Section
    $sessionsHeader.ForeColor = $theme.Text
    $sessionsHeader.AutoSize = $true
    [void]$sessionsLayout.Controls.Add($sessionsHeader, 0, 0)

    $sessionsList = New-Object System.Windows.Forms.ListView
    $sessionsList.Dock = 'Fill'
    Set-ListViewStyle -ListView $sessionsList
    [void]$sessionsList.Columns.Add('ID', 48)
    [void]$sessionsList.Columns.Add('Name', 160)
    [void]$sessionsList.Columns.Add('Status', 86)
    [void]$sessionsLayout.Controls.Add($sessionsList, 0, 1)

    $rightLayout = New-Object System.Windows.Forms.TableLayoutPanel
    $rightLayout.Dock = 'Fill'
    $rightLayout.ColumnCount = 1
    $rightLayout.RowCount = 2
    [void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 55)))
    [void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 45)))
    [void]$mainSplit.Panel2.Controls.Add($rightLayout)

    $tasksCard = New-Object System.Windows.Forms.Panel
    $tasksCard.Dock = 'Fill'
    $tasksCard.Padding = New-Object System.Windows.Forms.Padding(14)
    Set-CardStyle -Control $tasksCard -BackColor $theme.Card
    [void]$rightLayout.Controls.Add($tasksCard, 0, 0)

    $tasksLayout = New-Object System.Windows.Forms.TableLayoutPanel
    $tasksLayout.Dock = 'Fill'
    $tasksLayout.ColumnCount = 1
    $tasksLayout.RowCount = 2
    [void]$tasksLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 38)))
    [void]$tasksLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$tasksCard.Controls.Add($tasksLayout)

    $tasksHeader = New-Object System.Windows.Forms.Label
    $tasksHeader.Text = 'Queue Tasks'
    $tasksHeader.Font = $fonts.Section
    $tasksHeader.ForeColor = $theme.Text
    $tasksHeader.AutoSize = $true
    [void]$tasksLayout.Controls.Add($tasksHeader, 0, 0)

    $tasksList = New-Object System.Windows.Forms.ListView
    $tasksList.Dock = 'Fill'
    Set-ListViewStyle -ListView $tasksList
    [void]$tasksList.Columns.Add('#', 44)
    [void]$tasksList.Columns.Add('Command', 160)
    [void]$tasksList.Columns.Add('Status', 90)
    [void]$tasksList.Columns.Add('Priority', 74)
    [void]$tasksList.Columns.Add('Retries', 64)
    [void]$tasksLayout.Controls.Add($tasksList, 0, 1)

    $bottomSplit = New-Object System.Windows.Forms.SplitContainer
    $bottomSplit.Dock = 'Fill'
    $bottomSplit.SplitterDistance = 430
    $bottomSplit.BackColor = $theme.Window
    [void]$rightLayout.Controls.Add($bottomSplit, 0, 1)

    $summaryCard = New-Object System.Windows.Forms.Panel
    $summaryCard.Dock = 'Fill'
    $summaryCard.Padding = New-Object System.Windows.Forms.Padding(14)
    Set-CardStyle -Control $summaryCard -BackColor $theme.Card
    [void]$bottomSplit.Panel1.Controls.Add($summaryCard)

    $summaryLayout = New-Object System.Windows.Forms.TableLayoutPanel
    $summaryLayout.Dock = 'Fill'
    $summaryLayout.ColumnCount = 1
    $summaryLayout.RowCount = 2
    [void]$summaryLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 38)))
    [void]$summaryLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$summaryCard.Controls.Add($summaryLayout)

    $summaryHeader = New-Object System.Windows.Forms.Label
    $summaryHeader.Text = 'Session Summary'
    $summaryHeader.Font = $fonts.Section
    $summaryHeader.ForeColor = $theme.Text
    $summaryHeader.AutoSize = $true
    [void]$summaryLayout.Controls.Add($summaryHeader, 0, 0)

    $sessionSummaryBox = New-Object System.Windows.Forms.TextBox
    $sessionSummaryBox.Dock = 'Fill'
    $sessionSummaryBox.Multiline = $true
    $sessionSummaryBox.ReadOnly = $true
    $sessionSummaryBox.ScrollBars = 'Vertical'
    Set-TextSurfaceStyle -TextBox $sessionSummaryBox -Mono
    [void]$summaryLayout.Controls.Add($sessionSummaryBox, 0, 1)

    $exceptionCard = New-Object System.Windows.Forms.Panel
    $exceptionCard.Dock = 'Fill'
    $exceptionCard.Padding = New-Object System.Windows.Forms.Padding(14)
    Set-CardStyle -Control $exceptionCard -BackColor $theme.Card
    [void]$bottomSplit.Panel2.Controls.Add($exceptionCard)

    $exceptionLayout = New-Object System.Windows.Forms.TableLayoutPanel
    $exceptionLayout.Dock = 'Fill'
    $exceptionLayout.ColumnCount = 1
    $exceptionLayout.RowCount = 3
    [void]$exceptionLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 38)))
    [void]$exceptionLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
    [void]$exceptionLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 42)))
    [void]$exceptionCard.Controls.Add($exceptionLayout)

    $exceptionHeader = New-Object System.Windows.Forms.Label
    $exceptionHeader.Text = 'Exceptions'
    $exceptionHeader.Font = $fonts.Section
    $exceptionHeader.ForeColor = $theme.Text
    $exceptionHeader.AutoSize = $true
    [void]$exceptionLayout.Controls.Add($exceptionHeader, 0, 0)

    $exceptionsList = New-Object System.Windows.Forms.ListView
    $exceptionsList.Dock = 'Fill'
    Set-ListViewStyle -ListView $exceptionsList
    [void]$exceptionsList.Columns.Add('ID', 46)
    [void]$exceptionsList.Columns.Add('Kind', 110)
    [void]$exceptionsList.Columns.Add('Status', 90)
    [void]$exceptionsList.Columns.Add('Message', 260)
    [void]$exceptionLayout.Controls.Add($exceptionsList, 0, 1)

    $exceptionActions = New-Object System.Windows.Forms.FlowLayoutPanel
    $exceptionActions.Dock = 'Fill'
    $exceptionActions.FlowDirection = 'LeftToRight'
    $exceptionActions.WrapContents = $false
    [void]$exceptionLayout.Controls.Add($exceptionActions, 0, 2)

    $approveExceptionButton = New-Object System.Windows.Forms.Button
    $approveExceptionButton.Text = 'Approve'
    $approveExceptionButton.Size = New-Object System.Drawing.Size(90, 28)
    Set-SecondaryButtonStyle -Button $approveExceptionButton
    [void]$exceptionActions.Controls.Add($approveExceptionButton)

    $retryExceptionButton = New-Object System.Windows.Forms.Button
    $retryExceptionButton.Text = 'Retry'
    $retryExceptionButton.Size = New-Object System.Drawing.Size(80, 28)
    Set-PrimaryButtonStyle -Button $retryExceptionButton
    [void]$exceptionActions.Controls.Add($retryExceptionButton)

    $operatorHint = New-Object System.Windows.Forms.Label
    $operatorHint.Text = 'Create a session from a natural request, then run the next task or the full safe queue.'
    $operatorHint.Font = $fonts.Small
    $operatorHint.ForeColor = $theme.Muted
    $operatorHint.AutoSize = $true
    $operatorHint.Margin = New-Object System.Windows.Forms.Padding(12, 7, 0, 0)
    [void]$exceptionActions.Controls.Add($operatorHint)

    function Resize-OperatorSessionColumns {
        $width = [Math]::Max(240, $sessionsList.ClientSize.Width - 6)
        $sessionsList.Columns[0].Width = 44
        $sessionsList.Columns[2].Width = 84
        $sessionsList.Columns[1].Width = [Math]::Max(120, $width - 44 - 84)
    }

    function Resize-OperatorTaskColumns {
        $width = [Math]::Max(420, $tasksList.ClientSize.Width - 6)
        $tasksList.Columns[0].Width = 38
        $tasksList.Columns[2].Width = 90
        $tasksList.Columns[3].Width = 72
        $tasksList.Columns[4].Width = 64
        $tasksList.Columns[1].Width = [Math]::Max(140, $width - 38 - 90 - 72 - 64)
    }

    function Resize-OperatorExceptionColumns {
        $width = [Math]::Max(360, $exceptionsList.ClientSize.Width - 6)
        $exceptionsList.Columns[0].Width = 42
        $exceptionsList.Columns[1].Width = 100
        $exceptionsList.Columns[2].Width = 82
        $exceptionsList.Columns[3].Width = [Math]::Max(120, $width - 42 - 100 - 82)
    }

    function Get-SelectedOperatorSession {
        if ($sessionsList.SelectedItems.Count -le 0) { return $null }
        return $sessionsList.SelectedItems[0].Tag
    }

    function Get-SelectedOperatorException {
        if ($exceptionsList.SelectedItems.Count -le 0) { return $null }
        return $exceptionsList.SelectedItems[0].Tag
    }

    function Show-OperatorSessionDetails {
        param([int]$SessionId)
        $payload = Invoke-BackendJson -Arguments @('operator-session-details', '--session-id', [string]$SessionId)
        $tasksList.Items.Clear()
        foreach ($task in $payload.tasks) {
            $row = New-Object System.Windows.Forms.ListViewItem([string]$task.position)
            [void]$row.SubItems.Add([string]$task.command_name)
            [void]$row.SubItems.Add([string]$task.status)
            [void]$row.SubItems.Add([string]$task.priority)
            [void]$row.SubItems.Add(([string]$task.retries + '/' + [string]$task.max_retries))
            $row.Tag = $task
            [void]$tasksList.Items.Add($row)
        }
        $exceptionsList.Items.Clear()
        foreach ($exception in $payload.exceptions) {
            $row = New-Object System.Windows.Forms.ListViewItem([string]$exception.id)
            [void]$row.SubItems.Add([string]$exception.kind)
            [void]$row.SubItems.Add([string]$exception.status)
            [void]$row.SubItems.Add([string]$exception.message)
            $row.Tag = $exception
            [void]$exceptionsList.Items.Add($row)
        }
        $sessionSummaryBox.Text = $payload.summary_text
        Resize-OperatorTaskColumns
        Resize-OperatorExceptionColumns
    }

    function Load-OperatorSessions {
        $selectedId = if ($sessionsList.SelectedItems.Count -gt 0) { [int]$sessionsList.SelectedItems[0].Tag.id } else { $null }
        $payload = Invoke-BackendJson -Arguments @('operator-list-sessions', '--limit', '25', '--status', 'all')
        $sessionsList.Items.Clear()
        foreach ($session in $payload.sessions) {
            $row = New-Object System.Windows.Forms.ListViewItem([string]$session.id)
            [void]$row.SubItems.Add([string]$session.name)
            [void]$row.SubItems.Add([string]$session.status)
            $row.Tag = $session
            [void]$sessionsList.Items.Add($row)
        }
        Resize-OperatorSessionColumns
        if ($null -ne $selectedId) {
            foreach ($row in $sessionsList.Items) {
                if ([int]$row.Tag.id -eq $selectedId) {
                    $row.Selected = $true
                    break
                }
            }
        }
        elseif ($sessionsList.Items.Count -gt 0) {
            $sessionsList.Items[0].Selected = $true
        }
    }

    function Refresh-SelectedOperatorSession {
        $selected = Get-SelectedOperatorSession
        if ($null -eq $selected) {
            $tasksList.Items.Clear()
            $exceptionsList.Items.Clear()
            $sessionSummaryBox.Text = ''
            return
        }
        Show-OperatorSessionDetails -SessionId ([int]$selected.id)
    }

    function Invoke-OperatorAction {
        param([string[]]$Arguments)
        $dialog.UseWaitCursor = $true
        [System.Windows.Forms.Application]::DoEvents()
        try {
            [void](Invoke-BackendJson -Arguments $Arguments)
            Load-OperatorSessions
            Refresh-SelectedOperatorSession
            Load-Runs
        }
        finally {
            $dialog.UseWaitCursor = $false
        }
    }

    $sessionsList.Add_SelectedIndexChanged({ Refresh-SelectedOperatorSession })
    $sessionsList.Add_Resize({ Resize-OperatorSessionColumns })
    $tasksList.Add_Resize({ Resize-OperatorTaskColumns })
    $exceptionsList.Add_Resize({ Resize-OperatorExceptionColumns })
    $refreshOperatorButton.Add_Click({ Load-OperatorSessions; Refresh-SelectedOperatorSession })
    $createSessionButton.Add_Click({
        try {
            $instruction = $sessionInstructionBox.Text.Trim()
            if ([string]::IsNullOrWhiteSpace($instruction)) { throw 'Enter a request to build the operator session.' }
            $payload = Invoke-BackendJson -Arguments @('operator-create-session', '--instruction', $instruction)
            Load-OperatorSessions
            foreach ($row in $sessionsList.Items) {
                if ([int]$row.Tag.id -eq [int]$payload.session.id) { $row.Selected = $true; break }
            }
        }
        catch {
            [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Operator Session Error', 'OK', 'Warning') | Out-Null
        }
    })
    $runNextSessionButton.Add_Click({
        $selected = Get-SelectedOperatorSession
        if ($null -eq $selected) { return }
        $arguments = @('operator-run-next', '--session-id', ([string]$selected.id))
        if ($safeModeCheckbox.Checked) { $arguments += '--safe-mode' }
        if ($confirmRiskCheckbox.Checked) { $arguments += '--confirm-risky' }
        Invoke-OperatorAction -Arguments $arguments
    })
    $runQueueButton.Add_Click({
        $selected = Get-SelectedOperatorSession
        if ($null -eq $selected) { return }
        $arguments = @('operator-run-session', '--session-id', ([string]$selected.id))
        if ($safeModeCheckbox.Checked) { $arguments += '--safe-mode' }
        if ($confirmRiskCheckbox.Checked) { $arguments += '--confirm-risky' }
        Invoke-OperatorAction -Arguments $arguments
    })
    $pauseSessionButton.Add_Click({
        $selected = Get-SelectedOperatorSession
        if ($null -eq $selected) { return }
        Invoke-OperatorAction -Arguments @('operator-pause-session', '--session-id', ([string]$selected.id))
    })
    $approveExceptionButton.Add_Click({
        $selected = Get-SelectedOperatorException
        if ($null -eq $selected) { return }
        Invoke-OperatorAction -Arguments @('operator-resolve-exception', '--exception-id', ([string]$selected.id), '--resolution', 'approved')
    })
    $retryExceptionButton.Add_Click({
        $selected = Get-SelectedOperatorException
        if ($null -eq $selected) { return }
        Invoke-OperatorAction -Arguments @('operator-resolve-exception', '--exception-id', ([string]$selected.id), '--resolution', 'retry')
    })

    Load-OperatorSessions
    Refresh-SelectedOperatorSession
    [void]$dialog.ShowDialog($script:form)
}


function Update-ModeText {
    $safeText = if ($safeModeCheckbox.Checked) { 'Safe mode on' } else { 'Safe mode off' }
    $confirmText = if ($confirmRiskCheckbox.Checked) { 'risky actions auto-approved' } else { 'risky actions require manual approval' }
    $plannerText = if ($localModelCheckbox.Checked) { 'local model active' } else { 'built-in planner active' }
    $screenText = if ($screenContextCheckbox.Checked) { 'screen context on' } else { 'screen context off' }
    if ($script:isCompactLayout) {
        $safeText = if ($safeModeCheckbox.Checked) { 'Safe on' } else { 'Safe off' }
        $confirmText = if ($confirmRiskCheckbox.Checked) { 'risky allowed' } else { 'risky blocked' }
        $plannerText = if ($localModelCheckbox.Checked) { 'Local on' } else { 'Local off' }
        $screenText = if ($screenContextCheckbox.Checked) { 'screen on' } else { 'screen off' }
    }
    $script:heroModeLabel.Text = "$safeText, $confirmText, $plannerText, $screenText."
}

function Update-LocalAgentOptions {
    $screenContextCheckbox.Enabled = $localModelCheckbox.Checked
    if (-not $localModelCheckbox.Checked) {
        $screenContextCheckbox.Checked = $false
    }
}

function Update-TrainingApprovalState {
    if ($null -eq $script:approveTrainingButton) { return }
    $enabled = $false
    if ($null -ne $script:lastAssistantPlan -and -not [string]::IsNullOrWhiteSpace($script:lastAssistantInstruction)) {
        $commandCount = @($script:lastAssistantPlan.commands).Count
        $currentInstruction = [string]$script:agentInputBox.Text
        $enabled = ($commandCount -gt 0 -and $currentInstruction.Trim() -eq $script:lastAssistantInstruction.Trim())
    }
    $script:approveTrainingButton.Enabled = $enabled
}

function Clear-AssistantPlanState {
    $script:lastAssistantInstruction = ''
    $script:lastAssistantPlan = $null
    $script:lastAssistantScreenContext = @{}
    Update-TrainingApprovalState
}

function Set-AssistantPlanState {
    param(
        [string]$Instruction,
        [object]$Plan,
        [object]$ScreenContext
    )
    $script:lastAssistantInstruction = [string]$Instruction
    $script:lastAssistantPlan = $Plan
    if ($null -eq $ScreenContext) {
        $script:lastAssistantScreenContext = @{}
    }
    else {
        $script:lastAssistantScreenContext = $ScreenContext
    }
    Update-TrainingApprovalState
}

function Save-AssistantPlanFeedback {
    if ($null -eq $script:lastAssistantPlan -or [string]::IsNullOrWhiteSpace($script:lastAssistantInstruction)) {
        [System.Windows.Forms.MessageBox]::Show('Preview an assistant plan first, then approve it for training.', 'No Plan Ready', 'OK', 'Warning') | Out-Null
        return
    }
    $currentInstruction = [string]$script:agentInputBox.Text
    if ($currentInstruction.Trim() -ne $script:lastAssistantInstruction.Trim()) {
        Clear-AssistantPlanState
        [System.Windows.Forms.MessageBox]::Show('The request changed after the last preview. Preview the plan again before saving it for training.', 'Plan Outdated', 'OK', 'Warning') | Out-Null
        return
    }

    try {
        $planJson = $script:lastAssistantPlan | ConvertTo-Json -Depth 12 -Compress
        $screenJson = $script:lastAssistantScreenContext | ConvertTo-Json -Depth 8 -Compress
        $origin = if ([string]$script:lastAssistantPlan.source -match 'local') { 'desktop-gui-local' } else { 'desktop-gui' }
        $payload = Invoke-BackendJson -Arguments @(
            'save-plan-feedback',
            '--instruction', $script:lastAssistantInstruction,
            '--plan-json', $planJson,
            '--screen-context-json', $screenJson,
            '--origin', $origin,
            '--notes', 'Approved from desktop GUI'
        )
        $recordId = [string]$payload.record.metadata.record_id
        $capturedAt = [string]$payload.record.metadata.captured_at
        $datasetFile = [string]$payload.dataset_file
        Set-StatusText -Text 'Saved' -Color $theme.Success
        $script:detailBox.Text = (Format-AssistantPlanText -Plan $script:lastAssistantPlan) + "`r`n`r`nSaved for training:`r`nRecord: $recordId`r`nSaved at: $capturedAt`r`nDataset: $datasetFile"
        Clear-AssistantPlanState
    }
    catch {
        Set-StatusText -Text 'Save Failed' -Color $theme.Danger
        $script:detailBox.Text = $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Training Save Failed', 'OK', 'Error') | Out-Null
    }
}

function Set-StatusText {
    param([string]$Text, [System.Drawing.Color]$Color)
    $script:statusMetric.ValueLabel.Text = $Text
    $script:statusMetric.ValueLabel.ForeColor = $Color
}

function Resize-RunColumns {
    $width = [Math]::Max($(if ($script:isCompactLayout) { 260 } else { 340 }), $script:runsList.ClientSize.Width - 6)
    if ($script:isCompactLayout) {
        $script:runsList.Columns[0].Width = 0
        $script:runsList.Columns[2].Width = 78
        $script:runsList.Columns[3].Width = 90
        $script:runsList.Columns[1].Width = [Math]::Max(116, $width - 78 - 90)
    }
    else {
        $script:runsList.Columns[0].Width = 54
        $script:runsList.Columns[2].Width = 86
        $script:runsList.Columns[3].Width = 148
        $script:runsList.Columns[1].Width = [Math]::Max(120, $width - 54 - 86 - 148)
    }
}

function Resize-LogColumns {
    $width = [Math]::Max($(if ($script:isCompactLayout) { 360 } else { 400 }), $script:logsList.ClientSize.Width - 6)
    if ($script:isCompactLayout) {
        $script:logsList.Columns[0].Width = 104
        $script:logsList.Columns[1].Width = 72
        $script:logsList.Columns[3].Width = 72
        $script:logsList.Columns[2].Width = [Math]::Max(150, $width - 104 - 72 - 72)
    }
    else {
        $script:logsList.Columns[0].Width = 150
        $script:logsList.Columns[1].Width = 96
        $script:logsList.Columns[3].Width = 118
        $script:logsList.Columns[2].Width = [Math]::Max(160, $width - 150 - 96 - 118)
    }
}

function Add-RunListItem {
    param($Run)
    $item = New-Object System.Windows.Forms.ListViewItem([string]$Run.id)
    [void]$item.SubItems.Add([string]$Run.command_name)
    [void]$item.SubItems.Add([string]$Run.status)
    [void]$item.SubItems.Add((Format-DisplayTimestamp -Value ([string]$Run.started_at) -CompactPattern 'MM-dd HH:mm'))
    $item.Tag = $Run
    [void]$script:runsList.Items.Add($item)
}

function Add-StepListItem {
    param($Step)
    $item = New-Object System.Windows.Forms.ListViewItem([string]$Step.step_id)
    [void]$item.SubItems.Add([string]$Step.status)
    [void]$item.SubItems.Add([string]$Step.message)
    [void]$item.SubItems.Add((Format-DisplayTimestamp -Value ([string]$Step.created_at) -CompactPattern 'HH:mm:ss'))
    $item.Tag = $Step
    [void]$script:logsList.Items.Add($item)
}

function Refresh-CommandCatalog {
    $filter = $script:catalogSearchBox.Text.Trim().ToLowerInvariant()
    $selectedName = if ($script:selectedCommand) { [string]$script:selectedCommand.name } else { '' }
    $script:visibleCommands = @()
    $script:commandList.Items.Clear()
    foreach ($command in ($script:commandListData | Sort-Object name)) {
        $name = [string]$command.name
        $description = [string]$command.description
        if ([string]::IsNullOrWhiteSpace($filter) -or $name.ToLowerInvariant().Contains($filter) -or $description.ToLowerInvariant().Contains($filter)) {
            $script:visibleCommands += $command
            [void]$script:commandList.Items.Add($name)
        }
    }
    $script:catalogCountLabel.Text = "{0} workflows visible" -f $script:visibleCommands.Count
    if (-not [string]::IsNullOrWhiteSpace($selectedName)) {
        for ($index = 0; $index -lt $script:visibleCommands.Count; $index++) {
            if ([string]$script:visibleCommands[$index].name -eq $selectedName) {
                $script:commandList.SelectedIndex = $index
                break
            }
        }
    }
}

function Update-ParameterFieldWidths {
    if ($null -eq $script:parameterFieldsHost) { return }
    $width = [Math]::Max($layout.ParameterMinWidth, $script:parameterFieldsHost.ClientSize.Width - 28)
    foreach ($panel in $script:parameterFieldPanels) {
        $panel.Width = $width
    }
}

function Get-GuidedValues {
    param([object]$Command, [switch]$AllowPlaceholders)
    $values = @{}
    $missing = @()
    foreach ($parameter in $Command.parameters) {
        $text = ''
        if ($script:parameterInputs.ContainsKey($parameter.name)) { $text = [string]$script:parameterInputs[$parameter.name].Text }
        $text = $text.Trim()
        if (-not [string]::IsNullOrWhiteSpace($text)) { $values[$parameter.name] = $text; continue }
        $default = Get-ParameterDefault -CommandName ([string]$Command.name) -ParameterName ([string]$parameter.name) -ExistingValues $values
        if (-not [string]::IsNullOrWhiteSpace([string]$default)) { $values[$parameter.name] = [string]$default; continue }
        if ($AllowPlaceholders) { $values[$parameter.name] = "<$($parameter.name)>"; continue }
        if ($parameter.required) { $missing += [string]$parameter.name }
    }
    return [pscustomobject]@{ Values = $values; Missing = $missing }
}

function Update-GuidedPreview {
    if ($null -eq $script:selectedCommand) { $script:previewBox.Text = ''; return }
    $state = Get-GuidedValues -Command $script:selectedCommand -AllowPlaceholders
    $script:previewBox.Text = Build-AgentCommand -CommandName ([string]$script:selectedCommand.name) -Values $state.Values -Metadata $script:selectedCommand
}

function Reset-SelectedCommandInputs {
    if ($null -eq $script:selectedCommand) { return }
    $existing = @{}
    foreach ($parameter in $script:selectedCommand.parameters) {
        $default = Get-ParameterDefault -CommandName ([string]$script:selectedCommand.name) -ParameterName ([string]$parameter.name) -ExistingValues $existing
        $text = if ($null -ne $default) { [string]$default } else { '' }
        if ($script:parameterInputs.ContainsKey($parameter.name)) { $script:parameterInputs[$parameter.name].Text = $text }
        if (-not [string]::IsNullOrWhiteSpace($text)) { $existing[$parameter.name] = $text }
    }
    Update-GuidedPreview
}

function Render-SelectedCommand {
    param([object]$Command)
    $script:selectedCommand = $Command
    $script:parameterInputs = @{}
    $script:parameterFieldPanels = @()
    $script:parameterFieldsHost.Controls.Clear()
    $script:guidedInnerSplit.Panel1Collapsed = $false
    $descriptionText = [string]$Command.description
    if ($script:isCompactLayout -and $descriptionText.Length -gt 52) {
        $descriptionText = $descriptionText.Substring(0, 49) + '...'
    }
    $script:selectedCommandLabel.Text = [string]$Command.name
    if ($script:isCompactLayout) {
        $script:selectedCommandDescription.Text = "$($Command.workflow_id) | risk: $($Command.risk) | $descriptionText"
    }
    else {
        $script:selectedCommandDescription.Text = "Workflow: $($Command.workflow_id)    Risk: $($Command.risk)`r`n$($Command.description)"
    }
    if (-not $Command.parameters -or $Command.parameters.Count -eq 0) {
        $script:guidedInnerSplit.Panel1Collapsed = $true
        $empty = New-Object System.Windows.Forms.Label
        $empty.Text = 'This workflow has no editable fields. Review the command preview and run it directly.'
        $empty.Font = $fonts.Body
        $empty.ForeColor = $theme.Muted
        $empty.AutoSize = $true
        $empty.Margin = New-Object System.Windows.Forms.Padding(0, 8, 0, 0)
        $script:selectedCommandDescription.Text = if ($script:isCompactLayout) { "$($Command.workflow_id) | risk: $($Command.risk) | Uses built-in defaults." } else { "Workflow: $($Command.workflow_id)    Risk: $($Command.risk)`r`nThis workflow uses built-in defaults, so only the resolved preview is shown." }
        Update-GuidedPreview
        Update-ResponsiveLayout
        return
    }
    foreach ($parameter in $Command.parameters) {
        $name = [string]$parameter.name
        $required = [bool]$parameter.required
        $isMultiline = $name -match '(text|content|summary|message)'
        $fieldPanel = New-Object System.Windows.Forms.Panel
        $fieldPanel.Height = if ($isMultiline) { 118 } else { 88 }
        $fieldPanel.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 12)
        $fieldPanel.Padding = New-Object System.Windows.Forms.Padding(12)
        $fieldPanel.BackColor = $theme.Input
        $fieldPanel.BorderStyle = 'FixedSingle'

        $fieldLabel = New-Object System.Windows.Forms.Label
        $fieldLabel.Text = if ($required) { "$name *" } else { $name }
        $fieldLabel.Font = $fonts.Label
        $fieldLabel.ForeColor = $theme.Text
        $fieldLabel.AutoSize = $true
        $fieldLabel.Location = New-Object System.Drawing.Point(10, 8)
        [void]$fieldPanel.Controls.Add($fieldLabel)

        $fieldMeta = New-Object System.Windows.Forms.Label
        $fieldMeta.Text = if ($required) { "type=$($parameter.type)  required" } else { "type=$($parameter.type)  optional" }
        $fieldMeta.Font = $fonts.Small
        $fieldMeta.ForeColor = $theme.Muted
        $fieldMeta.AutoSize = $true
        $fieldMeta.Location = New-Object System.Drawing.Point(10, 28)
        [void]$fieldPanel.Controls.Add($fieldMeta)

        $input = New-Object System.Windows.Forms.TextBox
        $input.Location = New-Object System.Drawing.Point(10, 50)
        $input.Width = 240
        if ($isMultiline) {
            $input.Multiline = $true
            $input.Height = 54
            $input.ScrollBars = 'Vertical'
        }
        else {
            $input.Height = 28
        }
        Set-TextSurfaceStyle -TextBox $input
        $default = Get-ParameterDefault -CommandName ([string]$Command.name) -ParameterName $name -ExistingValues @{}
        if (-not [string]::IsNullOrWhiteSpace([string]$default)) { $input.Text = [string]$default }
        $input.Add_TextChanged({ Update-GuidedPreview })
        $fieldPanel.Tag = $input
        $fieldPanel.Add_Resize({
            $localInput = $this.Tag
            if ($null -ne $localInput) { $localInput.Width = [Math]::Max(180, $this.ClientSize.Width - 22) }
        })
        [void]$fieldPanel.Controls.Add($input)

        $script:parameterInputs[$name] = $input
        $script:parameterFieldPanels += $fieldPanel
        $script:parameterFieldsHost.Controls.Add($fieldPanel)
    }
    Update-ParameterFieldWidths
    Update-GuidedPreview
    Update-ResponsiveLayout
}

function Select-CommandByName {
    param([string]$CommandName)
    if (-not [string]::IsNullOrWhiteSpace($script:catalogSearchBox.Text)) {
        $script:catalogSearchBox.Text = ''
    }
    for ($index = 0; $index -lt $script:visibleCommands.Count; $index++) {
        if ([string]$script:visibleCommands[$index].name -eq $CommandName) {
            $script:commandList.SelectedIndex = $index
            return
        }
    }
}

function Show-RunDetails {
    param([int]$RunId)
    $script:logsList.Items.Clear()
    $payload = Invoke-BackendJson -Arguments @('run-details', '--run-id', [string]$RunId)
    $summaryJson = $payload.run.summary | ConvertTo-Json -Depth 10
    $artifactCount = @($payload.artifacts).Count
    $script:detailBox.Text = "Run #$RunId`r`nCommand: $($payload.run.command_name)`r`nWorkflow: $($payload.run.workflow_id)`r`nStatus: $($payload.run.status)`r`nStarted: $($payload.run.started_at)`r`nArtifacts: $artifactCount`r`nSummary:`r`n$summaryJson"
    Set-ArtifactControls -Artifacts @($payload.artifacts)
    foreach ($step in $payload.steps) { Add-StepListItem -Step $step }
    Resize-LogColumns
}

function Load-Runs {
    $payload = Invoke-BackendJson -Arguments @('list-runs', '--limit', '60')
    $dashboardPayload = Invoke-BackendJson -Arguments @('dashboard', '--limit', '60')
    $script:allRuns = @($payload.runs)
    Refresh-RunListView
    Update-FailureInboxButton

    $latestRun = $dashboardPayload.dashboard.latest_run
    if ($null -ne $latestRun) {
        $latestStatus = [string]$latestRun.status
        if ($latestStatus -eq 'failed') { Set-StatusText -Text 'Failed' -Color $theme.Danger }
        elseif ($latestStatus -eq 'completed') { Set-StatusText -Text 'Completed' -Color $theme.Success }
        elseif ($latestStatus -eq 'running') { Set-StatusText -Text 'Running' -Color $theme.Warning }
        else { Set-StatusText -Text $latestStatus -Color $theme.Muted }
    }
}

function Get-SelectedWorkflowCommand {
    if ($null -eq $script:selectedCommand) { throw 'Select a workflow first.' }
    $state = Get-GuidedValues -Command $script:selectedCommand
    if ($state.Missing.Count -gt 0) { throw "Fill these fields before running: $($state.Missing -join ', ')" }
    return Build-AgentCommand -CommandName ([string]$script:selectedCommand.name) -Values $state.Values -Metadata $script:selectedCommand
}

function Invoke-RunWorkflow {
    param([string]$RawCommand)
    if ([string]::IsNullOrWhiteSpace($RawCommand)) {
        [System.Windows.Forms.MessageBox]::Show('Enter a command or select a workflow before running.', 'Missing Command', 'OK', 'Warning') | Out-Null
        return
    }
    try {
        $arguments = @('run-command', '--raw-command', $RawCommand)
        if ($safeModeCheckbox.Checked) { $arguments += '--safe-mode' }
        if ($confirmRiskCheckbox.Checked) { $arguments += '--confirm-risky' }
        Set-StatusText -Text 'Running' -Color $theme.Warning
        $script:detailBox.Text = "Running:`r`n$RawCommand"
        $script:form.UseWaitCursor = $true
        [System.Windows.Forms.Application]::DoEvents()
        $payload = Invoke-BackendJson -Arguments $arguments
        $outcome = $payload.outcome
        $summaryJson = $outcome.summary | ConvertTo-Json -Depth 10
        $artifactCount = @($payload.artifacts).Count
        $script:detailBox.Text = "Run #$($outcome.run_id)`r`nStatus: $($outcome.status)`r`nArtifacts: $artifactCount`r`nSummary:`r`n$summaryJson"
        Set-ArtifactControls -Artifacts @($payload.artifacts)
        if ($outcome.status -eq 'completed') { Set-StatusText -Text 'Completed' -Color $theme.Success }
        elseif ($outcome.status -eq 'failed') { Set-StatusText -Text 'Failed' -Color $theme.Danger }
        else { Set-StatusText -Text ([string]$outcome.status) -Color $theme.Muted }
        Load-Runs
        if ($outcome.run_id) { Show-RunDetails -RunId ([int]$outcome.run_id) }
    }
    catch {
        Set-StatusText -Text 'Failed' -Color $theme.Danger
        $script:detailBox.Text = $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Run Failed', 'OK', 'Error') | Out-Null
    }
    finally {
        $script:form.UseWaitCursor = $false
    }
}

function Show-AssistantPlanPreview {
    param([string]$Instruction)
    if ([string]::IsNullOrWhiteSpace($Instruction)) {
        [System.Windows.Forms.MessageBox]::Show('Type a request before previewing the assistant plan.', 'Missing Request', 'OK', 'Warning') | Out-Null
        return
    }
    try {
        $payload = Get-AssistantPlanPayload -Instruction $Instruction
        Set-AssistantPlanState -Instruction $Instruction -Plan $payload.plan -ScreenContext $payload.screen_context
        $planText = Format-AssistantPlanText -Plan $payload.plan
        $script:detailBox.Text = $planText
        if ($payload.plan.commands.Count -eq 1) {
            Select-CommandByName -CommandName ([string]$payload.plan.commands[0].command_name)
        }
        if ($payload.plan.status -eq 'ready') {
            Set-StatusText -Text 'Plan Ready' -Color $theme.Success
        }
        elseif ($payload.plan.status -eq 'needs_confirmation') {
            Set-StatusText -Text 'Review Plan' -Color $theme.Warning
        }
        else {
            Set-StatusText -Text 'Need Input' -Color $theme.Warning
        }
    }
    catch {
        Clear-AssistantPlanState
        Set-StatusText -Text 'Plan Error' -Color $theme.Danger
        $script:detailBox.Text = $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Plan Error', 'OK', 'Error') | Out-Null
    }
}

function Invoke-RunInstruction {
    param([string]$Instruction)
    if ([string]::IsNullOrWhiteSpace($Instruction)) {
        [System.Windows.Forms.MessageBox]::Show('Enter a request or select a workflow before running.', 'Missing Request', 'OK', 'Warning') | Out-Null
        return
    }
    $baseArguments = @('run-instruction', '--instruction', $Instruction)
    if ($localModelCheckbox.Checked) {
        $baseArguments += '--local-model'
        if ($screenContextCheckbox.Checked) { $baseArguments += '--with-screen' }
    }
    if ($safeModeCheckbox.Checked) { $baseArguments += '--safe-mode' }
    if ($confirmRiskCheckbox.Checked) { $baseArguments += '--confirm-risky' }
    try {
        Set-StatusText -Text 'Running' -Color $theme.Warning
        $script:detailBox.Text = "Planning and running:`r`n$Instruction"
        $script:form.UseWaitCursor = $true
        [System.Windows.Forms.Application]::DoEvents()
        $payload = Invoke-BackendJson -Arguments $baseArguments
        Set-AssistantPlanState -Instruction $Instruction -Plan $payload.plan -ScreenContext $payload.screen_context
        if ($payload.outcome.status -eq 'needs_confirmation') {
            $message = (Format-AssistantPlanText -Plan $payload.plan) + "`r`n`r`nRun this reviewed plan?"
            $decision = [System.Windows.Forms.MessageBox]::Show($message, 'Confirm Assistant Plan', 'YesNo', 'Question')
            if ($decision -ne [System.Windows.Forms.DialogResult]::Yes) {
                Set-StatusText -Text 'Review Plan' -Color $theme.Warning
                $script:detailBox.Text = Format-AssistantPlanText -Plan $payload.plan
                return
            }
            $payload = Invoke-BackendJson -Arguments ($baseArguments + '--confirm-plan')
            Set-AssistantPlanState -Instruction $Instruction -Plan $payload.plan -ScreenContext $payload.screen_context
        }

        if ($payload.outcome.status -in @('needs_clarification', 'unmatched')) {
            Set-StatusText -Text 'Need Input' -Color $theme.Warning
            $script:detailBox.Text = Format-AssistantPlanText -Plan $payload.plan
            return
        }

        if ($payload.outcome.status -eq 'completed') {
            Set-StatusText -Text 'Completed' -Color $theme.Success
        }
        elseif ($payload.outcome.status -eq 'partial') {
            Set-StatusText -Text 'Partial' -Color $theme.Warning
        }
        else {
            Set-StatusText -Text 'Failed' -Color $theme.Danger
        }

        Load-Runs
        if ($payload.runs.Count -gt 0) {
            $latestRunId = [int]$payload.runs[-1].outcome.run_id
            Show-RunDetails -RunId $latestRunId
            $latestDetail = $script:detailBox.Text
            $script:detailBox.Text = (Format-AssistantPlanText -Plan $payload.plan) + "`r`n`r`nExecution:`r`nStatus: $($payload.outcome.status)`r`nCompleted: $($payload.outcome.summary.completed_commands) / $($payload.outcome.summary.total_commands)`r`n`r`nLatest run detail:`r`n$latestDetail"
        }
        else {
            $script:detailBox.Text = (Format-AssistantPlanText -Plan $payload.plan) + "`r`n`r`nExecution status: $($payload.outcome.status)"
        }
    }
    catch {
        Clear-AssistantPlanState
        Set-StatusText -Text 'Failed' -Color $theme.Danger
        $script:detailBox.Text = $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Run Failed', 'OK', 'Error') | Out-Null
    }
    finally {
        $script:form.UseWaitCursor = $false
    }
}

$quickButtonSpecs = @(
    @{ Text = 'Start Day'; CompactText = 'Start'; Command = 'mvp.start_day'; Input = 'start day'; Description = 'Create a daily note and open the workspace tools.' },
    @{ Text = 'Quick Note'; CompactText = 'Note'; Command = 'mvp.note'; Input = 'note '; Description = 'Write a quick note and open it in Notepad.' },
    @{ Text = 'Download Report'; CompactText = 'Report'; Command = 'mvp.download_report'; Input = 'download report'; Description = 'Download the daily report into exports.' },
    @{ Text = 'End Day'; CompactText = 'End'; Command = 'mvp.end_day'; Input = 'end day'; Description = 'Export a day summary and open it.' },
    @{ Text = 'Workspace'; CompactText = 'Workspace'; Command = 'workspace.open_all'; Input = 'workspace'; Description = 'Open the workspace page and exports folder.' },
    @{ Text = 'Paint Demo'; CompactText = 'Paint'; Command = 'desktop.demo_paint'; Input = 'paint'; Description = 'Launch Paint to test desktop automation.' }
)

 $quickButtonIndex = 0
foreach ($spec in $quickButtonSpecs) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = if ($script:isCompactLayout -and $spec.ContainsKey('CompactText')) { [string]$spec.CompactText } else { [string]$spec.Text }
    $button.Size = New-Object System.Drawing.Size($layout.QuickButtonWidth, $layout.QuickButtonHeight)
    $button.Margin = if ($script:isCompactLayout) { (New-Object System.Windows.Forms.Padding(0, 0, 6, 6)) } else { (New-Object System.Windows.Forms.Padding(0, 0, 0, 8)) }
    $button.Dock = 'Fill'
    Set-SecondaryButtonStyle -Button $button
    $button.Tag = $spec
    $button.Add_Click({
        $data = $this.Tag
        Select-CommandByName -CommandName ([string]$data.Command)
        $script:agentInputBox.Text = [string]$data.Input
        $script:detailBox.Text = [string]$data.Description
        if ([string]$data.Command -eq 'mvp.note' -and $script:parameterInputs.ContainsKey('note_text')) {
            $script:parameterInputs['note_text'].Focus()
        }
        else {
            $script:agentInputBox.Focus()
            $script:agentInputBox.SelectionStart = $script:agentInputBox.Text.Length
        }
    })
    if ($script:isCompactLayout) {
        $quickColumn = $quickButtonIndex % 2
        $quickRow = [int][Math]::Floor($quickButtonIndex / 2)
        [void]$quickButtonsHost.Controls.Add($button, $quickColumn, $quickRow)
    }
    else {
        [void]$quickButtonsHost.Controls.Add($button, 0, $quickButtonIndex)
    }
    $quickButtonIndex += 1
}

foreach ($spec in $quickButtonSpecs) {
    $chip = New-Object System.Windows.Forms.Button
    $chip.Text = [string]$spec.Text
    $chip.AutoSize = $true
    $chip.Padding = New-Object System.Windows.Forms.Padding($(if ($script:isCompactLayout) { 8 } else { 10 }), 6, $(if ($script:isCompactLayout) { 8 } else { 10 }), 6)
    Set-ChipButtonStyle -Button $chip
    $chip.Tag = $spec
    $chip.Add_Click({
        $data = $this.Tag
        $script:agentInputBox.Text = [string]$data.Input
        Select-CommandByName -CommandName ([string]$data.Command)
        $script:agentInputBox.Focus()
        $script:agentInputBox.SelectionStart = $script:agentInputBox.Text.Length
    })
    [void]$shortcutFlow.Controls.Add($chip)
}

$catalogSearchBox.Add_TextChanged({ Refresh-CommandCatalog })
$statusFilterBox.Add_SelectedIndexChanged({ Refresh-RunListView; Save-UiPreferences })
$runSearchBox.Add_TextChanged({ Refresh-RunListView })
$failureInboxButton.Add_Click({
    if ([string]$script:statusFilterBox.SelectedItem -eq 'Failed') {
        $script:statusFilterBox.SelectedItem = 'All'
    }
    else {
        $script:statusFilterBox.SelectedItem = 'Failed'
    }
    Refresh-RunListView
    Save-UiPreferences
})
$reviewQueueButton.Add_Click({
    Show-ReviewQueueDialog
    Load-Runs
})
$operatorDashboardButton.Add_Click({
    Show-OperatorDashboardDialog
    Load-Runs
})
$trainingModeButton.Add_Click({
    Start-Process powershell -ArgumentList @('-ExecutionPolicy', 'Bypass', '-File', $trainingScript) | Out-Null
    Set-StatusText -Text 'Training mode opened.' -Color $theme.Success
})
$artifactComboBox.Add_SelectedIndexChanged({
    $enabled = ($script:artifactComboBox.SelectedIndex -ge 0)
    $script:openArtifactButton.Enabled = $enabled
    $script:copyArtifactButton.Enabled = $enabled
})
$openArtifactButton.Add_Click({ Open-SelectedArtifact })
$copyArtifactButton.Add_Click({ Copy-SelectedArtifactPath })
$commandList.Add_SelectedIndexChanged({
    if ($commandList.SelectedIndex -lt 0) { return }
    $selected = $script:visibleCommands[$commandList.SelectedIndex]
    Render-SelectedCommand -Command $selected
    $script:detailBox.Text = "Command: $($selected.name)`r`nWorkflow: $($selected.workflow_id)`r`nRisk: $($selected.risk)`r`nDescription: $($selected.description)"
})
$runsList.Add_SelectedIndexChanged({ if ($runsList.SelectedItems.Count -gt 0) { Show-RunDetails -RunId ([int]$runsList.SelectedItems[0].Tag.id) } })
$refreshButton.Add_Click({ Load-Runs; Set-StatusText -Text 'Ready' -Color $theme.Success })
$runInputButton.Add_Click({
    try {
        $text = $script:agentInputBox.Text.Trim()
        if ([string]::IsNullOrWhiteSpace($text) -and $script:selectedCommand) {
            $text = Get-SelectedWorkflowCommand
            $script:agentInputBox.Text = $text
        }
        Invoke-RunInstruction -Instruction $text
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Input Error', 'OK', 'Warning') | Out-Null
    }
})
$runSelectedButton.Add_Click({
    try {
        $rawCommand = Get-SelectedWorkflowCommand
        $script:agentInputBox.Text = $rawCommand
        Invoke-RunWorkflow -RawCommand $rawCommand
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Workflow Error', 'OK', 'Warning') | Out-Null
    }
})
$resetDefaultsButton.Add_Click({ Reset-SelectedCommandInputs })
$usePreviewButton.Add_Click({
    $typedInput = $script:agentInputBox.Text.Trim()
    if (-not [string]::IsNullOrWhiteSpace($typedInput)) {
        Show-AssistantPlanPreview -Instruction $typedInput
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($script:previewBox.Text)) {
        $script:agentInputBox.Text = $script:previewBox.Text
        $script:agentInputBox.Focus()
        $script:agentInputBox.SelectionStart = $script:agentInputBox.Text.Length
    }
})
$approveTrainingButton.Add_Click({ Save-AssistantPlanFeedback })
$clearInputButton.Add_Click({ Clear-AssistantPlanState; $script:agentInputBox.Clear(); $script:agentInputBox.Focus() })
$agentInputBox.Add_TextChanged({
    if ($null -ne $script:lastAssistantPlan -and $script:agentInputBox.Text.Trim() -ne $script:lastAssistantInstruction.Trim()) {
        Clear-AssistantPlanState
    }
    else {
        Update-TrainingApprovalState
    }
})
$agentInputBox.Add_KeyDown({ if ($_.KeyCode -eq [System.Windows.Forms.Keys]::Enter) { $_.SuppressKeyPress = $true; $runInputButton.PerformClick() } })
$safeModeCheckbox.Add_CheckedChanged({ Update-ModeText; Save-UiPreferences })
$confirmRiskCheckbox.Add_CheckedChanged({ Update-ModeText; Save-UiPreferences })
$localModelCheckbox.Add_CheckedChanged({ Clear-AssistantPlanState; Update-LocalAgentOptions; Update-ModeText; Save-UiPreferences })
$screenContextCheckbox.Add_CheckedChanged({ Clear-AssistantPlanState; Update-ModeText; Save-UiPreferences })
$parameterFieldsHost.Add_Resize({ Update-ParameterFieldWidths })
$quickButtonsHost.Add_Resize({ Resize-QuickButtons })
$buttonFlow.Add_Resize({ Resize-CommandBarControls })
$runsList.Add_Resize({ Resize-RunColumns })
$logsList.Add_Resize({ Resize-LogColumns })
$form.Add_Resize({ Update-ResponsiveLayout; Resize-QuickButtons; Resize-CommandBarControls; Resize-RunColumns; Resize-LogColumns; Update-ParameterFieldWidths })
$form.Add_FormClosing({ Save-UiPreferences })
$form.Add_Shown({
    Apply-SplitterConstraints
    Update-ResponsiveLayout
    Update-LocalAgentOptions
    Resize-QuickButtons
    Resize-CommandBarControls
    Resize-RunColumns
    Resize-LogColumns
    Update-ParameterFieldWidths
    if ($script:isCompactLayout) {
        $commandFooter.Visible = $false
        $commandLayout.RowStyles[5].Height = 0
        $guidedActionsNote.Visible = $false
    }
})

$uiPreferences = Load-UiPreferences
Update-ModeText
Refresh-CommandCatalog
Load-Runs
Set-ArtifactControls -Artifacts @()
Apply-UiPreferences -Preferences $uiPreferences
if (-not $uiPreferences.ContainsKey('selected_command')) {
    Select-CommandByName -CommandName 'mvp.start_day'
}
$agentInputBox.Text = if ($uiPreferences.ContainsKey('last_input')) { [string]$uiPreferences['last_input'] } else { 'start day' }
$detailBox.Text = 'Type a natural request, use a quick action, or run a guided workflow. Every run appears below with full step history.'
Set-StatusText -Text 'Ready' -Color $theme.Success
Resize-RunColumns
Resize-LogColumns
Update-ParameterFieldWidths
[void]$form.ShowDialog()


