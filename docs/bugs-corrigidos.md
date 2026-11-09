# Bugs encontrados e corrigidos

Registro da auditoria do sistema por área: qual era o problema, a causa, como foi
resolvido e como a correção foi verificada. Situação da verificação:

- **Testado**: o bug foi reproduzido e um teste automatizado cobre a correção.
- **Compilado**: depende do hardware; a correção compila, mas ainda não foi ensaiada na placa.

## Firmware

### F1. Bloco de transferência com posição inválida era aceito

- **Problema:** um `LOAD_CHUNK` com posição perto do limite de 32 bits (por exemplo
  `0xFFFFFFF0` com 16 bytes) recebia resposta de sucesso em vez de `BAD_OFFSET`. Não havia
  corrupção de memória, porque a cópia só ocorre quando a posição é a esperada.
- **Causa:** a conta `offset + n` estourava 32 bits e o resultado passava pela comparação com o
  tamanho do programa ([plc_runtime.c](../firmware/lib/plc_core/plc_runtime.c), `cmd_load_chunk`).
- **Solução:** a verificação passou a ser `offset > load_size || n > load_size - offset`, que não soma.
- **Verificação (Testado):** `test_chunk_offset_near_32_bit_limit_is_refused`, em `desktop/tests/test_comm.py`,
  falha com o código antigo e passa com o novo.

### F2. Programa incompleto podia substituir o programa válido na flash

- **Problema:** se a gravação falhasse ao fechar o arquivo (erro de flash ou falta de espaço), o
  `/prog.new` incompleto substituía o `/prog.bin` e o `COMMIT` respondia sucesso. Na partida
  seguinte, o CLP entrava em FAULT e o programa anterior estava perdido.
- **Causa:** o LittleFS grava de fato ao fechar o arquivo, mas `File::close()` não informa erro.
- **Solução:** antes de renomear, `storage_save` relê o arquivo e compara tamanho e conteúdo com o
  programa recebido; se diferir, apaga o temporário e retorna erro, preservando o programa anterior
  ([storage.cpp](../firmware/src/storage.cpp)).
- **Verificação (Compilado):** `pio run` sem erros; a falha de flash não é reproduzível no PC.

### F3. Respostas longas atrasavam a varredura

- **Problema:** com o monitor online em RUN, respostas acima de 128 bytes atrasavam a varredura de
  10 ms: cerca de 10 ms para 243 bytes e até 66 ms para 894 bytes.
- **Causa:** a serial usava só a FIFO de 128 bytes do ESP32, então `Serial.write` bloqueava enquanto
  a tarefa de comunicação segurava o mutex de que a varredura depende.
- **Solução:** buffer de transmissão de 2048 bytes, maior que a maior resposta do protocolo, de modo
  que a escrita não bloqueia ([main.cpp](../firmware/src/main.cpp)).
- **Verificação (Compilado):** `pio run` sem erros; confirmar no ensaio H13 do
  [roteiro de hardware](hardware-test-procedure.md) (intervalo máximo de varredura).

## Documentação

### D1. Valores divergentes do código

- **Problema:** `docs/intermediate-format.md` dizia que imagens com menos de 32 bytes são curtas demais, e
  `docs/communication-protocol.md` limitava o programa a 8 740 bytes.
- **Causa:** os textos não acompanharam o formato LDRB 2.0, com cabeçalho de 36 bytes e tamanho
  máximo de 9 256 bytes.
- **Solução:** valores atualizados para 36 e 9 256 bytes.

### D2. Mensagens apontavam para um menu que não existe

- **Problema:** a IDE e os manuais mandavam ajustar em "Programa > Propriedades".
- **Causa:** o item fica no menu Editar.
- **Solução:** textos corrigidos para "Editar > Propriedades do projeto".

## Código C++ gerado e núcleo

### C1. C++ não compilava na placa com certos nomes

- **Problema:** um temporizador sem símbolo (`T0` a `T9`) não compilava no ESP32. Símbolos válidos na IDE, como
  `PB0`, `A0`, `SDA`, `init`, `map`, `time`, `y1` ou `int16_t`, também quebravam a compilação em alguma placa. A
  verificação aprovava o projeto e o erro só aparecia ao compilar.
- **Causa:** esses nomes já existem nas placas (`T0` a `T9` são os pinos de toque do ESP32; os demais são macros,
  registradores e funções do Arduino ou da biblioteca C), e a lista de nomes reservados era curta.
- **Solução:** todo nome em maiúsculas ganha `_` no fim, menos os endereços do CLP (`Q0_0`), porque macros e
  registradores são maiúsculos e variam por placa. Nomes `*_t` e os globais conhecidos em minúsculas também são
  renomeados ([cpp.py](../desktop/src/ladderide/codegen/cpp.py), `_collides`).
- **Verificação (Testado):** `test_c1_*`, em `desktop/tests/test_regressions.py`.

### C2. Comentários podiam quebrar o arquivo C++

- **Problema:** um comentário terminado em `\` emendava a linha seguinte, e uma quebra de linha em comentário de rede
  ou nome de projeto virava código.
- **Causa:** o texto do usuário ia direto para comentários `//`.
- **Solução:** `_comment_text` troca quebras de linha por espaço e `\` por `/`.
- **Verificação (Testado):** `test_c2_comments_cannot_break_the_generated_file` compila o resultado com g++.

### C3. Projeto sem entradas e saídas derrubava o painel C++

- **Problema:** um `.ladproj` com 0 entradas e 0 saídas fazia `generate_cpp` lançar `ValueError`.
- **Causa:** `max()` sobre uma lista vazia.
- **Solução:** `max(..., default=1)`; o arquivo sai com o diagnóstico de E/S.
- **Verificação (Testado):** `test_c3_generate_with_no_io_does_not_raise`.

### C4. Ramo paralelo vazio divergia do simulador

- **Problema:** `Parallel([])` conduzia no simulador e não conduzia no C++. Só ocorre com arquivo editado à mão.
- **Causa:** a lista vazia era tratada como condição falsa.
- **Solução:** sem ramos, o valor de entrada segue, como na máquina virtual.
- **Verificação (Testado):** `test_c4_empty_parallel_conducts_like_the_vm`.

### C5. `IW0`/`QW0` com 32 pontos davam resultado errado no simulador

- **Problema:** com o bit 31 ligado, o simulador tratava a palavra como positiva e o C++ como negativa. `GRT IW0,0`
  ligava a saída só no simulador.
- **Causa:** a máquina virtual em Python devolvia 2^31, fora do inteiro de 32 bits definido pela ISA.
- **Solução:** `read_word` converte `IW` e `QW` para int32 ([vm.py](../desktop/src/ladderide/core/vm.py)).
- **Verificação (Testado):** `test_c5_input_word_with_bit_31_is_a_negative_int32`; as 4 divergências da comparação
  aleatória entre C++ e simulador desapareceram.

### C6. Símbolo como `_5` era lido como a constante 5

- **Problema:** um símbolo chamado `_5` era tratado como o número 5 nos blocos de comparação e matemática.
- **Causa:** `parse_constant` removia todos os `_` antes de testar se era número.
- **Solução:** `_` só é aceito depois do primeiro dígito ([asm.py](../desktop/src/ladderide/core/asm.py)).
- **Verificação (Testado):** `test_c6_underscore_name_is_not_a_constant`.

### C7. Verificação dizia "todas passaram" com itens não verificados

- **Problema:** sem placa conectada, o resumo afirmava que todas as verificações tinham passado.
- **Causa:** `summary` só olhava erros e avisos.
- **Solução:** o resumo informa quantos itens não foram verificados.
- **Verificação (Testado):** `test_c7_summary_mentions_items_not_verified`.

## Gravação nas placas

### U1. Gravava na porta errada quando a porta era digitada

- **Problema:** com COM3 e COM4 na lista, digitar `COM9` gravava em COM3, tanto em "Gravar firmware" quanto em "Gravar
  C++". O botão Atualizar também apagava o texto digitado. No painel de CLP real, `COM10` era confundida com `COM1`.
- **Causa:** o código dava prioridade ao item da lista (`currentData`), que continua selecionado quando se digita.
- **Solução:** a porta é sempre o texto da caixa, e Atualizar preserva o que foi digitado
  ([flash_dialog.py](../desktop/src/ladderide/ui/flash_dialog.py), [cpp_upload_dialog.py](../desktop/src/ladderide/ui/cpp_upload_dialog.py),
  [plc_panel.py](../desktop/src/ladderide/ui/plc_panel.py)).
- **Verificação (Testado):** `test_u1_typed_port_wins_over_the_list`, no diálogo de gravar C++; os outros dois usam a
  mesma lógica.

## Simulador e ambientes

### S1. Clique em pulsador se perdia em velocidade baixa

- **Problema:** a 0,01× a maioria dos cliques não chegava ao programa (53 de 58 no teste).
- **Causa:** se pressionar e soltar coubessem entre duas varreduras, a varredura só via o botão solto.
- **Solução:** o clique fica guardado (`Environment.clicked`) até uma varredura lê-lo; o desenho continua mostrando
  o estado real do botão ([base.py](../desktop/src/ladderide/envs/base.py)).
- **Verificação (Testado):** `test_s1_click_shorter_than_a_scan_is_seen`.

### S2. Partida a frio desligava as chaves com trava

- **Problema:** ao dar RUN ou Reiniciar, as chaves do ambiente voltavam a desligadas, embora a simulação prometa manter
  as entradas.
- **Causa:** o reinício apagava todo o estado do operador.
- **Solução:** só os pulsadores são liberados; as chaves mantêm a posição.
- **Verificação (Testado):** `test_s2_cold_start_keeps_latching_switches`.

### S3. Alarme falso de chamada no elevador

- **Problema:** apertar o andar com a porta já aberta nele gerava, 60 s depois, o alarme de chamada esperando.
- **Causa:** a chamada ficava pendente e só era baixada na abertura seguinte da porta.
- **Solução:** a chamada no andar com a porta aberta não fica pendente.
- **Verificação (Testado):** `test_s3_elevator_call_at_open_door_is_not_pending`.

### S4. Controles extras de plugins eram ignorados

- **Problema:** `on_control` não era chamado para controles que não são entradas, ao contrário da documentação.
- **Causa:** `press` retornava antes quando o ponto não existia.
- **Solução:** `press` chama `on_control` nesse caso.
- **Verificação (Testado):** `test_s4_on_control_receives_controls_that_are_not_inputs`.

### S5. Plugin com `@dataclass` não carregava

- **Problema:** um plugin escrito como os ambientes internos falhava com `AttributeError`.
- **Causa:** o módulo do plugin não estava em `sys.modules` durante o carregamento.
- **Solução:** o módulo é registrado antes de executar e removido em caso de erro.
- **Verificação (Testado):** `test_s5_plugin_with_dataclass_loads`.

### S6. Plugin com defeito impedia o painel de abrir

- **Problema:** um plugin cujo `reset()` falhasse derrubava o painel de ambientes e, com ele, a abertura da IDE. Esse
  defeito veio do filtro de ambientes por controlador.
- **Causa:** o painel criava os ambientes sem proteção.
- **Solução:** cada ambiente é testado ao montar a lista; o que falha fica de fora e aparece nos erros do painel.
- **Verificação (Testado):** `test_s6_broken_plugin_is_listed_and_does_not_break_the_panel`.

### S7. Endereço inválido derrubava a ponte do Factory IO

- **Problema:** um host como `fabrica..local` matava a ponte em silêncio, e o botão Testar não respondia.
- **Causa:** a conexão só tratava `OSError`, e nome inválido gera `UnicodeError`.
- **Solução:** o erro vira `ModbusError` com a mensagem de conexão ([modbus_tcp.py](../desktop/src/ladderide/comm/modbus_tcp.py)).
- **Verificação (Testado):** `test_s7_invalid_host_is_a_modbus_error`.

### S8. Resposta malformada do CP1E encerrava a ligação com o CLP real

- **Problema:** dados inválidos com FCS correto matavam a thread, e a tela ficava em "conectando".
- **Causa:** `int(..., 16)` gerava `ValueError`, que a ponte não tratava.
- **Solução:** `_hex` transforma o erro em `PlcError`, e a ponte registra e tenta de novo.
- **Verificação (Testado):** `test_s8_malformed_plc_answer_is_a_plc_error`.

### S9. Reiniciar uma ponte lenta deixava duas threads

- **Problema:** depois de `stop()` com tempo esgotado, `start()` reativava a thread antiga e criava outra.
- **Causa:** as duas compartilhavam o mesmo evento de parada.
- **Solução:** cada thread recebe o próprio evento ([factoryio.py](../desktop/src/ladderide/sim/factoryio.py),
  [plc_link.py](../desktop/src/ladderide/sim/plc_link.py)).
- **Verificação (Testado):** `test_s9_restart_after_slow_stop_does_not_revive_old_thread`, na ponte do Factory IO; a outra
  segue o mesmo padrão.

### S10. A 1000× a velocidade real ficava abaixo do pedido

- **Problema:** o simulador cortava em 2000 varreduras por atualização e culpava o PC ("limite do PC").
- **Causa:** o limite fixo valia mesmo com tempo de CPU sobrando.
- **Solução:** quando a interface informa o tempo de CPU disponível, só ele limita.
- **Verificação (Testado):** `test_s10_speed_is_limited_by_cpu_time_when_the_interface_gives_it`.

### S11. Velocidade real oscilava em velocidade baixa

- **Problema:** a 0,01× o valor exibido variava de 0,00004× a 0,0667×.
- **Causa:** a média era feita a cada atualização da tela, e a maioria não tinha varredura nenhuma.
- **Solução:** medição em janelas de tempo, sem contar a primeira varredura.
- **Verificação (Testado):** `test_s11_speed_reading_is_steady_at_low_speed`.

## Importação e modelo de projeto

### K1. Importar perdia o estado seguro das saídas

- **Problema:** ao importar LIL ou LDRB, `safe_outputs` ia parar em `n_words`, e o estado seguro se perdia.
- **Causa:** `IOConfig` era preenchido por posição, e o quarto campo é `n_words`.
- **Solução:** argumentos nomeados ([importer.py](../desktop/src/ladderide/compiler/importer.py)).
- **Verificação (Testado):** `test_k1_import_keeps_safe_outputs_and_words`.

### K2. Identificador do programa ignorava o estado seguro

- **Problema:** dois programas com estados seguros diferentes tinham o mesmo `build_id`, e o painel dizia "Igual ao projeto
  aberto".
- **Causa:** o cálculo não incluía `safe_outputs`.
- **Solução:** o valor entra no cálculo quando existe; programas sem estado seguro mantêm o mesmo id.
- **Verificação (Testado):** `test_k2_build_id_depends_on_safe_outputs`.

### K3. Constante decimal grande virava número negativo

- **Problema:** `3000000000` compilava como -1294967296, sem aviso. `007` dava uma mensagem interna do Python.
- **Causa:** a conversão pensada para máscaras hexadecimais valia também para decimais.
- **Solução:** valores de 2^31 a 2^32-1 só em hexadecimal ou binário; zeros à esquerda são aceitos.
- **Verificação (Testado):** `test_k3_decimal_constant_must_fit_int32`.

### K4. Importação recusava blocos gerados pelo próprio compilador

- **Problema:** LIL ou LDRB com comparação ou matemática falhava com "GRT inesperado".
- **Causa:** o importador não conhecia esses blocos, criados no LDRB 2.0.
- **Solução:** `CompareBox` e `MathBox` são reconstruídos com os operandos e constantes.
- **Verificação (Testado):** `test_k4_import_understands_compare_and_math_blocks`.

### K5. Importação cortava as E/S para 8/8

- **Problema:** um programa de 16/16 E/S importado ficava com 8/8 e não compilava.
- **Causa:** o projeto importado ficava no controlador padrão, e abrir ajustava as E/S a ele.
- **Solução:** escolhe um controlador que comporte as E/S do programa.
- **Verificação (Testado):** `test_k5_import_does_not_cut_io_to_the_default_controller`.

### K6. Listagem LIL inválida era aceita ou derrubava a IDE

- **Problema:** `.timer T0 FOO 10` gerava `KeyError`; `OTE I0.0`, `XIC I99.0` ou preset negativo eram aceitos.
- **Causa:** a listagem não passava pela validação aplicada às imagens binárias.
- **Solução:** a listagem é codificada e validada como imagem antes de virar diagrama.
- **Verificação (Testado):** `test_k6_invalid_listing_is_refused_with_a_handled_error`.

### K7. Arquivo de projeto corrompido derrubava a IDE ou era apagado

- **Problema:** projetos com estrutura ou tipos errados geravam exceção não tratada ao abrir ou compilar. Uma falha ao
  salvar deixava o arquivo com 0 bytes. Arquivos com BOM UTF-8 eram recusados.
- **Causa:** a carga não verificava tipos, e a gravação escrevia direto sobre o arquivo.
- **Solução:** erros viram `ProjectFormatError`, tipos são conferidos ao carregar e a gravação usa arquivo temporário com
  troca atômica ([project.py](../desktop/src/ladderide/model/project.py)).
- **Verificação (Testado):** `test_k8_*`.

### K8. Tabela de símbolos aceitava nomes inválidos

- **Problema:** nome vazio apagava os operandos, e um nome já usado fundia dois sinais em um.
- **Causa:** a tabela renomeava sem as validações usadas em outros pontos da IDE.
- **Solução:** nome inválido é recusado, a célula volta ao valor anterior e a barra de status explica o motivo.
- **Verificação (Testado):** `test_k9_invalid_rename_in_symbol_table_is_refused`.

### K9. Próximo temporizador livre ignorava símbolos

- **Problema:** com `TON Atraso` (Atraso = T0), um novo temporizador também recebia T0 e dava erro de duplicidade.
- **Causa:** só comparava o texto do operando.
- **Solução:** o operando é traduzido pela tabela de símbolos.
- **Verificação (Testado):** `test_k10_next_free_element_understands_symbols`.

### K10. CP1E de 10, 14 e 20 pontos aceitavam expansão

- **Problema:** sete modelos DT1 aceitavam módulos, contra o que o manual e a documentação indicam.
- **Causa:** valor errado em `controllers.json`.
- **Solução:** `max_expansions: 0` nesses modelos.
- **Verificação (Testado):** `test_k11_small_cp1e_do_not_accept_expansions`.

### K11. Edição recusada apagava o refazer

- **Problema:** depois de um desfazer, uma edição recusada zerava o refazer e marcava o projeto como alterado.
- **Causa:** o histórico era limpo antes de a edição ser validada.
- **Solução:** histórico e estado são restaurados quando a edição falha.
- **Verificação (Testado):** `test_k12_refused_edit_keeps_redo_and_clean_state`.

### K12. Casos de borda do compilador e da especificação

- **Problema:** `safe_outputs` acima de 16 bits derrubava o compilador; a mensagem com 0 registradores mostrava "N0 a N-1";
  a especificação listava 4 bits de sistema, e são 7.
- **Solução:** máscara de 16 bits, mensagem específica e tabela atualizada.

## Comunicação e linha de comando

### M1. Comando novo podia receber a resposta do anterior

- **Problema:** com o mesmo número de sequência, um `SET_MODE(STOP)` depois de um `RUN` recebia a resposta antiga e o CLP
  **continuava em RUN**.
- **Causa:** o firmware identificava retransmissões só por sequência e tipo.
- **Solução:** o conteúdo do pedido também entra na comparação ([plc_runtime.c](../firmware/lib/plc_core/plc_runtime.c)).
- **Verificação (Testado):** `test_new_command_with_repeated_sequence_is_executed`, em `test_comm.py`.

### M2. Resposta inesperada encerrava a sessão com o dispositivo

- **Problema:** uma resposta curta com CRC válido matava a fila de trabalho, e nada mais executava.
- **Causa:** o laço só tratava erros conhecidos.
- **Solução:** qualquer erro de um trabalho é informado, e a fila continua ([device_panel.py](../desktop/src/ladderide/ui/device_panel.py)).

### M3. Prazo de quadro parcial era renovado por leituras vazias

- **Problema:** leituras sem dados impediam o descarte de um quadro incompleto.
- **Causa:** o relógio era atualizado mesmo sem bytes.
- **Solução:** só atualiza quando chegam dados.
- **Verificação (Testado):** `test_m3_frame_timeout_is_not_renewed_by_empty_reads`.

### M4. Linha de comando terminava em erro interno ou falso sucesso

- **Problema:** arquivo inexistente ou argumento inválido gerava traceback, e uma pasta de vetores vazia contava como sucesso.
- **Causa:** faltava tratamento dessas entradas.
- **Solução:** `ERRO:` com código 2, Ctrl+C sai limpo e sem vetores a equivalência falha ([cli.py](../desktop/src/ladderide/cli.py)).
- **Verificação (Testado):** `test_m4_*` e `test_m5_*`.

### M5. Mensagens do compilador com acentos quebravam a compilação da placa simulada

- **Problema:** erro do g++ com caractere fora do cp1252 virava `AttributeError`, e a placa ficava em "COMPILANDO...".
- **Causa:** a saída era decodificada em cp1252 estrito.
- **Solução:** decodifica em UTF-8 tolerante.

### M6. Falhas de ferramentas externas sem tratamento

- **Problema:** placa simulada que encerrava sem aviso; `close()` preso com o pipe cheio; laço infinito com bloco de tamanho
  0; `flash.json` danificado e erro de arquivo ao gerar o C++ fora do tratamento dos diálogos; janela de console no
  dispositivo virtual.
- **Solução:** encerramento sempre notificado, `close()` sem depender da escrita, tamanho 0 recusado, erros convertidos
  para as mensagens dos diálogos e processo sem janela.

### M7. Leitura de `board_config.h` ignorava formatos comuns

- **Problema:** `0x21`, `33 // comentário`, `50000UL` e `OUT_MAP[BOARD_OUTPUTS]` eram ignorados ou quebravam a leitura.
- **Causa:** expressões regulares restritas demais.
- **Solução:** aceita hexadecimal, sufixos, comentários `//` e tamanho simbólico ([board.py](../desktop/src/ladderide/comm/board.py)).
- **Verificação (Testado):** `test_m7_board_config_accepts_common_c_forms`.

### M8. CLIC-02 aceitava resposta de outro escravo ou eco errado

- **Problema:** exceção de outro escravo era atribuída ao CLP, e um eco com endereço ou valor diferente contava como sucesso.
- **Causa:** a resposta não era conferida nesses caminhos.
- **Solução:** confere escravo, função e o eco das escritas ([plc_serial.py](../desktop/src/ladderide/comm/plc_serial.py)).
- **Verificação (Testado):** `test_m9_clic02_checks_slave_and_write_echo`.

## Editor e janela principal

Testes em `desktop/tests/test_regressions.py` (`test_u2` a `test_u11`).

| Código | Problema | Causa | Solução |
|---|---|---|---|
| E1 | **Delete com o foco na tabela ou nas mensagens apagava o elemento selecionado no diagrama** | Atalho valia na janela inteira | Delete e Enter só valem com o foco no diagrama |
| E2 | Enter em campos de texto não confirmava e abria o diálogo do elemento | Mesma causa | Mesma solução |
| E3 | F5 com célula de símbolo em edição encerrava a simulação recém-iniciada | A célula era confirmada no meio da troca de modo | A célula é confirmada antes de compilar |
| E4 | Símbolo com endereço fora da faixa (`I99.0`) gerava erro a cada atualização e travava o ambiente e o Factory IO | O painel lia o endereço sem conferir a faixa | Endereços fora da faixa são ignorados no painel |
| E5 | O programa podia ser editado durante o monitor online | O bloqueio só olhava a simulação | Edição bloqueada também com o monitor ligado |
| E6 | Excluir a última rede e apertar Delete de novo dava erro e sujava o desfazer | A seleção continuava apontando para a rede excluída | A seleção é limpa ao excluir |
| E7 | Projeto com ramo vazio ou comentário de tipo errado ficava carregado e quebrava a tela | A troca de projeto não era desfeita em caso de falha | Validação ao carregar e volta ao projeto anterior |
| E8 | Fechar durante a simulação salvava a paleta oculta; "Restaurar layout" no monitor também a perdia | O layout gravava o estado temporário | O layout salvo considera a paleta do modo de edição |
| E9 | Travar o layout congelava as abas com largura antiga | Aba oculta guarda tamanho antigo; a paleta também ficava de fora | Usa o maior tamanho do grupo e reaplica ao voltar a paleta |
| E10 | "Salvar como" que falhava mantinha o caminho ruim | O caminho mudava antes de gravar | Volta ao caminho anterior |
| E11 | Exportar LIL/LDRB em pasta sem permissão dava erro sem mensagem | Faltava tratamento | Mensagem de erro |
| E12 | Ctrl+Z desfazia a escolha do ambiente sem atualizar o painel | A escolha estava no instantâneo, mas não é uma edição | O desfazer mantém o ambiente atual |
| E13 | Trocar o tema não atualizava o selo de modo | Faltava atualizar | Atualiza ao trocar o tema |
| E14 | Novas variáveis recebiam todas `M0.0`; OK sem alterar criava entrada no desfazer; "Abrir exemplo" funcionava durante a simulação | Faltavam essas verificações | Próximo `M` livre, comparação antes de aplicar e bloqueio durante a simulação |

## Painéis de processo e dispositivo

| Código | Problema | Causa | Solução |
|---|---|---|---|
| P1 | Com o CLP real conectado, trocar módulos ou controlador deixava a troca de dados errada (escrevia em M05 em vez do módulo) | O driver só lê os módulos ao conectar | Pede para desconectar antes dessas alterações |
| P2 | Transferência recusada (programa grande demais, FAULT) derrubava a conexão | Recusa era tratada como queda | Nova exceção `TransferRefused`, que mantém a conexão |
| P3 | Factory IO e CLP real ligados juntos: o Factory IO também recebia as saídas | Saídas enviadas aos dois | Só o processo ativo recebe saídas |
| P4 | Desligar durante a compilação do exemplo Arduino não cancelava e podia deixar processo órfão | O resultado da compilação era sempre aceito | Resultado de compilação cancelada é descartado |
| P5 | Se o esptool não iniciava, Gravar e Fechar ficavam desabilitados para sempre | O Qt não emite `finished` nesse caso | Botões reabilitados nesse erro |
| P6 | A gravação podia começar com a porta ainda aberta pela IDE | `close` só enfileirava | `close_and_wait` espera a porta ser liberada |
| P7 | Segunda transferência em paralelo deixava um diálogo preso | Faltava bloqueio | Recusa enquanto há transferência |
| P8 | Casos menores: botão Padrão ativo com o link ligado; Atualizar com só espaços; Encaixar módulos em CPU sem expansão; controlador do usuário com protocolo desconhecido; guia de comunicação redesenhando depois de fechado | Faltavam essas verificações | Corrigidos |

Os itens E e P têm testes para E1, E4 a E7, E10, E12, E14, P2 e P4; os demais foram confirmados pelos scripts da auditoria,
sem teste automatizado próprio.

## Instalador e empacotamento

| Código | Problema | Causa | Solução | Verificação |
|---|---|---|---|---|
| I1 | Exemplos Arduino da placa simulada não iniciavam na IDE instalada | Os executáveis dependiam de DLLs do MinGW | Compilação estática no Windows ([sketch.py](../desktop/src/ladderide/comm/sketch.py)) | Compilação pela suíte |
| I2 | O instalador não detectava a IDE aberta e podia deixar a pasta quebrada | Testava renomeando, e o Windows permite | Tenta abrir o executável para escrita ([ladderide_setup.py](../installer/ladderide_setup.py)) | Script da auditoria; instalador não executado |
| I3 | Apóstrofo no caminho (`D'Avila`) quebrava a criação de atalhos | Caminho sem escape no PowerShell | Apóstrofos escapados | Sintaxe do script gerado |
| I4 | Área de Trabalho com acento era lida errada e o atalho ia para outra pasta | Saída do PowerShell lida na página de código errada | Saída em UTF-8 | Script da auditoria |
| I5 | Desinstalar pelo menu deixava a pasta vazia | O `rmdir` rodava de dentro dela | Roda a partir da pasta temporária | Linha de comando equivalente |
| I6 | Atalho Linux inválido em caminho com espaço | `Exec=` sem aspas | Aspas e outro delimitador no `sed` ([build_app.py](../scripts/build_app.py)) | Arquivo gerado |

## Pendências não corrigidas

- **Programas de exemplo em uso anormal:** garrafas transborda se o seletor mudar durante o enchimento; o misturador termina
  a descarga fora de ordem com STOP no meio; os compressores precisam de mais dreno a 100% de consumo por muito tempo. No
  uso normal não há alarme. Corrigir exige regerar os exemplos.
- **`make_examples.py`** não gera o exemplo `simulador_es`, e os `.ladproj` versionados ainda estão no formato antigo (a IDE
  os converte ao abrir).
- **`pip install` sem `-e`** não funciona, porque as especificações ficam fora do pacote. O README só documenta `-e`.

- **Factory IO:** registradores além dos N disponíveis aparecem "sem endereço", mas Conectar recusa, com mensagem clara; o
  campo `holding_from` é reduzido sem aviso quando o projeto tem menos N.
- **Remover símbolo em uso** não avisa; o erro aparece ao compilar e Ctrl+Z desfaz.

- **Host Link com resposta `IC` de 9 caracteres** e **progresso do esptool 5**: o formato veio de memória e precisa ser
  conferido na fonte antes de alterar o código.
- **Dispositivo virtual em pasta com caracteres fora da página de código do Windows** (por exemplo, `日本語`): a transferência
  falha ao gravar; acentos comuns e espaços funcionam.

## Limitação conhecida

"Verificar para ESP32" confere só o perfil do ESP32: um projeto para Arduino Mega com 16 E/S recebe o erro de que a placa
tem 8 entradas. Os limites de UNO e Mega são conferidos ao gravar o C++.
