# Cria ou remove as duas impressoras da ponte MTI-773 no Windows.
# Chamado pelo instalador (como administrador):
#   impressoras.ps1 -Acao criar     (a ponte precisa estar aberta: o Windows consulta o IPP)
#   impressoras.ps1 -Acao remover
# So mexe nas impressoras "MTI-773 Texto" e "MTI-773" e nas portas delas.
# (Arquivo sem acentos de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.)
param([Parameter(Mandatory = $true)][ValidateSet('criar', 'remover')][string]$Acao)

$ErrorActionPreference = 'Stop'
$pasta = Join-Path $env:ProgramData 'MTI773Ponte'
New-Item -ItemType Directory -Force -Path $pasta | Out-Null
Start-Transcript -Path (Join-Path $pasta "instalador_$Acao.log") -Force | Out-Null

$TEXTO = 'MTI-773 Texto'
$IMAGEM = 'MTI-773'
$PORTA_RAW = 'MTI773_RAW'

function Esperar-Ponte([int]$segundos) {
    # Espera a ponte abrir a porta 631 (IPP)
    $fim = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $fim) {
        $c = New-Object System.Net.Sockets.TcpClient
        try { $c.Connect('127.0.0.1', 631); return $true } catch { Start-Sleep -Milliseconds 500 } finally { $c.Close() }
    }
    return $false
}

$erros = 0
try {
    if ($Acao -eq 'criar') {
        # 1) Impressora de TEXTO: driver "Generic / Text Only" (vem com o Windows) + porta RAW 127.0.0.1:9100
        try {
            Add-PrinterDriver -Name 'Generic / Text Only'
            if (-not (Get-PrinterPort -Name $PORTA_RAW -ErrorAction SilentlyContinue)) {
                Add-PrinterPort -Name $PORTA_RAW -PrinterHostAddress '127.0.0.1' -PortNumber 9100
            }
            if (-not (Get-Printer -Name $TEXTO -ErrorAction SilentlyContinue)) {
                Add-Printer -Name $TEXTO -DriverName 'Generic / Text Only' -PortName $PORTA_RAW
                "criada: $TEXTO"
            } else { "ja existia: $TEXTO" }
        } catch { "ERRO ($TEXTO): $($_.Exception.Message)"; $erros++ }

        # 2) Impressora de IMAGENS/PDF: driver de classe IPP da Microsoft apontando para a ponte
        try {
            if (Get-Printer -Name $IMAGEM -ErrorAction SilentlyContinue) {
                "ja existia: $IMAGEM"
            } elseif (-not (Esperar-Ponte 40)) {
                throw 'a ponte nao abriu a porta 631 a tempo'
            } else {
                Add-Printer -Name $IMAGEM -IppURL 'ipp://127.0.0.1:631/ipp/print'
                "criada: $IMAGEM"
            }
        } catch { "ERRO ($IMAGEM): $($_.Exception.Message)"; $erros++ }
    } else {
        foreach ($nome in $TEXTO, $IMAGEM) {
            $p = Get-Printer -Name $nome -ErrorAction SilentlyContinue
            if (-not $p) { "nao existe: $nome"; continue }
            $porta = $p.PortName
            try {
                Get-PrintJob -PrinterName $nome -ErrorAction SilentlyContinue | Remove-PrintJob -ErrorAction SilentlyContinue
                Remove-Printer -Name $nome
                "removida: $nome"
            } catch { "ERRO ao remover ${nome}: $($_.Exception.Message)"; $erros++; continue }
            # A porta so e removida se nenhuma outra impressora a usa
            if ($porta -and -not (Get-Printer | Where-Object { $_.PortName -eq $porta })) {
                try { Remove-PrinterPort -Name $porta; "porta removida: $porta" }
                catch { "aviso: porta $porta nao removida ($($_.Exception.Message))" }
            }
        }
    }
} finally {
    "concluido com $erros erro(s)"
    Stop-Transcript | Out-Null
}
exit $erros
