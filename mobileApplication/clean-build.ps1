# Script to clean Android build directory, handling file locks gracefully
# Usage: .\clean-build.ps1

Write-Host "Cleaning Android build directory..." -ForegroundColor Yellow

$buildDir = Join-Path $PSScriptRoot "app\build"
$gradleDir = Join-Path $PSScriptRoot ".gradle"

# Function to remove directory with retry logic
function Remove-DirectoryWithRetry {
    param(
        [string]$Path,
        [int]$MaxRetries = 3,
        [int]$DelaySeconds = 2
    )
    
    if (-not (Test-Path $Path)) {
        Write-Host "Directory does not exist: $Path" -ForegroundColor Gray
        return $true
    }
    
    for ($i = 1; $i -le $MaxRetries; $i++) {
        try {
            Write-Host "Attempt $i of $MaxRetries: Removing $Path..." -ForegroundColor Cyan
            Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
            Write-Host "Successfully removed: $Path" -ForegroundColor Green
            return $true
        }
        catch {
            if ($i -lt $MaxRetries) {
                Write-Host "Failed to remove (attempt $i). Waiting $DelaySeconds seconds..." -ForegroundColor Yellow
                Start-Sleep -Seconds $DelaySeconds
            }
            else {
                Write-Host "Warning: Could not remove $Path after $MaxRetries attempts." -ForegroundColor Red
                Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
                Write-Host "This is likely due to OneDrive sync or another process locking files." -ForegroundColor Yellow
                Write-Host "You can:" -ForegroundColor Yellow
                Write-Host "  1. Pause OneDrive sync temporarily" -ForegroundColor Yellow
                Write-Host "  2. Close Android Studio/IDE" -ForegroundColor Yellow
                Write-Host "  3. Build without cleaning (./gradlew assembleDebug)" -ForegroundColor Yellow
                return $false
            }
        }
    }
}

# Stop Gradle daemon first
Write-Host "`nStopping Gradle daemon..." -ForegroundColor Cyan
& "$PSScriptRoot\gradlew.bat" --stop 2>&1 | Out-Null
Start-Sleep -Seconds 1

# Try to remove build directories
$success = $true
if (Test-Path $buildDir) {
    $success = Remove-DirectoryWithRetry -Path $buildDir
}

# Optionally clean .gradle cache (commented out as it's large and takes time)
# if (Test-Path $gradleDir) {
#     Write-Host "`nNote: Skipping .gradle cache cleanup (uncomment in script to enable)" -ForegroundColor Gray
# }

if ($success) {
    Write-Host "`nBuild directory cleaned successfully!" -ForegroundColor Green
}
else {
    Write-Host "`nBuild directory cleanup had issues, but you can still build without cleaning." -ForegroundColor Yellow
}

