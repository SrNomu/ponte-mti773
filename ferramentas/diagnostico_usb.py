r"""
Diagnóstico da MTI-773 pela USB, SEM driver e SEM fila de impressão.

Como funciona:
  Quando uma impressora USB é ligada, o driver "usbprint" do Windows cria um
  "caminho de dispositivo" (device interface), algo como:
      \\?\USB#VID_28E9&PID_0289#000000000004#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}
  Esse GUID no final identifica a classe "impressora USB". Abrindo esse caminho
  com CreateFile, podemos escrever bytes (imprimir) e ler bytes (status),
  exatamente como se fosse um arquivo.

  Usamos I/O "overlapped" (assíncrono) só para poder ter TIMEOUT na leitura:
  se a impressora não responder, uma leitura comum ficaria travada para sempre.

Uso:  python ferramentas\diagnostico_usb.py
"""

import ctypes
import sys
import time
import winreg
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# GUID da classe de interface "impressora USB" (GUID_DEVINTERFACE_USBPRINT)
GUID_USBPRINT = "{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"

# Constantes da API do Windows
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# IOCTL que pede a "identidade" IEEE 1284 da impressora (texto tipo "MFG:...;MDL:...;")
IOCTL_USBPRINT_GET_1284_ID = 0x220034


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.c_void_p, ctypes.POINTER(OVERLAPPED)]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.c_void_p, ctypes.POINTER(OVERLAPPED)]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                     ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def listar_impressoras_usb():
    """Lê do registro os caminhos de todas as impressoras USB conectadas."""
    chave = rf"SYSTEM\CurrentControlSet\Control\DeviceClasses\{GUID_USBPRINT}"
    caminhos = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, chave) as k:
            i = 0
            while True:
                try:
                    nome = winreg.EnumKey(k, i)  # ex.: ##?#USB#VID_28E9&PID_0289#...#{GUID}
                except OSError:
                    break
                i += 1
                # No registro o "\" vira "#"; os 4 primeiros caracteres "##?#" = "\\?\"
                caminhos.append("\\\\?\\" + nome[4:])
    except FileNotFoundError:
        pass
    return caminhos


def _io(handle, func, timeout_ms, *args):
    """Executa uma operação overlapped e espera no máximo timeout_ms.
    Retorna o número de bytes transferidos (0 se deu timeout)."""
    ov = OVERLAPPED()
    ov.hEvent = kernel32.CreateEventW(None, True, False, None)
    try:
        ok = func(handle, *args, None, ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise ctypes.WinError(err)
        if kernel32.WaitForSingleObject(ov.hEvent, timeout_ms) != WAIT_OBJECT_0:
            # Não respondeu a tempo: cancelamos a operação
            kernel32.CancelIoEx(handle, ctypes.byref(ov))
        n = wintypes.DWORD(0)
        kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(n), True)
        return n.value
    finally:
        kernel32.CloseHandle(ov.hEvent)


def escrever(h, dados: bytes, timeout_ms=10000, verbose=True):
    buf = ctypes.create_string_buffer(dados, len(dados))
    n = _io(h, kernel32.WriteFile, timeout_ms, buf, len(dados))
    if verbose:
        print(f"  escreveu {n}/{len(dados)} bytes")
    return n


def ler(h, tamanho=64, timeout_ms=1500) -> bytes:
    buf = ctypes.create_string_buffer(tamanho)
    n = _io(h, kernel32.ReadFile, timeout_ms, buf, tamanho)
    return buf.raw[:n]


def id_1284(h) -> str:
    buf = ctypes.create_string_buffer(1024)
    n = _io(h, kernel32.DeviceIoControl, 3000, IOCTL_USBPRINT_GET_1284_ID, None, 0, buf, 1024)
    # Os 2 primeiros bytes são o tamanho (big-endian); o resto é texto
    return buf.raw[2:n].decode("latin-1", "replace") if n > 2 else "(sem resposta)"


# ---------------------------------------------------------------------------
# Comandos ESC/POS usados no teste
ESC, GS, DLE, EOT, FS = b"\x1b", b"\x1d", b"\x10", b"\x04", b"\x1c"
INICIALIZAR = ESC + b"@"
# A placa GEZHI aceita caracteres chineses de 2 bytes (GS I 2 = 0x03, bit 0).
# No modo chinês, todo byte > 127 (onde ficam ç, ã, é) vira metade de um
# caractere chinês. FS . desliga esse modo.
DESLIGAR_CHINES = FS + b"."


def barra_raster(largura=384, altura=24) -> bytes:
    """Imagem de teste em GS v 0: barra preta com 'janelas' brancas a cada 48 pontos.
    Se a barra sair inteira, a largura de 384 pontos está certa."""
    bpl = largura // 8  # bytes por linha (cada byte = 8 pontos)
    linhas = []
    for y in range(altura):
        linha = bytearray(b"\xff" * bpl)  # tudo preto
        if 6 <= y < altura - 6:
            for x in range(0, bpl, 6):  # a cada 48 pontos (6 bytes), abre um vão branco
                linha[x + 2] = 0x00
                linha[x + 3] = 0x00
        linhas.append(bytes(linha))
    cab = GS + b"v0" + b"\x00" + bytes([bpl & 0xFF, bpl >> 8, altura & 0xFF, altura >> 8])
    return cab + b"".join(linhas)


LARGURA_COLUNAS = 32  # fonte padrão (12 pontos) em 384 pontos = 32 caracteres


def ler_status(h):
    """Pergunta os 4 tipos de status (DLE EOT 1..4). Retorna {n: byte ou None}."""
    st = {}
    for n in (1, 2, 3, 4):
        escrever(h, DLE + EOT + bytes([n]), verbose=False)
        resp = ler(h, 64, 800)
        st[n] = resp[-1] if resp else None  # o último byte é a resposta mais recente
    return st


def descrever_status(st) -> str:
    """Traduz os bits do status ESC/POS para português."""
    if any(v is None for v in st.values()):
        return "sem resposta"
    problemas = []
    if st[1] & 0x08: problemas.append("offline")
    if st[2] & 0x04: problemas.append("tampa aberta")
    if st[2] & 0x20: problemas.append("parou por falta de papel")
    if st[2] & 0x40: problemas.append("erro")
    if st[3] & 0x20: problemas.append("erro irrecuperavel")
    if st[3] & 0x40: problemas.append("erro auto-recuperavel (ex.: cabeca quente / tensao)")
    if st[4] & 0x60: problemas.append("sem papel")
    elif st[4] & 0x0C: problemas.append("papel acabando")
    return ", ".join(problemas) or "OK"


def esperar_pronta(h, limite_s=5.0) -> bool:
    """Consulta o status até a impressora estar OK ou estourar o tempo."""
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite_s:
        if descrever_status(ler_status(h)) == "OK":
            return True
        time.sleep(0.2)
    return False


def enviar_em_pedacos(h, linhas, tamanho=64, pausa_s=0.05) -> bool:
    """Agrupa LINHAS INTEIRAS em pedaços de até `tamanho` bytes.
    Nunca cortamos no meio de uma linha: assim um comando como "ESC t n"
    não fica partido em dois envios com um DLE EOT no meio."""
    pedacos, atual = [], b""
    for linha in linhas:
        if atual and len(atual) + len(linha) > tamanho:
            pedacos.append(atual)
            atual = b""
        atual += linha
    if atual:
        pedacos.append(atual)

    for i, p in enumerate(pedacos, 1):
        if not esperar_pronta(h):
            print(f"  pedaco {i}: impressora NAO ficou pronta: {descrever_status(ler_status(h))}")
            return False
        n = escrever(h, p, verbose=False)
        print(f"  pedaco {i}/{len(pedacos)}: {n}/{len(p)} bytes")
        time.sleep(pausa_s)
    return True


def monitorar(h, duracao_s=15.0, intervalo_s=0.5):
    """Depois do envio, a impressora ainda está imprimindo fisicamente.
    Observamos o status nesse período para flagrar o momento de um alarme."""
    print(f"  observando o status por {duracao_s:.0f}s (mostra só quando muda)...")
    inicio, anterior = time.monotonic(), None
    while time.monotonic() - inicio < duracao_s:
        st = ler_status(h)
        desc = descrever_status(st)
        if desc != anterior:
            bytes_hex = " ".join("--" if v is None else f"{v:02X}" for v in st.values())
            print(f"  t={time.monotonic() - inicio:5.1f}s  [{bytes_hex}]  {desc}")
            anterior = desc
        time.sleep(intervalo_s)


def teste_acentos(h):
    """Só texto, linhas de no máximo 32 caracteres, enviado em pedaços."""
    frase = "ação ÁÉÍÓÚ çÇ ãõ âêô à ü"  # 25 caracteres
    linhas = [
        INICIALIZAR + DESLIGAR_CHINES,
        b"TESTE 3 - ACENTOS + FS . (USB)\n",
        b"12345678901234567890123456789012\n",  # régua de exatamente 32 colunas
    ]
    for n, codec in [(2, "cp850"), (3, "cp860"), (16, "cp1252")]:
        linhas.append(ESC + b"t" + bytes([n]) + f"ESC t {n} = {codec}:\n".encode("ascii"))
        linhas.append(frase.encode(codec) + b"\n")
    linhas.append(b"--- fim ---\n" + ESC + b"d\x03")
    for l in linhas:  # conferência: nenhuma linha visível passa de 32 colunas
        assert len(l.rstrip(b"\n")) <= LARGURA_COLUNAS + 3, l

    print("\nStatus antes:", descrever_status(ler_status(h)))
    print("Enviando texto em pedacos de 64 bytes:")
    if enviar_em_pedacos(h, linhas):
        monitorar(h)


def main():
    caminhos = listar_impressoras_usb()
    print("Impressoras USB encontradas:")
    for c in caminhos:
        print("  ", c)
    alvo = [c for c in caminhos if "VID_28E9&PID_0289" in c.upper()]
    if not alvo:
        print("MTI-773 (VID_28E9 PID_0289) não encontrada.")
        return 1
    caminho = alvo[0]

    h = kernel32.CreateFileW(caminho, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if h == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        # A barra raster (barra_raster) fica para um teste separado, em faixas pequenas.
        teste_acentos(h)
    finally:
        kernel32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
