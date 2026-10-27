r"""
Teste da tampa / sensores, SEM imprimir.

Liga o Automatic Status Back (GS a), escuta por N segundos as mensagens que a
impressora manda sozinha quando algo muda (abrir a tampa, acabar o papel...)
e desliga o ASB no final.

Uso:  python ferramentas\teste_tampa.py [segundos]
"""

import sys
import time

from consulta_somente_leitura import formatar, ler_resposta
from diagnostico_usb import (
    GS, FILE_FLAG_OVERLAPPED, FILE_SHARE_READ, FILE_SHARE_WRITE, GENERIC_READ,
    GENERIC_WRITE, INVALID_HANDLE_VALUE, OPEN_EXISTING, ctypes, descrever_status,
    escrever, kernel32, ler_status, listar_impressoras_usb,
)


def descrever_asb(m: bytes) -> str:
    """Traduz a mensagem de 4 bytes do ASB (formato Epson)."""
    if len(m) != 4:
        return "formato inesperado"
    b1, b2, b3, _ = m
    itens = []
    if b1 & 0x08: itens.append("offline")
    if b1 & 0x20: itens.append("tampa aberta")
    if b1 & 0x40: itens.append("botao de avanco pressionado")
    if b2 & 0x08: itens.append("erro de guilhotina")
    if b2 & 0x20: itens.append("erro irrecuperavel")
    if b2 & 0x40: itens.append("erro auto-recuperavel")
    if b3 & 0x0C: itens.append("sem papel")
    elif b3 & 0x03: itens.append("papel acabando")
    return ", ".join(itens) or "OK"


def main():
    segundos = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    alvo = [c for c in listar_impressoras_usb() if "VID_28E9&PID_0289" in c.upper()]
    if not alvo:
        print("MTI-773 não encontrada.")
        return 1
    h = kernel32.CreateFileW(alvo[0], GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if h == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        print("Status antes:", descrever_status(ler_status(h)))
        ler_resposta(h, 150, 100)  # descarta sobras
        escrever(h, GS + b"a\x0f", verbose=False)
        print(f"ASB ligado; escutando por {segundos:.0f}s...")
        inicio = time.monotonic()
        while time.monotonic() - inicio < segundos:
            msg = ler_resposta(h, espera_ms=300, fim_ms=50)
            # Pode chegar mais de uma mensagem junta: separamos de 4 em 4 bytes
            for i in range(0, len(msg), 4):
                parte = msg[i:i + 4]
                print(f"  t={time.monotonic() - inicio:5.1f}s  {formatar(parte):<24} -> {descrever_asb(parte)}")
    finally:
        escrever(h, GS + b"a\x00", verbose=False)
        print("ASB desligado (GS a 0)")
        ler_resposta(h, 300, 100)
        print("Status depois:", descrever_status(ler_status(h)))
        kernel32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
