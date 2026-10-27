$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$templateRoot = Join-Path $root 'templates\workstation-originals'
$records = Get-Content -LiteralPath (Join-Path $templateRoot 'source-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$docxOut = Join-Path $templateRoot 'word-converted'
$pdfOut = Join-Path $templateRoot 'word-reference-pdf'
New-Item -ItemType Directory -Force -Path $docxOut,$pdfOut | Out-Null
$result = @()
  foreach ($entry in $records) {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $word.Options.UpdateLinksAtOpen = $false
    $document = $null
    try {
      $source = Join-Path (Join-Path $templateRoot 'source') $entry.name
      $stem = [System.IO.Path]::GetFileNameWithoutExtension($entry.name)
      $destination = Join-Path $docxOut ($stem + '.docx')
      $pdf = Join-Path $pdfOut ($stem + '.pdf')
      $document = $word.Documents.Open($source,$false,$true,$false)
      $document.SaveAs2($destination,16)
      $pages = $document.ComputeStatistics(2)
      $document.Close(0)
      $document = $null
      $result += [pscustomobject]@{name=$entry.name;docx=[System.IO.Path]::GetFileName($destination);pages=$pages;sha256=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()}
      Write-Output ($entry.name + ': ' + $pages + ' pages')
    } finally {
      if ($null -ne $document) { try { $document.Close(0) } catch {} }
      try { $word.Quit(0) } catch {}
      [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $templateRoot 'word-conversion-index.json') -Encoding UTF8
  }
