# Pester 5 tests for the collector's functions. Run on Windows:
#   Invoke-Pester collector/tests
# They need no admin rights, no PresentMon and no LibreHardwareMonitor.

BeforeAll {
    Import-Module (Join-Path $PSScriptRoot '..\PCDoctorCollector.psm1') -Force -DisableNameChecking

    function New-Sensor([string]$Id, [string]$Type, [string]$Text, $Value) {
        [pscustomobject]@{ SensorId = $Id; Type = $Type; Text = $Text; Value = $Value }
    }
}

Describe 'Protect-PCDoctorText' {
    It 'removes user folders, serial numbers and the computer name' {
        $text = "Dump at C:\Users\Alice\AppData\x.dmp, device serial number: ABC123XYZ on $env:COMPUTERNAME"
        $clean = Protect-PCDoctorText -Text $text
        $clean | Should -Not -Match 'Alice'
        $clean | Should -Not -Match 'ABC123XYZ'
        $clean | Should -Not -Match ([regex]::Escape($env:COMPUTERNAME))
        $clean | Should -Match 'C:\\Users\\<user>'
    }
    It 'caps the length and survives empty input' {
        (Protect-PCDoctorText -Text ('x' * 5000)).Length | Should -Be 600
        Protect-PCDoctorText -Text $null | Should -Be ''
    }
    It 'leaves hardware text alone' {
        $text = 'A fatal hardware error has occurred. Reported by component: Processor Core'
        Protect-PCDoctorText -Text $text | Should -Be $text
    }
}

Describe 'Test-PCDoctorUnderLoad' {
    It 'calls a desktop with nothing running idle' {
        $verdict = Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = 3; cpu_load_pct = 6 }, @{ gpu_load_pct = 2; cpu_load_pct = 9 }, @{ gpu_load_pct = 4; cpu_load_pct = 5 })
        $verdict.busy | Should -BeFalse
        $verdict.gpu_load_pct | Should -Be 3
        $verdict.cpu_load_pct | Should -Be 6
        Format-PCDoctorLoad $verdict | Should -Be 'GPU 3%, CPU 6%'
    }
    It 'counts a game (GPU) and a CPU stress test (CPU only) as load' {
        (Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = 97; cpu_load_pct = 20 })).busy | Should -BeTrue
        (Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = 1; cpu_load_pct = 100 })).busy | Should -BeTrue
    }
    It 'is not started by one busy second' {
        (Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = 2 }, @{ gpu_load_pct = 90 }, @{ gpu_load_pct = 3 })).busy | Should -BeFalse
    }
    It 'takes the middle of an even number of readings' {
        (Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = 20 }, @{ gpu_load_pct = 50 })).gpu_load_pct | Should -Be 35
    }
    It 'says nothing when the PC gave no load reading' {
        $verdict = Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = $null; cpu_load_pct = $null }, $null)
        $verdict.busy | Should -BeNullOrEmpty
        $verdict.busy -eq $false | Should -BeFalse
        Format-PCDoctorLoad $verdict | Should -Be ''
        (Test-PCDoctorUnderLoad -Samples @()).busy | Should -BeNullOrEmpty
    }
    It 'judges on the reading it has when the other is missing' {
        (Test-PCDoctorUnderLoad -Samples @(@{ gpu_load_pct = $null; cpu_load_pct = 8 })).busy | Should -BeFalse
    }
}

Describe 'ConvertTo-PCDoctorNumber' {
    It 'reads numbers, formatted values and decimal commas' {
        ConvertTo-PCDoctorNumber 45.5 | Should -Be 45.5
        ConvertTo-PCDoctorNumber '45.0 C' | Should -Be 45
        ConvertTo-PCDoctorNumber '45,5 %' | Should -Be 45.5
        ConvertTo-PCDoctorNumber '[N/A]' | Should -BeNullOrEmpty
        ConvertTo-PCDoctorNumber $null | Should -BeNullOrEmpty
    }
    It 'brings data sizes to megabytes so two of them compare' {
        ConvertTo-PCDoctorNumber '8.0 GB' | Should -Be 8192
        ConvertTo-PCDoctorNumber '512.0 MB' | Should -Be 512
    }
}

Describe 'ConvertTo-PCDoctorIsoTime' {
    It 'writes UTC with a Z' {
        $time = [datetime]::new(2026, 11, 1, 18, 0, 0, [DateTimeKind]::Utc)
        ConvertTo-PCDoctorIsoTime $time | Should -Be '2026-11-01T18:00:00Z'
        ConvertTo-PCDoctorIsoTime $null | Should -BeNullOrEmpty
    }
}

Describe 'Disk and memory module entries' {
    It 'reads the Windows disk number from DeviceId' {
        ConvertTo-PCDoctorDiskNumber '3' | Should -Be 3
        ConvertTo-PCDoctorDiskNumber '3' | Should -BeOfType [int]
        ConvertTo-PCDoctorDiskNumber 0 | Should -Be 0
        ConvertTo-PCDoctorDiskNumber '' | Should -BeNullOrEmpty
        ConvertTo-PCDoctorDiskNumber 'abc' | Should -BeNullOrEmpty
        ConvertTo-PCDoctorDiskNumber '-1' | Should -BeNullOrEmpty
        ConvertTo-PCDoctorDiskNumber $null | Should -BeNullOrEmpty
    }

    It 'builds a physical disk entry with its number last' {
        $fake = [pscustomobject]@{
            FriendlyName = ' Samsung SSD 980 PRO 2TB '; MediaType = 'SSD'; BusType = 'NVMe'
            HealthStatus = 'Healthy'; OperationalStatus = @('OK'); Size = 2000398934016
            FirmwareVersion = '5B2QGXA7'; DeviceId = '3'; SerialNumber = 'FAKE-DISK-SERIAL-0000'
        }
        $entry = ConvertTo-PCDoctorPhysicalDisk -Disk $fake -Reliability $null
        @($entry.Keys) | Should -Be @('name', 'media_type', 'bus_type', 'health_status', 'operational_status', 'size_bytes', 'firmware', 'reliability', 'number')
        $entry['name'] | Should -Be 'Samsung SSD 980 PRO 2TB'
        $entry['number'] | Should -Be 3
        (ConvertTo-Json -InputObject $entry -Depth 8) | Should -Not -Match 'FAKE-DISK-SERIAL-0000'
        $fake.DeviceId = ''
        (ConvertTo-PCDoctorPhysicalDisk -Disk $fake -Reliability $null)['number'] | Should -BeNullOrEmpty
        $fake.DeviceId = 'abc'
        (ConvertTo-PCDoctorPhysicalDisk -Disk $fake -Reliability $null)['number'] | Should -BeNullOrEmpty
    }

    It 'builds a memory module entry with its bank label last' {
        $fake = [pscustomobject]@{
            DeviceLocator = 'DIMM 1'; BankLabel = '  P0 CHANNEL A '; Capacity = 17179869184
            Speed = 4800; ConfiguredClockSpeed = 6000; Manufacturer = 'Kingston'; PartNumber = 'KF560C36-16 '
            SMBIOSMemoryType = 34; FormFactor = 8; SerialNumber = 'FAKE-RAM-SERIAL-0000'
        }
        $entry = ConvertTo-PCDoctorMemoryModule -Module $fake
        @($entry.Keys) | Should -Be @('slot', 'capacity_bytes', 'speed_mhz', 'configured_speed_mhz', 'manufacturer', 'part_number', 'type', 'form_factor', 'bank')
        $entry['slot'] | Should -Be 'DIMM 1'
        $entry['bank'] | Should -Be 'P0 CHANNEL A'
        $entry['capacity_bytes'] | Should -Be 17179869184
        $entry['form_factor'] | Should -Be 'DIMM'
        (ConvertTo-Json -InputObject $entry -Depth 8) | Should -Not -Match 'FAKE-RAM-SERIAL-0000'
        $fake.BankLabel = ''
        (ConvertTo-PCDoctorMemoryModule -Module $fake)['bank'] | Should -BeNullOrEmpty
        $fake.BankLabel = $null
        (ConvertTo-PCDoctorMemoryModule -Module $fake)['bank'] | Should -BeNullOrEmpty
        $fake.BankLabel = 'B' * 60
        (ConvertTo-PCDoctorMemoryModule -Module $fake)['bank'] | Should -Be ('B' * 40)
    }
}

Describe 'LibreHardwareMonitor mapping' {
    BeforeAll {
        # Names as LibreHardwareMonitor's source defines them.
        $script:Intel = @(
            New-Sensor '/intelcpu/0/temperature/8' 'Temperature' 'CPU Package' 71.0
            New-Sensor '/intelcpu/0/temperature/0' 'Temperature' 'P-Core #1' 69.0
            New-Sensor '/intelcpu/0/temperature/9' 'Temperature' 'P-Core #1 Distance to TjMax' 31.0
            New-Sensor '/intelcpu/0/load/0' 'Load' 'CPU Total' 42.0
            New-Sensor '/intelcpu/0/load/1' 'Load' 'CPU Core Max' 97.0
            New-Sensor '/intelcpu/0/clock/0' 'Clock' 'Bus Speed' 100.0
            New-Sensor '/intelcpu/0/clock/1' 'Clock' 'P-Core #1' 5000.0
            New-Sensor '/intelcpu/0/clock/2' 'Clock' 'E-Core #1' 4000.0
            New-Sensor '/intelcpu/0/power/0' 'Power' 'CPU Package' 120.5
            New-Sensor '/gpu-intel-integrated/0/load/0' 'Load' 'GPU Core' 3.0
            New-Sensor '/gpu-nvidia/0/temperature/0' 'Temperature' 'GPU Core' 66.0
            New-Sensor '/gpu-nvidia/0/temperature/2' 'Temperature' 'GPU Hot Spot' 78.0
            New-Sensor '/gpu-nvidia/0/load/0' 'Load' 'GPU Core' 98.0
            New-Sensor '/gpu-nvidia/0/clock/0' 'Clock' 'GPU Core' 1905.0
            New-Sensor '/gpu-nvidia/0/power/0' 'Power' 'GPU Package' 210.0
            New-Sensor '/gpu-nvidia/0/fan/1' 'Fan' 'GPU Fan' 1500.0
            New-Sensor '/gpu-nvidia/0/smalldata/1' 'SmallData' 'GPU Memory Used' 6144.0
            New-Sensor '/gpu-nvidia/0/smalldata/2' 'SmallData' 'GPU Memory Total' 8192.0
            New-Sensor '/ram/load/0' 'Load' 'Memory' 55.0
            New-Sensor '/vram/load/1' 'Load' 'Memory' 12.0
        )
    }

    It 'maps an Intel CPU and an NVIDIA card' {
        $sample = ConvertTo-PCDoctorSample -Sensors $script:Intel
        $sample['cpu_temp_c'] | Should -Be 71
        $sample['cpu_load_pct'] | Should -Be 42
        $sample['cpu_core_max_load_pct'] | Should -Be 97
        $sample['cpu_clock_mhz'] | Should -Be 4500     # average of the cores, not the bus speed
        $sample['cpu_power_w'] | Should -Be 120.5
        $sample['gpu_temp_c'] | Should -Be 66
        $sample['gpu_hotspot_c'] | Should -Be 78
        $sample['gpu_load_pct'] | Should -Be 98        # the graphics card, not the integrated GPU
        $sample['gpu_clock_mhz'] | Should -Be 1905
        $sample['gpu_power_w'] | Should -Be 210
        $sample['gpu_fan_rpm'] | Should -Be 1500
        $sample['gpu_vram_used_pct'] | Should -Be 75
        $sample['ram_used_pct'] | Should -Be 55        # physical memory, not virtual
    }

    It 'maps an AMD CPU and falls back when a named sensor is missing' {
        $amd = @(
            New-Sensor '/amdcpu/0/temperature/2' 'Temperature' 'Core (Tctl/Tdie)' 88.5
            New-Sensor '/amdcpu/0/clock/1' 'Clock' 'Cores (Average)' 4650.0
            New-Sensor '/amdcpu/0/clock/3' 'Clock' 'Core #1' 4700.0
            New-Sensor '/amdcpu/0/power/0' 'Power' 'Package' 95.0
            New-Sensor '/amdcpu/0/load/2' 'Load' 'CPU Core #1' 60.0
            New-Sensor '/amdcpu/0/load/3' 'Load' 'CPU Core #2' 91.0
            New-Sensor '/gpu-amd/0/load/0' 'Load' 'GPU Core' 77.0
            New-Sensor '/gpu-amd/0/load/1' 'Load' 'GPU Memory' 64.0
        )
        $sample = ConvertTo-PCDoctorSample -Sensors $amd
        $sample['cpu_temp_c'] | Should -Be 88.5
        $sample['cpu_clock_mhz'] | Should -Be 4650
        $sample['cpu_power_w'] | Should -Be 95
        $sample['cpu_core_max_load_pct'] | Should -Be 91   # no "CPU Core Max": the busiest core
        $sample['cpu_load_pct'] | Should -BeNullOrEmpty
        $sample['gpu_load_pct'] | Should -Be 77
        $sample['gpu_vram_used_pct'] | Should -Be 64       # no used/total: the load sensor
    }

    It 'prefers a graphics card over integrated graphics and keeps to the chosen one' {
        Select-PCDoctorGpuPrefix $script:Intel | Should -Be '/gpu-nvidia/0'
        $sample = ConvertTo-PCDoctorSample -Sensors $script:Intel -GpuPrefix '/gpu-intel-integrated/0'
        $sample['gpu_load_pct'] | Should -Be 3
        Select-PCDoctorGpuPrefix @(New-Sensor '/ram/load/0' 'Load' 'Memory' 1.0) | Should -BeNullOrEmpty
    }

    It 'returns every column, empty, when there are no sensors' {
        $sample = ConvertTo-PCDoctorSample -Sensors @()
        $sample.Keys.Count | Should -Be (Get-PCDoctorSensorColumns).Count
        @($sample.Values | Where-Object { $null -ne $_ }).Count | Should -Be 0
    }

    It 'flattens the data.json tree, using RawValue and falling back to Value' {
        $tree = [pscustomobject]@{
            Text = 'Sensor'; Children = @(
                [pscustomobject]@{
                    Text = 'PC'; Children = @(
                        [pscustomobject]@{
                            Text = 'CPU'; HardwareId = '/intelcpu/0'; Children = @(
                                [pscustomobject]@{ Text = 'CPU Package'; SensorId = '/intelcpu/0/temperature/8'; Type = 'Temperature'; Value = '70,0 C'; RawValue = 71.5; Children = @() }
                                [pscustomobject]@{ Text = 'CPU Total'; SensorId = '/intelcpu/0/load/0'; Type = 'Load'; Value = '42,5 %'; Children = @() }
                            )
                        }
                    )
                }
            )
        }
        $sensors = ConvertFrom-PCDoctorLhmTree $tree
        $sensors.Count | Should -Be 2
        ($sensors | Where-Object Text -eq 'CPU Package').Value | Should -Be 71.5
        ($sensors | Where-Object Text -eq 'CPU Total').Value | Should -Be 42.5
    }
}

Describe 'sensors.csv rows' {
    It 'uses the fixed column order and a dot for decimals' {
        $sample = @{}
        foreach ($column in (Get-PCDoctorSensorColumns)) { $sample[$column] = $null }
        $sample['cpu_temp_c'] = 71.456
        $sample['ram_used_pct'] = 55
        $row = Format-PCDoctorSensorRow -ElapsedSeconds 2.5 -Sample $sample
        $row | Should -Be '2.50,71.46,,,,,,,,,,,,,55'
        (Get-PCDoctorSensorHeader).Split(',').Count | Should -Be $row.Split(',').Count
        (Get-PCDoctorSensorHeader) | Should -Match '^elapsed_s,cpu_temp_c,'
    }
}

Describe 'Select-PCDoctorPresentMonRows' {
    BeforeAll {
        $script:Csv = Join-Path $TestDrive 'raw.csv'
        $lines = @('Application,ProcessID,SwapChainAddress,TimeInSeconds,MsBetweenPresents')
        1..40 | ForEach-Object { $lines += "dwm.exe,10,0xA,$_,16.6" }
        1..25 | ForEach-Object { $lines += "Game.exe,20,0xB,$_,7.1" }
        1..5 | ForEach-Object { $lines += "chrome.exe,30,0xC,$_,16.6" }
        Set-Content -LiteralPath $script:Csv -Value $lines -Encoding ASCII
    }

    It 'keeps only the busiest program that is not the Windows shell' {
        $out = Join-Path $TestDrive 'kept.csv'
        $result = Select-PCDoctorPresentMonRows -Path $script:Csv -Destination $out
        $result.application | Should -Be 'Game.exe'
        $result.frames | Should -Be 25
        $result.other_processes_removed | Should -Be 2
        $kept = Get-Content -LiteralPath $out
        $kept.Count | Should -Be 26
        $kept[0] | Should -Match '^Application,'
        ($kept -join "`n") | Should -Not -Match 'chrome|dwm'
    }

    It 'keeps the named process when one is given' {
        $out = Join-Path $TestDrive 'named.csv'
        $result = Select-PCDoctorPresentMonRows -Path $script:Csv -Destination $out -Process 'chrome'
        $result.application | Should -Be 'chrome.exe'
        (Get-Content -LiteralPath $out).Count | Should -Be 6
    }

    It 'reports nothing kept for a header-only file' {
        $empty = Join-Path $TestDrive 'empty.csv'
        Set-Content -LiteralPath $empty -Value 'Application,ProcessID,MsBetweenPresents' -Encoding ASCII
        $result = Select-PCDoctorPresentMonRows -Path $empty -Destination (Join-Path $TestDrive 'none.csv')
        $result.frames | Should -Be 0
    }
}

Describe 'PresentMon arguments' {
    It 'uses the flags that were verified against PresentMon 2.6.0' {
        $arguments = Get-PCDoctorPresentMonArguments -OutputFile 'C:\runs\my run\pm.csv' -Seconds 300 -Process 'game.exe'
        ($arguments -join ' ') | Should -Be '--output_file "C:\runs\my run\pm.csv" --timed 300 --terminate_after_timed --no_console_stats --stop_existing_session --session_name PCDoctor --process_name "game.exe"'
        (Get-PCDoctorPresentMonArguments -OutputFile 'x.csv' -Seconds 5) -join ' ' | Should -Not -Match 'process_name'
    }
}

Describe 'Only signed tools are run' {
    It 'checks a real signature and its publisher' {
        $notepad = Join-Path $env:SystemRoot 'System32\notepad.exe'
        Test-PCDoctorSignedBy -Path $notepad -Publisher 'Microsoft Corporation' | Should -BeTrue
        Test-PCDoctorSignedBy -Path $notepad -Publisher 'Intel Corporation' | Should -BeFalse
    }

    It 'refuses an unsigned file and a missing one' {
        $fake = Join-Path $TestDrive 'PresentMon-9.9.9-x64.exe'
        Set-Content -LiteralPath $fake -Value 'not a program'
        Test-PCDoctorSignedBy -Path $fake -Publisher 'Intel Corporation' | Should -BeFalse
        Test-PCDoctorSignedBy -Path (Join-Path $TestDrive 'missing.exe') -Publisher 'Intel Corporation' | Should -BeFalse
    }

    It 'does not run a PresentMon that fails the check, and says why' {
        $tools = Join-Path $TestDrive 'tools-unsigned'
        New-Item -ItemType Directory -Path $tools | Out-Null
        Set-Content -LiteralPath (Join-Path $tools 'PresentMon-2.6.0-x64.exe') -Value 'swapped'
        $found = Find-PCDoctorPresentMon -ToolsDir $tools
        $found.Path | Should -BeNullOrEmpty
        $found.Problem | Should -Match 'Intel signature'
    }

    It 'takes the first PresentMon that passes, even if another sorts higher' {
        $tools = Join-Path $TestDrive 'tools-mixed'
        New-Item -ItemType Directory -Path $tools | Out-Null
        Set-Content -LiteralPath (Join-Path $tools 'PresentMon-2.6.0-x64.exe') -Value 'good'
        Set-Content -LiteralPath (Join-Path $tools 'PresentMon-9.9.9-x64.exe') -Value 'planted'
        $found = Find-PCDoctorPresentMon -ToolsDir $tools -IsTrusted { param($file) $file -like '*2.6.0*' }
        $found.Path | Should -BeLike '*PresentMon-2.6.0-x64.exe'
        $found.Problem | Should -BeNullOrEmpty
    }

    It 'looks on the PATH only when not elevated' {
        $folder = Join-Path $TestDrive 'on-path'
        New-Item -ItemType Directory -Path $folder | Out-Null
        Set-Content -LiteralPath (Join-Path $folder 'PresentMon.exe') -Value 'x'
        $saved = $env:PATH
        try {
            $env:PATH = "$folder;$saved"
            $empty = Join-Path $TestDrive 'no-tools'
            (Find-PCDoctorPresentMon -ToolsDir $empty -IsTrusted { $true }).Path | Should -BeLike '*on-path*'
            $elevated = Find-PCDoctorPresentMon -ToolsDir $empty -Elevated -IsTrusted { $true }
            $elevated.Path | Should -BeNullOrEmpty
            $elevated.Problem | Should -BeNullOrEmpty
        } finally {
            $env:PATH = $saved
        }
    }

    It 'never returns an nvidia-smi that fails the check' {
        $folder = Join-Path $TestDrive 'smi'
        New-Item -ItemType Directory -Path $folder | Out-Null
        Set-Content -LiteralPath (Join-Path $folder 'nvidia-smi.exe') -Value 'x'
        $saved = $env:PATH
        try {
            $env:PATH = "$folder;$saved"
            Find-PCDoctorNvidiaSmi -IsTrusted { $false } | Should -BeNullOrEmpty
            Find-PCDoctorNvidiaSmi -IsTrusted { param($file) $file -like '*smi*' } | Should -Not -BeNullOrEmpty
            Find-PCDoctorNvidiaSmi -Elevated -IsTrusted { param($file) $file -like "$folder*" } | Should -BeNullOrEmpty
        } finally {
            $env:PATH = $saved
        }
    }
}

Describe 'The link after an upload' {
    It 'is built only from parts with the expected shape' {
        $guest = [pscustomobject]@{ share_key = 'k3Jv9Qp_2xZr-7LmN0aBcDeFgHiJkLmN'; run = [pscustomobject]@{ id = 'a' * 32 } }
        Get-PCDoctorResultLink -BaseUrl 'http://192.168.1.20:8080/' -Answer $guest | Should -Be 'http://192.168.1.20:8080/r/k3Jv9Qp_2xZr-7LmN0aBcDeFgHiJkLmN'
        $master = [pscustomobject]@{ share_key = $null; run = [pscustomobject]@{ id = '0123456789abcdef0123456789abcdef' } }
        Get-PCDoctorResultLink -BaseUrl 'https://pc.example.com' -Answer $master | Should -Be 'https://pc.example.com/runs/0123456789abcdef0123456789abcdef'
    }

    It 'gives no link for a hostile or broken answer' {
        foreach ($key in @('x', '../../evil', 'abc def ghi jkl mno', 'aaaaaaaaaaaaaaaa?x=1', "aaaaaaaaaaaaaaaa`nfile:///")) {
            $answer = [pscustomobject]@{ share_key = $key; run = [pscustomobject]@{ id = 'a' * 32 } }
            Get-PCDoctorResultLink -BaseUrl 'http://localhost:8080' -Answer $answer | Should -BeNullOrEmpty
        }
        $odd = [pscustomobject]@{ share_key = $null; run = [pscustomobject]@{ id = 'calc.exe' } }
        Get-PCDoctorResultLink -BaseUrl 'http://localhost:8080' -Answer $odd | Should -BeNullOrEmpty
        $good = [pscustomobject]@{ share_key = 'k3Jv9Qp_2xZr-7LmN0aBcDeFgHiJkLmN'; run = $null }
        Get-PCDoctorResultLink -BaseUrl 'file:///C:/Windows' -Answer $good | Should -BeNullOrEmpty
    }
}

Describe 'Reading this PC' {
    It 'reads specs without names or serial numbers' {
        $specs = Get-PCDoctorSpecs
        $specs.cpu.Count | Should -BeGreaterThan 0
        $specs.cpu[0].name | Should -Not -BeNullOrEmpty
        $specs.memory.total_bytes | Should -BeGreaterThan 0
        foreach ($module in @($specs.memory.modules)) { $module.Contains('bank') | Should -BeTrue }
        $specs.system.type | Should -BeIn @('desktop', 'laptop', 'server')
        $json = ConvertTo-Json -InputObject $specs -Depth 8
        $json | Should -Not -Match ([regex]::Escape($env:COMPUTERNAME))
        $json | Should -Not -Match '(?i)serial'
    }

    It 'reads events and disks in the documented shape' {
        $events = Get-PCDoctorEvents -Days 30
        $events.window_days | Should -Be 30
        , $events.events | Should -BeOfType [array]
        $disks = Get-PCDoctorDisks
        @($disks.physical_disks).Count | Should -BeGreaterThan 0
        foreach ($disk in @($disks.physical_disks)) { $disk.Contains('number') | Should -BeTrue }
        @($disks.volumes | Where-Object { $_.is_system }).Count | Should -Be 1
        (ConvertTo-Json -InputObject $disks -Depth 8) | Should -Not -Match '(?i)serial'
    }

    It 'summarises events for the console' {
        $document = @{ events = @(
                @{ provider = 'Microsoft-Windows-WHEA-Logger'; id = 18; message = ''; data = @{} }
                @{ provider = 'Microsoft-Windows-Kernel-Power'; id = 41; message = ''; data = @{} }
                @{ provider = 'Microsoft-Windows-WER-SystemErrorReporting'; id = 1001; message = ''; data = @{ param1 = '0x00000124 (0x0, 0x1, 0x2, 0x3)' } }
                @{ provider = 'disk'; id = 153; message = ''; data = @{} }
            )
        }
        $summary = Get-PCDoctorEventSummary -EventDocument $document
        $summary.whea_errors | Should -Be 1
        $summary.unexpected_shutdowns | Should -Be 1
        $summary.blue_screens | Should -Be 1
        $summary.stop_codes | Should -Be @('0x00000124')
        $summary.disk_errors | Should -Be 1
    }

    It 'reads a Windows sensor sample with a CPU load and RAM use' {
        $sample = Get-PCDoctorWindowsSample
        $sample['cpu_load_pct'] | Should -Not -BeNullOrEmpty
        $sample['ram_used_pct'] | Should -BeGreaterThan 0
        $sample['ram_used_pct'] | Should -BeLessOrEqual 100
    }

    It 'finds no LibreHardwareMonitor where none is running' {
        Get-PCDoctorLhmSensors -Url 'http://localhost:59999' -TimeoutSec 1 | Should -BeNullOrEmpty
    }
}
