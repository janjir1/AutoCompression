# Ensure script is saved as UTF-8 with BOM

# Hardcoded variables with Czech diacritics
$InputFile    = 'E:\Filmy\hrané\Action\Kingsman.avi'
$MovieName    = 'Kingsman'
$ProfilePath  = 'Profiles\h265_slow_nvenc.yaml'
$SettingsPath = 'Profiles\Test_settings.yaml'
$WorkspaceDir = 'D:\Files\Projects\AutoCompression\workspace'
$ToolsDir     = 'D:\Files\Projects\AutoCompression\tools'

# Path to virtual environment activation script
$VenvActivate = '.venv\Scripts\Activate.ps1'

if (-Not (Test-Path $VenvActivate)) {
    Write-Error "Virtual environment activation script not found at $VenvActivate"
    exit 1
}

# Activate the virtual environment
. $VenvActivate

Write-Host "Starting compression for '$MovieName'" -ForegroundColor Cyan
Write-Host "Input File:     $InputFile"
Write-Host "Profile Path:   $ProfilePath"
Write-Host "Settings Path:  $SettingsPath"
Write-Host "Workspace Dir:  $WorkspaceDir"
Write-Host "Tools Dir:      $ToolsDir"

# Run the Python script
& python "code\main.py" `
    --input_file   $InputFile `
    --movie_name   $MovieName `
    --profile      $ProfilePath `
    --settings     $SettingsPath `
    --workspace    $WorkspaceDir `
    --tools        $ToolsDir

if ($LASTEXITCODE -ne 0) {
    Write-Error "Compression script exited with errors."
} else {
    Write-Host "Compression finished successfully for '$MovieName'" -ForegroundColor Green
}

# Keep the window open when double-clicked
if ($Host.Name -eq 'ConsoleHost') {
    Write-Host "`nPress Enter to exit..."
    [void][System.Console]::ReadLine()
}
