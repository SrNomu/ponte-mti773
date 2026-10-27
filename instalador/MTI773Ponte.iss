; Instalador da Ponte MTI-773 (Inno Setup 6). Compilado por construir.ps1.
; Tudo é offline: o executável já leva o Python e o Pillow dentro.
;
; Instala:   ponte em "Arquivos de Programas\Ponte MTI-773", início automático
;            (para todos os usuários), pasta de dados em C:\ProgramData\MTI773Ponte
;            e as impressoras "MTI-773 Texto" e "MTI-773".
; Remove:    tudo isso (impressoras, portas, início automático, arquivos e dados).

#define Nome "Ponte MTI-773"
#define Exe "MTI773Ponte.exe"
#ifndef Versao
  #define Versao "1.0.0"
#endif

[Setup]
AppId={{6C1F3E52-7A0B-4C55-9E3D-77300C0FFEE1}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher=Ponte MTI-773
DefaultDirName={autopf}\Ponte MTI-773
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\saida
OutputBaseFilename=Setup_PonteMTI773_{#Versao}
SetupIconFile=ponte.ico
UninstallDisplayIcon={app}\{#Exe}
UninstallDisplayName={#Nome}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
LicenseFile=LICENCAS.txt

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Dirs]
; Usuários comuns precisam poder editar o config.ini e gravar o log
Name: "{commonappdata}\MTI773Ponte"; Permissions: users-modify

[Files]
Source: "..\build\dist\MTI773Ponte\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "impressoras.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENCAS.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{group}\Desinstalar {#Nome}"; Filename: "{uninstallexe}"

[Registry]
; Início automático ao entrar no Windows (todos os usuários)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "PonteMTI773"; ValueData: """{app}\{#Exe}"""; Flags: uninsdeletevalue

[Run]
; 1) Abre a ponte (como o usuário normal, não como administrador)
Filename: "{app}\{#Exe}"; Flags: nowait runasoriginaluser; StatusMsg: "Abrindo a ponte..."
; 2) Cria as impressoras (o script espera a ponte abrir a porta 631)
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\impressoras.ps1"" -Acao criar"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Criando as impressoras MTI-773 Texto e MTI-773..."

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#Exe}"; Flags: runhidden waituntilterminated; RunOnceId: "FecharPonte"
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\impressoras.ps1"" -Acao remover"; \
  Flags: runhidden waituntilterminated; RunOnceId: "RemoverImpressoras"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\MTI773Ponte"
Type: filesandordirs; Name: "{app}"

[Code]
// Fecha a ponte antes de instalar por cima (atualização), senão os arquivos estão em uso
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#Exe}', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Sleep(1000);
  Result := '';
end;

// Avisa se alguma impressora não pôde ser criada (o detalhe fica no log)
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssDone) and not WizardSilent then
    MsgBox('Pronto! A ponte está aberta (ícone perto do relógio) e as impressoras ' +
           '"MTI-773 Texto" e "MTI-773" foram criadas.' + #13#10#13#10 +
           'Se alguma impressora não aparecer, veja o arquivo ' +
           ExpandConstant('{commonappdata}') + '\MTI773Ponte\instalador_criar.log',
           mbInformation, MB_OK);
end;
