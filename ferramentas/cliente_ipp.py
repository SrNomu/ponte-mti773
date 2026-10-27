r"""
Cliente IPP de teste: faz o papel do Windows para testar o servidor IPP da
ponte SEM precisar criar a impressora no Windows.

  python ferramentas\cliente_ipp.py --atributos        mostra o que a "impressora" anuncia
  python ferramentas\cliente_ipp.py --teste            imprime a página de teste (imagem)
  python ferramentas\cliente_ipp.py --imagem logo.png  imprime uma imagem qualquer
  python ferramentas\cliente_ipp.py --salvar-teste X.png   só salva a página de teste
"""

import argparse
import http.client
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from ponte import ipp, pwg  # noqa: E402

DPI = 203
LARGURA_PAGINA = round(58 / 25.4 * DPI)  # 463 pontos = 58 mm
AREA = 384                               # largura imprimível (48 mm)


def fonte(tamanho, negrito=False):
    try:
        return ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf" if negrito else r"C:\Windows\Fonts\arial.ttf",
                                  tamanho)
    except OSError:
        return ImageFont.load_default(tamanho)


def pagina_teste() -> Image.Image:
    """Página de 58 mm como o Windows mandaria; o conteúdo fica nos 48 mm do centro."""
    w, h = LARGURA_PAGINA, 760
    m = (w - AREA) // 2  # 39: começo da área imprimível
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([m, 0, m + AREA - 1, 600], outline=0, width=2)  # borda da área imprimível
    d.text((m + 10, 10), "TESTE 7 - IMAGEM (IPP)", font=fonte(24, True), fill=0)
    d.text((m + 10, 45), "ação ÁÉÍÓÚ çÇ ãõ", font=fonte(24), fill=0)
    d.text((m + 10, 80), "Texto 14 px: Batom R$ 39,90", font=fonte(14), fill=0)
    d.text((m + 10, 100), "Texto 10 px: Delineador R$ 24,50", font=fonte(10), fill=0)
    for x in range(364):  # degradê do preto ao branco
        d.line([(m + 10 + x, 125), (m + 10 + x, 165)], fill=round(x / 363 * 255))
    y = 180
    for esp in (1, 2, 3):  # linhas horizontais finas
        d.rectangle([m + 10, y, m + 373, y + esp - 1], fill=0)
        d.text((m + 10, y + 5), f"linha de {esp} ponto(s)", font=fonte(12), fill=0)
        y += 30
    for i, esp in enumerate((1, 2, 3)):  # diagonais
        d.line([(m + 10 + i * 120, 360), (m + 110 + i * 120, 280)], fill=0, width=esp)
    cx, cy = w // 2, 440  # "logo": anéis + círculo cheio
    for r in (70, 55, 40):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=3)
    d.ellipse([cx - 25, cy - 25, cx + 25, cy + 25], fill=0)
    for yy in range(530, 590, 4):  # xadrez de 4 pontos
        for xx in range(m + 10, m + 374, 4):
            if ((xx - m) // 4 + (yy - 530) // 4) % 2 == 0:
                d.rectangle([xx, yy, xx + 3, yy + 3], fill=0)
    d.text((m + 10, 610), "fim da imagem", font=fonte(16), fill=0)
    return img  # de 640 a 760 fica branco: a ponte deve cortar


def pagina_de_imagem(caminho) -> Image.Image:
    img = Image.open(caminho).convert("L")
    if img.width > AREA:
        img = img.resize((AREA, round(img.height * AREA / img.width)), Image.Resampling.LANCZOS)
    pagina = Image.new("L", (LARGURA_PAGINA, img.height), 255)
    pagina.paste(img, ((LARGURA_PAGINA - img.width) // 2, 0))
    return pagina


def enviar(host, porta, mensagem: bytes) -> ipp.Mensagem:
    c = http.client.HTTPConnection(host, porta, timeout=60)
    c.request("POST", "/ipp/print", body=mensagem, headers={"Content-Type": "application/ipp"})
    r = c.getresponse()
    corpo = r.read()
    c.close()
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}: {corpo[:200]!r}")
    return ipp.ler(corpo)


def operacao(codigo, pedido, uri, extras=(), dados=b"") -> bytes:
    attrs = [(ipp.CHARSET, "attributes-charset", ["utf-8"]),
             (ipp.IDIOMA, "attributes-natural-language", ["en"]),
             (ipp.URI, "printer-uri", [uri])] + list(extras)
    return ipp.codificar((2, 0), codigo, pedido, [(ipp.GRUPO_OPERACAO, attrs)], dados)


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--atributos", action="store_true")
    g.add_argument("--teste", action="store_true")
    g.add_argument("--imagem", type=Path)
    g.add_argument("--salvar-teste", type=Path)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=631)
    a = p.parse_args()
    uri = f"ipp://{a.host}:{a.porta}/ipp/print"

    if a.salvar_teste:
        pagina_teste().save(a.salvar_teste)
        print("salvo em", a.salvar_teste)
        return
    if a.atributos:
        r = enviar(a.host, a.porta, operacao(0x000B, 1, uri))
        print(f"status 0x{r.codigo:04X}")
        for nome, valores in r.grupo(ipp.GRUPO_IMPRESSORA).items():
            txt = ", ".join(str(v) for v in valores)
            print(f"  {nome} = {txt[:110]}{'...' if len(txt) > 110 else ''}")
        return

    img = pagina_teste() if a.teste else pagina_de_imagem(a.imagem)
    nome = "pagina de teste" if a.teste else a.imagem.name
    dados = pwg.escrever([img], DPI)
    r = enviar(a.host, a.porta, operacao(
        0x0002, 2, uri,
        [(ipp.NOME, "requesting-user-name", ["teste"]), (ipp.NOME, "job-name", [nome]),
         (ipp.TIPO_MIME, "document-format", ["image/pwg-raster"])], dados))
    print(f"Print-Job: status 0x{r.codigo:04X}, {len(dados)} bytes de PWG enviados")
    print("  trabalho:", r.grupo(ipp.GRUPO_TRABALHO))


if __name__ == "__main__":
    main()
