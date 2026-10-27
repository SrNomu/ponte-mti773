"""
Imagens -> ESC/POS raster.

Caminho de uma página que veio do Windows (via IPP):
  1. ajustar à largura imprimível: a página tem 58 mm (463 pontos a 203 dpi),
     mas a cabeça só imprime 48 mm (384 pontos) no centro -> cortamos as laterais
     (por isso anunciamos margens laterais de 5 mm aos programas);
  2. cortar o branco do começo e do fim (as margens do programa);
  3. juntar as páginas uma embaixo da outra (um cupom longo pode vir em várias);
  4. converter para preto e branco: pontilhado (fotos, degradês) ou limiar;
  5. fatiar em faixas e gerar um comando GS v 0 por faixa. Entre faixas a ponte
     pode consultar o status sem risco de cair no meio de uma imagem.
"""

from PIL import Image

from . import escpos
from .impressora import Trabalho

INVERTER = bytes(255 - i for i in range(256))  # tabela para trocar todos os bits de um byte
BRANCO = 245  # tons acima disto contam como papel em branco


def paginas_para_trabalho(paginas, cfg, nome):
    tiras = []
    for img in paginas:
        img = _ajustar_largura(_ajustar_dpi(img.convert("L"), cfg), cfg)
        if cfg.cortar_branco:
            img = _cortar_branco(img)
        if img is not None:
            tiras.append(img)
    if not tiras:
        return None  # tudo em branco

    altura = sum(t.height for t in tiras)
    folha = Image.new("L", (cfg.largura_pontos, altura), 255)
    y = 0
    for t in tiras:
        folha.paste(t, (0, y))
        y += t.height

    blocos = [escpos.inicializar(cfg)] + _faixas(_para_1bit(folha, cfg), cfg.altura_faixa)
    if cfg.linhas_finais:
        blocos.append(escpos.avancar_linhas(cfg.linhas_finais))
    mm = altura * 25.4 / cfg.dpi
    return Trabalho(nome, blocos, descricao=f"imagem {cfg.largura_pontos}x{altura} ({mm:.0f} mm), "
                                            f"{len(paginas)} página(s)")


def _ajustar_dpi(img, cfg):
    dpi = img.info.get("dpi")
    if dpi and dpi[0] and abs(dpi[0] - cfg.dpi) > 1:
        f = cfg.dpi / dpi[0]
        img = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))),
                         Image.Resampling.LANCZOS)
    return img


def _ajustar_largura(img, cfg):
    w = cfg.largura_pontos
    papel = round(cfg.largura_papel_mm / 25.4 * cfg.dpi)  # 58 mm -> 463 pontos
    if img.width > w:
        if img.width <= papel + 2:
            # Página do tamanho do papel: corta as laterais que a cabeça não alcança.
            # O Windows começa a área imprimível exatamente na margem anunciada
            # (5 mm = ponto 40); usar (463 - 384) // 2 = 39 deslocava 1 ponto.
            x = round(cfg.ipp_margem_lateral_mm / 25.4 * cfg.dpi)
            x = max(0, min(x, img.width - w))
            img = img.crop((x, 0, x + w, img.height))
        else:
            # Imagem maior que o papel: reduz mantendo a proporção
            img = img.resize((w, max(1, round(img.height * w / img.width))), Image.Resampling.LANCZOS)
    if img.width < w:
        fundo = Image.new("L", (w, img.height), 255)
        fundo.paste(img, ((w - img.width) // 2, 0))
        img = fundo
    return img


def _cortar_branco(img):
    tinta = img.point(lambda v: 255 if v < BRANCO else 0)  # 255 onde há algo impresso
    caixa = tinta.getbbox()
    if not caixa:
        return None
    return img.crop((0, caixa[1], img.width, caixa[3]))


def _para_1bit(img, cfg):
    if cfg.imagem_modo == "limiar":
        return img.point(lambda v: 255 if v >= cfg.imagem_limiar else 0).convert("1", dither=Image.Dither.NONE)
    # Texto colorido chega como cinza médio (ex.: rosa ~ 100) e o pontilhado o
    # deixa claro e "borrado". A curva v' = 255 * (v/255) ** escurecer (> 1)
    # escurece os tons médios sem mexer no branco (255) nem no preto (0).
    if cfg.imagem_escurecer != 1:
        g = cfg.imagem_escurecer
        img = img.point(lambda v: round(255 * (v / 255) ** g))
    # Pontilhado (Floyd-Steinberg). Antes, quase branco vira branco e quase preto
    # vira preto: o fundo fica limpo e o texto não ganha "chuvisco" em volta.
    img = img.point(lambda v: 255 if v >= 225 else (0 if v <= 30 else v))
    return img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)


def _faixas(mono, altura_faixa) -> list:
    bpl = mono.width // 8
    # No Pillow o bit 1 é branco; no ESC/POS o bit 1 é preto: invertemos tudo
    bruto = mono.tobytes().translate(INVERTER)
    blocos = []
    for y in range(0, mono.height, altura_faixa):
        n = min(altura_faixa, mono.height - y)
        blocos.append(escpos.raster(bruto[y * bpl:(y + n) * bpl], bpl, n))
    return blocos
