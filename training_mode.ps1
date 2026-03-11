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

if (-not (Test-Path $python)) { throw "Portable Python runtime not found at $python" }
if (-not (Test-Path $backend)) { throw "Desktop backend not found at $backend" }

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

if ($SelfTest) {
    $templates = Invoke-BackendJson -Arguments @('training-list-templates')
    if ($null -eq $templates) { throw 'training backend unavailable.' }
    Write-Output 'training-mode-selftest-ok'
    exit 0
}

$theme = @{
    Window = [System.Drawing.Color]::FromArgb(244, 239, 231)
    Card = [System.Drawing.Color]::FromArgb(255, 252, 247)
    Accent = [System.Drawing.Color]::FromArgb(191, 108, 68)
    Border = [System.Drawing.Color]::FromArgb(221, 210, 197)
    Text = [System.Drawing.Color]::FromArgb(34, 35, 36)
    Muted = [System.Drawing.Color]::FromArgb(104, 97, 90)
}

$fonts = @{
    Title = New-Object System.Drawing.Font('Segoe UI Semibold', 15)
    Section = New-Object System.Drawing.Font('Segoe UI Semibold', 10.5)
    Body = New-Object System.Drawing.Font('Segoe UI', 9)
    Small = New-Object System.Drawing.Font('Segoe UI', 8)
    Mono = New-Object System.Drawing.Font('Consolas', 9)
}

function Set-CardStyle {
    param([System.Windows.Forms.Control]$Control)
    $Control.BackColor = $theme.Card
    $Control.Padding = New-Object System.Windows.Forms.Padding(12)
}

function Set-ButtonStyle {
    param([System.Windows.Forms.Button]$Button, [switch]$Primary)
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderColor = $theme.Border
    $Button.FlatAppearance.BorderSize = 1
    $Button.Font = $fonts.Body
    $Button.ForeColor = if ($Primary) { [System.Drawing.Color]::White } else { $theme.Text }
    $Button.BackColor = if ($Primary) { $theme.Accent } else { $theme.Card }
}

function Set-TextStyle {
    param([System.Windows.Forms.TextBox]$TextBox, [switch]$Mono)
    $TextBox.BorderStyle = 'FixedSingle'
    $TextBox.BackColor = [System.Drawing.Color]::White
    $TextBox.ForeColor = $theme.Text
    $TextBox.Font = if ($Mono) { $fonts.Mono } else { $fonts.Body }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Screen Training Mode'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(1220, 820)
$form.MinimumSize = New-Object System.Drawing.Size(1024, 720)
$form.BackColor = $theme.Window
$form.Font = $fonts.Body

$root = New-Object System.Windows.Forms.TableLayoutPanel
$root.Dock = 'Fill'
$root.ColumnCount = 1
$root.RowCount = 2
[void]$root.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 68)))
[void]$root.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$form.Controls.Add($root)

$header = New-Object System.Windows.Forms.Panel
$header.Dock = 'Fill'
$header.Padding = New-Object System.Windows.Forms.Padding(16, 14, 16, 10)
$header.BackColor = $theme.Window
[void]$root.Controls.Add($header, 0, 0)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Teach Desktop Screens'
$title.Font = $fonts.Title
$title.ForeColor = $theme.Text
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(0, 0)
[void]$header.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = 'Capture a screen, label important regions, save a reusable template, and test the current screen against taught templates.'
$subtitle.Font = $fonts.Small
$subtitle.ForeColor = $theme.Muted
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(2, 32)
[void]$header.Controls.Add($subtitle)

$mainSplit = New-Object System.Windows.Forms.SplitContainer
$mainSplit.Dock = 'Fill'
$mainSplit.SplitterDistance = 340
[void]$root.Controls.Add($mainSplit, 0, 1)

$leftCard = New-Object System.Windows.Forms.Panel
$leftCard.Dock = 'Fill'
Set-CardStyle -Control $leftCard
[void]$mainSplit.Panel1.Controls.Add($leftCard)

$leftLayout = New-Object System.Windows.Forms.TableLayoutPanel
$leftLayout.Dock = 'Fill'
$leftLayout.ColumnCount = 1
$leftLayout.RowCount = 4
[void]$leftLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 28)))
[void]$leftLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 34)))
[void]$leftLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$leftLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 160)))
[void]$leftCard.Controls.Add($leftLayout)

$templateHeader = New-Object System.Windows.Forms.Label
$templateHeader.Text = 'Saved Templates'
$templateHeader.Font = $fonts.Section
$templateHeader.ForeColor = $theme.Text
$templateHeader.AutoSize = $true
[void]$leftLayout.Controls.Add($templateHeader, 0, 0)

$appFilterBox = New-Object System.Windows.Forms.TextBox
$appFilterBox.Dock = 'Fill'
Set-TextStyle -TextBox $appFilterBox
[void]$leftLayout.Controls.Add($appFilterBox, 0, 1)

$templateList = New-Object System.Windows.Forms.ListView
$templateList.Dock = 'Fill'
$templateList.View = 'Details'
$templateList.FullRowSelect = $true
$templateList.GridLines = $true
$templateList.HideSelection = $false
$templateList.Font = $fonts.Body
[void]$templateList.Columns.Add('ID', 110)
[void]$templateList.Columns.Add('Screen', 170)
[void]$leftLayout.Controls.Add($templateList, 0, 2)

$analysisBox = New-Object System.Windows.Forms.TextBox
$analysisBox.Dock = 'Fill'
$analysisBox.Multiline = $true
$analysisBox.ReadOnly = $true
$analysisBox.ScrollBars = 'Vertical'
Set-TextStyle -TextBox $analysisBox -Mono
[void]$leftLayout.Controls.Add($analysisBox, 0, 3)

$rightCard = New-Object System.Windows.Forms.Panel
$rightCard.Dock = 'Fill'
Set-CardStyle -Control $rightCard
[void]$mainSplit.Panel2.Controls.Add($rightCard)

$rightLayout = New-Object System.Windows.Forms.TableLayoutPanel
$rightLayout.Dock = 'Fill'
$rightLayout.ColumnCount = 1
$rightLayout.RowCount = 5
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 88)))
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 250)))
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 130)))
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$rightLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 44)))
[void]$rightCard.Controls.Add($rightLayout)

$metaLayout = New-Object System.Windows.Forms.TableLayoutPanel
$metaLayout.Dock = 'Fill'
$metaLayout.ColumnCount = 4
$metaLayout.RowCount = 2
[void]$metaLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 25)))
[void]$metaLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 25)))
[void]$metaLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 25)))
[void]$metaLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 25)))
[void]$rightLayout.Controls.Add($metaLayout, 0, 0)

function New-LabeledBox {
    param([string]$LabelText)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Dock = 'Fill'
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $LabelText
    $label.Font = $fonts.Small
    $label.ForeColor = $theme.Muted
    $label.AutoSize = $true
    $label.Location = New-Object System.Drawing.Point(0, 0)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point(0, 18)
    $box.Width = 180
    Set-TextStyle -TextBox $box
    [void]$panel.Controls.Add($label)
    [void]$panel.Controls.Add($box)
    return [pscustomobject]@{ Panel = $panel; Box = $box }
}

$appNameControl = New-LabeledBox -LabelText 'App Name'
$appNameControl.Box.Text = 'voucher_app'
[void]$metaLayout.Controls.Add($appNameControl.Panel, 0, 0)

$screenNameControl = New-LabeledBox -LabelText 'Screen Name'
$screenNameControl.Box.Text = 'voucher_print_page'
[void]$metaLayout.Controls.Add($screenNameControl.Panel, 1, 0)

$windowTitleControl = New-LabeledBox -LabelText 'Expected Window Title'
[void]$metaLayout.Controls.Add($windowTitleControl.Panel, 2, 0)

$templateIdControl = New-LabeledBox -LabelText 'Template Id (optional)'
[void]$metaLayout.Controls.Add($templateIdControl.Panel, 3, 0)

$controlsControl = New-LabeledBox -LabelText 'Expected Controls (comma separated)'
[void]$metaLayout.Controls.Add($controlsControl.Panel, 0, 1)

$textsControl = New-LabeledBox -LabelText 'Expected Texts (comma separated)'
[void]$metaLayout.Controls.Add($textsControl.Panel, 1, 1)

$notesControl = New-LabeledBox -LabelText 'Notes'
[void]$metaLayout.Controls.Add($notesControl.Panel, 2, 1)

$capturePathControl = New-LabeledBox -LabelText 'Capture Path'
$capturePathControl.Box.ReadOnly = $true
$capturePathControl.Box.Width = 220
[void]$metaLayout.Controls.Add($capturePathControl.Panel, 3, 1)

$previewSplit = New-Object System.Windows.Forms.SplitContainer
$previewSplit.Dock = 'Fill'
$previewSplit.SplitterDistance = 520
[void]$rightLayout.Controls.Add($previewSplit, 0, 1)

$picturePanel = New-Object System.Windows.Forms.Panel
$picturePanel.Dock = 'Fill'
$picturePanel.BorderStyle = 'FixedSingle'
$picturePanel.BackColor = [System.Drawing.Color]::White
[void]$previewSplit.Panel1.Controls.Add($picturePanel)

$pictureBox = New-Object System.Windows.Forms.PictureBox
$pictureBox.Dock = 'Fill'
$pictureBox.SizeMode = 'Zoom'
[void]$picturePanel.Controls.Add($pictureBox)

$captureActions = New-Object System.Windows.Forms.FlowLayoutPanel
$captureActions.Dock = 'Fill'
$captureActions.FlowDirection = 'TopDown'
$captureActions.WrapContents = $false
[void]$previewSplit.Panel2.Controls.Add($captureActions)

$captureButton = New-Object System.Windows.Forms.Button
$captureButton.Text = 'Capture Screen'
$captureButton.Size = New-Object System.Drawing.Size(150, 32)
Set-ButtonStyle -Button $captureButton -Primary
[void]$captureActions.Controls.Add($captureButton)

$analyzeButton = New-Object System.Windows.Forms.Button
$analyzeButton.Text = 'Analyze Current Screen'
$analyzeButton.Size = New-Object System.Drawing.Size(150, 32)
Set-ButtonStyle -Button $analyzeButton
[void]$captureActions.Controls.Add($analyzeButton)

$cursorButton = New-Object System.Windows.Forms.Button
$cursorButton.Text = 'Use Cursor Pos'
$cursorButton.Size = New-Object System.Drawing.Size(150, 32)
Set-ButtonStyle -Button $cursorButton
[void]$captureActions.Controls.Add($cursorButton)

$regionHint = New-Object System.Windows.Forms.Label
$regionHint.Text = 'Tip: capture the screen first, move your mouse to the target area, then use cursor position as the top-left corner.'
$regionHint.Font = $fonts.Small
$regionHint.ForeColor = $theme.Muted
$regionHint.MaximumSize = New-Object System.Drawing.Size(180, 0)
$regionHint.AutoSize = $true
$regionHint.Margin = New-Object System.Windows.Forms.Padding(0, 8, 0, 0)
[void]$captureActions.Controls.Add($regionHint)

$regionEditor = New-Object System.Windows.Forms.TableLayoutPanel
$regionEditor.Dock = 'Fill'
$regionEditor.ColumnCount = 6
$regionEditor.RowCount = 2
[void]$regionEditor.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 40)))
[void]$regionEditor.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 40)))
[void]$rightLayout.Controls.Add($regionEditor, 0, 2)

$regionNameControl = New-LabeledBox -LabelText 'Region Label'
[void]$regionEditor.Controls.Add($regionNameControl.Panel, 0, 0)

$regionRoleControl = New-LabeledBox -LabelText 'Role'
$regionRoleControl.Box.Text = 'button'
[void]$regionEditor.Controls.Add($regionRoleControl.Panel, 1, 0)

$leftControl = New-LabeledBox -LabelText 'Left'
[void]$regionEditor.Controls.Add($leftControl.Panel, 2, 0)

$topControl = New-LabeledBox -LabelText 'Top'
[void]$regionEditor.Controls.Add($topControl.Panel, 3, 0)

$widthControl = New-LabeledBox -LabelText 'Width'
$widthControl.Box.Text = '120'
[void]$regionEditor.Controls.Add($widthControl.Panel, 4, 0)

$heightControl = New-LabeledBox -LabelText 'Height'
$heightControl.Box.Text = '36'
[void]$regionEditor.Controls.Add($heightControl.Panel, 5, 0)

$regionNotesControl = New-LabeledBox -LabelText 'Region Notes'
[void]$regionEditor.Controls.Add($regionNotesControl.Panel, 0, 1)

$addRegionButton = New-Object System.Windows.Forms.Button
$addRegionButton.Text = 'Add Region'
$addRegionButton.Size = New-Object System.Drawing.Size(108, 28)
Set-ButtonStyle -Button $addRegionButton -Primary
$addRegionButton.Margin = New-Object System.Windows.Forms.Padding(8, 18, 0, 0)
[void]$regionEditor.Controls.Add($addRegionButton, 4, 1)

$removeRegionButton = New-Object System.Windows.Forms.Button
$removeRegionButton.Text = 'Remove Region'
$removeRegionButton.Size = New-Object System.Drawing.Size(108, 28)
Set-ButtonStyle -Button $removeRegionButton
$removeRegionButton.Margin = New-Object System.Windows.Forms.Padding(8, 18, 0, 0)
[void]$regionEditor.Controls.Add($removeRegionButton, 5, 1)

$regionsList = New-Object System.Windows.Forms.ListView
$regionsList.Dock = 'Fill'
$regionsList.View = 'Details'
$regionsList.FullRowSelect = $true
$regionsList.GridLines = $true
$regionsList.HideSelection = $false
$regionsList.Font = $fonts.Body
[void]$regionsList.Columns.Add('Label', 150)
[void]$regionsList.Columns.Add('Role', 90)
[void]$regionsList.Columns.Add('Rect', 210)
[void]$regionsList.Columns.Add('Notes', 250)
[void]$rightLayout.Controls.Add($regionsList, 0, 3)

$footer = New-Object System.Windows.Forms.FlowLayoutPanel
$footer.Dock = 'Fill'
$footer.FlowDirection = 'LeftToRight'
$footer.WrapContents = $false
[void]$rightLayout.Controls.Add($footer, 0, 4)

$saveTemplateButton = New-Object System.Windows.Forms.Button
$saveTemplateButton.Text = 'Save Template'
$saveTemplateButton.Size = New-Object System.Drawing.Size(120, 30)
Set-ButtonStyle -Button $saveTemplateButton -Primary
[void]$footer.Controls.Add($saveTemplateButton)

$refreshTemplatesButton = New-Object System.Windows.Forms.Button
$refreshTemplatesButton.Text = 'Refresh Templates'
$refreshTemplatesButton.Size = New-Object System.Drawing.Size(130, 30)
Set-ButtonStyle -Button $refreshTemplatesButton
[void]$footer.Controls.Add($refreshTemplatesButton)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = 'Ready.'
$statusLabel.Font = $fonts.Small
$statusLabel.ForeColor = $theme.Muted
$statusLabel.AutoSize = $true
$statusLabel.Margin = New-Object System.Windows.Forms.Padding(14, 8, 0, 0)
[void]$footer.Controls.Add($statusLabel)

$script:regionItems = @()

function Split-CommaList {
    param([string]$Value)
    return @($Value.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Resize-TemplateColumns {
    $width = [Math]::Max(220, $templateList.ClientSize.Width - 6)
    $templateList.Columns[0].Width = 110
    $templateList.Columns[1].Width = [Math]::Max(100, $width - 110)
}

function Resize-RegionColumns {
    $width = [Math]::Max(520, $regionsList.ClientSize.Width - 6)
    $regionsList.Columns[0].Width = 140
    $regionsList.Columns[1].Width = 88
    $regionsList.Columns[2].Width = 200
    $regionsList.Columns[3].Width = [Math]::Max(120, $width - 140 - 88 - 200)
}

function Refresh-RegionList {
    $regionsList.Items.Clear()
    foreach ($region in $script:regionItems) {
        $row = New-Object System.Windows.Forms.ListViewItem([string]$region.label)
        [void]$row.SubItems.Add([string]$region.role)
        [void]$row.SubItems.Add("L=$($region.left) T=$($region.top) W=$($region.width) H=$($region.height)")
        [void]$row.SubItems.Add([string]$region.notes)
        $row.Tag = $region
        [void]$regionsList.Items.Add($row)
    }
    Resize-RegionColumns
}

function Set-PreviewImage {
    param([string]$PathValue)
    $capturePathControl.Box.Text = $PathValue
    if (-not [string]::IsNullOrWhiteSpace($PathValue) -and (Test-Path $PathValue)) {
        $pictureBox.ImageLocation = $PathValue
    }
    else {
        $pictureBox.Image = $null
        $pictureBox.ImageLocation = $null
    }
}

function Load-TemplateList {
    $selectedId = if ($templateList.SelectedItems.Count -gt 0) { [string]$templateList.SelectedItems[0].Tag.template_id } else { '' }
    $payload = Invoke-BackendJson -Arguments @('training-list-templates', '--app-name', $appFilterBox.Text.Trim())
    $templateList.Items.Clear()
    foreach ($template in $payload.templates) {
        $row = New-Object System.Windows.Forms.ListViewItem([string]$template.template_id)
        [void]$row.SubItems.Add([string]$template.screen_name)
        $row.Tag = $template
        [void]$templateList.Items.Add($row)
    }
    Resize-TemplateColumns
    if (-not [string]::IsNullOrWhiteSpace($selectedId)) {
        foreach ($row in $templateList.Items) {
            if ([string]$row.Tag.template_id -eq $selectedId) { $row.Selected = $true; break }
        }
    }
}

function Load-TemplateIntoEditor {
    param([object]$Template)
    if ($null -eq $Template) { return }
    $templateIdControl.Box.Text = [string]$Template.template_id
    $appNameControl.Box.Text = [string]$Template.app_name
    $screenNameControl.Box.Text = [string]$Template.screen_name
    $windowTitleControl.Box.Text = [string]$Template.window_title
    $controlsControl.Box.Text = ([string[]]$Template.expected_controls) -join ', '
    $textsControl.Box.Text = ([string[]]$Template.expected_texts) -join ', '
    $notesControl.Box.Text = [string]$Template.notes
    $script:regionItems = @($Template.regions)
    Refresh-RegionList
    Set-PreviewImage -PathValue ([string]$Template.capture_path)
    $statusLabel.Text = "Loaded template $($Template.template_id)."
}

$templateList.Add_SelectedIndexChanged({
    if ($templateList.SelectedItems.Count -le 0) { return }
    Load-TemplateIntoEditor -Template $templateList.SelectedItems[0].Tag
})
$templateList.Add_Resize({ Resize-TemplateColumns })
$regionsList.Add_Resize({ Resize-RegionColumns })
$appFilterBox.Add_TextChanged({ Load-TemplateList })

$captureButton.Add_Click({
    try {
        $payload = Invoke-BackendJson -Arguments @(
            'training-capture-screen',
            '--app-name', $appNameControl.Box.Text.Trim(),
            '--screen-name', $screenNameControl.Box.Text.Trim()
        )
        Set-PreviewImage -PathValue ([string]$payload.capture.path)
        $statusLabel.Text = [string]$payload.capture.message
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Capture Error', 'OK', 'Error') | Out-Null
    }
})

$analyzeButton.Add_Click({
    try {
        $payload = Invoke-BackendJson -Arguments @('training-analyze-screen', '--app-name', $appNameControl.Box.Text.Trim())
        $analysis = $payload.analysis
        $lines = @(
            "Status: $($analysis.status)"
            "Active window: $($analysis.snapshot.active_window)"
        )
        if ($null -ne $analysis.best_match) {
            $lines += "Best match: $($analysis.best_match.template_id)"
            $lines += "Confidence: $($analysis.best_match.confidence)"
            foreach ($reason in $analysis.best_match.reasons) { $lines += "- $reason" }
        }
        $analysisBox.Text = $lines -join "`r`n"
        $statusLabel.Text = "Analyzed current screen."
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Analyze Error', 'OK', 'Error') | Out-Null
    }
})

$cursorButton.Add_Click({
    $cursor = [System.Windows.Forms.Cursor]::Position
    $leftControl.Box.Text = [string]$cursor.X
    $topControl.Box.Text = [string]$cursor.Y
    $statusLabel.Text = "Loaded cursor position $($cursor.X), $($cursor.Y)."
})

$addRegionButton.Add_Click({
    try {
        $region = [pscustomobject]@{
            label = $regionNameControl.Box.Text.Trim()
            role = $regionRoleControl.Box.Text.Trim()
            left = [int]$leftControl.Box.Text.Trim()
            top = [int]$topControl.Box.Text.Trim()
            width = [int]$widthControl.Box.Text.Trim()
            height = [int]$heightControl.Box.Text.Trim()
            notes = $regionNotesControl.Box.Text.Trim()
        }
        if ([string]::IsNullOrWhiteSpace([string]$region.label)) { throw 'Region label is required.' }
        $script:regionItems += $region
        Refresh-RegionList
        $statusLabel.Text = "Added region $($region.label)."
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Region Error', 'OK', 'Warning') | Out-Null
    }
})

$removeRegionButton.Add_Click({
    if ($regionsList.SelectedItems.Count -le 0) { return }
    $selected = $regionsList.SelectedItems[0].Tag
    $script:regionItems = @($script:regionItems | Where-Object { $_ -ne $selected })
    Refresh-RegionList
    $statusLabel.Text = 'Removed selected region.'
})

$saveTemplateButton.Add_Click({
    try {
        $appName = $appNameControl.Box.Text.Trim()
        $screenName = $screenNameControl.Box.Text.Trim()
        if ([string]::IsNullOrWhiteSpace($appName) -or [string]::IsNullOrWhiteSpace($screenName)) {
            throw 'App name and screen name are required.'
        }
        $regionsJson = @($script:regionItems) | ConvertTo-Json -Depth 6 -Compress
        $controlsJson = (Split-CommaList -Value $controlsControl.Box.Text.Trim()) | ConvertTo-Json -Compress
        $textsJson = (Split-CommaList -Value $textsControl.Box.Text.Trim()) | ConvertTo-Json -Compress
        $payload = Invoke-BackendJson -Arguments @(
            'training-save-template',
            '--template-id', $templateIdControl.Box.Text.Trim(),
            '--app-name', $appName,
            '--screen-name', $screenName,
            '--window-title', $windowTitleControl.Box.Text.Trim(),
            '--capture-path', $capturePathControl.Box.Text.Trim(),
            '--regions-json', $regionsJson,
            '--expected-controls-json', $controlsJson,
            '--expected-texts-json', $textsJson,
            '--notes', $notesControl.Box.Text.Trim()
        )
        $templateIdControl.Box.Text = [string]$payload.template.template_id
        Load-TemplateList
        $statusLabel.Text = "Saved template $($payload.template.template_id)."
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Save Error', 'OK', 'Error') | Out-Null
    }
})

$refreshTemplatesButton.Add_Click({ Load-TemplateList })

Load-TemplateList
Resize-TemplateColumns
Resize-RegionColumns
[void]$form.ShowDialog()
