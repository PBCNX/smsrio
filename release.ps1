param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Remote = 'public',
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'

if (git status --porcelain) {
    throw 'working tree is not clean; commit or stash first'
}

$url = git remote get-url $Remote 2>$null
if (-not $url -or $url -notmatch 'github\.com') {
    throw "remote '$Remote' is missing or not a GitHub URL"
}

if (git rev-parse -q --verify "refs/tags/v$Version") {
    throw "tag v$Version already exists"
}

# Vendor material lives in the private tree so it can be tested out of the box;
# the public snapshot never carries it.  Protocol captures such as
# sequence.bin are not firmware and are kept.
$vendorPattern = '(^|/)([^/]*firmware[^/]*\.(bin|fw)|[^/]*\.inp|[^/]*\.pcap|[^/]*\.ts|[^/]*\.fw)$'

$release = "release-$Version"
git checkout --orphan $release
git add -A

$vendor = @(git ls-files | Select-String -Pattern $vendorPattern | ForEach-Object { $_.Line })
if ($vendor.Count -gt 0) {
    Write-Host "withholding $($vendor.Count) vendor file(s) from the snapshot:"
    foreach ($path in $vendor) {
        Write-Host "  $path"
        git rm --cached --quiet -- $path
    }
}

git commit -m "Release $Version"
git tag -a "v$Version" -m "v$Version"

git push --force $Remote "${release}:${Branch}"
git push $Remote "v$Version"

git checkout $Branch
git branch -D $release
Write-Host "released v$Version to $Remote ($($vendor.Count) vendor file(s) withheld)"
