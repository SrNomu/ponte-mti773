"""
A "dona" da conexão com a impressora.

Uma única thread fala com a impressora, pegando trabalhos de uma fila. Assim,
se dois programas imprimirem ao mesmo tempo, os bytes nunca se misturam.

Para cada trabalho:
  1. garante a conexão (reconecta sozinha se o cabo foi tirado e recolocado);
  2. espera o status ficar OK (com papel, sem erro);
  3. envia os blocos em pedaços pequenos, com pausa, consultando o status
     ENTRE blocos (nunca no meio de um comando ESC/POS);
  4. se algo falhar no meio, NÃO reimprime (para não sair em dobro).

Sem trabalhos, a mesma thread consulta o status a cada poucos segundos. Como é
a mesma thread, a consulta nunca cai no meio de uma impressão.

O "estado" (verde/amarelo/vermelho + mensagem) é o que a bandeja mostra.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from . import escpos
from .transporte import ErroTransporte

# Mensagens mostradas ao usuário (log e notificações da bandeja)
MSG_PRONTA = "Impressora pronta"
MSG_PAPEL = ("Sem papel detectado (4 bipes): abra e feche a tampa com firmeza e confira "
             "se o papel está encaixado")  # texto definido pelo usuário (4 bipes = sensor de papel)
MSG_PAPEL_ACABANDO = "Papel acabando: troque o rolo em breve"
MSG_CABECA = ("Cabeça de impressão quente ou tensão baixa: aguarde alguns segundos; "
              "se repetir, carregue a bateria")
MSG_ERRO = "Erro na impressora: desligue, tire o cabo USB, espere 5 s e reconecte"
MSG_OFFLINE = "Impressora offline: confira a tampa e o papel"
MSG_DESCONECTADA = "Impressora desconectada: confira o cabo USB e se ela está ligada"
MSG_TRAVADA = ("Impressora travada (não responde): desligue, TIRE O CABO USB, espere 5 s e "
               "reconecte. Se acontecer no meio da impressão, provável bateria fraca: carregue")
MSG_PAUSADA = "Pausada: os trabalhos ficam na fila até você retomar"


@dataclass(frozen=True)
class Estado:
    nivel: str      # "ok" (verde), "aviso" (amarelo) ou "erro" (vermelho)
    mensagem: str


def estado_do_status(st: escpos.Status) -> Estado:
    if not st.respondeu:
        return Estado("erro", MSG_TRAVADA)
    if st.erro:
        return Estado("erro", MSG_ERRO)
    if st.sem_papel:
        return Estado("aviso", MSG_PAPEL)
    if st.cabeca_quente:
        return Estado("aviso", MSG_CABECA)
    if st.offline:
        return Estado("aviso", MSG_OFFLINE)
    if st.papel_acabando:
        return Estado("aviso", MSG_PAPEL_ACABANDO)
    return Estado("ok", MSG_PRONTA)


@dataclass
class Trabalho:
    nome: str                # de onde veio (ex.: "TCP 127.0.0.1:53211")
    blocos: list             # pedaços "seguros": entre eles podemos consultar o status
    descricao: str = ""
    criado: float = field(default_factory=time.monotonic)

    @property
    def tamanho(self) -> int:
        return sum(len(b) for b in self.blocos)


class ImpressoraIndisponivel(Exception):
    pass


def ler_status(transporte, tentativas=3) -> escpos.Status:
    """Consulta DLE EOT 1..4. Logo depois de receber uma imagem grande a
    impressora pode demorar mais de 1 s para responder (visto no teste 4),
    então uma consulta sem resposta é repetida esperando cada vez mais."""
    # Descarta respostas atrasadas que tenham sobrado no canal de leitura
    for _ in range(10):
        if not transporte.ler(64, 0.02):
            break
    respostas = []
    for consulta in escpos.CONSULTAS_STATUS:
        r = b""
        for tentativa in range(tentativas):
            transporte.escrever(consulta, timeout_s=2)
            r = transporte.ler(64, 0.8 * (tentativa + 1))  # 0,8 s, 1,6 s, 2,4 s
            if r:
                break
        respostas.append(r[-1] if r else None)  # último byte = resposta mais recente
    return escpos.Status(tuple(respostas))


class Impressora:
    def __init__(self, cfg, transporte, log):
        self._cfg, self._t, self._log = cfg, transporte, log
        self._fila = queue.Queue()
        self._parar = threading.Event()
        self._thread = None
        self._enviados = 0
        self._ultima_verificacao = 0.0
        self._pausado = False
        self._retomado_em = 0.0
        self.status = None                      # último escpos.Status lido
        self.estado = Estado("aviso", "Iniciando...")
        self.impressos = 0                      # trabalhos enviados nesta sessão
        self.ao_mudar_estado = None             # função(Estado), chamada de qualquer thread
        self.ao_avisar = None                   # função(titulo, mensagem, nivel)

    # --- interface pública ---------------------------------------------
    def iniciar(self):
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="impressora", daemon=True)
        self._thread.start()

    def parar(self):
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=15)
        self._t.fechar()

    def enviar(self, trabalho: Trabalho):
        """Coloca o trabalho na fila (pode ser chamado de qualquer thread)."""
        self._log.info("recebido: %s (%s, %d bytes)", trabalho.nome, trabalho.descricao, trabalho.tamanho)
        self._fila.put(trabalho)

    def aguardar(self):
        """Bloqueia até a fila esvaziar (usado pela linha de comando)."""
        self._fila.join()

    @property
    def pausada(self) -> bool:
        return self._pausado

    def pausar(self, pausar: bool):
        """Pausada, a ponte solta a USB e não imprime; os trabalhos esperam na fila."""
        if pausar == self._pausado:
            return
        self._pausado = pausar
        if pausar:
            self._definir_estado(Estado("aviso", MSG_PAUSADA))
        else:
            self._retomado_em = time.monotonic()  # o prazo dos trabalhos recomeça
            self._ultima_verificacao = 0.0        # verifica a impressora já
            self._definir_estado(Estado("aviso", "Retomando..."))

    @property
    def na_fila(self) -> int:
        return self._fila.qsize()

    # --- laço principal ------------------------------------------------
    def _laco(self):
        while not self._parar.is_set():
            if self._pausado:
                if self._t.aberto:
                    self._t.fechar()
                    self._log.info("pausada: conexão com a impressora liberada")
                self._parar.wait(0.5)
                continue
            try:
                trab = self._fila.get(timeout=1.0)
            except queue.Empty:
                self._verificar_ocioso()
                continue
            try:
                self._imprimir(trab)
            except Exception:
                self._log.exception("erro inesperado ao imprimir %s", trab.nome)
            finally:
                self._fila.task_done()

    def _imprimir(self, trab: Trabalho):
        while not self._parar.is_set():
            if self._pausado:
                self._parar.wait(0.5)
                continue
            prazo = max(trab.criado, self._retomado_em) + self._cfg.espera_max_s
            if time.monotonic() > prazo:
                self._log.error("trabalho %s DESCARTADO: impressora indisponível por mais de %d s",
                                trab.nome, self._cfg.espera_max_s)
                self._avisar("Trabalho não impresso", f"{trab.nome}: impressora indisponível. "
                             f"{self.estado.mensagem}", "erro")
                return
            if not self._garantir_conexao():
                self._parar.wait(2)
                continue
            self._enviados = 0
            try:
                if not self._esperar_pronta(prazo):
                    continue  # volta ao topo: confere o prazo
                inicio = time.monotonic()
                self._enviar_blocos(trab, prazo)
                self.impressos += 1
                self._log.info("impresso: %s (%d bytes em %.1f s) — total nesta sessão: %d",
                               trab.nome, trab.tamanho, time.monotonic() - inicio, self.impressos)
                return
            except ErroTransporte as e:
                self._falha(e)
                if self._enviados == 0 and not e.travada:
                    continue  # nada saiu ainda: tenta de novo quando reconectar
                self._log.error("trabalho %s INTERROMPIDO depois de %d de %d bytes; não será "
                                "repetido para não imprimir em dobro", trab.nome, self._enviados,
                                trab.tamanho)
                self._avisar("Impressão interrompida", f"{trab.nome} saiu pela metade. "
                             f"{self.estado.mensagem}", "erro")
                return
            except ImpressoraIndisponivel as e:
                self._log.error("trabalho %s INTERROMPIDO: %s", trab.nome, e)
                self._avisar("Impressão interrompida", f"{trab.nome}: {e}", "erro")
                return

    def _enviar_blocos(self, trab: Trabalho, prazo: float):
        cfg = self._cfg
        desde_status = 0
        for bloco in trab.blocos:
            if cfg.usar_status and desde_status >= cfg.intervalo_status_bytes:
                if not self._esperar_pronta(prazo):
                    raise ImpressoraIndisponivel("a impressora não ficou pronta a tempo")
                desde_status = 0
            for i in range(0, len(bloco), cfg.tamanho_pedaco):
                pedaco = bloco[i:i + cfg.tamanho_pedaco]
                self._t.escrever(pedaco)
                self._enviados += len(pedaco)
                if cfg.pausa_ms:
                    time.sleep(cfg.pausa_ms / 1000)
            desde_status += len(bloco)

    # --- conexão, status e estado --------------------------------------
    def _garantir_conexao(self) -> bool:
        if self._t.aberto:
            return True
        try:
            self._t.abrir()
        except ErroTransporte as e:
            self._definir_estado(Estado("erro", MSG_DESCONECTADA), f"({e})")
            return False
        self._log.info("conectado: %s (%s)", self._t.descricao, getattr(self._t, "caminho", ""))
        return True

    def _falha(self, e: ErroTransporte):
        self._t.fechar()
        if e.travada:
            self._definir_estado(Estado("erro", MSG_TRAVADA), f"({e})")
        else:
            self._definir_estado(Estado("erro", MSG_DESCONECTADA), f"(conexão perdida: {e})")

    def _ler_status(self) -> escpos.Status:
        return ler_status(self._t)

    def _registrar_status(self, st: escpos.Status):
        self.status = st
        self._definir_estado(estado_do_status(st), f"[{st.hexa()}]")

    def _definir_estado(self, estado: Estado, detalhe=""):
        """Guarda o estado; só registra no log e avisa a bandeja quando MUDA."""
        if estado == self.estado:
            return
        self.estado = estado
        nivel = {"ok": logging.INFO, "aviso": logging.WARNING}.get(estado.nivel, logging.ERROR)
        self._log.log(nivel, "estado: %s %s", estado.mensagem, detalhe)
        if self.ao_mudar_estado:
            try:
                self.ao_mudar_estado(estado)
            except Exception:
                self._log.exception("erro ao avisar mudança de estado")

    def _avisar(self, titulo, mensagem, nivel):
        if self.ao_avisar:
            try:
                self.ao_avisar(titulo, mensagem, nivel)
            except Exception:
                self._log.exception("erro ao mostrar aviso")

    def _esperar_pronta(self, prazo: float) -> bool:
        if not self._cfg.usar_status:
            return True
        while not self._parar.is_set():
            st = self._ler_status()
            self._registrar_status(st)
            if st.ok:
                return True
            if time.monotonic() > prazo:
                return False
            self._parar.wait(1.0)
        return False

    def _verificar_ocioso(self):
        """Sem trabalhos: de tempos em tempos confere conexão e status."""
        intervalo = self._cfg.verificar_ocioso_s
        if not intervalo or time.monotonic() - self._ultima_verificacao < intervalo:
            return
        self._ultima_verificacao = time.monotonic()
        if not self._garantir_conexao():
            return
        if not self._cfg.usar_status:
            self._definir_estado(Estado("ok", MSG_PRONTA))
            return
        try:
            self._registrar_status(self._ler_status())
        except ErroTransporte as e:
            self._falha(e)
