<#
  aiwork ulanishini tekshirish (Windows). Hech narsani o'zgartirmaydi: faqat o'qiydi.

      .\check.ps1
      .\check.ps1 -Url http://127.0.0.1:8310/mcp      # mahalliy stek

  Token muhitdan olinadi (AIWORK_TOKEN), loyiha slug'i - .mcp.json dan.
#>
[CmdletBinding()]
param(
    [string]$Url = $(if ($env:AIWORK_URL) { $env:AIWORK_URL } else { 'https://work.ai-energy.team/mcp' }),
    [string]$Project = $env:AIWORK_PROJECT
)

$ErrorActionPreference = 'Stop'

if (-not $env:AIWORK_TOKEN) {
    Write-Error "AIWORK_TOKEN muhitda yo'q. setx AIWORK_TOKEN `"...`" qiling va terminalni qayta oching."
}

# Loyiha slug'i .mcp.json da bo'lsa - o'shani olamiz: klient ham shundan ishlaydi.
if (-not $Project -and (Test-Path .mcp.json)) {
    try {
        $cfg = Get-Content -Raw .mcp.json | ConvertFrom-Json
        $Project = $cfg.mcpServers.aiwork.headers.'X-Aiwork-Project'
    } catch { }
}

$headers = @{
    'Authorization' = "Bearer $($env:AIWORK_TOKEN)"
    'Content-Type'  = 'application/json'
    'Accept'        = 'application/json, text/event-stream'
}
if ($Project) { $headers['X-Aiwork-Project'] = $Project }

function Say($text) { Write-Host "`n-- $text" -ForegroundColor Cyan }

Write-Host "manzil:  $Url"
if ($Project) { Write-Host "loyiha:  $Project" } else { Write-Host "loyiha:  <hammasi>" }

# -- 1. Ulanish: seansni server sarlavhada beradi -----------------------------
Say 'ulanish'
$init = @{
    jsonrpc = '2.0'; id = 1; method = 'initialize'
    params  = @{
        protocolVersion = '2025-06-18'; capabilities = @{}
        clientInfo      = @{ name = 'check'; version = '1' }
    }
} | ConvertTo-Json -Depth 6

try {
    $response = Invoke-WebRequest -Uri $Url -Method Post -Headers $headers -Body $init -UseBasicParsing
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) { Write-Error "401: token yaroqsiz yoki bekor qilingan. Yangisini so'rang." }
    Write-Error "Ulanmadi ($code): $($_.Exception.Message)"
}

$session = $response.Headers['Mcp-Session-Id']
if ($session -is [array]) { $session = $session[0] }
Write-Host "  ulandi, sessiya: $session"
if ($session) { $headers['Mcp-Session-Id'] = $session }

Invoke-WebRequest -Uri $Url -Method Post -Headers $headers -UseBasicParsing -Body (
    @{ jsonrpc = '2.0'; method = 'notifications/initialized' } | ConvertTo-Json
) | Out-Null

function Invoke-Tool($id, $name, $arguments) {
    $body = @{
        jsonrpc = '2.0'; id = $id; method = 'tools/call'
        params  = @{ name = $name; arguments = $arguments }
    } | ConvertTo-Json -Depth 6
    $raw = Invoke-WebRequest -Uri $Url -Method Post -Headers $headers -Body $body -UseBasicParsing
    $envelope = $raw.Content | ConvertFrom-Json
    if ($envelope.error) { throw $envelope.error.message }
    return $envelope.result.content[0].text | ConvertFrom-Json
}

# -- 2. Asboblar --------------------------------------------------------------
Say 'asboblar'
$listBody = @{ jsonrpc = '2.0'; id = 2; method = 'tools/list' } | ConvertTo-Json
$tools = ((Invoke-WebRequest -Uri $Url -Method Post -Headers $headers -Body $listBody -UseBasicParsing).Content |
    ConvertFrom-Json).result.tools
Write-Host "  soni: $($tools.Count)"
Write-Host "  $(($tools | ForEach-Object { $_.name }) -join ', ')"

# -- 3. Doska ustunlari va oqim ----------------------------------------------
Say 'ustunlar'
$columns = (Invoke-Tool 3 'list_columns' @{}).columns
$byId = @{}
foreach ($c in $columns) { $byId[$c.id] = $c.name }
foreach ($c in $columns) {
    $next = if ($c.next_column_id -and $byId.ContainsKey($c.next_column_id)) { $byId[$c.next_column_id] } else { '-' }
    Write-Host ("  {0,-20} {1,-10} -> {2}" -f $c.name, $c.kind, $next)
}

# -- 4. Sizga tegishli ish ----------------------------------------------------
Say 'sizning vazifalaringiz'
$mine = Invoke-Tool 4 'list_my_tasks' @{}
if (-not $mine.tasks -or $mine.tasks.Count -eq 0) {
    Write-Host "  bitta ham yo'q - doskada o'zingizni ijrochi qilib qo'ying"
}
foreach ($task in ($mine.tasks | Select-Object -First 10)) {
    $mark = ''
    if ($task.checklist -and $task.checklist.total) {
        $mark = " [$($task.checklist.done)/$($task.checklist.total)]"
    }
    $title = if ($task.title.Length -gt 40) { $task.title.Substring(0, 40) } else { $task.title }
    Write-Host ("  {0,-40} {1,-14}{2}" -f $title, $task.column, $mark)
}
if ($mine.warning) { Write-Host "  ogohlantirish: $($mine.warning)" }

# -- 5. Faoliyat izi ---------------------------------------------------------
# Hook mustaqil qatlam: server bilan gaplashmaydi va MCP haqida bilmaydi.
# Shuning uchun tekshiruvi ham mahalliy - fayl, sozlama, jurnal.
Say 'faoliyat izi'
$installer = Join-Path $PSScriptRoot 'hooks\install-hook.py'
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if ((Test-Path -LiteralPath $installer) -and $py) {
    & $py $installer '.' '--check'
} else {
    Write-Host "  hooks\install-hook.py yoki python topilmadi"
}

Say 'tayyor'
