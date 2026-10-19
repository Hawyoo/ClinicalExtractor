Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"
function Convert-UnicodeText([int[]]$CodeUnits) {
    return -join ($CodeUnits | ForEach-Object { [char]$_ })
}
$root = Split-Path -Parent $PSCommandPath
$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
trap {
    $detail = "[$(Get-Date -Format s)] $($_.Exception.Message)`r`n$($_.ScriptStackTrace)`r`n"
    Add-Content -LiteralPath (Join-Path $logsDir "startup-error.log") -Value $detail -Encoding ASCII
    [System.Windows.Forms.MessageBox]::Show("Startup failed. See logs\\startup-error.log", "ClinicalExtractor")
    break
}
$exe = Join-Path $root "ClinicalExtractor.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    [System.Windows.Forms.MessageBox]::Show((Convert-UnicodeText @(0x672a,0x627e,0x5230,0x20,0x43,0x6c,0x69,0x6e,0x69,0x63,0x61,0x6c,0x45,0x78,0x74,0x72,0x61,0x63,0x74,0x6f,0x72,0x2e,0x65,0x78,0x65,0x3002)), "ClinicalExtractor")
    exit 1
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

$port = Get-FreePort
$url = "http://127.0.0.1:$port"
$form = [System.Windows.Forms.Form]::new()
$form.Text = Convert-UnicodeText @(0x4e34,0x5e8a,0x62a5,0x544a,0x63d0,0x53d6,0x5668)
$form.ClientSize = [System.Drawing.Size]::new(450, 190)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$iconPath = Join-Path $root "clinical-extractor.ico"
if (Test-Path -LiteralPath $iconPath) {
    $form.Icon = [System.Drawing.Icon]::new($iconPath)
}

$title = [System.Windows.Forms.Label]::new()
$title.Text = Convert-UnicodeText @(0x4e34,0x5e8a,0x62a5,0x544a,0x63d0,0x53d6,0x5668)
$title.Font = [System.Drawing.Font]::new("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
$title.Location = [System.Drawing.Point]::new(24, 22)
$title.AutoSize = $true
$form.Controls.Add($title)

$subtitle = [System.Windows.Forms.Label]::new()
$subtitle.Text = Convert-UnicodeText @(0x672c,0x5730,0x4e34,0x5e8a,0x62a5,0x544a,0x7ed3,0x6784,0x5316,0x63d0,0x53d6)
$subtitle.Font = [System.Drawing.Font]::new("Microsoft YaHei", 9)
$subtitle.Location = [System.Drawing.Point]::new(27, 55)
$subtitle.AutoSize = $true
$form.Controls.Add($subtitle)

$status = [System.Windows.Forms.Label]::new()
$status.Text = Convert-UnicodeText @(0x6b63,0x5728,0x542f,0x52a8,0x672c,0x5730,0x670d,0x52a1,0x2026)
$status.Font = [System.Drawing.Font]::new("Microsoft YaHei", 9)
$status.Location = [System.Drawing.Point]::new(27, 86)
$status.Size = [System.Drawing.Size]::new(390, 25)
$form.Controls.Add($status)

$progress = [System.Windows.Forms.ProgressBar]::new()
$progress.Style = "Marquee"
$progress.MarqueeAnimationSpeed = 25
$progress.Location = [System.Drawing.Point]::new(27, 116)
$progress.Size = [System.Drawing.Size]::new(390, 18)
$form.Controls.Add($progress)

$openButton = [System.Windows.Forms.Button]::new()
$openButton.Text = Convert-UnicodeText @(0x6253,0x5f00,0x6d4f,0x89c8,0x5668)
$openButton.Location = [System.Drawing.Point]::new(27, 146)
$openButton.Enabled = $false
$form.Controls.Add($openButton)
$closeButton = [System.Windows.Forms.Button]::new()
$closeButton.Text = Convert-UnicodeText @(0x9000,0x51fa,0x7a0b,0x5e8f)
$closeButton.Location = [System.Drawing.Point]::new(142, 146)
$closeButton.Enabled = $false
$form.Controls.Add($closeButton)

$info = [System.Diagnostics.ProcessStartInfo]::new()
$info.FileName = $exe
$info.Arguments = "--app-service --port $port"
$info.WorkingDirectory = $root
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$process = [System.Diagnostics.Process]::Start($info)

$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 350
$attempts = 0
$script:ready = $false
$timer.Add_Tick({
    if ($process.HasExited) {
        $timer.Stop()
        $form.Close()
        return
    }
    if ($script:ready) { return }
    $attempts++
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "$url/health"
        if ($response.StatusCode -eq 200) {
            $script:ready = $true
            $progress.Visible = $false
            $status.Text = Convert-UnicodeText @(0x670d,0x52a1,0x5df2,0x542f,0x52a8,0xff0c,0x53ef,0x5f00,0x59cb,0x4f7f,0x7528,0x3002)
            $openButton.Enabled = $true
            $closeButton.Enabled = $true
            Start-Process $url
        }
    } catch {
        if ($attempts -ge 45) {
            $timer.Stop()
            $progress.Visible = $false
            $status.Text = Convert-UnicodeText @(0x542f,0x52a8,0x5931,0x8d25,0xff0c,0x8bf7,0x67e5,0x770b,0x20,0x6c,0x6f,0x67,0x73,0x5c,0x6c,0x61,0x75,0x6e,0x63,0x68,0x65,0x72,0x2e,0x6c,0x6f,0x67)
            $closeButton.Enabled = $true
        }
    }
})
$openButton.Add_Click({ Start-Process $url })
$closeButton.Add_Click({ if (-not $process.HasExited) { $process.Kill() }; $form.Close() })
$form.Add_FormClosing({ if (-not $process.HasExited) { $process.Kill() } })
$timer.Start()
[void]$form.ShowDialog()
