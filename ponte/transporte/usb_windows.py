r"""
Transporte USB para Windows, SEM driver de impressora.

Quando uma impressora USB é ligada, o driver "usbprint" (do próprio Windows)
cria um caminho de dispositivo, por exemplo:
    \\?\USB#VID_28E9&PID_0289#000000000004#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}
Abrindo esse caminho com CreateFile, lemos e escrevemos bytes como num arquivo.

Usamos I/O "overlapped" (assíncrono) para ter TIMEOUT: uma leitura comum
ficaria travada para sempre se a impressora não respondesse.
"""

import ctypes
import uuid
from ctypes import wintypes

from .base import ErroTransporte, Transporte

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
cfgmgr32 = ctypes.WinDLL("cfgmgr32")

# Classe de interface "impressora USB" (GUID_DEVINTERFACE_USBPRINT)
GUID_USBPRINT = "{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995
WAIT_OBJECT_0 = 0
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
CR_SUCCESS = 0
CR_BUFFER_SMALL = 0x1A
CM_GET_DEVICE_INTERFACE_LIST_PRESENT = 0  # só dispositivos conectados agora

# Códigos de erro que significam "o dispositivo não está mais lá"
# (5 = "Acesso negado": visto ao tirar o cabo USB com a conexão aberta)
ERROS_DESCONEXAO = {2, 3, 5, 6, 22, 31, 55, 433, 1167}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def de_texto(cls, texto):
        u = uuid.UUID(texto)
        return cls(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
for _f in (kernel32.WriteFile, kernel32.ReadFile):
    _f.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                   ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

cfgmgr32.CM_Get_Device_Interface_List_SizeW.argtypes = [ctypes.POINTER(ctypes.c_ulong),
                                                        ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                                        ctypes.c_ulong]
cfgmgr32.CM_Get_Device_Interface_ListW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                                   ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong]


def listar_impressoras_usb() -> list[str]:
    """Caminhos de todas as impressoras USB conectadas AGORA (pergunta ao Windows)."""
    guid = GUID.de_texto(GUID_USBPRINT)
    for _ in range(5):  # a lista pode mudar entre as duas chamadas; tentamos de novo
        tamanho = ctypes.c_ulong(0)
        if cfgmgr32.CM_Get_Device_Interface_List_SizeW(
                ctypes.byref(tamanho), ctypes.byref(guid), None,
                CM_GET_DEVICE_INTERFACE_LIST_PRESENT) != CR_SUCCESS:
            return []
        buf = ctypes.create_unicode_buffer(tamanho.value)
        r = cfgmgr32.CM_Get_Device_Interface_ListW(ctypes.byref(guid), None, buf, tamanho.value,
                                                   CM_GET_DEVICE_INTERFACE_LIST_PRESENT)
        if r == CR_SUCCESS:
            # O resultado é uma lista "texto\0texto\0\0"
            return [c for c in buf[:tamanho.value].split("\0") if c]
        if r != CR_BUFFER_SMALL:
            return []
    return []


class TransporteUSB(Transporte):
    def __init__(self, vid: int, pid: int):
        self.vid, self.pid = vid, pid
        self.descricao = f"USB {vid:04X}:{pid:04X}"
        self.caminho = None
        self._h = None

    # --- conexão -------------------------------------------------------
    def abrir(self):
        if self._h:
            return
        filtro = f"vid_{self.vid:04x}&pid_{self.pid:04x}"
        caminhos = [c for c in listar_impressoras_usb() if filtro in c.lower()]
        if not caminhos:
            raise ErroTransporte(f"impressora {self.descricao} não encontrada "
                                 "(cabo desconectado ou impressora desligada?)", desconectado=True)
        h = kernel32.CreateFileW(caminhos[0], GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                 OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if h in (None, INVALID_HANDLE_VALUE):
            raise self._erro(ctypes.get_last_error(), "abrir")
        self._h, self.caminho = h, caminhos[0]

    def fechar(self):
        if self._h:
            kernel32.CloseHandle(self._h)
        self._h = None

    @property
    def aberto(self) -> bool:
        return self._h is not None

    # --- leitura e escrita ---------------------------------------------
    def escrever(self, dados: bytes, timeout_s: float = 10.0) -> int:
        self._exigir_aberto()
        buf = ctypes.create_string_buffer(bytes(dados), len(dados))
        n, _ = self._io(kernel32.WriteFile, timeout_s, buf, len(dados))
        if n < len(dados):
            raise ErroTransporte(f"a impressora aceitou só {n} de {len(dados)} bytes em "
                                 f"{timeout_s:.0f} s (travada ou em alarme?)", travada=True)
        return n

    def ler(self, tamanho: int = 64, timeout_s: float = 1.0) -> bytes:
        self._exigir_aberto()
        buf = ctypes.create_string_buffer(tamanho)
        n, _ = self._io(kernel32.ReadFile, timeout_s, buf, tamanho)
        return buf.raw[:n]

    # --- detalhes internos ---------------------------------------------
    def _exigir_aberto(self):
        if not self._h:
            raise ErroTransporte("conexão USB fechada", desconectado=True)

    def _erro(self, codigo, acao="comunicar") -> ErroTransporte:
        return ErroTransporte(f"falha ao {acao} ({codigo}: {ctypes.FormatError(codigo).strip()})",
                              desconectado=codigo in ERROS_DESCONEXAO)

    def _io(self, funcao, timeout_s, *args) -> tuple[int, bool]:
        """Executa ReadFile/WriteFile overlapped esperando no máximo timeout_s.
        Devolve (bytes transferidos, se estourou o tempo)."""
        ov = OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        try:
            if not funcao(self._h, *args, None, ctypes.byref(ov)):
                codigo = ctypes.get_last_error()
                if codigo != ERROR_IO_PENDING:
                    raise self._erro(codigo)
            estourou = kernel32.WaitForSingleObject(ov.hEvent, int(timeout_s * 1000)) != WAIT_OBJECT_0
            if estourou:
                kernel32.CancelIoEx(self._h, ctypes.byref(ov))
            n = wintypes.DWORD(0)
            # wait=True: só retorna quando a operação terminou (ou foi cancelada),
            # então o buffer e a estrutura OVERLAPPED podem ser liberados com segurança
            if not kernel32.GetOverlappedResult(self._h, ctypes.byref(ov), ctypes.byref(n), True):
                codigo = ctypes.get_last_error()
                if codigo != ERROR_OPERATION_ABORTED:  # cancelamento nosso = só timeout
                    raise self._erro(codigo)
            return n.value, estourou
        finally:
            kernel32.CloseHandle(ov.hEvent)
