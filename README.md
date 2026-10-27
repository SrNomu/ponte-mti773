# Ponte MTI-773

Programa gratuito para Windows que faz a **mini impressora térmica MTI-773** (58 mm, USB)
imprimir a partir de **qualquer programa**: Bloco de Notas, Word, navegador, PDF, sistemas de
venda etc. Também funciona com **outras impressoras de 58 mm com comandos ESC/POS**.

Ela cria duas impressoras no Windows e fica rodando em segundo plano, com um ícone perto do
relógio que mostra se a impressora está pronta, sem papel ou desconectada.

> **Projeto independente.** Não tem nenhuma ligação com a marca Tomate, com o fabricante da
> impressora nem com seus revendedores. Os nomes são citados só para identificar o modelo
> compatível. Use por sua conta e risco (veja a [licença](LICENSE)).

## Impressoras compatíveis

| Impressora | Situação |
|---|---|
| Tomate MTI-773 (USB `28E9:0289`) | Testada |
| Outras 58 mm ESC/POS pela USB (padrão "usbprint" do Windows) | Devem funcionar: ajuste `usb_vid` e `usb_pid` no `config.ini` |
| Bluetooth | Ainda não suportado (planejado) |

## Instalação

1. Baixe o `Setup_PonteMTI773_1.0.0.exe` na página de
   [**Releases**](../../releases/latest).
2. Ligue a impressora e conecte o cabo USB.
3. Execute o Setup (ele pede permissão de administrador para criar as impressoras).

Não é preciso instalar Python nem nenhum outro programa: está tudo dentro do instalador, que
funciona sem internet.

Como o executável não tem assinatura digital, o Windows pode mostrar "O Windows protegeu o
computador". Nesse caso, clique em **Mais informações → Executar assim mesmo**.

O instalador:

- instala a ponte em `C:\Program Files\Ponte MTI-773`;
- faz a ponte abrir junto com o Windows;
- cria as impressoras **"MTI-773 Texto"** e **"MTI-773"**.

Para remover, use **Configurações → Aplicativos → Ponte MTI-773 → Desinstalar**. O
desinstalador remove tudo: o programa, as duas impressoras, as portas, o início automático e as
configurações.

## Como usar

### Impressora "MTI-773 Texto" (cupons e textos)

É a melhor para cupons: o texto sai nítido, rápido e economiza bateria.

- Quebra as linhas automaticamente em **32 colunas**, sem cortar palavras.
- Os acentos saem corretos (á, ç, ã, õ, ê...).
- **QR Code:** escreva `{{QR:o texto ou link}}` em qualquer lugar do texto e ele sai como
  um QR Code centralizado. Exemplo:

  ```
  Obrigado pela compra!
  {{QR:https://meusite.com.br}}
  Volte sempre.
  ```

- Programas que mandam comandos ESC/POS prontos também funcionam por ela.

### Impressora "MTI-773" (imagens, PDF, páginas com formatação)

Use esta para imprimir logotipos, imagens, PDFs e páginas do navegador. O Windows desenha a
página, e a ponte a converte em pontos pretos e brancos e corta a parte em branco do final.

- Escolha o tamanho de papel **58 x 100**, **58 x 200** ou **58 x 297 mm**.
- A área útil tem **48 mm** de largura, com 5 mm de margem de cada lado.
- Texto colorido ou cinza sai escurecido para continuar legível.
- A marcação `{{QR:...}}` não funciona aqui, porque o Windows envia uma imagem e não o texto.

### Ícone na bandeja

| Cor | Significado |
|---|---|
| 🟢 Verde | Impressora pronta |
| 🟡 Amarelo | Aviso: sem papel, pausada, papel acabando |
| 🔴 Vermelho | Erro, desconectada ou travada |

Quando o estado muda, aparece uma notificação do Windows explicando o que fazer. Clique no
ícone para abrir o menu: **status**, **imprimir página de teste**, **calibrar avanço**,
**abrir log**, **abrir config.ini**, **reiniciar ponte**, **pausar** e **sair**.

## Calibração do avanço do papel

Depois de imprimir, a ponte avança o papel para que a última linha passe da serrilha. Para
acertar a medida na sua impressora:

1. No menu do ícone, clique em **Calibrar avanço do papel**. Sai uma régua numerada de 01 a 12.
2. Rasgue na serrilha **sem** apertar o botão de avanço.
3. Veja o último número que saiu **inteiro** no pedaço rasgado.
4. Abra o `config.ini` pelo menu e defina `linhas_finais = 12 - esse número`.
   Por exemplo, se o último número inteiro foi 08, use `linhas_finais = 4` (o padrão).
5. Salve e clique em **Reiniciar ponte**.

## Configuração

O arquivo fica em `C:\ProgramData\MTI773Ponte\config.ini` e é comentado em português. Os
ajustes mais usados são:

| Seção | Opção | Para quê |
|---|---|---|
| `[impressora]` | `usb_vid`, `usb_pid` | Usar outra impressora USB ESC/POS |
| `[papel]` | `colunas`, `linhas_finais` | Largura do texto e avanço final |
| `[imagem]` | `escurecer`, `modo` | Deixar imagens mais escuras ou usar preto e branco puro |
| `[log]` | `nivel`, `salvar_trabalhos` | Diagnóstico |

O log fica em `C:\ProgramData\MTI773Ponte\ponte.log`.

## Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| **4 bipes**, nada imprime, ícone amarelo "Sem papel detectado" | O sensor não está detectando o papel. Abra e feche a tampa com firmeza e confira se o papel está encaixado. |
| Para no meio e apita, ou fica "travada" | Normalmente é bateria fraca. Carregue a impressora. Se não voltar: desligue, **tire o cabo USB** (a USB mantém a placa ligada), espere 5 s e reconecte. |
| Ícone vermelho "desconectada" | Confira o cabo e se a impressora está ligada. A ponte reconecta sozinha. |
| Depois de faltar papel, um trecho sai repetido | É uma limitação da própria impressora: ela reimprime o que estava na memória. Reimprima o cupom se precisar. |
| A última linha fica antes da serrilha | Faça a calibração do avanço (veja acima). |
| Acentos errados | Use a impressora "MTI-773 Texto". Se o seu programa envia ESC/POS próprio, ele precisa usar a página de código 860. |
| "A ponte não conseguiu iniciar: porta em uso" | Já existe outra cópia da ponte aberta, ou outro programa está usando a porta 9100 ou 631. |
| Não imprime nada e a fila do Windows fica parada | Confira se o ícone da ponte está perto do relógio. Se não estiver, abra **Ponte MTI-773** pelo menu Iniciar. |

## Como funciona

```
Programa ──► "MTI-773 Texto" (Generic / Text Only) ──► TCP 127.0.0.1:9100 ─┐
Programa ──► "MTI-773" (driver IPP do Windows)     ──► IPP 127.0.0.1:631  ─┼─► Ponte ──► USB ──► impressora
                                                                           ┘   (fila única, status,
                                                                               reconexão automática)
```

- A ponte fala com a impressora direto pela USB (interface usbprint do Windows), sem driver
  do fabricante.
- Uma única fila evita que dois trabalhos se misturem. O status (papel, erro) é consultado entre
  os blocos de impressão e, a cada 8 s, quando a impressora está parada.
- Se um trabalho falhar no meio, ele **não** é reenviado automaticamente, para não imprimir em
  dobro.
- A ponte só escuta conexões do próprio computador (127.0.0.1) e não acessa a internet.

## Como compilar

Requisitos (só no computador de desenvolvimento):

- Windows 10 ou 11, 64 bits
- [Python 3.11+](https://www.python.org/) com `pip install pillow pyinstaller`
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)

Rodar sem instalar (os dados ficam na pasta `dados\` do projeto):

```powershell
pythonw MTI773Ponte.pyw          # com o ícone na bandeja
python -m ponte                  # no console (Ctrl+C para sair)
python -m ponte --teste          # imprime uma página de teste e sai
python -m ponte --imprimir exemplos\qr_code.txt
python -m ponte --calibrar
```

Gerar o instalador:

```powershell
powershell -ExecutionPolicy Bypass -File instalador\construir.ps1
# resultado: saida\Setup_PonteMTI773_<versão>.exe
```

Não rode a versão de desenvolvimento junto com a instalada, porque as duas disputam as portas
9100 e 631 e a conexão USB. Feche a instalada antes (menu do ícone → Sair).

### Estrutura

| Pasta | Conteúdo |
|---|---|
| `ponte/` | Código da ponte: fila e status (`impressora.py`), texto (`conversor.py`), imagens (`imagem.py`, `pwg.py`), servidores RAW e IPP, bandeja (`bandeja.py`) |
| `ponte/transporte/` | Conexão USB (Windows) e esqueleto do Bluetooth |
| `ferramentas/` | Scripts de diagnóstico e teste usados no desenvolvimento |
| `instalador/` | Script do Inno Setup, criação/remoção das impressoras e build |
| `exemplos/` | Textos de exemplo para imprimir |
| `PLANO.md` | Diário de desenvolvimento e achados sobre o hardware |

## Licença

[MIT](LICENSE) © 2026 Pedro. Componentes incluídos no instalador (Python, Pillow,
PyInstaller, Inno Setup) estão listados em [instalador/LICENCAS.txt](instalador/LICENCAS.txt).
