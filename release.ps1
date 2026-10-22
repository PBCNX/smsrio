param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Remote = 'public',
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'

if (git status --porcelain) {
    throw 'working tree is not clean; commit or stash first'
}

# Vendor material must never reach the public snapshot, even if a future
# .gitignore change lets it into the private tree.
$forbidden = git ls-files | Select-String -Pattern '\.(inp|ts|pcap|bin)$'
if ($forbidden) {
    throw "vendor material is tracked: $($forbidden -join ', ')"
}

$url = git remote get-url $Remote 2>$null
if (-not $url -or $url -notmatch 'github\.com') {
    throw "remote '$Remote' is missing or not a GitHub URL"
}

if (git rev-parse -q --verify "refs/tags/v$Version") {
    throw "tag v$Version already exists"
}

$release = "release-$Version"
git checkout --orphan $release
git add -A
git commit -m "Release $Version"
git tag -a "v$Version" -m "v$Version"

git push --force $Remote "${release}:${Branch}"
git push $Remote "v$Version"

git checkout $Branch
git branch -D $release
Write-Host "released v$Version to $Remote"
