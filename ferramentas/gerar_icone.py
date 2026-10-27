"""Gera o ícone do programa/instalador (o mesmo desenho da bandeja, em verde).

  python ferramentas\\gerar_icone.py instalador\\ponte.ico
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ponte.bandeja import CORES, desenhar_icone  # noqa: E402

destino = Path(sys.argv[1] if len(sys.argv) > 1 else "ponte.ico")
desenhar_icone(CORES["ok"]).resize((256, 256)).save(
    destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
print(f"ícone salvo em {destino}")
