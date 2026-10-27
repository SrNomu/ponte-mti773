"""
PWG Raster (norma PWG 5102.4): o formato de imagem que o Windows manda para
impressoras IPP "sem driver".

Estrutura do arquivo:
  "RaS2"                      (4 bytes de sincronia)
  para cada página:
    cabeçalho de 1796 bytes   (largura, altura, dpi, bits por ponto...)
    linhas comprimidas:
      1 byte  = quantas vezes a linha se repete (valor + 1)
      depois, até completar a linha, pares de controle:
        0..127   -> o próximo ponto se repete (valor + 1) vezes
        128..255 -> seguem (257 - valor) pontos literais
"""

import struct
from dataclasses import dataclass

from PIL import Image, ImageOps

SINCRONIA = b"RaS2"
TAMANHO_CABECALHO = 1796

# Espaços de cor (campo cupsColorSpace)
CINZA = 18   # sgray: 0 = preto, 255 = branco
PRETO = 3    # black: 1 = tinta
RGB = 19     # srgb


@dataclass
class Cabecalho:
    largura: int
    altura: int
    bits_pixel: int
    bytes_linha: int
    espaco_cor: int
    dpi: tuple
    nome_papel: str


def _ler_cabecalho(b: bytes) -> Cabecalho:
    def u32(pos):
        return struct.unpack_from(">I", b, pos)[0]
    return Cabecalho(
        largura=u32(372), altura=u32(376), bits_pixel=u32(388), bytes_linha=u32(392),
        espaco_cor=u32(400), dpi=(u32(276), u32(280)),
        nome_papel=b[1732:1796].split(b"\0")[0].decode("ascii", "replace"),
    )


def ler(dados: bytes) -> list:
    """Devolve a lista de páginas como imagens Pillow em tons de cinza ("L")."""
    if not dados.startswith(SINCRONIA):
        raise ValueError("os dados não são PWG Raster (sem 'RaS2' no início)")
    pos, paginas = 4, []
    try:
        while pos + TAMANHO_CABECALHO <= len(dados):
            cab = _ler_cabecalho(dados[pos:pos + TAMANHO_CABECALHO])
            pos += TAMANHO_CABECALHO
            bruto, pos = _descomprimir(dados, pos, cab)
            paginas.append(_para_imagem(bruto, cab))
    except (IndexError, struct.error) as e:
        raise ValueError(f"PWG Raster truncado ou corrompido ({e})") from e
    return paginas


def _descomprimir(dados, pos, cab):
    unidade = max(1, cab.bits_pixel // 8)  # bytes por "ponto" na compressão
    bpl = cab.bytes_linha
    saida, y = bytearray(), 0
    while y < cab.altura:
        repete = dados[pos] + 1
        pos += 1
        linha = bytearray()
        while len(linha) < bpl:
            c = dados[pos]
            pos += 1
            if c < 128:
                linha += dados[pos:pos + unidade] * (c + 1)
                pos += unidade
            else:
                n = (257 - c) * unidade
                linha += dados[pos:pos + n]
                pos += n
        del linha[bpl:]
        repete = min(repete, cab.altura - y)
        saida += bytes(linha) * repete
        y += repete
    return bytes(saida), pos


def _para_imagem(bruto, cab) -> Image.Image:
    tam = (cab.largura, cab.altura)
    if cab.bits_pixel == 8 and cab.espaco_cor == CINZA:
        img = Image.frombytes("L", tam, bruto)
    elif cab.bits_pixel == 8 and cab.espaco_cor == PRETO:
        img = ImageOps.invert(Image.frombytes("L", tam, bruto))
    elif cab.bits_pixel == 1:
        img = Image.frombytes("1", tam, bruto).convert("L")  # no Pillow, bit 1 = branco
        if cab.espaco_cor == PRETO:
            img = ImageOps.invert(img)
    elif cab.bits_pixel == 24 and cab.espaco_cor == RGB:
        img = Image.frombytes("RGB", tam, bruto).convert("L")
    else:
        raise ValueError(f"tipo de PWG não suportado: {cab.bits_pixel} bits, espaço de cor {cab.espaco_cor}")
    img.info["dpi"] = cab.dpi
    img.info["papel"] = cab.nome_papel
    return img


# --- escrita (para testes: o cliente IPP de teste faz o papel do Windows) ---
def escrever(paginas, dpi=203) -> bytes:
    saida = bytearray(SINCRONIA)
    for img in paginas:
        img = img.convert("L")
        saida += _cabecalho(img.width, img.height, dpi, len(paginas))
        saida += _comprimir(img.tobytes(), img.width, img.height)
    return bytes(saida)


def _cabecalho(w, h, dpi, total) -> bytes:
    b = bytearray(TAMANHO_CABECALHO)
    b[0:9] = b"PwgRaster"
    struct.pack_into(">II", b, 276, dpi, dpi)                                  # resolução
    struct.pack_into(">II", b, 352, round(w * 72 / dpi), round(h * 72 / dpi))  # tamanho em pontos tipográficos
    struct.pack_into(">II", b, 372, w, h)                                      # largura, altura
    struct.pack_into(">IIIII", b, 384, 8, 8, w, 0, CINZA)                      # bits/cor, bits/ponto, bytes/linha, ordem, espaço
    struct.pack_into(">I", b, 420, 1)                                          # número de cores
    struct.pack_into(">I", b, 452, total)                                      # total de páginas
    return bytes(b)


def _comprimir(bruto, w, h) -> bytes:
    saida, y = bytearray(), 0
    while y < h:
        linha = bruto[y * w:(y + 1) * w]
        rep = 1
        while y + rep < h and rep < 256 and bruto[(y + rep) * w:(y + rep + 1) * w] == linha:
            rep += 1
        saida.append(rep - 1)
        saida += _comprimir_linha(linha)
        y += rep
    return bytes(saida)


def _comprimir_linha(linha) -> bytes:
    saida, i, n = bytearray(), 0, len(linha)
    while i < n:
        j = i + 1
        while j < n and j - i < 128 and linha[j] == linha[i]:
            j += 1
        if j - i >= 2:  # repetição
            saida += bytes([j - i - 1, linha[i]])
            i = j
            continue
        j = i + 1  # literais, até começar uma repetição (máx. 128)
        while j < n and j - i < 128 and not (j + 1 < n and linha[j] == linha[j + 1]):
            j += 1
        k = j - i
        saida += bytes([0, linha[i]]) if k == 1 else bytes([257 - k]) + linha[i:j]
        i = j
    return bytes(saida)
