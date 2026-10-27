#Requires -Version 5.1
<#
Reviewed deployment helper. This file is NOT run by the application.
Default: read-only preflight. -Apply: create one scoped inbound firewall rule
and export only the public CA certificate under workstation-data/tls/client-public.
No service start/restart, certificate trust installation, ACL changes or downloads.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium', DefaultParameterSetName = 'Enable')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Enable')][string]$LanAddress,
    [Parameter(Mandatory = $true, ParameterSetName = 'Enable')][string]$InterfaceAlias,
    [Parameter(Mandatory = $true, ParameterSetName = 'Disable')][switch]$Disable,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'This helper requires Windows.' }

$installationRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$dataDirectory = Join-Path $installationRoot 'workstation-data'
$tlsDirectory = Join-Path $dataDirectory 'tls'
$runtimeDirectory = Join-Path $installationRoot 'runtime\caddy'
$caddyBinary = Join-Path $runtimeDirectory 'caddy.exe'
$caPath = Join-Path $tlsDirectory 'GD-workstation-CA.crt'
$configPath = Join-Path $tlsDirectory 'Caddyfile'
$addressesPath = Join-Path $tlsDirectory 'addresses.json'
$publicDirectory = Join-Path $tlsDirectory 'client-public'
# Fingerprint of this installation's reviewed binary; not a vendor signature.
$expectedCaddyHash = '5F93A9BD555F3AAC9D33AF2756BA14B3519D8CCA4FFD55256BDAEAB444C9DB2A'

function Assert-OwnedPath([string]$Path, [string]$Boundary, [switch]$MayNotExist) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $boundaryAbsolute = [IO.Path]::GetFullPath($Boundary).TrimEnd('\')
    if ($absolute -ne $boundaryAbsolute -and -not $absolute.StartsWith($boundaryAbsolute + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the permitted installation directory: $absolute"
    }
    if (-not $MayNotExist -and -not (Test-Path -LiteralPath $absolute)) { throw "Required path is missing: $absolute" }
    $cursor = $absolute
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing a symbolic link or junction: $cursor"
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $absolute
}
function Test-PrivateIPv4([string]$Address) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed) -or $parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { return $false }
    if ($parsed.ToString() -ne $Address) { return $false }
    $b = $parsed.GetAddressBytes()
    return ($b[0] -eq 10 -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168))
}
function Get-HexHash([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '') }
    finally { $sha.Dispose() }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($Apply -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Apply requires a PowerShell window explicitly opened as Administrator. No setting was changed.'
}
$ruleSuffix = (Get-HexHash ([Text.Encoding]::UTF8.GetBytes($installationRoot.ToLowerInvariant()))).Substring(0, 12)
$ruleName = 'GDWorkstation-8443-' + $ruleSuffix
$description = 'GD workstation local HTTPS; installation=' + $installationRoot
$existing = @(Get-NetFirewallRule -PolicyStore PersistentStore -ErrorAction Stop | Where-Object Name -eq $ruleName)
if ($existing.Count -gt 1) { throw 'Unexpected duplicate firewall rule identity.' }
if ($existing.Count -eq 1 -and $existing[0].Description -ne $description) { throw 'Existing rule does not belong to this installation.' }

if ($Disable) {
    if (-not $existing.Count) { Write-Output 'No matching rule exists; nothing to disable.'; return }
    if (-not $Apply) { Write-Output "Preflight only: would disable $ruleName. Add -Apply to perform this action."; return }
    if ($PSCmdlet.ShouldProcess($ruleName, 'Disable only this installation firewall rule')) {
        Disable-NetFirewallRule -InputObject $existing[0] -ErrorAction Stop | Out-Null
        Write-Output 'This installation firewall rule is disabled. Other rules and certificate stores were not changed.'
    }
    return
}

foreach ($path in @($tlsDirectory, $caPath, $configPath, $addressesPath, (Join-Path $tlsDirectory 'server.crt'), (Join-Path $tlsDirectory 'server.key'))) {
    $null = Assert-OwnedPath $path $tlsDirectory
}
$null = Assert-OwnedPath $caddyBinary $runtimeDirectory
if ((Get-FileHash -LiteralPath $caddyBinary -Algorithm SHA256).Hash -ne $expectedCaddyHash) {
    throw 'Caddy binary fingerprint differs. Re-review the installed version before updating this script.'
}

if (-not (Test-PrivateIPv4 $LanAddress)) { throw 'Use one literal RFC1918 IPv4 address assigned to the trusted office network.' }
if ([Management.Automation.WildcardPattern]::ContainsWildcardCharacters($InterfaceAlias)) { throw 'InterfaceAlias must be exact, without wildcard characters.' }
$localAddress = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object { $_.IPAddress -eq $LanAddress -and $_.InterfaceAlias -eq $InterfaceAlias })
if ($localAddress.Count -ne 1) { throw 'The selected IP and exact interface alias do not match one local adapter.' }
$profiles = @(Get-NetConnectionProfile -InterfaceIndex $localAddress[0].InterfaceIndex -ErrorAction Stop)
if ($profiles.Count -ne 1 -or $profiles[0].NetworkCategory.ToString() -notin @('Private', 'DomainAuthenticated')) {
    throw 'The chosen adapter must already use the trusted Private or Domain network profile. This script does not change network profiles.'
}
$metadata = Get-Content -LiteralPath $addressesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$hosts = @()
foreach ($url in $metadata.urls) {
    $uri = [Uri]$url
    if ($uri.Scheme -ne 'https' -or $uri.Port -ne 8443 -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') { throw 'Unexpected HTTPS address metadata.' }
    if ($uri.Host -ne '127.0.0.1' -and -not (Test-PrivateIPv4 $uri.Host)) { throw 'Proxy address is not loopback or RFC1918.' }
    $hosts += $uri.Host
}
if ($hosts -notcontains $LanAddress -or $hosts -notcontains '127.0.0.1') { throw 'Selected address is missing from the prepared HTTPS configuration. Re-prepare TLS before enabling LAN access.' }
if ([IO.Path]::GetFullPath([string]$metadata.ca_certificate) -ne $caPath) { throw 'CA metadata points outside the expected certificate path.' }
$serverCertificate = (Join-Path $tlsDirectory 'server.crt').Replace('\', '/')
$serverKey = (Join-Path $tlsDirectory 'server.key').Replace('\', '/')
$expectedConfig = "{`n admin off`n auto_https off`n}`n" + (($hosts | ForEach-Object { 'https://' + $_ + ':8443' }) -join ', ') + " {`n bind " + ($hosts -join ' ') + "`n"
$expectedConfig += ' tls "' + $serverCertificate + '" "' + $serverKey + '"' + "`n"
$expectedConfig += " @outside not remote_ip 127.0.0.1 ::1 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12`n respond @outside 403`n reverse_proxy 127.0.0.1:8765`n}"
$actualConfig = (Get-Content -LiteralPath $configPath -Raw -Encoding UTF8).Replace("`r`n", "`n").Trim()
if ($actualConfig -ne $expectedConfig) { throw 'Caddyfile differs from the reviewed private-network configuration. Review it before enabling access.' }
& $caddyBinary validate --config $configPath --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy rejected the current TLS configuration.' }
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8443 -ErrorAction Stop | Where-Object LocalAddress -eq $LanAddress)
if (-not $listeners.Count) { throw 'No HTTPS listener exists on the selected IP. Start the workstation locally first.' }
foreach ($listener in $listeners) {
    if ((Get-Process -Id $listener.OwningProcess -ErrorAction Stop).Path -ne $caddyBinary) { throw 'The HTTPS listener is not the pinned Caddy executable.' }
}
$request = [Net.WebRequest]::Create('http://127.0.0.1:8765/api/health')
$request.Proxy = $null; $request.Timeout = 3000
$response = $request.GetResponse()
try {
    $reader = New-Object IO.StreamReader($response.GetResponseStream())
    try { $health = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
} finally { $response.Dispose() }
if ($health.application -ne 'gd-workstation') { throw 'The local backend did not identify itself as the GD workstation.' }

$caText = Get-Content -LiteralPath $caPath -Raw -Encoding ASCII
if ($caText -match 'PRIVATE KEY') { throw 'Refusing to distribute a file containing a private key.' }
$certificatePattern = '-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----'
$caBlocks = [regex]::Matches($caText, $certificatePattern)
if ($caBlocks.Count -ne 1 -or $caText.Trim() -ne $caBlocks[0].Value) { throw 'The public CA file must contain exactly one certificate and no extra content.' }
$certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2($caPath)
if ($certificate.HasPrivateKey -or $certificate.Subject -ne $certificate.Issuer -or $certificate.NotBefore.ToUniversalTime() -gt [DateTime]::UtcNow -or $certificate.NotAfter.ToUniversalTime() -le [DateTime]::UtcNow) { throw 'The public root CA is invalid, expired, or includes a private key.' }
$basic = @($certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.19' })
if ($basic.Count -ne 1 -or -not ([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($basic[0], $basic[0].Critical)).CertificateAuthority) { throw 'The public certificate is not a CA.' }
$serverText = Get-Content -LiteralPath (Join-Path $tlsDirectory 'server.crt') -Raw -Encoding ASCII
$serverBlocks = [regex]::Matches($serverText, $certificatePattern)
if ($serverBlocks.Count -ne 2) { throw 'Expected one server certificate and its root CA in the prepared chain.' }
$bundledRootDer = [Convert]::FromBase64String(($serverBlocks[1].Value -replace '-----BEGIN CERTIFICATE-----|-----END CERTIFICATE-----|\s', ''))
if ((Get-HexHash $bundledRootDer) -ne (Get-HexHash $certificate.RawData)) { throw 'Public CA differs from the root included in the server certificate chain.' }
$fileHash = (Get-FileHash -LiteralPath $caPath -Algorithm SHA256).Hash
$certificateHash = Get-HexHash $certificate.RawData
Write-Output "Reviewed target: https://${LanAddress}:8443 ; interface=$InterfaceAlias ; profile=Private,Domain ; remote=LocalSubnet ; TCP only."
Write-Output "Public CA file SHA256: $fileHash"
Write-Output "CA certificate DER SHA256: $certificateHash"
Write-Output "CA SHA1 store identifier (for later removal): $($certificate.Thumbprint)"
if (-not $Apply) { Write-Output 'Preflight completed. No setting changed. Add -Apply after review, or use -Apply -WhatIf to inspect actions.'; return }
if ($existing.Count) { throw "Rule $ruleName already exists. This script refuses to broaden or replace existing rules; inspect its settings before changing it." }

$null = Assert-OwnedPath $publicDirectory $tlsDirectory -MayNotExist
$publicCa = Join-Path $publicDirectory 'GD-workstation-CA.crt'
$publicInfo = Join-Path $publicDirectory 'CA-fingerprints.txt'
foreach ($path in @($publicCa, $publicInfo)) { $null = Assert-OwnedPath $path $tlsDirectory -MayNotExist }
if ($PSCmdlet.ShouldProcess($publicDirectory, 'Export only the public CA certificate and fingerprints')) {
    New-Item -ItemType Directory -Path $publicDirectory -Force | Out-Null
    Copy-Item -LiteralPath $caPath -Destination $publicCa
    [IO.File]::WriteAllText($publicInfo, "Public CA only. Never distribute *.key or the full tls directory.`r`nFile SHA256: $fileHash`r`nCertificate DER SHA256: $certificateHash`r`nStore SHA1 identifier: $($certificate.Thumbprint)`r`nURL: https://${LanAddress}:8443`r`n", [Text.Encoding]::UTF8)
}
if ($PSCmdlet.ShouldProcess($ruleName, 'Allow pinned Caddy TCP 8443 from LocalSubnet only on the chosen Private/Domain interface and IP')) {
    New-NetFirewallRule -Name $ruleName -DisplayName 'GD Workstation HTTPS - office LAN only' -Description $description -Group 'GD Workstation' -PolicyStore PersistentStore -Direction Inbound -Action Allow -Enabled True -Profile Private,Domain -Protocol TCP -LocalPort 8443 -LocalAddress $LanAddress -RemoteAddress LocalSubnet -InterfaceAlias $InterfaceAlias -Program $caddyBinary -EdgeTraversalPolicy Block -ErrorAction Stop | Out-Null
    Write-Output "Created scoped rule $ruleName. Client CA installation and a second-computer HTTPS test are still required."
}
