# Script to help resolve OneDrive build locking issues
# Run this script and then try building again

Write-Host "Attempting to fix OneDrive build locking issues..." -ForegroundColor Yellow

# Stop Gradle daemon
Write-Host "`n1. Stopping Gradle daemon..." -ForegroundColor Cyan
./gradlew --stop 2>&1 | Out-Null

# Wait a moment
Start-Sleep -Seconds 2

# Try to remove locked directories with retries
Write-Host "`n2. Attempting to clear build directories..." -ForegroundColor Cyan
$directories = @(
    "app\build\intermediates\project_dex_archive",
    "app\build\intermediates\dex_metadata_directory",
    "app\build\intermediates\merged_res_blame_folder"
)

foreach ($dir in $directories) {
    if (Test-Path $dir) {
        Write-Host "   Removing: $dir" -ForegroundColor Gray
        for ($i = 0; $i -lt 3; $i++) {
            try {
                Remove-Item -Path $dir -Recurse -Force -ErrorAction Stop
                Write-Host "   ✓ Successfully removed" -ForegroundColor Green
                break
            } catch {
                if ($i -lt 2) {
                    Write-Host "   ⚠ Retry $($i+1)/3..." -ForegroundColor Yellow
                    Start-Sleep -Seconds 1
                } else {
                    Write-Host "   ✗ Could not remove (likely locked by OneDrive)" -ForegroundColor Red
                }
            }
        }
    }
}

Write-Host "`n3. Recommendations:" -ForegroundColor Cyan
Write-Host "   • Pause OneDrive sync temporarily: Right-click OneDrive icon → Pause syncing → 2 hours" -ForegroundColor White
Write-Host "   • Or exclude build folders from OneDrive:" -ForegroundColor White
Write-Host "     1. Right-click OneDrive icon → Settings" -ForegroundColor Gray
Write-Host "     2. Go to Sync and backup → Advanced settings" -ForegroundColor Gray
Write-Host "     3. Choose folders and exclude:" -ForegroundColor Gray
Write-Host "        - mobileApplication/app/build" -ForegroundColor Gray
Write-Host "        - mobileApplication/.gradle" -ForegroundColor Gray
Write-Host "        - mobileApplication/build" -ForegroundColor Gray

Write-Host "`n4. After pausing OneDrive or excluding folders, run:" -ForegroundColor Cyan
Write-Host "   ./gradlew assembleRelease --no-daemon" -ForegroundColor White

Write-Host "`nDone!" -ForegroundColor Green







