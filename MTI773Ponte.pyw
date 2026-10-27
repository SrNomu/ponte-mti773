r"""
Ponto de entrada do executável (MTI773Ponte.exe, feito com PyInstaller).

  MTI773Ponte.exe              abre a ponte com o ícone na bandeja
  MTI773Ponte.exe --teste      (e as outras opções de "python -m ponte")
"""

import sys

if len(sys.argv) > 1:
    from ponte.__main__ import main
    sys.exit(main())
else:
    from ponte.bandeja import main
    sys.exit(main())
