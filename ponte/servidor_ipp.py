"""
Servidor IPP: faz a ponte parecer uma impressora "sem driver" para o Windows.

O Windows (driver "Microsoft IPP Class Driver", que já vem no sistema):
  1. pergunta o que a impressora suporta (Get-Printer-Attributes). Respondemos:
     papel de 58 mm com 5 mm de margem de cada lado, 203 dpi, cinza de 8 bits;
  2. os programas montam a página nesse tamanho;
  3. ao imprimir, o Windows desenha a página e manda em PWG Raster
     (Print-Job, ou Create-Job + Send-Document).

Escutamos só em 127.0.0.1: nada fica exposto na rede.
Tudo que o cliente pede e não temos vai para o log, para diagnóstico.
"""

import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, ipp, pwg
from .ipp import (BOOLEANO, CHARSET, COLECAO, ENUM, GRUPO_IMPRESSORA, GRUPO_OPERACAO,
                  GRUPO_TRABALHO, IDIOMA, INTEIRO, INTERVALO, NOME, PALAVRA, RESOLUCAO,
                  TEXTO, TIPO_MIME, URI)

CAMINHO = "/ipp/print"
FORMATO_PWG = "image/pwg-raster"
LIMITE_BYTES = 64 * 1024 * 1024
MAX_TRABALHOS_LEMBRADOS = 50
# Identificador fixo da impressora (o Windows usa para reconhecê-la)
UUID_IMPRESSORA = uuid.uuid5(uuid.NAMESPACE_URL, "urn:mti773-ponte:impressora")

# Estados de trabalho (IPP)
PENDENTE, PROCESSANDO, ABORTADO, CONCLUIDO = 3, 5, 8, 9
MOTIVO_ESTADO = {PENDENTE: "none", PROCESSANDO: "job-printing",
                 ABORTADO: "aborted-by-system", CONCLUIDO: "job-completed-successfully"}
# Pedidos de grupos inteiros de atributos
GRUPOS_ATRIBUTOS = {"all", "printer-description", "job-template"}


def nome_papel(largura_mm, comprimento_mm) -> str:
    """Nome no padrão PWG: classe_nome_LARGURAxALTURAmm (om = "outro, métrico")."""
    return f"om_cupom-{comprimento_mm:g}mm_{largura_mm:g}x{comprimento_mm:g}mm"


class ImpressoraIPP:
    """A lógica do protocolo (sem HTTP), para poder ser testada sozinha."""

    def __init__(self, cfg, ao_receber_paginas, ao_salvar, log):
        self._cfg, self._ao_receber, self._ao_salvar, self._log = cfg, ao_receber_paginas, ao_salvar, log
        self._trabalhos = {}
        self._proximo_id = 1
        self._trava = threading.Lock()
        self._inicio = time.time()

    # --- entrada ---------------------------------------------------------
    def processar(self, corpo: bytes, host: str, cliente: str) -> bytes:
        try:
            req = ipp.ler(corpo)
        except Exception as e:
            self._log.warning("IPP: mensagem inválida de %s: %s", cliente, e)
            return ipp.codificar((1, 1), ipp.ERRO_PEDIDO, 0, [(GRUPO_OPERACAO, self._attrs_operacao())])

        nome_op = ipp.OPERACOES.get(req.codigo, f"0x{req.codigo:04X}")
        self._log.debug("IPP %s v%d.%d #%d: %s", nome_op, *req.versao, req.pedido, req.resumo())
        metodo = {
            0x000B: self._get_printer_attributes, 0x0002: self._print_job,
            0x0004: self._validate_job, 0x0005: self._create_job, 0x0006: self._send_document,
            0x0009: self._get_job_attributes, 0x000A: self._get_jobs,
            0x0008: self._ok, 0x003B: self._ok, 0x003C: self._ok,
        }.get(req.codigo)
        if metodo is None:
            self._log.info("IPP: operação não suportada: %s", nome_op)
            status, grupos = ipp.ERRO_OPERACAO, []
        else:
            try:
                status, grupos = metodo(req, host)
            except Exception:
                self._log.exception("IPP: erro ao processar %s", nome_op)
                status, grupos = ipp.ERRO_INTERNO, []
        versao = (2, 0) if req.versao[0] >= 2 else (1, 1)
        return ipp.codificar(versao, status, req.pedido,
                             [(GRUPO_OPERACAO, self._attrs_operacao())] + grupos)

    def _attrs_operacao(self):
        return [(CHARSET, "attributes-charset", ["utf-8"]),
                (IDIOMA, "attributes-natural-language", ["en"])]

    # --- operações -------------------------------------------------------
    def _get_printer_attributes(self, req, host):
        todos = self._atributos_impressora(host)
        temos = {a[1] for a in todos}
        pedidos = set(req.grupo(GRUPO_OPERACAO).get("requested-attributes") or [])
        if not pedidos or pedidos & GRUPOS_ATRIBUTOS:
            # "all" não inclui media-col-database: só vai se for pedido pelo nome
            escolhidos = [a for a in todos if a[1] != "media-col-database" or "media-col-database" in pedidos]
        else:
            escolhidos = [a for a in todos if a[1] in pedidos]
        faltam = pedidos - temos - GRUPOS_ATRIBUTOS
        self._log.info("IPP: Get-Printer-Attributes (%d pedidos, %d enviados)%s", len(pedidos),
                       len(escolhidos), f"; pedidos que NÃO temos: {', '.join(sorted(faltam))}" if faltam else "")
        return ipp.OK, [(GRUPO_IMPRESSORA, escolhidos)]

    def _validate_job(self, req, host):
        formato = req.valor("document-format")
        if formato and not self._formato_aceito(formato):
            self._log.info("IPP: Validate-Job com formato não suportado: %s", formato)
            return ipp.ERRO_FORMATO, []
        return ipp.OK, []

    def _print_job(self, req, host):
        tid = self._novo_trabalho(req)
        status = self._receber_documento(tid, req.valor("document-format", padrao=FORMATO_PWG), req.dados)
        return status, [(GRUPO_TRABALHO, self._attrs_trabalho(tid, host))]

    def _create_job(self, req, host):
        tid = self._novo_trabalho(req)
        return ipp.OK, [(GRUPO_TRABALHO, self._attrs_trabalho(tid, host))]

    def _send_document(self, req, host):
        tid = req.valor("job-id")
        with self._trava:
            t = self._trabalhos.get(tid)
        if t is None:
            return ipp.ERRO_NAO_ENCONTRADO, []
        t["dados"] += req.dados
        status = ipp.OK
        if req.valor("last-document", padrao=True):
            status = self._receber_documento(tid, req.valor("document-format", padrao=FORMATO_PWG), t["dados"])
            t["dados"] = b""
        return status, [(GRUPO_TRABALHO, self._attrs_trabalho(tid, host))]

    def _get_job_attributes(self, req, host):
        tid = req.valor("job-id")
        with self._trava:
            existe = tid in self._trabalhos
        if not existe:
            return ipp.ERRO_NAO_ENCONTRADO, []
        return ipp.OK, [(GRUPO_TRABALHO, self._attrs_trabalho(tid, host))]

    def _get_jobs(self, req, host):
        quais = req.valor("which-jobs", padrao="not-completed")
        with self._trava:
            ids = sorted(self._trabalhos)
        if quais != "all":
            terminados = quais == "completed"
            ids = [i for i in ids if (self._trabalhos[i]["estado"] in (ABORTADO, CONCLUIDO)) == terminados]
        return ipp.OK, [(GRUPO_TRABALHO, self._attrs_trabalho(i, host)) for i in ids[-20:]]

    def _ok(self, req, host):
        return ipp.OK, []

    # --- trabalhos -------------------------------------------------------
    def _formato_aceito(self, formato):
        return formato in (FORMATO_PWG, "application/octet-stream")

    def _novo_trabalho(self, req) -> int:
        nome = req.valor("job-name", padrao=None) or req.valor("job-name", GRUPO_TRABALHO, "sem nome")
        pedido_trabalho = ipp.Mensagem(req.versao, req.codigo, req.pedido,
                                       [(GRUPO_TRABALHO, req.grupo(GRUPO_TRABALHO))]).resumo()
        if pedido_trabalho:  # ex.: media-col, output-bin, copies... (ajuda no diagnóstico)
            self._log.info("IPP: atributos do trabalho '%s': %s", nome, pedido_trabalho)
        with self._trava:
            tid = self._proximo_id
            self._proximo_id += 1
            self._trabalhos[tid] = {"nome": nome, "usuario": req.valor("requesting-user-name", padrao=""),
                                    "estado": PENDENTE, "dados": b""}
            for antigo in sorted(self._trabalhos)[:-MAX_TRABALHOS_LEMBRADOS]:
                del self._trabalhos[antigo]
        return tid

    def _receber_documento(self, tid, formato, dados) -> int:
        t = self._trabalhos[tid]
        origem = f"IPP trabalho {tid} '{t['nome']}'"
        if not self._formato_aceito(formato) and not dados.startswith(pwg.SINCRONIA):
            self._log.warning("%s: formato não suportado: %s (%d bytes)", origem, formato, len(dados))
            t["estado"] = ABORTADO
            return ipp.ERRO_FORMATO
        self._ao_salvar(dados, ".pwg")
        try:
            paginas = pwg.ler(dados)
        except ValueError as e:
            self._log.error("%s: não consegui ler o PWG Raster: %s", origem, e)
            t["estado"] = ABORTADO
            return ipp.ERRO_PEDIDO
        self._log.info("%s: %d página(s) %s, papel %s", origem, len(paginas),
                       ", ".join(f"{p.width}x{p.height}" for p in paginas),
                       paginas[0].info.get("papel") if paginas else "-")
        self._ao_receber(paginas, origem)
        # Simplificação da v1: o trabalho conta como "concluído" ao entrar na fila
        # da ponte. Erros da impressora aparecem no log (e na bandeja, etapa 4).
        t["estado"] = CONCLUIDO
        return ipp.OK

    def _attrs_trabalho(self, tid, host):
        t = self._trabalhos[tid]
        return [(URI, "job-uri", [f"ipp://{host}{CAMINHO}/{tid}"]),
                (INTEIRO, "job-id", [tid]),
                (ENUM, "job-state", [t["estado"]]),
                (PALAVRA, "job-state-reasons", [MOTIVO_ESTADO[t["estado"]]]),
                (NOME, "job-name", [t["nome"]]),
                (NOME, "job-originating-user-name", [t["usuario"] or "anonimo"])]

    # --- o que a impressora "é" ------------------------------------------
    def _atributos_impressora(self, host):
        cfg = self._cfg
        dpi = (cfg.dpi, cfg.dpi, 3)  # 3 = pontos por polegada
        largura = round(cfg.largura_papel_mm * 100)  # IPP usa centésimos de mm
        margem = round(cfg.ipp_margem_lateral_mm * 100)
        comprimentos = [round(c * 100) for c in cfg.ipp_comprimentos_mm]
        nomes = [nome_papel(cfg.largura_papel_mm, c) for c in cfg.ipp_comprimentos_mm]

        def tamanho(c):
            return [(INTEIRO, "x-dimension", [largura]), (INTEIRO, "y-dimension", [c])]

        def media_col(c):
            return [(COLECAO, "media-size", [tamanho(c)]),
                    (INTEIRO, "media-left-margin", [margem]), (INTEIRO, "media-right-margin", [margem]),
                    (INTEIRO, "media-top-margin", [0]), (INTEIRO, "media-bottom-margin", [0]),
                    (PALAVRA, "media-source", ["main-roll"]), (PALAVRA, "media-type", ["stationery"])]

        return [
            (URI, "printer-uri-supported", [f"ipp://{host}{CAMINHO}"]),
            (PALAVRA, "uri-security-supported", ["none"]),
            (PALAVRA, "uri-authentication-supported", ["none"]),
            (NOME, "printer-name", [cfg.ipp_nome]),
            (TEXTO, "printer-info", [f"{cfg.ipp_nome} (Ponte MTI-773 v{__version__})"]),
            (TEXTO, "printer-location", ["Este computador"]),
            (TEXTO, "printer-make-and-model", ["Tomate MTI-773 58mm"]),
            (TEXTO, "printer-device-id", ["MFG:Tomate;MDL:MTI-773;CMD:PWGRaster;CLS:PRINTER;"]),
            (URI, "printer-uuid", [f"urn:uuid:{UUID_IMPRESSORA}"]),
            (URI, "printer-more-info", [f"http://{host}/"]),
            (PALAVRA, "printer-kind", ["receipt", "roll"]),
            (ENUM, "printer-state", [3]),  # 3 = ociosa
            (PALAVRA, "printer-state-reasons", ["none"]),
            (TEXTO, "printer-state-message", ["Pronta"]),
            (BOOLEANO, "printer-is-accepting-jobs", [True]),
            (INTEIRO, "queued-job-count", [0]),
            (INTEIRO, "printer-up-time", [max(1, int(time.time() - self._inicio))]),
            (PALAVRA, "ipp-versions-supported", ["1.1", "2.0"]),
            (ENUM, "operations-supported", [0x0002, 0x0004, 0x0005, 0x0006, 0x0008, 0x0009,
                                            0x000A, 0x000B, 0x003B, 0x003C]),
            (CHARSET, "charset-configured", ["utf-8"]),
            (CHARSET, "charset-supported", ["utf-8"]),
            (IDIOMA, "natural-language-configured", ["en"]),
            (IDIOMA, "generated-natural-language-supported", ["en"]),
            (TIPO_MIME, "document-format-default", [FORMATO_PWG]),
            (TIPO_MIME, "document-format-supported", [FORMATO_PWG]),
            (PALAVRA, "pdl-override-supported", ["attempted"]),
            (PALAVRA, "compression-supported", ["none"]),
            (BOOLEANO, "color-supported", [False]),
            (PALAVRA, "print-color-mode-supported", ["monochrome"]),
            (PALAVRA, "print-color-mode-default", ["monochrome"]),
            (PALAVRA, "pwg-raster-document-type-supported", ["sgray_8"]),
            (RESOLUCAO, "pwg-raster-document-resolution-supported", [dpi]),
            (PALAVRA, "pwg-raster-document-sheet-back", ["normal"]),
            (RESOLUCAO, "printer-resolution-supported", [dpi]),
            (RESOLUCAO, "printer-resolution-default", [dpi]),
            (ENUM, "print-quality-supported", [4]),
            (ENUM, "print-quality-default", [4]),
            (PALAVRA, "sides-supported", ["one-sided"]),
            (PALAVRA, "sides-default", ["one-sided"]),
            (INTERVALO, "copies-supported", [(1, 99)]),
            (INTEIRO, "copies-default", [1]),
            (ENUM, "orientation-requested-supported", [3]),  # 3 = retrato
            (ENUM, "orientation-requested-default", [3]),
            (ENUM, "finishings-supported", [3]),  # 3 = nenhum acabamento
            (ENUM, "finishings-default", [3]),
            # "face-up" fazia o Windows mandar as páginas da ÚLTIMA para a primeira
            # (para a pilha de folhas sair em ordem). Num rolo queremos 1, 2, 3...
            (PALAVRA, "output-bin-supported", ["face-down"]),
            (PALAVRA, "output-bin-default", ["face-down"]),
            (BOOLEANO, "multiple-document-jobs-supported", [False]),
            (PALAVRA, "media-supported", nomes),
            (PALAVRA, "media-default", [nomes[0]]),
            (PALAVRA, "media-ready", nomes),
            (COLECAO, "media-size-supported", [tamanho(c) for c in comprimentos]),
            (COLECAO, "media-col-default", [media_col(comprimentos[0])]),
            (COLECAO, "media-col-ready", [media_col(c) for c in comprimentos]),
            (COLECAO, "media-col-database", [media_col(c) for c in comprimentos]),
            (PALAVRA, "media-col-supported", ["media-size", "media-left-margin", "media-right-margin",
                                              "media-top-margin", "media-bottom-margin",
                                              "media-source", "media-type"]),
            (INTEIRO, "media-left-margin-supported", [margem]),
            (INTEIRO, "media-right-margin-supported", [margem]),
            (INTEIRO, "media-top-margin-supported", [0]),
            (INTEIRO, "media-bottom-margin-supported", [0]),
            (PALAVRA, "media-source-supported", ["main-roll"]),
            (PALAVRA, "media-type-supported", ["stationery"]),
            (PALAVRA, "job-creation-attributes-supported",
             ["copies", "media", "media-col", "orientation-requested", "print-color-mode",
              "print-quality", "printer-resolution", "sides"]),
        ]

    def pagina_html(self) -> str:
        return (f"<html><head><meta charset='utf-8'><title>{self._cfg.ipp_nome}</title></head><body>"
                f"<h1>{self._cfg.ipp_nome}</h1><p>Ponte MTI-773 v{__version__}: impressora IPP "
                f"local para a térmica de 58 mm.</p></body></html>")


class _ManipuladorHTTP(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # conexões persistentes e "Expect: 100-continue"
    server_version = f"MTI773-Ponte/{__version__}"

    def do_POST(self):
        tipo = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        try:
            corpo = self._ler_corpo()
        except ValueError as e:
            self.server.log.warning("IPP: pedido HTTP inválido: %s", e)
            self.close_connection = True
            self._responder(400, b"pedido invalido", "text/plain")
            return
        if tipo != "application/ipp":
            self._responder(400, b"esperava application/ipp", "text/plain")
            return
        resposta = self.server.impressora_ipp.processar(
            corpo, self.headers.get("Host") or "127.0.0.1", self.client_address[0])
        self._responder(200, resposta, "application/ipp")

    def do_GET(self):
        self._responder(200, self.server.impressora_ipp.pagina_html().encode("utf-8"), "text/html; charset=utf-8")

    def _ler_corpo(self) -> bytes:
        # O Windows costuma mandar trabalhos em "chunked" (pedaços sem tamanho total)
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            partes, total = [], 0
            while True:
                linha = self.rfile.readline(65537)
                if not linha:
                    raise ValueError("conexão fechada no meio do envio")
                tamanho = int(linha.split(b";")[0].strip() or b"0", 16)
                if tamanho == 0:
                    while self.rfile.readline(65537).strip():  # cabeçalhos finais (raros)
                        pass
                    break
                partes.append(self.rfile.read(tamanho))
                self.rfile.readline()  # \r\n depois de cada pedaço
                total += tamanho
                if total > LIMITE_BYTES:
                    raise ValueError("trabalho grande demais")
            return b"".join(partes)
        n = int(self.headers.get("Content-Length") or 0)
        if n > LIMITE_BYTES:
            raise ValueError("trabalho grande demais")
        return self.rfile.read(n)

    def _responder(self, codigo, corpo: bytes, tipo: str):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato, *args):
        self.server.log.debug("HTTP %s: " + formato, self.client_address[0], *args)


class _ServidorHTTP(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # no Windows, True deixaria duas pontes na mesma porta


class ServidorIPP:
    def __init__(self, cfg, ao_receber_paginas, ao_salvar, log):
        self._cfg, self._log = cfg, log
        self.impressora_ipp = ImpressoraIPP(cfg, ao_receber_paginas, ao_salvar, log)
        self._srv = None

    def iniciar(self):
        endereco = (self._cfg.endereco, self._cfg.ipp_porta)
        try:
            self._srv = _ServidorHTTP(endereco, _ManipuladorHTTP)
        except OSError as e:
            raise RuntimeError(f"não consegui escutar IPP em {endereco[0]}:{endereco[1]} "
                               f"(a porta já está em uso?): {e}") from e
        self._srv.impressora_ipp = self.impressora_ipp
        self._srv.log = self._log
        threading.Thread(target=self._srv.serve_forever, name="servidor-ipp", daemon=True).start()
        self._log.info("impressora IPP em http://%s:%d%s", *endereco, CAMINHO)

    def parar(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
