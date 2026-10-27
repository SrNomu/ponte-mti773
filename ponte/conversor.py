"""
Transforma os bytes recebidos de um programa em um Trabalho para a impressora.

Dois casos:
  1. Já é ESC/POS (sistemas de loja mandam comandos prontos): repassamos como
     veio, só colocando antes a inicialização (modo chinês desligado + cp860).
     Limitação: se o sistema mandar seu próprio ESC @ / ESC t, vale o dele.
  2. É texto puro (Bloco de Notas via "Generic / Text Only", scripts...):
     descobrimos a codificação, trocamos caracteres que a impressora não tem,
     quebramos as linhas em 32 colunas e geramos o ESC/POS nós mesmos.
"""

import codecs
import re
import textwrap
import unicodedata

from . import escpos
from .impressora import Trabalho

# Caracteres comuns que não existem na cp860 -> equivalente simples
SUBSTITUICOES = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'", "´": "'",
    "–": "-", "—": "-", "−": "-", "…": "...",
    "€": "EUR", " ": " ", "•": "*", "·": ".",
    "™": "TM", "®": "(R)", "©": "(C)",
}


# {{QR:conteúdo}} — o conteúdo não pode ter quebra de linha
MARCACAO_QR = re.compile(r"\{\{QR:([^\n]*?)\}\}")
# Cada QR vira 1 caractere da "área de uso privado" do Unicode (U+E000...),
# que nenhum texto normal usa. Assim ele atravessa a limpeza, a remoção de
# margens e a quebra de linhas como se fosse uma palavra de 1 letra.
PRIMEIRO_MARCADOR = 0xE000


def extrair_qr(texto: str) -> tuple[str, dict]:
    """Troca cada {{QR:...}} por um marcador. Devolve (texto, {marcador: conteúdo})."""
    qrs = {}

    def trocar(m):
        marcador = chr(PRIMEIRO_MARCADOR + len(qrs))
        qrs[marcador] = m.group(1).strip()
        return marcador

    return MARCACAO_QR.sub(trocar, texto), qrs


def bloco_qr(conteudo: str, cfg) -> bytes:
    """Linha em branco + QR centralizado + linha em branco."""
    dados = conteudo.encode("utf-8")
    if not dados:
        return b""
    modulo = escpos.modulo_qr(len(dados), cfg.qr_correcao, cfg.largura_pontos, cfg.qr_modulo)
    espaco = escpos.LF * cfg.qr_linhas_espaco
    return (espaco + escpos.alinhar(1) + escpos.qr_code(dados, modulo, cfg.qr_correcao)
            + escpos.alinhar(0) + espaco)


def eh_escpos(dados: bytes) -> bool:
    """Texto puro não tem ESC (1B), GS (1D) nem FS (1C)."""
    return any(c in dados for c in (b"\x1b", b"\x1d", b"\x1c"))


def decodificar(dados: bytes, cfg) -> tuple[str, str]:
    """Devolve (texto, nome da codificação detectada)."""
    if dados.startswith(codecs.BOM_UTF8):
        return dados[3:].decode("utf-8", "replace"), "utf-8 (BOM)"
    if dados.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return dados.decode("utf-16", "replace"), "utf-16"
    try:
        return dados.decode("utf-8"), "utf-8"  # ASCII puro também passa aqui
    except UnicodeDecodeError:
        return dados.decode(cfg.codificacao_entrada, "replace"), cfg.codificacao_entrada


def simplificar(texto: str, codificacao: str, manter=()) -> str:
    """Garante que todo caractere exista na codificação da impressora.
    Ordem: o próprio caractere -> tabela de substituições -> sem acento -> '?'
    Caracteres em `manter` (marcadores de QR) passam intactos."""
    cache = {}

    def trocar(c):
        if c in cache:
            return cache[c]
        r = c
        if c == "\n" or c in manter:
            pass
        elif ord(c) < 32 or ord(c) == 127:  # caracteres de controle: removemos
            r = ""
        else:
            try:
                c.encode(codificacao)
            except UnicodeEncodeError:
                r = SUBSTITUICOES.get(c)
                if r is None:
                    base = "".join(x for x in unicodedata.normalize("NFKD", c)
                                   if not unicodedata.combining(x))
                    try:
                        base.encode(codificacao)
                        r = base or "?"
                    except UnicodeEncodeError:
                        r = "?"
        cache[c] = r
        return r

    return "".join(trocar(c) for c in texto)


def tirar_margens(pagina: str) -> str:
    """Remove o recuo que TODAS as linhas não vazias têm em comum (a margem
    esquerda virada espaços) e as linhas vazias do início (a margem de cima).
    Recuos que só algumas linhas têm, como itens de lista, são mantidos."""
    linhas = pagina.split("\n")
    recuos = [len(l) - len(l.lstrip(" ")) for l in linhas if l.strip()]
    corte = min(recuos, default=0)
    linhas = [l[corte:] if l.strip() else "" for l in linhas]
    while linhas and not linhas[0]:
        linhas.pop(0)
    return "\n".join(linhas)


def quebrar_linhas(texto: str, colunas: int, remover_margens: bool = False) -> list[str]:
    """Quebra em linhas de no máximo `colunas` caracteres, sem cortar palavras
    (só corta se uma palavra sozinha for maior que a linha)."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    # \f (form feed) separa páginas. Tiramos as linhas vazias do fim de cada
    # página para não gastar papel em branco.
    paginas = texto.split("\f")
    if remover_margens:
        paginas = [tirar_margens(p) for p in paginas]
    paginas = [p.rstrip() for p in paginas]
    linhas = []
    for linha in "\n".join(p for p in paginas if p).split("\n"):
        linha = linha.rstrip()
        if not linha:
            linhas.append("")
            continue
        linhas.extend(textwrap.wrap(linha, width=colunas, expand_tabs=False,
                                    replace_whitespace=False, break_on_hyphens=False) or [""])
    while linhas and not linhas[-1]:
        linhas.pop()
    return linhas


def agrupar(blocos: list[bytes], limite: int) -> list[bytes]:
    """Junta blocos pequenos (linhas) em blocos de até `limite` bytes,
    sem nunca partir um bloco. Menos chamadas à USB, mesmos pontos seguros."""
    saida, atual = [], b""
    for b in blocos:
        if atual and len(atual) + len(b) > limite:
            saida.append(atual)
            atual = b""
        atual += b
    if atual:
        saida.append(atual)
    return saida


def texto_para_trabalho(texto: str, cfg, nome: str, linhas_finais: int | None = None) -> Trabalho:
    # 1º os QR: a marcação sai do texto ANTES da quebra em colunas
    texto, qrs = extrair_qr(texto)
    linhas = quebrar_linhas(_preparar_texto(texto, cfg, manter=qrs), cfg.colunas, cfg.remover_margens)

    blocos = [escpos.inicializar(cfg)]
    separar = re.compile("([" + "".join(qrs) + "])") if qrs else None
    for linha in linhas:
        if not separar or not separar.search(linha):
            blocos.append(linha.encode(cfg.codificacao) + escpos.LF)
            continue
        # A linha tem QR: o texto antes/depois vira linhas separadas
        for parte in separar.split(linha):
            if parte in qrs:
                blocos.append(bloco_qr(qrs[parte], cfg))
            elif parte.strip():
                blocos.append(parte.strip().encode(cfg.codificacao) + escpos.LF)

    finais = cfg.linhas_finais if linhas_finais is None else linhas_finais
    if finais:
        blocos.append(escpos.avancar_linhas(finais))
    descricao = f"texto, {len(linhas)} linhas" + (f", {len(qrs)} QR" if qrs else "")
    return Trabalho(nome, agrupar(blocos, cfg.tamanho_pedaco), descricao=descricao)


def _preparar_texto(texto: str, cfg, manter=()) -> str:
    # \f e \t precisam sobreviver à limpeza de caracteres de controle,
    # então os tratamos antes: tab vira espaços e \f é guardado como marcador.
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    paginas = [simplificar(p, cfg.codificacao, manter) for p in texto.split("\f")]
    return "\f".join(paginas)


def preparar(dados: bytes, cfg, origem: str):
    """Ponto de entrada: bytes recebidos -> Trabalho (ou None se vazio)."""
    if not dados.strip(b" \r\n\t\f\x00"):
        return None
    if eh_escpos(dados) and not dados.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return Trabalho(origem, [escpos.inicializar(cfg), dados], descricao="ESC/POS repassado")
    texto, codificacao = decodificar(dados, cfg)
    trab = texto_para_trabalho(texto, cfg, origem)
    trab.descricao += f", entrada {codificacao}"
    return trab
