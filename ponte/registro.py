"""
Log da ponte: grava em <pasta de dados>\\ponte.log e, se houver console, mostra na tela.

O arquivo "gira" ao chegar em 1 MB (ponte.log.1, .2, .3), para nunca encher o disco.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler


def configurar(cfg) -> logging.Logger:
    log = logging.getLogger("ponte")
    if log.handlers:  # já configurado (ex.: Ponte criada duas vezes no mesmo processo)
        return log
    log.setLevel(cfg.nivel_log)
    formato = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s")

    arquivo = RotatingFileHandler(cfg.pasta / "ponte.log", maxBytes=1_000_000,
                                  backupCount=3, encoding="utf-8")
    arquivo.setFormatter(formato)
    log.addHandler(arquivo)

    # Num executável "janela" (sem console) sys.stderr é None
    if sys.stderr is not None:
        try:
            sys.stderr.reconfigure(errors="replace")  # acentos nunca derrubam o log
        except (AttributeError, ValueError):
            pass
        tela = logging.StreamHandler(sys.stderr)
        tela.setFormatter(formato)
        log.addHandler(tela)
    return log
