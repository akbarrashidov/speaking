<#
  aiwork klientini loyihaga o'rnatish (Windows).

      .\install.ps1 -Target C:\projects\mening-loyiham
      .\install.ps1 -Target C:\projects\x -NoHook     # faoliyat izisiz

  Ko'chirishlardan iborat va boshqa hech narsa qilmaydi. Mavjud .mcp.json va
  CLAUDE.md ustiga yozilmaydi: ular loyihaniki, biznikimas.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Target,
    [switch]$NoHook
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    Write-Error "Papka topilmadi: $Target"
}

function Say($text) { Write-Host "  $text" }

# -- 1. MCP ulanishi ---------------------------------------------------------
$mcpTarget = Join-Path $Target '.mcp.json'
if (Test-Path -LiteralPath $mcpTarget) {
    $same = (Get-Content -Raw -LiteralPath $mcpTarget) -eq (Get-Content -Raw -LiteralPath (Join-Path $here '.mcp.json'))
    if ($same) { Say ".mcp.json - allaqachon o'rnida" }
    else { Say ".mcp.json BOR va boshqacha - tegilmadi. O'zingiz solishtiring: $mcpTarget" }
} else {
    Copy-Item -LiteralPath (Join-Path $here '.mcp.json') -Destination $mcpTarget
    Say ".mcp.json ko'chirildi"
}

# -- 2. Qoidalar -------------------------------------------------------------
# Skill ustiga yoziladi ataylab: u qoidalarning yagona manbasi, va eskirgan
# nusxa bilan ishlagan agent xatosini bir oydan keyin payqashadi.
$skillDir = Join-Path $Target '.claude\skills\aiwork'
New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
Copy-Item -LiteralPath (Join-Path $here 'skills\aiwork\SKILL.md') -Destination (Join-Path $skillDir 'SKILL.md') -Force
Say ".claude\skills\aiwork\SKILL.md yangilandi"

# -- 3. CLAUDE.md ------------------------------------------------------------
$claudeMd = Join-Path $Target 'CLAUDE.md'
$snippet = Get-Content -Raw -LiteralPath (Join-Path $here 'CLAUDE.md.snippet')
$has = (Test-Path -LiteralPath $claudeMd) -and ((Get-Content -Raw -LiteralPath $claudeMd) -match 'aiwork board over MCP')
if ($has) {
    Say "CLAUDE.md - aiwork bo'limi allaqachon bor"
} else {
    if (-not (Test-Path -LiteralPath $claudeMd)) { New-Item -ItemType File -Path $claudeMd | Out-Null }
    Add-Content -LiteralPath $claudeMd -Value "`r`n$snippet" -Encoding utf8
    Say "CLAUDE.md ga aiwork bo'limi qo'shildi"
}

# -- 4. Faoliyat izi (hook) --------------------------------------------------
# Ko'rsatma ehtimollikni oshiradi, kafolat bermaydi. Hook deterministik: uni
# Claude Code runtime majburan chaqiradi, model qarori qatnashmaydi. Shuning
# uchun u ko'rsatmaning o'rnini emas, YONINI egallaydi: hisobot yozmaydi, faqat
# "ish bo'ldi" faktini qayd qiladi.
if ($NoHook) {
    Say "faoliyat izi: -NoHook berilgan, o'tkazib yuborildi"
} else {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
    if ($py) { & $py (Join-Path $here 'hooks\install-hook.py') $Target }
    else { Say "faoliyat izi: python topilmadi, hook o'rnatilmadi" }
}

# -- 5. Kalit ----------------------------------------------------------------
if (-not $env:AIWORK_TOKEN) {
    Write-Host ""
    Write-Warning "AIWORK_TOKEN muhitda yo'q. Qo'shing:  setx AIWORK_TOKEN `"...`""
    Write-Warning "setx yangi oynalarga ta'sir qiladi - terminalni qayta oching. Usiz har chaqiruv 401."
}

Write-Host ""
Say "Tayyor. Endi tekshiring:  .\check.ps1"
