r"""
Teste 4 (etapa 3): raster GS v 0 em faixas + QR Code nativo (GS ( k).

Usa o código da própria ponte (config.ini, transporte USB, status).
ATENÇÃO: pare a ponte antes de rodar; ela consulta o status de tempos em
tempos e uma consulta no meio de uma imagem pode ser confundida com dados.

Uso:  python ferramentas\teste_raster_qr.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ponte import config, escpos  # noqa: E402
from ponte.transporte import criar_transporte  # noqa: E402

LARGURA = 384
ESC, GS = escpos.ESC, escpos.GS


def gs_v0(funcao_preto, altura, largura=LARGURA) -> bytes:
    """Monta um comando GS v 0 a partir de uma função (x, y) -> True se o ponto é preto.
    Cada byte guarda 8 pontos; o bit mais alto é o ponto da esquerda."""
    bpl = largura // 8
    dados = bytearray()
    for y in range(altura):
        for xb in range(bpl):
            byte = 0
            for bit in range(8):
                if funcao_preto(xb * 8 + bit, y):
                    byte |= 0x80 >> bit
            dados.append(byte)
    # GS v 0 m xL xH yL yH (m=0: tamanho normal)
    return GS + b"v0\x00" + bytes([bpl & 0xFF, bpl >> 8, altura & 0xFF, altura >> 8]) + bytes(dados)


def janelas(x, y):
    """Barra preta com uma janela branca de 16 pontos a cada 48 pontos."""
    if y < 6 or y >= 18:
        return True
    return not (16 <= x % 48 < 32)


def moldura(deslocamento_y):
    """Moldura de 3 pontos com um X; altura total 48, desenhada em duas faixas."""
    def f(x, y):
        y += deslocamento_y
        if x < 3 or x >= LARGURA - 3 or y < 3 or y >= 45:
            return True
        # diagonais de 1 ponto de altura (bem "deitadas": saem tracejadas)
        dx = x * 48 / LARGURA
        return abs(dx - y) < 0.5 or abs((48 - dx) - y) < 0.5
    return f


def qr_nativo(texto: str, modulo=6) -> bytes:
    """QR Code modelo 2 pelo comando GS ( k (padrão Epson)."""
    d = texto.encode("ascii")
    n = len(d) + 3
    return (GS + b"(k\x04\x001A2\x00"                         # modelo 2
            + GS + b"(k\x03\x001C" + bytes([modulo])          # tamanho do módulo
            + GS + b"(k\x03\x001E1"                           # correção de erro M
            + GS + b"(k" + bytes([n & 0xFF, n >> 8]) + b"1P0" + d   # guarda os dados
            + GS + b"(k\x03\x001Q0")                          # imprime


from ponte.impressora import ler_status  # noqa: E402  (com novas tentativas)


def main():
    cfg = config.carregar()
    t = criar_transporte(cfg)
    t.abrir()
    try:
        st = ler_status(t)
        print("Status antes:", st.hexa(), st.descricao())
        if not st.ok:
            return 1

        partes = [
            ("titulo", escpos.inicializar(cfg) + b"TESTE 4 - RASTER EM FAIXAS\nFaixa 1: 8 janelas\n"),
            ("faixa 1 (janelas)", gs_v0(janelas, 24)),
            ("texto", b"\nFaixas 2+3: moldura com X\n"),
            ("faixa 2 (moldura, cima)", gs_v0(moldura(0), 24)),
            ("faixa 3 (moldura, baixo)", gs_v0(moldura(24), 24)),
            ("texto", b"\nQR nativo (GS ( k):\n" + ESC + b"a\x01"),
            ("qr nativo", qr_nativo("https://exemplo.com.br/mti773")),
            ("fim", ESC + b"a\x00" + b"\n--- fim ---\n" + escpos.avancar_linhas(3)),
        ]
        if "--so-qr" in sys.argv:  # só o QR nativo (o raster já foi aprovado)
            partes = [("titulo", escpos.inicializar(cfg) + b"TESTE 5 - QR NATIVO\n")] + partes[5:]
        for nome, dados in partes:
            st = ler_status(t)
            if not st.ok:
                print(f"  PAREI antes de '{nome}': {st.hexa()} {st.descricao()}")
                return 2
            for i in range(0, len(dados), cfg.tamanho_pedaco):
                t.escrever(dados[i:i + cfg.tamanho_pedaco])
                time.sleep(cfg.pausa_ms / 1000)
            print(f"  {nome}: {len(dados)} bytes")

        print("observando o status por 15 s (mostra quando muda)...")
        inicio, anterior = time.monotonic(), None
        while time.monotonic() - inicio < 15:
            st = ler_status(t)
            if st.descricao() != anterior:
                print(f"  t={time.monotonic() - inicio:5.1f}s [{st.hexa()}] {st.descricao()}")
                anterior = st.descricao()
            time.sleep(0.5)
    finally:
        t.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
