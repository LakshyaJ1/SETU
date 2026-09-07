$SetuAdb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
$SetuSerial = 'emulator-5554'
$SetuEvidence = Join-Path (Split-Path -Parent $PSScriptRoot) 'docs\verification\android\manual'

function Get-SetuUi {
    $dump = ''
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $dump = (& $SetuAdb -s $SetuSerial shell uiautomator dump /sdcard/setu-ui.xml 2>&1) -join "`n"
        if ($LASTEXITCODE -eq 0 -and $dump -match 'dumped to') { break }
        Start-Sleep -Seconds 2
    }
    if ($dump -notmatch 'dumped to') { throw "Could not read the current emulator interface: $dump" }
    $document = [xml]((& $SetuAdb -s $SetuSerial exec-out cat /sdcard/setu-ui.xml) -join "`n")
    $document.SelectNodes('//node')
}

function Touch-Setu {
    param([string]$Text, [string]$Description)
    $nodes = @(Get-SetuUi | Where-Object { ($Text -and $_.text -eq $Text) -or ($Description -and $_.'content-desc' -eq $Description) })
    if ($nodes.Count -ne 1) { throw "Expected one control, found $($nodes.Count): $Text $Description" }
    $coordinates = [regex]::Matches($nodes[0].bounds, '\d+') | ForEach-Object { [int]$_.Value }
    $horizontal = [int](($coordinates[0] + $coordinates[2]) / 2)
    $vertical = [int](($coordinates[1] + $coordinates[3]) / 2)
    & $SetuAdb -s $SetuSerial shell input tap $horizontal $vertical
    Start-Sleep -Milliseconds 500
}

function Save-SetuScreenshot {
    param([Parameter(Mandatory = $true)][string]$Name)
    if ($Name -notmatch '^[a-zA-Z0-9-]+$') { throw 'Use a plain screenshot name.' }
    New-Item -ItemType Directory -Path $SetuEvidence -Force | Out-Null
    $destination = Join-Path $SetuEvidence "$Name.png"
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        & $SetuAdb -s $SetuSerial shell screencap -p "/sdcard/setu-$Name.png"
        if ($LASTEXITCODE -eq 0) {
            & $SetuAdb -s $SetuSerial pull "/sdcard/setu-$Name.png" $destination
            if ($LASTEXITCODE -eq 0 -and (Get-Item -LiteralPath $destination).Length -gt 0) {
                $package = ((& $SetuAdb -s $SetuSerial shell pm path com.setu.navigator) | Select-Object -First 1) -replace '^package:', ''
                $packageHash = ((& $SetuAdb -s $SetuSerial shell sha256sum $package) -split '\s+')[0]
                if ($packageHash -notmatch '^[a-f0-9]{64}$') { throw 'Could not verify the installed screenshot build.' }
                $metadata = @{
                    capture = "$Name.png"
                    apkSha256 = $packageHash
                    screenshotSha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
                    deviceClockSeconds = [long](& $SetuAdb -s $SetuSerial shell date +%s)
                    fontScale = [double](& $SetuAdb -s $SetuSerial shell settings get system font_scale)
                    rotationSetting = ((& $SetuAdb -s $SetuSerial shell wm user-rotation) -join '').Trim()
                    sdk = [int](& $SetuAdb -s $SetuSerial shell getprop ro.build.version.sdk)
                    source = 'adb shell screencap; unaltered PNG'
                }
                [IO.File]::WriteAllText((Join-Path $SetuEvidence "$Name.json"), ($metadata | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
                Write-Output $destination
                return
            }
        }
        Start-Sleep -Seconds 2
    }
    throw 'Screenshot capture or transfer failed after three attempts.'
}
