"""
Protocolo IPP (Internet Printing Protocol) — só a parte que a ponte precisa.

Uma mensagem IPP é binária (vai dentro de um POST HTTP):
  versão (2 bytes) | operação ou status (2) | número do pedido (4)
  grupos de atributos: [marcador do grupo] [atributo] [atributo] ...
  0x03 = fim dos atributos
  dados do documento (só no Print-Job / Send-Document)

Cada atributo: tipo (1) | tamanho do nome (2) | nome | tamanho do valor (2) | valor.
Um atributo com vários valores repete tipo + valor com o nome vazio.
"Coleções" (como media-col) são estruturas aninhadas com membros nomeados.

Aqui um atributo é representado como a tupla (tipo, nome, [valores]).
Numa coleção, cada valor é uma lista de atributos (os membros).
"""

import struct
from dataclasses import dataclass

# Marcadores de grupo
GRUPO_OPERACAO = 0x01
GRUPO_TRABALHO = 0x02
FIM = 0x03
GRUPO_IMPRESSORA = 0x04
GRUPO_NAO_SUPORTADO = 0x05

# Tipos de valor
SEM_VALOR = 0x13
INTEIRO = 0x21
BOOLEANO = 0x22
ENUM = 0x23
OCTETOS = 0x30
DATA_HORA = 0x31
RESOLUCAO = 0x32
INTERVALO = 0x33
COLECAO = 0x34
TEXTO_IDIOMA = 0x35
NOME_IDIOMA = 0x36
FIM_COLECAO = 0x37
TEXTO = 0x41
NOME = 0x42
PALAVRA = 0x44
URI = 0x45
ESQUEMA_URI = 0x46
CHARSET = 0x47
IDIOMA = 0x48
TIPO_MIME = 0x49
NOME_MEMBRO = 0x4A

OPERACOES = {
    0x0002: "Print-Job", 0x0004: "Validate-Job", 0x0005: "Create-Job",
    0x0006: "Send-Document", 0x0008: "Cancel-Job", 0x0009: "Get-Job-Attributes",
    0x000A: "Get-Jobs", 0x000B: "Get-Printer-Attributes", 0x003B: "Close-Job",
    0x003C: "Identify-Printer",
}

# Códigos de status
OK = 0x0000
ERRO_PEDIDO = 0x0400
ERRO_NAO_ENCONTRADO = 0x0406
ERRO_FORMATO = 0x040A
ERRO_INTERNO = 0x0500
ERRO_OPERACAO = 0x0501


@dataclass
class Mensagem:
    versao: tuple
    codigo: int       # operação (pedido) ou status (resposta)
    pedido: int       # número do pedido, devolvido igual na resposta
    grupos: list      # [(marcador, {nome: [valores]})]
    dados: bytes = b""

    def grupo(self, marcador) -> dict:
        for m, atributos in self.grupos:
            if m == marcador:
                return atributos
        return {}

    def valor(self, nome, marcador=GRUPO_OPERACAO, padrao=None):
        valores = self.grupo(marcador).get(nome)
        return valores[0] if valores else padrao

    def resumo(self, limite=60) -> str:
        """Texto curto com todos os atributos (para o log)."""
        partes = []
        for _, atributos in self.grupos:
            for nome, valores in atributos.items():
                txt = ",".join(str(v) for v in valores)
                partes.append(f"{nome}={txt[:limite]}{'...' if len(txt) > limite else ''}")
        return "; ".join(partes)


# --- leitura -------------------------------------------------------------
def ler(dados: bytes) -> Mensagem:
    if len(dados) < 9:
        raise ValueError("mensagem IPP curta demais")
    versao = (dados[0], dados[1])
    codigo, pedido = struct.unpack_from(">HI", dados, 2)
    pos, grupos, atual, ultimo_nome = 8, [], None, None
    while pos < len(dados):
        tipo = dados[pos]
        pos += 1
        if tipo == FIM:
            break
        if tipo < 0x10:  # começa um novo grupo
            atual = {}
            grupos.append((tipo, atual))
            ultimo_nome = None
            continue
        if atual is None:
            raise ValueError("atributo fora de um grupo")
        nome, valor, pos = _ler_campo(dados, pos)
        if tipo == COLECAO:
            valor, pos = _ler_colecao(dados, pos)
        else:
            valor = _decodificar(tipo, valor)
        if nome:
            ultimo_nome = nome
            atual[nome] = [valor]
        elif ultimo_nome:  # valor adicional do atributo anterior
            atual[ultimo_nome].append(valor)
    return Mensagem(versao, codigo, pedido, grupos, dados[pos:])


def _ler_campo(dados, pos):
    (n,) = struct.unpack_from(">H", dados, pos)
    nome = dados[pos + 2:pos + 2 + n].decode("utf-8", "replace")
    pos += 2 + n
    (n,) = struct.unpack_from(">H", dados, pos)
    valor = dados[pos + 2:pos + 2 + n]
    return nome, valor, pos + 2 + n


def _ler_colecao(dados, pos):
    """Lê os membros até o FIM_COLECAO. Devolve ({membro: [valores]}, pos)."""
    membros, membro = {}, None
    while pos < len(dados):
        tipo = dados[pos]
        _, valor, pos = _ler_campo(dados, pos + 1)
        if tipo == FIM_COLECAO:
            return membros, pos
        if tipo == NOME_MEMBRO:
            membro = valor.decode("utf-8", "replace")
            membros[membro] = []
            continue
        if tipo == COLECAO:
            valor, pos = _ler_colecao(dados, pos)
        else:
            valor = _decodificar(tipo, valor)
        membros.setdefault(membro, []).append(valor)
    raise ValueError("coleção sem fim")


def _decodificar(tipo, b: bytes):
    if tipo in (INTEIRO, ENUM) and len(b) == 4:
        return struct.unpack(">i", b)[0]
    if tipo == BOOLEANO and len(b) == 1:
        return bool(b[0])
    if tipo == RESOLUCAO and len(b) == 9:
        return struct.unpack(">iiB", b)
    if tipo == INTERVALO and len(b) == 8:
        return struct.unpack(">ii", b)
    if tipo in (TEXTO_IDIOMA, NOME_IDIOMA) and len(b) >= 4:
        (n,) = struct.unpack_from(">H", b, 0)
        return b[4 + n:].decode("utf-8", "replace")  # ignora o idioma
    if 0x40 <= tipo <= 0x4F:
        return b.decode("utf-8", "replace")
    if 0x10 <= tipo <= 0x1F:
        return None  # "sem valor", "desconhecido"...
    return bytes(b)


# --- escrita -------------------------------------------------------------
def codificar(versao, codigo, pedido, grupos, dados=b"") -> bytes:
    """grupos = [(marcador, [(tipo, nome, [valores]), ...]), ...]"""
    saida = bytearray(bytes(versao) + struct.pack(">HI", codigo, pedido))
    for marcador, atributos in grupos:
        saida.append(marcador)
        for tipo, nome, valores in atributos:
            saida += _codificar_atributo(tipo, nome, valores)
    saida.append(FIM)
    return bytes(saida) + dados


def _campo(tipo, nome: bytes, valor: bytes) -> bytes:
    return struct.pack(">BH", tipo, len(nome)) + nome + struct.pack(">H", len(valor)) + valor


def _codificar_atributo(tipo, nome, valores) -> bytes:
    saida = bytearray()
    for i, v in enumerate(valores):
        n = nome.encode("utf-8") if i == 0 else b""  # valores extras: nome vazio
        if tipo == COLECAO:
            saida += _campo(COLECAO, n, b"") + _codificar_membros(v) + _campo(FIM_COLECAO, b"", b"")
        else:
            saida += _campo(tipo, n, _valor_bytes(tipo, v))
    return bytes(saida)


def _codificar_membros(membros) -> bytes:
    saida = bytearray()
    for tipo, nome, valores in membros:
        saida += _campo(NOME_MEMBRO, b"", nome.encode("utf-8"))  # nome do membro uma vez...
        for v in valores:                                         # ...seguido de todos os valores
            if tipo == COLECAO:
                saida += _campo(COLECAO, b"", b"") + _codificar_membros(v) + _campo(FIM_COLECAO, b"", b"")
            else:
                saida += _campo(tipo, b"", _valor_bytes(tipo, v))
    return bytes(saida)


def _valor_bytes(tipo, v) -> bytes:
    if tipo in (INTEIRO, ENUM):
        return struct.pack(">i", v)
    if tipo == BOOLEANO:
        return bytes([1 if v else 0])
    if tipo == RESOLUCAO:
        return struct.pack(">iiB", *v)
    if tipo == INTERVALO:
        return struct.pack(">ii", *v)
    if isinstance(v, bytes):
        return v
    if v is None:
        return b""
    return str(v).encode("utf-8")
