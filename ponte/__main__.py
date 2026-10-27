r"""
Linha de comando da ponte.

  python -m ponte                     roda a ponte (servidor 127.0.0.1:9100) até Ctrl+C
  python -m ponte --teste             imprime uma página de teste e sai
  python -m ponte --imprimir X.txt    imprime um arquivo (texto ou ESC/POS) e sai
  python -m ponte --calibrar          imprime a régua para calibrar o avanço final
  python -m ponte --config C:\x.ini   usa outro arquivo de configuração
"""

import argparse
import sys
import time
from pathlib import Path

from . import config
from .app import Ponte, texto_pagina_teste


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ponte", description="Ponte de impressão MTI-773")
    p.add_argument("--config", type=Path, help="caminho do config.ini")
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--teste", action="store_true", help="imprime uma página de teste e sai")
    grupo.add_argument("--imprimir", type=Path, metavar="ARQUIVO", help="imprime um arquivo e sai")
    grupo.add_argument("--calibrar", action="store_true",
                       help="imprime a régua para calibrar o avanço final (linhas_finais)")
    args = p.parse_args(argv)

    try:
        ponte = Ponte(config.carregar(args.config))
    except ValueError as e:  # erro no config.ini
        print(f"Erro de configuração: {e}", file=sys.stderr)
        return 2

    if args.teste:
        ponte.imprimir_e_sair(texto_pagina_teste().encode("utf-8"), "pagina de teste")
        return 0
    if args.imprimir:
        ponte.imprimir_e_sair(args.imprimir.read_bytes(), f"arquivo {args.imprimir.name}")
        return 0
    if args.calibrar:
        ponte.calibrar()
        return 0

    try:
        ponte.iniciar()
    except RuntimeError as e:  # ex.: porta 9100 ou 631 já em uso
        ponte.log.error("%s", e)
        ponte.parar()
        return 1
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ponte.parar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
