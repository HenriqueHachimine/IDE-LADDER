# Roteiro da demonstração final

Mapeia os 17 passos exigidos para ações na IDE. Projeto de referência:
`examples/demo/demonstracao.ladproj` (pode ser recriado ao vivo).
Ensaie antes com o **dispositivo virtual** (painel Dispositivo → Meio
"Dispositivo virtual"), que executa o mesmo código do firmware.

| # | Passo exigido | Ação | Resultado esperado |
|---|---|---|---|
| 1 | Abrir a IDE | `python -m ladderide` ou `dist\LadderIDE\LadderIDE.exe` | Janela com paleta, diagrama, simulador |
| 2 | Criar projeto | Arquivo → Novo; Editar → Propriedades (nome, 8 E/S) | Projeto vazio com uma rede |
| 3 | Lógica combinacional NA/NF/bobina | Arrastar NA (Partida), Paralelo, NA (Motor) no ramo, NF (Parada), Bobina (Motor) | Rede 0 = selo de partida/parada |
| 4 | TON e TOF | Rede com NA Motor → TON 2000 ms; rede com NA Motor → TOF 3000 ms; bobinas com `.DN` | Caixas TON/TOF com PRE |
| 5 | Contagem | NA Motor + NA Sensor → CTU 5; NA Pecas.DN → bobina; NA Zera → RES Pecas | Caixa CTU e RES |
| 6 | Variáveis e E/S | Aba "Variáveis": Partida I0.0, Parada I0.1, Sensor_Peca I0.2, Zera_Contagem I0.3, Motor Q0.0... | Nomes aparecem no diagrama |
| 7 | Compilar e validar | F7 | "Compilação concluída", sem erros; mostrar um erro proposital (operando inexistente) destacado em vermelho e corrigi-lo |
| 8 | Simulador | F5 | Trilho verde, painel de entradas ativo |
| 9 | Entradas virtuais | Clicar I0.0 (Partida) e soltar | Motor liga e se mantém; após 2 s, Em_Regime; contagem com I0.2; Parada → ventilador continua 3 s. Mostrar F11 (passo) destacando a instrução |
| 10 | Conectar ao ESP32 | Shift+F5 (parar simulação); painel Dispositivo → Serial, COMx → Conectar | "Conectado", firmware e hardware identificados |
| 11 | Transferir e validar | F8 | Barra de progresso; mensagem com build_id e CRC; "Igual ao projeto aberto" |
| 12 | RUN | Botão RUN | Estado RUN (verde) |
| 13 | Entradas físicas | Acionar os botões ligados em I0.0–I0.3 | Relés respondem como no simulador |
| 14 | Oito relés | Transferir `examples/hardware/teste_reles.ladproj` (ou mostrar H2) | Relés 1→8 em sequência |
| 15 | Monitor online | Marcar "Monitor online" | Diagrama anima com a energia vinda do ESP32; colunas Lógico × Comandado |
| 16 | STOP | Botão STOP | Relés no estado seguro; estado STOP (laranja) |
| 17 | Falha de comunicação/validação | (a) desconectar o USB com monitor ligado → "Comunicação perdida… reconectando" e reconexão automática; ou (b) `cli download` interrompido → programa anterior preservado; ou (c) tentar transferir com erro de compilação → bloqueado | Tratamento visível e documentado |

Evidências a registrar (relatório, apêndice): vídeo da tela + placa,
`cli status` antes/depois, logs do `cli monitor`, saída do `cli equivalence`.
