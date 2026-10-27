"""
Transporte Bluetooth (porta COM virtual do perfil SPP) — AINDA NÃO IMPLEMENTADO.

Este PC de desenvolvimento não tem Bluetooth. Quando houver, o plano é:
  - abrir a porta COM (ex.: \\\\.\\COM5) com CreateFile, como no USB, e
    configurar velocidade/timeouts com SetCommState / SetCommTimeouts;
  - MANTER a porta aberta o tempo todo: no PC da loja o Windows pedia o PIN
    a cada nova conexão, então reconectar a cada trabalho seria inviável;
  - se a conexão cair, levantar ErroTransporte(desconectado=True): a classe
    Impressora já cuida de reconectar e reenviar.
Nada no resto da ponte precisa mudar: basta implementar os métodos de Transporte.
"""

from .base import ErroTransporte, Transporte


class TransporteBluetooth(Transporte):
    def __init__(self, porta_com: str, velocidade: int):
        self.porta_com, self.velocidade = porta_com, velocidade
        self.descricao = f"Bluetooth {porta_com} ({velocidade} bps)"

    def abrir(self):
        raise ErroTransporte("transporte Bluetooth ainda não implementado (use conexao = usb)")

    def fechar(self):
        pass

    @property
    def aberto(self) -> bool:
        return False

    def escrever(self, dados: bytes, timeout_s: float = 10.0) -> int:
        raise ErroTransporte("transporte Bluetooth ainda não implementado")

    def ler(self, tamanho: int = 64, timeout_s: float = 1.0) -> bytes:
        raise ErroTransporte("transporte Bluetooth ainda não implementado")
