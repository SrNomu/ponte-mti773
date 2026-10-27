"""
Interface comum de "transporte": o caminho físico até a impressora.

O resto da ponte só conhece esta interface. Para suportar uma nova forma de
conexão (ex.: Bluetooth), basta criar outra classe com estes mesmos métodos.
"""

from abc import ABC, abstractmethod


class ErroTransporte(Exception):
    """Falha de comunicação com a impressora.

    desconectado: o dispositivo sumiu (cabo tirado, impressora desligada...).
                  Vale a pena tentar reconectar.
    travada:      a impressora está conectada mas parou de aceitar dados
                  (na MTI-773 isso acontece em alarme: só tirando o cabo USB).
    """

    def __init__(self, mensagem, desconectado=False, travada=False):
        super().__init__(mensagem)
        self.desconectado = desconectado
        self.travada = travada


class Transporte(ABC):
    descricao = "transporte"

    @abstractmethod
    def abrir(self):
        """Conecta. Levanta ErroTransporte se não conseguir."""

    @abstractmethod
    def fechar(self):
        """Desconecta (pode ser chamado mesmo se já estiver fechado)."""

    @property
    @abstractmethod
    def aberto(self) -> bool:
        ...

    @abstractmethod
    def escrever(self, dados: bytes, timeout_s: float = 10.0) -> int:
        """Envia todos os bytes ou levanta ErroTransporte."""

    @abstractmethod
    def ler(self, tamanho: int = 64, timeout_s: float = 1.0) -> bytes:
        """Lê o que chegar em até timeout_s (b"" se nada chegou)."""
