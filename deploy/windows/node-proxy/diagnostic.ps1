# MYCOGEN V2 — diagnostic réseau / pare-feu (lecture seule, sans droits administrateur).
# Lancer avec diagnostic.bat, sur le serveur.
$ErrorActionPreference = 'Continue'
$config = Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$portWeb = [int]$config.web.ecoute_port
$portCible = [int]$config.web.cible_port

function Titre($t) { Write-Host ''; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Ok($t) { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Ko($t) { Write-Host "  [!!]   $t" -ForegroundColor Yellow }
function Info($t) { Write-Host "         $t" }

Titre 'Node.js'
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) { Ok "node : $($node.Source)  ($(& node --version))" } else { Ko 'node introuvable dans le PATH' }

Titre 'Profil du réseau (le pare-feu est plus strict en « Public »)'
try {
    Get-NetConnectionProfile -ErrorAction Stop | ForEach-Object {
        $msg = "$($_.InterfaceAlias) : $($_.NetworkCategory)"
        if ($_.NetworkCategory -eq 'Public') { Ko $msg } else { Ok $msg }
    }
} catch { Ko "lecture impossible ($($_.Exception.Message))" }

Titre 'Règles du pare-feu qui autorisent node.exe'
$regleNode = $false
try {
    $filtres = Get-NetFirewallApplicationFilter -ErrorAction Stop | Where-Object { $_.Program -like '*node.exe' }
    foreach ($f in $filtres) {
        $r = $f | Get-NetFirewallRule
        if ($r.Direction -ne 'Inbound') { continue }
        $ports = ($r | Get-NetFirewallPortFilter)
        $msg = "« $($r.DisplayName) »  action=$($r.Action) activée=$($r.Enabled) profils=$($r.Profile) " +
               "protocole=$($ports.Protocol) ports=$($ports.LocalPort)"
        if ($r.Action -eq 'Allow' -and $r.Enabled -eq 'True') { Ok $msg; $regleNode = $true } else { Ko $msg }
        Info "programme : $($f.Program)"
        if ($node -and ($f.Program -ne $node.Source) -and ($f.Program -notlike '%*')) {
            Info "(attention : ce n'est pas le même node.exe que celui du PATH)"
        }
    }
    if (-not $filtres) { Ko 'aucune règle trouvée pour node.exe' }
} catch { Ko "lecture des règles impossible ($($_.Exception.Message))" }
if ($regleNode) {
    Info "Si « ports » vaut Any : la passerelle peut utiliser n'importe quel port (ici $portWeb)."
    Info "Sinon : mettre l'un de ces ports dans config.json (web.ecoute_port), au besoin celui de MYCOGEN V1."
}

Titre "Règles du pare-feu sur le port $portWeb"
try {
    $pf = Get-NetFirewallPortFilter -ErrorAction Stop | Where-Object { $_.LocalPort -eq "$portWeb" }
    if (-not $pf) { Info 'aucune règle spécifique à ce port' }
    foreach ($p in $pf) {
        $r = $p | Get-NetFirewallRule
        Info "« $($r.DisplayName) »  $($r.Direction) $($r.Action) activée=$($r.Enabled) profils=$($r.Profile)"
    }
} catch { Ko "lecture impossible ($($_.Exception.Message))" }

Titre 'WSL'
$env:WSL_UTF8 = '1'
try { wsl.exe -l -v } catch { Ko 'wsl.exe indisponible' }

Titre 'Ports à l''écoute'
function Ecoute($port, $libelle) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($c) {
        foreach ($x in $c) {
            $p = Get-Process -Id $x.OwningProcess -ErrorAction SilentlyContinue
            Ok "$libelle : $($x.LocalAddress):$port  (processus : $($p.ProcessName))"
        }
    } else { Ko "$libelle : personne n'écoute sur le port $port" }
}
Ecoute $portWeb 'passerelle (réseau)'
Ecoute $portCible 'MYCOGEN Django (local)'
Info "(en mode réseau WSL « miroir », MYCOGEN apparaît ici ; en mode NAT il est relayé par wslrelay)"

Titre 'MYCOGEN répond-il ?'
foreach ($u in @("http://127.0.0.1:$portCible/", "http://127.0.0.1:$portWeb/")) {
    try {
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 10 -MaximumRedirection 0 -ErrorAction Stop
        Ok "$u -> HTTP $($r.StatusCode)"
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -and $code -lt 500) { Ok "$u -> HTTP $code" } else { Ko "$u -> $($_.Exception.Message)" }
    }
}

Write-Host ''
Write-Host 'Depuis un autre PC du labo, ouvrir : ' -NoNewline
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.InterfaceAlias -notlike 'vEthernet*' }
Write-Host (($ips | ForEach-Object { "http://$($_.IPAddress):$portWeb" }) -join '   ') -ForegroundColor Green
