r"""
Consulta SOMENTE LEITURA da MTI-773 pela USB: não imprime nem avança papel.

Envia apenas comandos documentados de consulta do ESC/POS, um de cada vez,
e mostra a resposta em hexadecimal e em texto. Se aparecer um erro de status
que não existia no início, para imediatamente.

A única exceção ao "só leitura" é o GS a (Automatic Status Back), que liga uma
opção TEMPORÁRIA. O script sempre a desliga no final (GS a 0).

Uso:  python ferramentas\consulta_somente_leitura.py
"""

import sys
import time

# Reaproveitamos a parte de baixo nível (abrir o USB, ler e escrever com timeout)
from diagnostico_usb import (
    DLE, EOT, GS, FILE_FLAG_OVERLAPPED, FILE_SHARE_READ, FILE_SHARE_WRITE,
    GENERIC_READ, GENERIC_WRITE, INVALID_HANDLE_VALUE, OPEN_EXISTING,
    ctypes, descrever_status, escrever, id_1284, kernel32, ler, ler_status,
    listar_impressoras_usb,
)


class ErroNovo(Exception):
    """Apareceu um erro de status que não existia no começo."""


def formatar(dados: bytes) -> str:
    """Mostra bytes como 'hex | texto' (caracteres não imprimíveis viram '.')."""
    if not dados:
        return "(sem resposta)"
    hexa = " ".join(f"{b:02X}" for b in dados)
    texto = "".join(chr(b) if 32 <= b < 127 else "." for b in dados)
    return f"{hexa}  |  {texto}"


def ler_resposta(h, espera_ms=1500, fim_ms=300) -> bytes:
    """Lê uma resposta que pode chegar em vários pacotes USB:
    espera até `espera_ms` pelo primeiro pacote e depois continua lendo
    enquanto chegarem pacotes com menos de `fim_ms` de intervalo."""
    dados = ler(h, 256, espera_ms)
    while dados:
        mais = ler(h, 256, fim_ms)
        if not mais:
            break
        dados += mais
    return dados


def descartar_pendentes(h):
    """Se sobrou algo para ler (ex.: resposta atrasada), mostramos e descartamos,
    para não confundir com a resposta do próximo comando."""
    sobra = ler_resposta(h, espera_ms=150, fim_ms=100)
    if sobra:
        print(f"    (dados pendentes descartados: {formatar(sobra)})")


def consultar(h, nome, comando: bytes, problemas_iniciais):
    descartar_pendentes(h)
    escrever(h, comando, verbose=False)
    resp = ler_resposta(h)
    print(f"  {nome:<34} [{comando.hex(' ').upper()}] -> {formatar(resp)}")

    # Vigia: confere se surgiu algum erro novo depois deste comando
    desc = descrever_status(ler_status(h))
    novos = set(desc.split(", ")) - problemas_iniciais - {"OK"}
    if novos:
        raise ErroNovo(f"depois de {nome}: {desc}")
    return resp


def main():
    alvo = [c for c in listar_impressoras_usb() if "VID_28E9&PID_0289" in c.upper()]
    if not alvo:
        print("MTI-773 (VID_28E9 PID_0289) não encontrada.")
        return 1

    h = kernel32.CreateFileW(alvo[0], GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if h == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    asb_ligado = False
    try:
        print("ID IEEE 1284 (via Windows):", id_1284(h))

        st = ler_status(h)
        desc_inicial = descrever_status(st)
        print("Status inicial:", " ".join("--" if v is None else f"{v:02X}" for v in st.values()),
              "->", desc_inicial)
        problemas_iniciais = set(desc_inicial.split(", "))

        print("\n1) DLE EOT (status em tempo real)")
        for n in (1, 2, 3, 4):
            consultar(h, f"DLE EOT {n}", DLE + EOT + bytes([n]), problemas_iniciais)

        print("\n2) GS r (status de papel / gaveta)")
        for n, nome in ((1, "GS r 1 (sensor de papel)"), (2, "GS r 2 (gaveta)")):
            consultar(h, nome, GS + b"r" + bytes([n]), problemas_iniciais)

        print("\n3) GS I (identificacao)")
        ids = [(1, "ID do modelo"), (2, "ID do tipo"), (3, "ID da versao"),
               (65, "firmware"), (66, "fabricante"), (67, "nome do modelo"),
               (68, "numero de serie"), (69, "fonte / idioma")]
        for n, nome in ids:
            consultar(h, f"GS I {n} ({nome})", GS + b"I" + bytes([n]), problemas_iniciais)

        print("\n4) GS a (Automatic Status Back)")
        descartar_pendentes(h)
        # 0x0F = avisar mudanças de gaveta, online/offline, erro e sensor de papel
        escrever(h, GS + b"a\x0f", verbose=False)
        asb_ligado = True
        print("  ASB ligado; escutando por 15 s (abrir/fechar a tampa deve gerar mensagens)...")
        inicio = time.monotonic()
        recebeu = False
        while time.monotonic() - inicio < 15:
            msg = ler_resposta(h, espera_ms=500, fim_ms=100)
            if msg:
                recebeu = True
                print(f"  t={time.monotonic() - inicio:5.1f}s  {formatar(msg)}")
        if not recebeu:
            print("  nenhuma mensagem automatica recebida")
    except ErroNovo as e:
        print(f"\n*** PAREI: apareceu um erro novo ({e}). Se estiver apitando, tire o cabo USB.")
        return 2
    finally:
        if asb_ligado:
            escrever(h, GS + b"a\x00", verbose=False)  # desliga o ASB (volta ao padrão)
            print("  ASB desligado de novo (GS a 0)")
        kernel32.CloseHandle(h)

    print("\nStatus final: (consulta concluida sem erros novos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
