r"""
Leitura do arquivo de configuração (config.ini).

Usamos o formato INI (módulo configparser) porque é fácil de editar no Bloco
de Notas. Se o arquivo não existir, ele é criado com os valores padrão e
comentários explicando cada opção.

Onde fica a pasta de dados (config.ini e ponte.log):
  - instalado (executável do PyInstaller): C:\ProgramData\MTI773Ponte
  - desenvolvimento (python -m ponte):     <projeto>\dados
"""

import codecs
import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_PADRAO = """\
; Configuração da Ponte MTI-773
; Linhas começando com ; são comentários. Depois de mudar, reinicie a ponte.

[impressora]
; Como falar com a impressora: usb ou bluetooth (bluetooth ainda não implementado)
conexao = usb
; Identificação USB da impressora (VID/PID em hexadecimal)
usb_vid = 28E9
usb_pid = 0289
; Para bluetooth (futuro): porta COM e velocidade
porta_com = COM5
velocidade = 9600

[papel]
; Papel de 58 mm; a cabeça imprime 48 mm = 384 pontos = 32 colunas na fonte padrão
largura_papel_mm = 58
largura_pontos = 384
dpi = 203
colunas = 32
; Linhas em branco no final de cada trabalho, para a última linha passar da
; serrilha. Calibrado na MTI-773 com "python -m ponte --calibrar": 4 linhas.
linhas_finais = 4

[texto]
; Codepage da impressora. Testado: cp860 com ESC t 3 imprime todos os acentos.
codificacao = cp860
tabela_esc_t = 3
; A placa vem com o modo chinês ligado, que estraga os acentos. FS . desliga.
desligar_modo_chines = sim
; Como interpretar texto recebido que NÃO está em UTF-8.
; O driver "Generic / Text Only" do Windows manda cp1252 (testado).
codificacao_entrada = cp1252
; O "Generic / Text Only" transforma as margens da página em espaços e linhas
; em branco. Isto remove o recuo comum a todas as linhas e as linhas vazias do início.
remover_margens = sim

[qr]
; No texto, {{QR:conteúdo}} vira um QR Code (comando nativo GS ( k, testado).
; Tamanho do módulo em pontos (1 ponto = 0,125 mm). Diminui sozinho (até 3) se o
; conteúdo for grande demais para a largura do papel.
modulo = 6
; Correção de erro: L, M, Q ou H (M é o padrão comum; H aguenta mais sujeira)
correcao = M
; Linhas em branco antes e depois de cada QR
linhas_espaco = 1

[envio]
; Tamanho de cada pedaço enviado (bytes) e pausa entre pedaços (ms)
tamanho_pedaco = 128
pausa_ms = 20
; Consultar o status da impressora antes de imprimir e a cada N bytes
; (sempre entre linhas/faixas de imagem, nunca no meio de um comando)
usar_status = sim
intervalo_status_bytes = 4096
; Por quanto tempo um trabalho espera a impressora ficar disponível (segundos)
espera_max_s = 300
; Sem trabalhos, verificar a conexão/status a cada N segundos (0 = nunca).
; É o que mantém o ícone da bandeja atualizado. Nunca interrompe uma impressão.
verificar_ocioso_s = 8

[servidor]
; Só 127.0.0.1: a porta não fica acessível pela rede
endereco = 127.0.0.1
porta_raw = 9100
; Se o programa não fechar a conexão, considera o trabalho completo após N s sem dados
tempo_ocioso_s = 5

[ipp]
; Impressora "sem driver" (IPP): o Windows desenha a página (texto, imagens,
; PDF...) e manda a imagem para a ponte. Endereço: http://127.0.0.1:631/ipp/print
ativo = sim
porta = 631
nome = MTI-773
; Comprimentos de página oferecidos aos programas, em mm (o 1º é o padrão).
; O branco que sobrar no fim é cortado, então página comprida não gasta papel.
comprimentos_mm = 297, 200, 100
; Margem esquerda/direita anunciada: (58 - 48) / 2 = 5 mm
margem_lateral_mm = 5

[imagem]
; pontilhado = bom para fotos, logos e degradês; limiar = só preto/branco puro
modo = pontilhado
; usado no modo limiar: tons abaixo disto viram preto (0 a 255)
limiar = 128
; Escurece os tons médios antes do pontilhado (texto colorido fica legível).
; 1 = não mexe; 1.8 = rosa/azul viram quase preto; branco e preto não mudam.
escurecer = 1.8
; cortar o papel em branco do começo e do fim de cada página
cortar_branco = sim
; linhas de cada faixa de imagem (GS v 0); entre faixas a ponte pode consultar o status
altura_faixa = 24

[log]
; DEBUG, INFO, WARNING ou ERROR
nivel = INFO
; Guardar os bytes recebidos de cada trabalho na pasta "trabalhos" (diagnóstico)
salvar_trabalhos = nao
"""


@dataclass
class Config:
    pasta: Path
    # [impressora]
    conexao: str
    usb_vid: int
    usb_pid: int
    porta_com: str
    velocidade: int
    # [papel]
    largura_papel_mm: float
    largura_pontos: int
    dpi: int
    colunas: int
    linhas_finais: int
    # [texto]
    codificacao: str
    tabela_esc_t: int
    desligar_modo_chines: bool
    codificacao_entrada: str
    remover_margens: bool
    # [qr]
    qr_modulo: int
    qr_correcao: str
    qr_linhas_espaco: int
    # [envio]
    tamanho_pedaco: int
    pausa_ms: int
    usar_status: bool
    intervalo_status_bytes: int
    espera_max_s: int
    verificar_ocioso_s: int
    # [servidor]
    endereco: str
    porta_raw: int
    tempo_ocioso_s: float
    # [ipp]
    ipp_ativo: bool
    ipp_porta: int
    ipp_nome: str
    ipp_comprimentos_mm: list
    ipp_margem_lateral_mm: float
    # [imagem]
    imagem_modo: str
    imagem_limiar: int
    imagem_escurecer: float
    cortar_branco: bool
    altura_faixa: int
    # [log]
    nivel_log: str
    salvar_trabalhos: bool


def pasta_dados() -> Path:
    if getattr(sys, "frozen", False):  # rodando como executável do PyInstaller
        base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "MTI773Ponte"
    else:
        base = Path(__file__).resolve().parent.parent / "dados"
    base.mkdir(parents=True, exist_ok=True)
    return base


def carregar(caminho: Path | None = None) -> Config:
    """Lê o config.ini (criando-o se não existir) e devolve um objeto Config."""
    if caminho is None:
        caminho = pasta_dados() / "config.ini"
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        caminho.write_text(CONFIG_PADRAO, encoding="utf-8")

    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    # Aceitar "sim"/"não" além de yes/no/true/false
    cp.BOOLEAN_STATES = {**cp.BOOLEAN_STATES, "sim": True, "nao": False, "não": False}
    cp.read_string(CONFIG_PADRAO)                # 1º os padrões...
    cp.read(caminho, encoding="utf-8-sig")       # ...depois o que o usuário mudou
    # (utf-8-sig aceita arquivos salvos pelo Bloco de Notas com BOM)

    cfg = Config(
        pasta=caminho.parent,
        conexao=cp.get("impressora", "conexao").strip().lower(),
        usb_vid=int(cp.get("impressora", "usb_vid"), 16),
        usb_pid=int(cp.get("impressora", "usb_pid"), 16),
        porta_com=cp.get("impressora", "porta_com").strip(),
        velocidade=cp.getint("impressora", "velocidade"),
        largura_papel_mm=cp.getfloat("papel", "largura_papel_mm"),
        largura_pontos=cp.getint("papel", "largura_pontos"),
        dpi=cp.getint("papel", "dpi"),
        colunas=cp.getint("papel", "colunas"),
        linhas_finais=cp.getint("papel", "linhas_finais"),
        codificacao=cp.get("texto", "codificacao").strip(),
        tabela_esc_t=cp.getint("texto", "tabela_esc_t"),
        desligar_modo_chines=cp.getboolean("texto", "desligar_modo_chines"),
        codificacao_entrada=cp.get("texto", "codificacao_entrada").strip(),
        remover_margens=cp.getboolean("texto", "remover_margens"),
        qr_modulo=cp.getint("qr", "modulo"),
        qr_correcao=cp.get("qr", "correcao").strip().upper(),
        qr_linhas_espaco=cp.getint("qr", "linhas_espaco"),
        tamanho_pedaco=cp.getint("envio", "tamanho_pedaco"),
        pausa_ms=cp.getint("envio", "pausa_ms"),
        usar_status=cp.getboolean("envio", "usar_status"),
        intervalo_status_bytes=cp.getint("envio", "intervalo_status_bytes"),
        espera_max_s=cp.getint("envio", "espera_max_s"),
        verificar_ocioso_s=cp.getint("envio", "verificar_ocioso_s"),
        endereco=cp.get("servidor", "endereco").strip(),
        porta_raw=cp.getint("servidor", "porta_raw"),
        tempo_ocioso_s=cp.getfloat("servidor", "tempo_ocioso_s"),
        ipp_ativo=cp.getboolean("ipp", "ativo"),
        ipp_porta=cp.getint("ipp", "porta"),
        ipp_nome=cp.get("ipp", "nome").strip(),
        ipp_comprimentos_mm=[float(c) for c in cp.get("ipp", "comprimentos_mm").split(",") if c.strip()],
        ipp_margem_lateral_mm=cp.getfloat("ipp", "margem_lateral_mm"),
        imagem_modo=cp.get("imagem", "modo").strip().lower(),
        imagem_limiar=cp.getint("imagem", "limiar"),
        imagem_escurecer=cp.getfloat("imagem", "escurecer"),
        cortar_branco=cp.getboolean("imagem", "cortar_branco"),
        altura_faixa=cp.getint("imagem", "altura_faixa"),
        nivel_log=cp.get("log", "nivel").strip().upper(),
        salvar_trabalhos=cp.getboolean("log", "salvar_trabalhos"),
    )
    _validar(cfg)
    return cfg


def _validar(cfg: Config):
    """Erros de configuração com mensagens claras, em vez de falhas estranhas depois."""
    if cfg.conexao not in ("usb", "bluetooth"):
        raise ValueError(f"config.ini: conexao deve ser 'usb' ou 'bluetooth' (está '{cfg.conexao}')")
    for nome in ("codificacao", "codificacao_entrada"):
        try:
            codecs.lookup(getattr(cfg, nome))
        except LookupError:
            raise ValueError(f"config.ini: codificação desconhecida em {nome}: {getattr(cfg, nome)}")
    if not 0 <= cfg.tabela_esc_t <= 255:
        raise ValueError("config.ini: tabela_esc_t deve estar entre 0 e 255")
    if cfg.qr_correcao not in ("L", "M", "Q", "H"):
        raise ValueError("config.ini: [qr] correcao deve ser L, M, Q ou H")
    if not 1 <= cfg.qr_modulo <= 16:
        raise ValueError("config.ini: [qr] modulo deve estar entre 1 e 16")
    if not 0.2 <= cfg.imagem_escurecer <= 5:
        raise ValueError("config.ini: [imagem] escurecer deve estar entre 0.2 e 5 (1 = não mexe)")
    if cfg.imagem_modo not in ("pontilhado", "limiar"):
        raise ValueError("config.ini: [imagem] modo deve ser 'pontilhado' ou 'limiar'")
    if not cfg.ipp_comprimentos_mm or min(cfg.ipp_comprimentos_mm) < 20:
        raise ValueError("config.ini: [ipp] comprimentos_mm precisa de pelo menos um valor >= 20")
    if cfg.largura_pontos % 8 or not 1 <= cfg.altura_faixa <= 1024:
        raise ValueError("config.ini: largura_pontos deve ser múltiplo de 8 e altura_faixa entre 1 e 1024")
    if cfg.colunas < 8 or cfg.tamanho_pedaco < 1:
        raise ValueError("config.ini: colunas (>= 8) ou tamanho_pedaco (>= 1) inválido")
