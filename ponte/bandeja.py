r"""
Ícone na bandeja do Windows (perto do relógio) que hospeda a ponte.

Feito só com ctypes (API do Windows) + Pillow para desenhar os ícones, sem
bibliotecas extras (assim tudo continua livre para distribuir).

  - verde = pronta, amarelo = aviso (papel, pausa...), vermelho = erro/desconectada;
  - notificação do Windows, em português, sempre que o estado muda;
  - clique direito (ou esquerdo) abre o menu.

Uma regra do Windows: só a thread que criou a janela pode mexer no ícone.
Por isso a thread da impressora apenas "posta" uma mensagem (PostMessageW) e
quem atualiza o ícone é a thread da janela.
"""

import ctypes
import os
import queue
import subprocess
import sys
from ctypes import wintypes

from PIL import Image, ImageDraw

from . import __version__, config
from .app import Ponte, LINHAS_REGUA

NOME = "Ponte MTI-773"

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# --- constantes da API -------------------------------------------------
WM_DESTROY, WM_CLOSE, WM_COMMAND = 0x0002, 0x0010, 0x0111
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_APP = 0x8000
WM_ICONE = WM_APP + 1      # eventos do ícone (cliques)
WM_ESTADO = WM_APP + 2     # a impressora mudou de estado
WM_AVISO = WM_APP + 3      # há um aviso na fila para mostrar

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NIIF_INFO, NIIF_WARNING, NIIF_ERROR = 1, 2, 3
NOTIFYICON_VERSION_4 = 4

MF_STRING, MF_GRAYED, MF_SEPARATOR, MF_CHECKED = 0x0, 0x1, 0x800, 0x8
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
MB_OK, MB_ICONINFO, MB_ICONWARN, MB_ICONERROR = 0x0, 0x40, 0x30, 0x10
ERROR_ALREADY_EXISTS = 183

# Itens do menu
(CMD_STATUS, CMD_TESTE, CMD_CALIBRAR, CMD_LOG, CMD_CONFIG,
 CMD_REINICIAR, CMD_PAUSAR, CMD_SAIR) = range(1, 9)

CORES = {"ok": (46, 160, 67), "aviso": (230, 180, 0), "erro": (210, 40, 40)}
NIVEL_BALAO = {"ok": NIIF_INFO, "aviso": NIIF_WARNING, "erro": NIIF_ERROR}


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


# Tipos de argumentos/retorno (evita erros com ponteiros em Windows 64 bits)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def mensagem(texto, titulo=NOME, icone=MB_ICONINFO):
    user32.MessageBoxW(None, texto, titulo, MB_OK | icone)


def desenhar_icone(cor) -> Image.Image:
    """Um rolinho de papel saindo de uma impressora, sobre um círculo colorido."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((1, 1, 62, 62), fill=cor + (255,))
    d.rectangle((20, 10, 44, 40), fill="white")                         # papel
    for y in (17, 23, 29):
        d.line((24, y, 40, y), fill=(90, 90, 90), width=2)              # "linhas" impressas
    d.rounded_rectangle((12, 34, 52, 52), radius=5, fill=(40, 40, 40))  # corpo da impressora
    d.rectangle((18, 36, 46, 39), fill=(140, 140, 140))                 # saída do papel
    return img


def gerar_icones(pasta) -> dict:
    """Salva um .ico por cor na pasta de dados e devolve os caminhos."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = {}
    for nivel, cor in CORES.items():
        caminho = pasta / f"icone_{nivel}.ico"
        desenhar_icone(cor).save(caminho, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
        caminhos[nivel] = caminho
    return caminhos


class Bandeja:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ponte = None
        self.avisos = queue.Queue()        # (titulo, texto, nivel) vindos de outras threads
        self.hwnd = None
        self.icones = {}
        self._ultimo_estado = None
        self._wndproc = WNDPROC(self._tratar)  # guardar referência: senão o Python a apaga
        self._msg_taskbar = user32.RegisterWindowMessageW("TaskbarCreated")

    # --- ciclo de vida ---------------------------------------------------
    def executar(self) -> int:
        self._criar_janela()
        for nivel, caminho in gerar_icones(self.cfg.pasta / "icones").items():
            self.icones[nivel] = user32.LoadImageW(None, str(caminho), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        self._iniciar_ponte()
        self._icone(NIM_ADD)
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0

    def _iniciar_ponte(self) -> bool:
        self.ponte = Ponte(self.cfg)
        imp = self.ponte.impressora
        imp.ao_mudar_estado = lambda estado: user32.PostMessageW(self.hwnd, WM_ESTADO, 0, 0)
        imp.ao_avisar = self._enfileirar_aviso
        try:
            self.ponte.iniciar()
        except RuntimeError as e:  # porta 9100 ou 631 ocupada
            self.ponte.log.error("%s", e)
            self.ponte.parar()
            self.ponte = None
            mensagem(f"A ponte não conseguiu iniciar:\n\n{e}\n\nTalvez ela já esteja aberta "
                     "(veja o ícone perto do relógio).", icone=MB_ICONERROR)
            return False
        return True

    def _parar_ponte(self):
        if self.ponte:
            self.ponte.parar()
            self.ponte = None

    def _criar_janela(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=hinst, lpszClassName="PonteMTI773Bandeja")
        user32.RegisterClassW(ctypes.byref(wc))
        # Janela invisível: só existe para receber as mensagens do ícone
        self.hwnd = user32.CreateWindowExW(0, wc.lpszClassName, NOME, 0, 0, 0, 0, 0,
                                           None, None, hinst, None)

    # --- ícone e notificações -------------------------------------------
    def _estado(self):
        if not self.ponte:
            return "erro", "Ponte parada (não iniciou)"
        e = self.ponte.impressora.estado
        return e.nivel, e.mensagem

    def _dados_icone(self) -> NOTIFYICONDATAW:
        nivel, texto = self._estado()
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID = self.hwnd, 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        nid.uCallbackMessage = WM_ICONE
        nid.hIcon = self.icones.get(nivel)
        nid.szTip = f"{NOME}: {texto}"[:127]
        return nid

    def _icone(self, operacao):
        nid = self._dados_icone()
        shell32.Shell_NotifyIconW(operacao, ctypes.byref(nid))
        if operacao == NIM_ADD:
            nid.uVersion = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

    def _balao(self, titulo, texto, nivel):
        nid = self._dados_icone()
        nid.uFlags |= NIF_INFO
        nid.szInfoTitle = titulo[:63]
        nid.szInfo = texto[:255]
        nid.dwInfoFlags = NIVEL_BALAO.get(nivel, NIIF_INFO)
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _enfileirar_aviso(self, titulo, texto, nivel):
        self.avisos.put((titulo, texto, nivel))
        user32.PostMessageW(self.hwnd, WM_AVISO, 0, 0)

    def _estado_mudou(self):
        self._icone(NIM_MODIFY)
        atual = self._estado()
        anterior, self._ultimo_estado = self._ultimo_estado, atual
        nivel, texto = atual
        if atual == anterior or texto in ("Iniciando...", "Retomando..."):
            return
        # A primeira vez que fica pronta não precisa de aviso (é só a ponte abrindo)
        if anterior is None and nivel == "ok":
            return
        titulo = {"ok": "Impressora pronta", "aviso": "Atenção"}.get(nivel, "Problema na impressora")
        self._balao(titulo, texto, nivel)

    # --- menu --------------------------------------------------------------
    def _menu(self):
        nivel, texto = self._estado()
        imp = self.ponte.impressora if self.ponte else None
        rotulo = f"Status: {texto}"
        if imp:
            rotulo += f"  (impressos: {imp.impressos}, na fila: {imp.na_fila})"
        if len(rotulo) > 90:
            rotulo = rotulo[:87] + "..."
        ativo = MF_STRING if self.ponte else MF_STRING | MF_GRAYED
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_STATUS, rotulo)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, ativo, CMD_TESTE, "Imprimir página de teste")
        user32.AppendMenuW(menu, ativo, CMD_CALIBRAR, "Calibrar avanço do papel")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_LOG, "Abrir log")
        user32.AppendMenuW(menu, MF_STRING, CMD_CONFIG, "Abrir config.ini")
        user32.AppendMenuW(menu, MF_STRING, CMD_REINICIAR, "Reiniciar ponte (aplica o config.ini)")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        pausada = bool(imp and imp.pausada)
        user32.AppendMenuW(menu, ativo | (MF_CHECKED if pausada else 0), CMD_PAUSAR, "Pausar")
        user32.AppendMenuW(menu, MF_STRING, CMD_SAIR, "Sair")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # sem isso o menu não fecha ao clicar fora
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if cmd:
            self._comando(cmd)

    def _comando(self, cmd):
        cfg = self.cfg
        if cmd == CMD_STATUS:
            nivel, texto = self._estado()
            detalhe = ""
            if self.ponte and self.ponte.impressora.status:
                detalhe = f"\n\nStatus bruto (DLE EOT 1-4): {self.ponte.impressora.status.hexa()}"
            icone = {"ok": MB_ICONINFO, "aviso": MB_ICONWARN}.get(nivel, MB_ICONERROR)
            mensagem(f"{texto}{detalhe}\n\nVersão {__version__}\nDados e log: {cfg.pasta}",
                     icone=icone)
        elif cmd == CMD_TESTE and self.ponte:
            self.ponte.enfileirar_teste()
        elif cmd == CMD_CALIBRAR and self.ponte:
            self.ponte.enfileirar_calibracao()
            mensagem("A régua de calibração está sendo impressa.\n\n"
                     "1. Rasgue o papel na serrilha, SEM apertar o botão de avanço.\n"
                     "2. Veja o último número que saiu INTEIRO no pedaço rasgado.\n"
                     f"3. Abra o config.ini (menu da bandeja) e use:\n"
                     f"     linhas_finais = {LINHAS_REGUA} - esse número\n"
                     f"   (valor atual: {cfg.linhas_finais})\n"
                     "4. Salve e clique em \"Reiniciar ponte\".")
        elif cmd == CMD_LOG:
            os.startfile(cfg.pasta / "ponte.log")
        elif cmd == CMD_CONFIG:
            subprocess.Popen(["notepad.exe", str(cfg.pasta / "config.ini")])
        elif cmd == CMD_REINICIAR:
            self._reiniciar()
        elif cmd == CMD_PAUSAR and self.ponte:
            imp = self.ponte.impressora
            imp.pausar(not imp.pausada)
        elif cmd == CMD_SAIR:
            user32.DestroyWindow(self.hwnd)

    def _reiniciar(self):
        try:
            novo = config.carregar(self.cfg.pasta / "config.ini")
        except ValueError as e:
            mensagem(f"O config.ini tem um erro e a ponte continua com a configuração "
                     f"anterior:\n\n{e}", icone=MB_ICONERROR)
            return
        self._parar_ponte()
        self.cfg = novo
        self._ultimo_estado = None
        if self._iniciar_ponte():
            self._balao("Ponte reiniciada", "Configuração recarregada.", "ok")
        self._icone(NIM_MODIFY)

    # --- mensagens da janela ----------------------------------------------
    def _tratar(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_ICONE:
                evento = lparam & 0xFFFF  # NOTIFYICON_VERSION_4: evento na parte baixa
                if evento in (WM_RBUTTONUP, WM_LBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                return 0
            if msg == WM_ESTADO:
                self._estado_mudou()
                return 0
            if msg == WM_AVISO:
                while not self.avisos.empty():
                    self._balao(*self.avisos.get())
                return 0
            if msg == self._msg_taskbar:  # o Explorer reiniciou: o ícone precisa voltar
                self._icone(NIM_ADD)
                return 0
            if msg == WM_DESTROY:
                self._parar_ponte()
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._dados_icone()))
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            if self.ponte:
                self.ponte.log.exception("erro na bandeja (mensagem %#x)", msg)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main(caminho_config=None) -> int:
    # Uma só ponte por sessão do Windows
    mutex = kernel32.CreateMutexW(None, False, "Local\\PonteMTI773")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        mensagem("A ponte já está aberta: procure o ícone perto do relógio.")
        return 0
    try:
        cfg = config.carregar(caminho_config)
    except ValueError as e:
        mensagem(f"Erro no config.ini:\n\n{e}", icone=MB_ICONERROR)
        return 2
    try:
        return Bandeja(cfg).executar()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())
