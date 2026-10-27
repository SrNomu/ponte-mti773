"""Escolhe o transporte (USB, Bluetooth...) de acordo com o config.ini."""

from .base import ErroTransporte, Transporte


def criar_transporte(cfg) -> Transporte:
    if cfg.conexao == "usb":
        from .usb_windows import TransporteUSB
        return TransporteUSB(cfg.usb_vid, cfg.usb_pid)
    if cfg.conexao == "bluetooth":
        from .bluetooth import TransporteBluetooth
        return TransporteBluetooth(cfg.porta_com, cfg.velocidade)
    raise ValueError(f"conexão desconhecida: {cfg.conexao}")


__all__ = ["ErroTransporte", "Transporte", "criar_transporte"]
