"""
Servidor "RAW" na porta 9100 (padrão de impressoras de rede, também chamado
JetDirect). A impressora do Windows aponta para 127.0.0.1:9100: o spooler
conecta, manda os bytes do trabalho e fecha a conexão.

Escutamos só em 127.0.0.1, então nada fica exposto na rede.
"""

import socket
import socketserver
import threading

LIMITE_BYTES = 32 * 1024 * 1024  # proteção: nenhum trabalho legítimo é maior que isso


class _Manipulador(socketserver.BaseRequestHandler):
    def handle(self):
        srv = self.server
        origem = f"TCP {self.client_address[0]}:{self.client_address[1]}"
        self.request.settimeout(srv.tempo_ocioso_s)
        partes, total = [], 0
        while True:
            try:
                dados = self.request.recv(65536)
            except socket.timeout:
                break  # o programa não fechou a conexão, mas parou de mandar dados
            except OSError as e:
                srv.log.warning("%s: conexão interrompida (%s)", origem, e)
                break
            if not dados:
                break  # o programa fechou a conexão: fim do trabalho
            partes.append(dados)
            total += len(dados)
            if total > LIMITE_BYTES:
                srv.log.error("%s: trabalho maior que %d MB, descartado", origem, LIMITE_BYTES >> 20)
                return
        if total:
            srv.ao_receber(b"".join(partes), origem)


class _ServidorTCP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # No Windows, SO_REUSEADDR deixaria DUAS pontes escutarem a mesma porta; não queremos.
    allow_reuse_address = False


class ServidorRaw:
    def __init__(self, cfg, ao_receber, log):
        self._cfg, self._ao_receber, self._log = cfg, ao_receber, log
        self._srv = None

    def iniciar(self):
        endereco = (self._cfg.endereco, self._cfg.porta_raw)
        try:
            self._srv = _ServidorTCP(endereco, _Manipulador)
        except OSError as e:
            raise RuntimeError(f"não consegui escutar em {endereco[0]}:{endereco[1]} "
                               f"(a porta já está em uso? outra ponte aberta?): {e}") from e
        self._srv.ao_receber = self._ao_receber
        self._srv.log = self._log
        self._srv.tempo_ocioso_s = self._cfg.tempo_ocioso_s
        threading.Thread(target=self._srv.serve_forever, name="servidor-raw", daemon=True).start()
        self._log.info("escutando trabalhos RAW em %s:%d", *endereco)

    def parar(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
