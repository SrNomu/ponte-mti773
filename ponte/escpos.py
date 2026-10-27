"""
Comandos ESC/POS usados pela ponte e interpretação do status.

Tudo aqui foi confirmado na MTI-773 (placa GEZHI PT2D) durante o diagnóstico.
"""

from dataclasses import dataclass

ESC = b"\x1b"
GS = b"\x1d"
FS = b"\x1c"
DLE = b"\x10"
EOT = b"\x04"
LF = b"\n"

# DLE EOT n: status em tempo real. A impressora responde 1 byte para cada.
CONSULTAS_STATUS = [DLE + EOT + bytes([n]) for n in (1, 2, 3, 4)]


def inicializar(cfg) -> bytes:
    """Início de todo trabalho:
    ESC @    -> reinicia a formatação (negrito, tamanho etc.)
    FS .     -> desliga o modo chinês (senão bytes > 127 viram ideogramas)
    ESC t n  -> escolhe a tabela de caracteres (3 = cp860, português)"""
    cmd = ESC + b"@"
    if cfg.desligar_modo_chines:
        cmd += FS + b"."
    return cmd + ESC + b"t" + bytes([cfg.tabela_esc_t])


def avancar_linhas(n: int) -> bytes:
    """ESC d n: imprime o que está no buffer e avança n linhas."""
    return ESC + b"d" + bytes([max(0, min(n, 255))])


def raster(dados: bytes, bytes_por_linha: int, altura: int) -> bytes:
    """GS v 0: imagem de 1 bit. Cada byte = 8 pontos (bit mais alto à esquerda), 1 = preto."""
    return (GS + b"v0\x00" + bytes([bytes_por_linha & 0xFF, bytes_por_linha >> 8,
                                    altura & 0xFF, altura >> 8]) + dados)


def alinhar(posicao: int) -> bytes:
    """ESC a n: 0 = esquerda, 1 = centro, 2 = direita."""
    return ESC + b"a" + bytes([posicao])


# --- QR Code nativo (GS ( k, padrão Epson; testado na MTI-773) -------------
# Quantos bytes cabem em cada versão do QR (modo byte), versões 1 a 15.
# A versão v tem 17 + 4v módulos de lado.
CAPACIDADE_QR = {
    "L": (17, 32, 53, 78, 106, 134, 154, 192, 230, 271, 321, 367, 425, 458, 520),
    "M": (14, 26, 42, 62, 84, 106, 122, 152, 180, 213, 251, 287, 331, 362, 412),
    "Q": (11, 20, 32, 46, 60, 74, 86, 108, 130, 151, 177, 203, 241, 258, 292),
    "H": (7, 14, 24, 34, 44, 58, 64, 84, 98, 119, 137, 155, 177, 194, 220),
}
CODIGO_CORRECAO = {"L": 48, "M": 49, "Q": 50, "H": 51}
MODULO_MINIMO = 3  # menos que 3 pontos (0,375 mm) fica difícil para a câmera do celular


def modulo_qr(n_bytes: int, correcao: str, largura_pontos: int, maximo: int) -> int:
    """Maior tamanho de módulo (<= maximo) que faz o QR caber na largura,
    contando a margem branca obrigatória de 4 módulos de cada lado."""
    for versao, capacidade in enumerate(CAPACIDADE_QR[correcao], start=1):
        if n_bytes <= capacidade:
            modulos = 17 + 4 * versao + 8  # + zona branca
            return max(MODULO_MINIMO, min(maximo, largura_pontos // modulos))
    return MODULO_MINIMO  # além da versão 15: usa o mínimo e torce para caber


def qr_code(dados: bytes, modulo: int, correcao: str) -> bytes:
    n = len(dados) + 3
    return (GS + b"(k\x04\x001A2\x00"                                   # modelo 2
            + GS + b"(k\x03\x001C" + bytes([modulo])                    # tamanho do módulo
            + GS + b"(k\x03\x001E" + bytes([CODIGO_CORRECAO[correcao]])  # correção de erro
            + GS + b"(k" + bytes([n & 0xFF, n >> 8]) + b"1P0" + dados    # guarda os dados
            + GS + b"(k\x03\x001Q0")                                    # imprime


@dataclass(frozen=True)
class Status:
    """Respostas de DLE EOT 1..4 (None = a impressora não respondeu)."""
    eot: tuple

    @property
    def respondeu(self) -> bool:
        return all(v is not None for v in self.eot)

    def _bit(self, n, mascara) -> bool:
        v = self.eot[n - 1]
        return v is not None and bool(v & mascara)

    @property
    def offline(self) -> bool:
        return self._bit(1, 0x08)

    @property
    def sem_papel(self) -> bool:
        # EOT 2 bit 5 = "parou por falta de papel"; EOT 4 bits 5-6 = sensor sem papel.
        # A MTI-773 não tem sensor de tampa: tampa aberta também aparece aqui.
        return self._bit(2, 0x20) or self._bit(4, 0x60)

    @property
    def papel_acabando(self) -> bool:
        return self._bit(4, 0x0C)

    @property
    def erro(self) -> bool:
        # EOT 2 bit 6 = erro; EOT 3 bit 5 = erro irrecuperável
        return self._bit(2, 0x40) or self._bit(3, 0x20)

    @property
    def cabeca_quente(self) -> bool:
        # EOT 3 bit 6 = erro auto-recuperável (padrão Epson: cabeça quente / tensão)
        return self._bit(3, 0x40)

    @property
    def ok(self) -> bool:
        return self.respondeu and not (self.offline or self.sem_papel or self.erro or self.cabeca_quente)

    def descricao(self) -> str:
        if not self.respondeu:
            return "a impressora não responde"
        itens = []
        if self.sem_papel:
            itens.append("sem papel ou tampa aberta")
        elif self.papel_acabando:
            itens.append("papel acabando")
        if self.offline:
            itens.append("offline")
        if self.erro:
            itens.append("erro na impressora")
        if self.cabeca_quente:
            itens.append("cabeça quente")
        return ", ".join(itens) or "OK"

    def hexa(self) -> str:
        return " ".join("--" if v is None else f"{v:02X}" for v in self.eot)
