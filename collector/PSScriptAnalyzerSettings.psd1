# PSScriptAnalyzer settings for the collector. CI fails on any Error and on
# any Warning that is not excluded here, each with its reason.
@{
    Severity     = @('Error', 'Warning')
    ExcludeRules = @(
        # This is a console tool for a person; coloured Write-Host is its UI.
        'PSAvoidUsingWriteHost',
        # "Get-PCDoctorSpecs", "-Events", "-Disks" read better than the singular.
        'PSUseSingularNouns',
        # A sensor or a registry key that cannot be read is skipped on purpose:
        # one missing reading must never end the run.
        'PSAvoidUsingEmptyCatchBlock',
        # Functions named Select-/Send- here read data; nothing on the PC changes.
        'PSUseShouldProcessForStateChangingFunctions',
        # Files are plain ASCII (checked in CI), so no byte-order mark is needed.
        'PSUseBOMForUnicodeEncodedFile'
    )
}
