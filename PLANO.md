# Plano da Ponte MTI-773

## Etapas
1. Diagnóstico — **concluído** (ver achados abaixo)
2. Texto — ponte RAW 127.0.0.1:9100 + impressora "MTI-773 Texto" (Generic / Text Only) — **concluído**
3. Imagens / PDF — impressora IPP "MTI-773" — **encerrada como está** (ajustes finos pausados pelo usuário)
4. Bandeja — **concluído na v1.0** (`ponte/bandeja.py`)
5. Instalador (Inno Setup) e desinstalador — **concluído na v1.0** (`instalador/`)

## Versão 1.0 (2026-10-26)
- **Gerar o instalador:** `powershell -ExecutionPolicy Bypass -File instalador\construir.ps1`
  → `saida\Setup_PonteMTI773_1.0.0.exe` (~20 MB, 100% offline). Precisa de PyInstaller (pip) e
  Inno Setup 6 instalados só no PC de desenvolvimento.
- **O Setup instala:** `C:\Program Files\Ponte MTI-773\MTI773Ponte.exe` (Python + Pillow embutidos),
  início automático (HKLM\...\Run, valor PonteMTI773, todos os usuários), pasta de dados
  `C:\ProgramData\MTI773Ponte` (config.ini, ponte.log, editáveis por usuários comuns) e as
  impressoras via `impressoras.ps1 -Acao criar` (reaproveita se já existirem; log em
  `instalador_criar.log`).
- **O desinstalador remove:** a ponte (fecha o processo), as duas impressoras, as portas
  (MTI773_RAW e a WSD da IPP), o início automático, a pasta do programa e a de dados.
- **Bandeja:** ícone verde/amarelo/vermelho, notificação ao mudar de estado (mensagens em
  `ponte/impressora.py`, incluindo a dos 4 bipes), menu: status, página de teste, calibrar avanço,
  abrir log, abrir config.ini, reiniciar ponte (aplica o config), pausar (solta a USB; fila espera),
  sair. Status consultado a cada 8 s quando parada, na mesma thread que imprime (nunca no meio).
  Uma instância por sessão (mutex). Teste e calibração passam pela fila da ponte em execução.
- **Testado neste PC:** Setup silencioso como admin → ponte aberta, "Impressora pronta",
  impressoras reaproveitadas (0 erros), impressão "TESTE FINAL v1.0" com QR pela fila do Windows.
- Desenvolvimento sem instalar: `pythonw MTI773Ponte.pyw` (bandeja) ou `python -m ponte` (console);
  dados em `dados\`. Não rodar junto com a versão instalada (as portas 9100/631 conflitam).
- Pendências para depois: Bluetooth (`ponte/transporte/bluetooth.py`), assinatura digital do .exe
  (sem ela o SmartScreen pode avisar "editor desconhecido"), sem papel recorrente (rolo/bateria).

## Achados do diagnóstico (2026-10-26)
- USB `28E9:0289`, placa GEZHI PT2D-V1.0, firmware JK-5801P-6102; aberta direto pelo caminho usbprint, sem driver.
- 384 pontos = 32 colunas; linha de 32 caracteres exatos não gera linha extra.
- Acentos: `FS .` (desliga modo chinês) + `ESC t 3` (cp860).
- Status: DLE EOT 1–4 funciona; GS a (ASB) só responde uma vez, não avisa mudanças.
- Sem sensor de tampa: tampa aberta aparece como "sem papel"; volta sozinho a OK.
- Bateria fraca: para no meio e apita. Sem comando de bateria documentado.
- Alarme/travamento: só sai tirando o cabo USB (a USB mantém a placa energizada).
- "Generic / Text Only" manda cp1252 e transforma margens em espaços/linhas em branco.
- Raster GS v 0 em faixas de 24 linhas: largura 384 ok, faixas emendam sem falha. Logo após
  ~3,5 KB de raster, DLE EOT pode demorar > 0,8 s (a ponte repete a consulta esperando mais).
- QR nativo GS ( k (modelo 2) funciona: nítido e centralizado. Leitura pelo celular: a confirmar.
- Avanço final calibrado: linhas_finais = 4 (régua: 08 inteiro, 09 cortado na serrilha).
- 2026-10-26: na régua, espaço grande entre 05/06 e linhas 06–08 apertadas (papel patinou;
  suspeita: rolo prendendo, ou bateria). Observar se repete.
- Fim de cupom longo: 4 bipes = alarme de sem papel; abrir e fechar a tampa resolve.
- Impressora IPP "MTI-773" criada (Add-Printer -IppURL ipp://127.0.0.1:631/ipp/print) com o
  Microsoft IPP Class Driver: Windows vê 58x100/200/297 mm, área de 48 mm a partir de 5 mm, 203 dpi.
  Atributos pedidos pelo Windows que ainda não temos (opcionais): print-scaling-*, number-up-*,
  pages-per-minute, multiple-document-handling-*, mopria-certified, printer-firmware-*, etc.
- "Sem papel" no meio de uma imagem: a ponte para e continua da faixa seguinte quando volta a OK,
  mas a IMPRESSORA reimprime o trecho que tinha na memória e avança um pedaço ao fechar a tampa.
  Limitação do firmware; não há comando documentado e testado para evitar.
- 3 bipes antes do teste 8: o status consultado a cada 30 s não registrou mudança (sempre OK).
  Não correspondem a sem papel/tampa/erro informados pela impressora. Suspeita: aviso de bateria
  ou bipe de ligar/conectar. A confirmar no manual/LED.
- "Sem papel" já ocorreu 4 vezes logo após o início/fim de um bloco de impressão. Verificar
  rolo no fim / mal assentado, ou bateria.
- **4 bipes = a impressora não está detectando o papel (sensor de papel)** — confirmado pelo usuário.
- Páginas invertidas na impressora IPP: o Windows mandava da última para a primeira porque a
  ponte anunciava output-bin "face-up". Trocado para "face-down" (2026-10-26).
- Texto colorido sai claro no pontilhado (cor vira cinza médio): opção [imagem] escurecer.
- A marcação {{QR:...}} só funciona na "MTI-773 Texto": na "MTI-773" (IPP) o Windows manda
  imagem, e a ponte não tem como ler o texto.

## Requisitos da etapa 4 (pedidos pelo usuário)
- Consultar status (DLE EOT) a cada 5–10 s quando parada, sem atrapalhar impressão em andamento
  e sem gastar bateria à toa.
- Ícone na bandeja com cor por estado: verde OK, amarelo aviso, vermelho erro/desconectada.
- Notificação do Windows quando o estado mudar, em português:
  sem papel ou tampa mal fechada; provável bateria fraca; cabeça quente; desconectada;
  travada (tire o cabo USB).
  - Texto definido pelo usuário para sem papel: **"Sem papel detectado (4 bipes): abra e feche a
    tampa com firmeza e confira se o papel está encaixado"**.
- Menu da bandeja: status, página de teste, calibrar, abrir log, abrir config, pausar e sair.
- Iniciar junto com o Windows.
- Histórico no log: cupons impressos, erros, reconexões.

### Notas de projeto para a etapa 4 (implementadas na v1.0)
- O monitoramento já roda na mesma thread que imprime (`Impressora._verificar_ocioso`), só quando a
  fila está vazia — por construção nunca intercala com um envio. Falta: intervalo padrão 10 s
  (hoje 30 s) e expor o estado para a bandeja (callback ao mudar).
- "Cabeça quente": EOT 3 bit 6 (erro auto-recuperável, padrão Epson). Hoje está junto em "erro";
  separar. Não confirmado que esta placa sinaliza — mensagem deve dizer "cabeça quente ou tensão".
- "Bateria fraca" não é medível: inferir por "sem papel" que aparece durante a impressão e some
  sozinho, ou por travamento no meio. Mensagem: "provável".
- "Travada": envio que não termina (timeout de escrita) ou sem resposta ao status com o USB conectado.
- Serviço do Windows roda na sessão 0 e NÃO pode mostrar ícone nem notificação. Recomendação:
  app de bandeja que hospeda a ponte, iniciando no logon. **Adotado.**
- Bandeja via ctypes (Shell_NotifyIconW + balão NIF_INFO), sem dependência extra: evita a questão
  de licença LGPL do pystray no executável.
- Medir se consultar a cada 10 s impede a impressora de entrar em economia/desligar sozinha.
