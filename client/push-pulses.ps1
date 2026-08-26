<#
  Faoliyat izini serverga yuborish (Windows).

      .\push-pulses.ps1              # yuborilmagan qatorlarni yuboradi
      .\push-pulses.ps1 -Read        # hech narsa yubormaydi, JSON massiv chiqaradi
      .\push-pulses.ps1 -All         # offset'ni inkor qilib, jurnalni boshidan

  Bu ZAXIRA yo'l. Odatda izni agentning o'zi olib ketadi: `start_session`,
  `report_progress`, `finish_task`, `report_unplanned` tool'larining `pulses`
  parametri bor. Bu skript agent serverga umuman kelmagan holat uchun - jurnal
  diskda qolib ketganda odam qo'lda ishga tushiradi.

  -Read - agent uchun: chiqishini to'g'ridan-to'g'ri `pulses` parametriga
  beriladi, keyin offset siljitiladi (ekranda aytiladi).
#>
[CmdletBinding()]
param(
    [switch]$Read,
    [switch]$All,
    [string]$Api = $(if ($env:AIWORK_API) { $env:AIWORK_API } else { 'https://work.ai-energy.team' }),
    [string]$Project = $env:AIWORK_PROJECT
)

$ErrorActionPreference = 'Stop'

$journal = if ($env:AIWORK_JOURNAL) { $env:AIWORK_JOURNAL } else { Join-Path $HOME '.aiwork\journal.ndjson' }
$offsetFile = if ($env:AIWORK_OFFSET) { $env:AIWORK_OFFSET } else { Join-Path $HOME '.aiwork\offset' }
# Serverning bir chaqiruvdagi chegarasi. Qolgani diskda qoladi.
$batch = 200

if (-not (Test-Path -LiteralPath $journal)) {
    Write-Host "Jurnal yo'q: $journal - hook hali bir marta ham ishlamagan."
    exit 0
}

# Offset - YUBORILGAN QATORLAR SONI, bayt emas. Aylanish (10 MB) yoki
# jurnalning qisqarishi offset'ni jurnaldan katta qilib qo'yishi mumkin -
# bunda noldan boshlanadi. Ortiqchasini server dublikat sifatida tashlaydi.
$lines = @(Get-Content -LiteralPath $journal -Encoding utf8)
$total = $lines.Count
$sent = 0
if (-not $All -and (Test-Path -LiteralPath $offsetFile)) {
    $raw = (Get-Content -Raw -LiteralPath $offsetFile).Trim()
    if ($raw -match '^\d+$') { $sent = [int]$raw }
}
if ($sent -gt $total) { $sent = 0 }

$pulses = @()
foreach ($line in ($lines | Select-Object -Skip $sent | Select-Object -First $batch)) {
    if (-not $line.Trim()) { continue }
    try { $row = $line | ConvertFrom-Json } catch { continue }  # buzuq qator pachkani bekor qilmaydi
    $pulses += [ordered]@{
        ts         = $row.ts
        client_sid = $row.client_sid
        tool       = $row.tool
        target     = $row.target
    }
}
$count = $pulses.Count

if ($Read) {
    if ($count -eq 0) { Write-Host '[]' } else { Write-Host (ConvertTo-Json @($pulses) -Depth 4) }
    Write-Warning "$count qator. Yuborgandan keyin: Set-Content -Path `"$offsetFile`" -Value $($sent + $count)"
    exit 0
}

if ($count -eq 0) {
    Write-Host "Yuboriladigan yangi qator yo'q ($total dan $sent tasi ketgan)."
    exit 0
}

if (-not $env:AIWORK_TOKEN) {
    Write-Error "AIWORK_TOKEN muhitda yo'q. setx AIWORK_TOKEN `"...`" qiling va terminalni qayta oching."
}

# Loyiha slug'i .mcp.json dan - klient ham shundan ishlaydi.
if (-not $Project -and (Test-Path .mcp.json)) {
    try {
        $cfg = Get-Content -Raw .mcp.json | ConvertFrom-Json
        $Project = $cfg.mcpServers.aiwork.headers.'X-Aiwork-Project'
    } catch { }
}

$payload = [ordered]@{ pulses = @($pulses) }
if ($Project) { $payload['project'] = $Project }
$body = ConvertTo-Json $payload -Depth 5 -Compress

Write-Host "manzil:  $Api/api/cli/pulses"
if ($Project) { Write-Host "loyiha:  $Project" } else { Write-Host "loyiha:  <hammasi>" }
Write-Host "pachka:  $count qator ($total dan $sent tasi avval ketgan)"

try {
    $response = Invoke-RestMethod -Uri "$Api/api/cli/pulses" -Method Post -Body $body -ContentType 'application/json' -Headers @{
        'Authorization' = "Bearer $($env:AIWORK_TOKEN)"
    }
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) { Write-Error "401: token yaroqsiz yoki bekor qilingan. Yangisini so'rang." }
    if ($code -eq 404) { Write-Error "404: loyiha topilmadi yoki sizga ko'rinmaydi ($Project)." }
    Write-Error "Yuborilmadi ($code): $($_.Exception.Message)"
}

Write-Host "  javob: qabul $($response.accepted), tashlandi $($response.dropped)"
# Offset faqat muvaffaqiyatdan keyin siljiydi. Aks holda uzilgan yuborishdan
# keyin ish jimgina yo'qolardi - bu esa aynan o'sha muammoning o'zi.
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $offsetFile) | Out-Null
Set-Content -Path $offsetFile -Value ($sent + $count) -Encoding utf8
Write-Host "  offset: $($sent + $count)"
