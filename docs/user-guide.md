# Manual do usuário — LadderIDE

## 1. Instalação

**Executável:** copie a pasta `dist\LadderIDE` (gerada por
`python scripts/build_windows.py`) e execute `LadderIDE.exe`.

**A partir do código:**

```powershell
python -m pip install -e "desktop[gui,comm,dev]"
python -m ladderide                      # abre a IDE
python -m ladderide examples\demo\demonstracao.ladproj
```

O dispositivo virtual e os testes de equivalência precisam de `gcc` no PATH
(MinGW). O executável já traz o dispositivo virtual compilado.

## 2. Tela

- **Instruções** (esquerda): arraste para o diagrama ou clique para inserir
  depois do elemento selecionado.
- **Diagrama** (centro): redes numeradas entre os trilhos.
- **Simulador / Dispositivo** (direita, abas).
- **Mensagens / Variáveis** (embaixo).

## 3. Editando

| Ação | Como |
|---|---|
| Inserir | Arrastar da paleta até a área destacada em azul (entre contatos, num ramo, na coluna de saídas ou abaixo da última rede para criar outra) |
| Mover | Arrastar o elemento para outro ponto |
| Editar operando/preset/tipo | Duplo clique ou Enter |
| Ramo paralelo (OU) | Arrastar "Paralelo" entre contatos, ou botão direito → Envolver em ramo paralelo / Adicionar ramo |
| Excluir | Delete (elemento ou rede selecionada pelo número) |
| Redes | Botão direito no número: inserir acima/abaixo, comentário, excluir; Ctrl+R nova rede |
| Desfazer/Refazer | Ctrl+Z / Ctrl+Y |
| Zoom | Ctrl+roda do mouse, Ctrl++ / Ctrl+-, Ctrl+0 |

Operandos: endereços (`I0.0`–`I1.7`, `Q0.0`–`Q1.7`, `M0.0`–`M31.7`, `T0`, `C0`,
`T0.DN`, `C0.DN`, `S0.0` primeira varredura, `S0.3` relógio 1 s) ou nomes da aba
**Variáveis** (ex.: `Partida` → `I0.0`; `Atraso.DN` se `Atraso` → `T0`).

Equivalências: XIC = contato NA, XIO = contato NF, OTL = SET, OTU = RESET.
Cada temporizador/contador é acionado por **uma** instrução TON/TOF/RTO/CTU/CTD;
`RES` pode aparecer várias vezes. Semântica completa:
`docs/ladder-specification.md` (F1 mostra um resumo).

## 4. Compilar (F7)

Erros e avisos aparecem em **Mensagens** com a rede; clique para selecionar o
elemento (destacado em vermelho). Programas com erro não são simulados nem
transferidos. Arquivo → Exportar gera a listagem LIL (texto) ou a imagem LDRB.

## 5. Simular

| Tecla | Ação |
|---|---|
| F5 | Executar continuamente (velocidade 0,1× a 10×) |
| F6 | Pausar |
| F10 | Uma varredura |
| F11 | Uma instrução (destaque laranja na instrução atual) |
| Ctrl+F5 | Reiniciar (partida a frio) |
| Shift+F5 | Parar e voltar à edição |

Verde = energizado. Contatos com preenchimento verde estão "fechados" pelo
valor do operando. Caixas mostram PRE, ACC e bits. Entradas: botões de
retenção ou, marcando "Botões pulsadores", momentâneos. O tempo é virtual
(cada varredura avança o período configurado em Propriedades do projeto).

## 6. Dispositivo

1. Aba **Dispositivo** → Meio: Serial (escolha a COM) ou Dispositivo virtual → **Conectar**.
2. **Transferir programa** (F8): compila, confirma se o CLP estiver em RUN,
   envia em blocos com CRC, o firmware valida e só então substitui o programa.
   Falhas preservam o programa anterior.
3. **RUN / STOP / Limpar falha**.
4. **Monitor online**: lê o dispositivo a cada 200 ms. O diagrama só é animado
   se o programa no dispositivo for igual ao projeto aberto (mesmo build_id).
   "Lógico" = resultado do programa; "Comandado" = enviado aos relés. A placa
   não mede o estado físico dos contatos.

Em caso de perda de comunicação, a IDE mostra o aviso e tenta reconectar a
cada 2 s. O CLP continua executando sem a IDE.

## 7. Linha de comando

```powershell
python -m ladderide.cli ports
python -m ladderide.cli --port COM5 info
python -m ladderide.cli --port COM5 download examples\demo\demonstracao.ladproj --stop
python -m ladderide.cli --port COM5 run
python -m ladderide.cli --port COM5 monitor --count 20
python -m ladderide.cli --port COM5 equivalence
python -m ladderide.cli --virtual status          # dispositivo virtual
```

## 8. Segurança

Este equipamento não é um CLP de segurança. Defina o estado seguro das saídas
(Propriedades do projeto) conforme a carga; desenergizar nem sempre é seguro.
Use cargas de baixa tensão nas aulas.
