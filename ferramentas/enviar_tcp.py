"""
Envia um arquivo (ou um texto) para a ponte pela porta TCP, imitando o que a
impressora do Windows faz: conecta, manda os bytes e fecha.

Uso:
  python ferramentas\\enviar_tcp.py arquivo.txt
  python ferramentas\\enviar_tcp.py --texto "Olá, ação!"
  python ferramentas\\enviar_tcp.py --teste          (página de teste da ponte)
"""

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # para achar o pacote "ponte"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("arquivo", nargs="?", type=Path)
    p.add_argument("--texto")
    p.add_argument("--teste", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=9100)
    a = p.parse_args()

    if a.teste:
        from ponte.app import texto_pagina_teste
        dados = texto_pagina_teste().encode("utf-8")
    elif a.texto is not None:
        dados = a.texto.encode("utf-8")
    elif a.arquivo:
        dados = a.arquivo.read_bytes()
    else:
        p.error("informe um arquivo, --texto ou --teste")

    with socket.create_connection((a.host, a.porta), timeout=5) as s:
        s.sendall(dados)
    print(f"enviados {len(dados)} bytes para {a.host}:{a.porta}")


if __name__ == "__main__":
    main()
