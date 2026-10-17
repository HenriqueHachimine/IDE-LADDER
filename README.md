# CLP LADDER com ESP32

IDE LADDER para Windows (editor gráfico, compilador, simulador, transferência e
monitor online) e firmware interpretador para uma placa ESP32 com 8 relés.
Trabalho final da disciplina de Controladores Lógicos Programáveis.

> **Situação (v0.9.0, 2026-10-16):** software completo e testado no PC
> (207 testes, incluindo o firmware executado como "dispositivo virtual").
> O firmware compila para o ESP32, mas **ainda não foi testado na placa** —
> ver [roteiro de hardware](docs/hardware-test-procedure.md).

## Funcionalidades

- **Editor gráfico** com arrastar e soltar, ramos paralelos, símbolos,
  desfazer/refazer, zoom, numeração e comentários de redes
- **Instruções:** contato NA (XIC), NF (XIO), NOT, bobina, SET (OTL), RESET
  (OTU), TON, TOF, RTO, CTU, CTD, RES
- **Compilador** com erros e avisos por rede e elemento; nunca gera programa inválido
- **Simulador** contínuo (0,1× a 10×), por varredura e passo a passo, com
  fluxo de energia, entradas virtuais, temporizadores e contadores ao vivo
- **Transferência** USB transacional (CRC, validação no firmware, gravação
  atômica; falhas preservam o programa anterior)
- **Monitor online** com o diagrama animado pelo estado do ESP32, lógico ×
  comandado, detecção de perda de comunicação e reconexão
- **Firmware** com STOP/RUN/PROGRAM_LOADING/FAULT, varredura de 10 ms,
  watchdog, estado seguro configurável e Modbus RTU somente leitura
- **Dispositivo virtual**: o firmware rodando no PC, para aulas e testes sem placa
- **Ambientes de simulação** animados (silo de envase, semáforo, portão de garagem)
  controlados pelo programa, com alarmes de erros de lógica; novos ambientes são
  plugins independentes ([guia](docs/simulation-environments.md))
- **Verificar para ESP32** (F9): executa o programa no código C do firmware,
  compara com o simulador varredura a varredura e confere memória, E/S e limites da placa
- **Blocos de instrução** (F12): o diagrama convertido em lista de instruções por
  rede, ligada ao diagrama e animada na simulação
- **Código C++** (Ctrl+F7): o diagrama traduzido para C++ legível enquanto se
  edita, antes de compilar; um teste compila o C++ e confere que ele reproduz o simulador
- **Equivalência garantida por testes**: simulador e firmware executam o mesmo
  bytecode e são comparados varredura a varredura

## Arquitetura

```
desktop/   IDE (Python + PySide6): core, model, compiler, sim, comm, ui, cli
firmware/  ESP32 (PlatformIO): lib/ladder_vm, lib/plc_core (C99 portátil), src/ (HAL ESP32)
shared/    isa.json, protocol.json (fontes únicas) e vetores de teste
examples/  demonstração, portas lógicas, temporizadores, contadores, testes de hardware
docs/      especificações, arquitetura, ADRs, manual, testes, relatório
scripts/   geração de headers, exemplos, executável Windows
```

Detalhes: [arquitetura](docs/architecture.md) · [especificação LADDER](docs/ladder-specification.md) ·
[formato LDRB](docs/intermediate-format.md) · [protocolo](docs/communication-protocol.md) ·
[formato de projeto](docs/project-format.md) · [decisões](docs/decisions/)

## Requisitos

- **Windows 10/11** ou **Linux** (testado em Debian 12 e Ubuntu 24.04), Python ≥ 3.11
- `gcc` no PATH para o dispositivo virtual, a verificação para ESP32 e os testes
  em C (Windows: MinGW; Linux: `sudo apt install build-essential`)
- Firmware: PlatformIO; placa ESP32 8 relés ([hardware](docs/hardware-setup.md))

## Instalação e execução

**Windows** (PowerShell):

```powershell
python -m pip install -e "desktop[gui,comm,dev]"
python -m ladderide                                   # abre a IDE
python -m ladderide examples\demo\demonstracao.ladproj
```

**Linux** (bash):

```bash
sudo apt install python3-venv build-essential libxcb-cursor0   # Debian/Ubuntu
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e "desktop[gui,comm,dev]"
python -m ladderide examples/demo/demonstracao.ladproj
sudo usermod -aG dialout $USER     # acesso a /dev/ttyUSB0 do ESP32 (saia e entre na sessao)
```

**Executável** (gerado no próprio sistema de destino):
`python -m pip install pyinstaller` e `python scripts/build_app.py`.
- Windows: `dist\LadderIDE\LadderIDE.exe`.
- Linux: `dist/LadderIDE/LadderIDE` e o pacote `dist/LadderIDE-linux-x86_64.tar.gz`.
  Para colocar no menu de aplicativos, rode `./install.sh` dentro do pacote.

Os dois incluem exemplos, a VM C e o dispositivo virtual.

Manual: [docs/user-guide.md](docs/user-guide.md).

## Firmware e primeira transferência

```powershell
python -m pip install platformio
cd firmware; pio run -t upload --upload-port COM5; cd ..     # Linux: --upload-port /dev/ttyUSB0
python -m ladderide.cli --port COM5 info
python -m ladderide.cli --port COM5 download examples\demo\demonstracao.ladproj
python -m ladderide.cli --port COM5 run
```

Ou pela IDE: aba **Dispositivo** → Serial → Conectar → **Transferir** (F8) → RUN.
Sem placa, escolha "Dispositivo virtual".

## Exemplos

| Exemplo | Conteúdo |
|---|---|
| `examples/demo` | Roteiro da demonstração: selo, TON, TOF, CTU, RES, relógio ([roteiro](docs/demo-script.md)) |
| `examples/combinational` | AND, OR, NOT, XOR, NAND, SET/RESET |
| `examples/timers` | TON, TOF, RTO, oscilador |
| `examples/counters` | CTU, CTD, RES |
| `examples/hardware` | Teste de relés em sequência, espelho de entradas |
| `examples/ambientes` | Soluções para os ambientes de simulação: silo, semáforo, portão |

## Testes

```powershell
cd desktop; python -m pytest -q
```

Estratégia e resultados: [docs/testing.md](docs/testing.md).

## Contribuir

[CONTRIBUTING.md](CONTRIBUTING.md) e [guia de desenvolvimento](docs/development-guide.md).

## Limitações conhecidas

- Não testado na placa real (pendências em [hardware-setup](docs/hardware-setup.md)).
- Sem memória retentiva entre partidas; sem forçamento de E/S; sem edição em RUN.
- Wi-Fi/TCP só no lado do Desktop.
- A placa não mede o estado físico dos relés.
- Não é um CLP de segurança: não use para proteção de pessoas.

## Créditos e referências

- Mapeamento da placa: [multigcs/esp32_relay_x8_modbus_303e32dc812](https://github.com/multigcs/esp32_relay_x8_modbus_303e32dc812) (MIT, © 2026 Oliver Dippel).
- Projeto anterior usado como referência de interface: [Pedrofrac/Trabalho-Final-CLP](https://github.com/Pedrofrac/Trabalho-Final-CLP).
- Nomenclatura de instruções inspirada na família Allen-Bradley; semântica própria e documentada.
- Bibliotecas: PySide6 (LGPL), pyserial (BSD), Arduino-ESP32 (LGPL), LittleFS (BSD).

Licença: [MIT](LICENSE). Relatório: [docs/report/relatorio.md](docs/report/relatorio.md).
