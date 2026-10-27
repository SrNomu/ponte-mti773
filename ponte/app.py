"""
Junta as peças: configuração, log, impressora e servidor.

A bandeja do Windows (etapa 4) e a linha de comando usam esta mesma classe:
só chamam iniciar() e parar().
"""

import datetime

from . import __version__, conversor, imagem, registro
from .impressora import Impressora
from .servidor_ipp import ServidorIPP
from .servidor_raw import ServidorRaw
from .transporte import criar_transporte

MAX_TRABALHOS_SALVOS = 50


class Ponte:
    def __init__(self, cfg):
        self.cfg = cfg
        self.log = registro.configurar(cfg)
        self.impressora = Impressora(cfg, criar_transporte(cfg), self.log)
        self.servidor = ServidorRaw(cfg, self.receber, self.log)
        self.servidor_ipp = (ServidorIPP(cfg, self.receber_paginas, self._salvar_se_ativo, self.log)
                             if cfg.ipp_ativo else None)

    def iniciar(self):
        self.log.info("Ponte MTI-773 v%s iniciando (conexão %s, %d colunas, %s / ESC t %d)",
                      __version__, self.cfg.conexao, self.cfg.colunas, self.cfg.codificacao,
                      self.cfg.tabela_esc_t)
        self.log.info("pasta de dados: %s", self.cfg.pasta)
        self.impressora.iniciar()
        self.servidor.iniciar()
        if self.servidor_ipp:
            self.servidor_ipp.iniciar()

    def parar(self):
        if self.servidor_ipp:
            self.servidor_ipp.parar()
        self.servidor.parar()
        self.impressora.parar()
        self.log.info("ponte parada")

    def receber_paginas(self, paginas, origem: str):
        """Chamado pelo servidor IPP com as páginas (imagens) de um trabalho."""
        try:
            trab = imagem.paginas_para_trabalho(paginas, self.cfg, origem)
        except Exception:
            self.log.exception("%s: não consegui converter a imagem", origem)
            return
        if trab is None:
            self.log.info("%s: página(s) em branco, nada a imprimir", origem)
            return
        self.impressora.enviar(trab)

    def receber(self, dados: bytes, origem: str):
        """Chamado pelo servidor (ou pela linha de comando) com os bytes de um trabalho."""
        self._salvar_se_ativo(dados, ".bin")
        try:
            trab = conversor.preparar(dados, self.cfg, origem)
        except Exception:
            self.log.exception("%s: não consegui converter o trabalho", origem)
            return
        if trab is None:
            self.log.info("%s: trabalho vazio, ignorado", origem)
            return
        self.impressora.enviar(trab)

    def imprimir_e_sair(self, dados: bytes, origem: str):
        """Imprime um único trabalho sem abrir o servidor (para testes)."""
        self.impressora.iniciar()
        try:
            self.receber(dados, origem)
            self.impressora.aguardar()
        finally:
            self.impressora.parar()

    def enfileirar_teste(self):
        """Página de teste pela ponte já em funcionamento (menu da bandeja)."""
        self.receber(texto_pagina_teste().encode("utf-8"), "pagina de teste")

    def enfileirar_calibracao(self):
        """Régua de calibração pela ponte já em funcionamento (menu da bandeja)."""
        self.impressora.enviar(self._trabalho_calibracao())

    def _trabalho_calibracao(self):
        """Régua 01..12 SEM avanço final: o usuário rasga na serrilha e diz o
        último número que saiu inteiro. linhas_finais = 12 - esse número."""
        return conversor.texto_para_trabalho(texto_calibracao(), self.cfg, "calibracao",
                                             linhas_finais=0)

    def calibrar(self):
        trab = self._trabalho_calibracao()
        self.impressora.iniciar()
        try:
            self.impressora.enviar(trab)
            self.impressora.aguardar()
        finally:
            self.impressora.parar()

    def _salvar_se_ativo(self, dados: bytes, extensao: str):
        """Guarda os bytes recebidos em <dados>\\trabalhos (opção salvar_trabalhos)."""
        if not self.cfg.salvar_trabalhos:
            return
        pasta = self.cfg.pasta / "trabalhos"
        pasta.mkdir(exist_ok=True)
        nome = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + extensao
        (pasta / nome).write_bytes(dados)
        for antigo in sorted(pasta.glob("*.*"))[:-MAX_TRABALHOS_SALVOS]:
            antigo.unlink(missing_ok=True)


LINHAS_REGUA = 12


def texto_calibracao() -> str:
    regua = "\n".join(f"{i:02d} " + "-" * 29 for i in range(1, LINHAS_REGUA + 1))
    return (
        "CALIBRAÇÃO DO AVANÇO FINAL\n"
        "Rasgue na serrilha AGORA, sem\n"
        "apertar o botão de avanço, e\n"
        "anote o último número que saiu\n"
        "INTEIRO no pedaço rasgado.\n"
        "================================\n"
        f"{regua}\n"
    )


def texto_pagina_teste() -> str:
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return (
        f"PONTE MTI-773 v{__version__}\n"
        "Teste de texto\n"
        "--------------------------------\n"
        "ação ÁÉÍÓÚ çÇ ãõ âêô à ü\n"
        "Coração, pão, maçã, avó, você.\n"
        "Esta linha é bem comprida e precisa ser quebrada em 32 colunas sem cortar as palavras.\n"
        "\t<- tab virou 4 espaços\n"
        "“Aspas curvas” – travessão … 10€\n"
        "--------------------------------\n"
        f"{agora}\n"
    )
