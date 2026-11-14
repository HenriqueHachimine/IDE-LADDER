# Ambientes de simulação

Os ambientes são processos físicos animados (silo, semáforo, portão, elevador...)
controlados pelo programa LADDER durante a simulação offline. Eles são
**plugins**: o simulador e a interface conhecem apenas um contrato genérico,
e cada ambiente fica em um arquivo independente.

## Ambientes incluídos

| Ambiente | Entradas | Saídas | Exemplo |
|---|---|---|---|
| **Silo de envase** (`silo`) | I0.0 Start, I0.1 Stop (NF), I0.2 sensor de presença, I0.3 sensor de nível | Q0.0 motor da esteira, Q0.1 válvula, Q0.2 RUN, Q0.3 FILL, Q0.4 FULL | `examples/ambientes/silo.ladproj` |
| **Semáforo de cruzamento** (`semaforo`) | I0.0/I0.1 botões de pedestre, I0.2/I0.3 sensores de carro | Q0.0–Q0.2 vermelho/amarelo/verde NS, Q0.3 pedestre NS, Q0.4–Q0.6 vermelho/amarelo/verde LO, Q0.7 pedestre LO | `examples/ambientes/semaforo.ladproj` |
| **Portão de garagem** (`portao`) | I0.0 Abrir, I0.1 Fechar, I0.2 Parar (NF), I0.3 LS1 aberto, I0.4 LS2 fechado, I0.5 fotocélula | Q0.0 sobe, Q0.1 desce, Q0.2 entreaberto, Q0.3 aberto, Q0.4 fechado | `examples/ambientes/portao.ladproj` |
| **Elevador de 4 andares** (`elevador`) | I0.0–I0.3 botões dos andares 1–4 (cabine ou pavimento), I0.4–I0.7 sensores de andar | Q0.0 sobe, Q0.1 desce, Q0.2 abrir porta, Q0.3–Q0.6 lâmpadas de chamada | `examples/ambientes/elevador.ladproj` |
| **Linha de garrafas** (`garrafas`) | I0.0 Start, I0.1 Stop (NF), I0.2 garrafa no bico, I0.3 nível OK, I0.4 garrafa na inspeção, I0.5 chave garrafa grande, I0.6 garrafa caindo na caixa, I0.7 caixa posicionada | Q0.0 esteira de garrafas, Q0.1 válvula, Q0.2 rejeitor, Q0.3 esteira de caixas, Q0.4 RUN | `examples/ambientes/garrafas.ladproj` |
| **Central de ar comprimido** (`compressores`) | I0.0 Start, I0.1 Stop (NF), I0.2 pressostato 1 (100/120 psi), I0.3 pressostato 2 (90/110 psi), I0.4/I0.5 relés térmicos (NF) | Q0.0 motor 1, Q0.1 motor 2, Q0.2 dreno, Q0.3 RUN, Q0.4 falha | `examples/ambientes/compressores.ladproj` |
| **Misturador de batelada** (`misturador`) | I0.0 Start, I0.1 Stop (NF), I0.2 nível baixo, I0.3 nível alto, I0.4 termostato, I0.5/I0.6 fluxômetros (1 pulso/L) | Q0.0 bomba A, Q0.1 bomba B, Q0.2 misturador, Q0.3 bomba de saída, Q0.4 aquecedor, Q0.5 RUN, Q0.6 cheio | `examples/ambientes/misturador.ladproj` |
| **Partida estrela-triângulo reversível** (`estrela_triangulo`) | I0.0 Liga Horario, I0.1 Liga Anti Horario, I0.2 Desliga (NF), I0.3 Rele Termico (NF), I0.4 Rele Falta Fase (NF), I0.5 Rotacao Nominal, I0.6 Motor Parado | Q0.0 K1 Horario, Q0.1 K4 Anti Horario, Q0.2 K2 Estrela, Q0.3 K3 Triangulo, Q0.4 Lampada Ligado, Q0.5 Lampada Falha | `examples/ambientes/estrela_triangulo.ladproj` |
| **Prensa hidráulica bimanual** (`prensa`) | I0.0 Botao Esquerdo, I0.1 Botao Direito, I0.2 Cortina Luz (NF), I0.3 PMS, I0.4 PMI, I0.5 Emergencia (NF), I0.6 Modo Ajuste, I0.7 Valvula Repouso | Q0.0 Valvula Desce, Q0.1 Valvula Sobe, Q0.2 Lampada Pronta, Q0.3 Velocidade Lenta, Q0.4 Valvula Seguranca, Q0.5 Lampada Falha, Q0.6 Bomba Lubrificacao | `examples/ambientes/prensa.ladproj` |
| **Furadeira automática (sequência)** (`furadeira`) | I0.0 Partida, I0.1 Emergencia (NF), I0.2 Peca Presente, I0.3 Fixador Avancado, I0.4 Broca Em Cima, I0.5 Broca Embaixo, I0.6 Ejetor Recuado, I0.7 Ejetor Avancado; N0 posição da broca, N1 broca montada | Q0.0 Fixador, Q0.1 Broca Desce, Q0.2 Broca Sobe, Q0.3 Motor Mandril, Q0.4 Ejetor, Q0.5 Lampada Ciclo, Q0.6 Refrigeracao, Q0.7 Lampada Trocar Broca | `examples/ambientes/furadeira.ladproj` |
| **Passagem de nível em linha dupla** (`passagem_nivel`) | I0.0 Via1 Oeste, I0.1 Via1 Ilha, I0.2 Via1 Leste, I0.3 Cancela Abaixada, I0.4 Cancela Levantada, I0.5 Via2 Oeste, I0.6 Via2 Ilha, I0.7 Via2 Leste | Q0.0 Luz Esquerda, Q0.1 Luz Direita, Q0.2 Sino, Q0.3 Cancela Abaixa, Q0.4 Cancela Levanta, Q0.5 Painel Outro Trem | `examples/ambientes/passagem_nivel.ladproj` |
| **Estacionamento de dois pisos** (`estacionamento`) | I0.0 Botao Ticket, I0.1 Laco Entrada, I0.2 Cartao Validado, I0.3 Laco Saida, I0.4 Zerar Contagem, I0.5 Rampa Laco A, I0.6 Rampa Laco B; painéis leem N0–N2 | Q0.0 Cancela Entrada, Q0.1 Cancela Saida, Q0.2 Painel Livre, Q0.3 Painel Lotado, Q0.4 Piso1 Lotado | `examples/ambientes/estacionamento.ladproj` |
| **Separação de peças configurável** (`seletor_pecas`) | I0.0 Liga, I0.1 Encoder, I0.2 Peca Inspecao, I0.3 Sensor Metal, I0.4 Sensor Altura, I0.5 Caixas Trocadas; tipo de cada caixa em N10–N12 | Q0.0 Motor Esteira, Q0.1 Desviador A, Q0.2 Desviador B, Q0.3 Lampada Run, Q0.4 Desviador C, Q0.5 Lampada Trocar | `examples/ambientes/seletor_pecas.ladproj` |
| **Detecção de gás analógica (2 de 3)** (`detector_gas`) | I0.0 Reconhecer, I0.1 Rearmar, I0.2 Fluxo Exaustao, I0.3 Teste Lampadas; leituras em N0–N2 (%LIE x10); mediana em N3 | Q0.0 Exaustor, Q0.1 Valvula Gas, Q0.2 Sirene, Q0.3 Luz Alarme, Q0.4 Luz Falha Detector, Q0.5 Luz Falha Exaustor, Q0.6 Exaustor Alta, Q0.7 Luz Pre Alarme | `examples/ambientes/detector_gas.ladproj` |
| **Dosagem por receita em balança** (`balanca`) | I0.0 Partida, I0.1 Parada (NF), I0.2 Recipiente Posicionado, I0.3 Peso Estavel, I0.4 Recipiente Rejeito; N0 peso bruto, N1/N2 alvos da receita | Q0.0 Valvula A Grossa, Q0.1 Valvula A Fina, Q0.2 Esteira, Q0.3 Lampada OK, Q0.4 Lampada Rejeito, Q0.5 Valvula B, Q0.6 Rejeitador | `examples/ambientes/balanca.ladproj` |
| **Estufa agrícola com irrigação** (`estufa`) | I0.0 Automatico, I0.1 Janela Aberta, I0.2 Janela Fechada, I0.3 Sensor Chuva, I0.4 Sensor Vento, I0.5 Reservatorio Baixo; N0 temperatura (décimos), N1 umidade, N2 hora, N3 solo | Q0.0 Aquecedor, Q0.1 Exaustor, Q0.2 Janela Abre, Q0.3 Janela Fecha, Q0.4 Nebulizador, Q0.5 Iluminacao, Q0.6 Alarme, Q0.7 Bomba Irrigacao | `examples/ambientes/estufa.ladproj` |
| **Ponte rolante com guincho** (`ponte_rolante`) | I0.0 Encoder, I0.1 Origem, I0.2 Gancho Topo, I0.3 Gancho Apoiado, I0.4 Carga Presa, I0.5 Iniciar, I0.6 Carga Sob Gancho, I0.7 Emergencia (NF); N10 origem e N11 destino da tarefa | Q0.0 Motor Direita, Q0.1 Motor Esquerda, Q0.2 Velocidade Lenta, Q0.3 Libera Freio, Q0.4 Lampada Pronta, Q0.5 Guincho Sobe, Q0.6 Guincho Desce, Q0.7 Eletroima | `examples/ambientes/ponte_rolante.ladproj` |
| **Máquina de venda (preços e troco)** (`venda`) | I0.0 Moeda 25, I0.1 Moeda 50, I0.2 Moeda 100, I0.3 Sensor Queda, I0.4 Devolver, I0.5 Tubo 25 Vazio, I0.6 Tubo 50 Vazio, I0.7 Porta Servico; N0 crédito, N1–N3 preços, N4 tecla | Q0.0 Espiral A, Q0.1 Espiral B, Q0.2 Espiral C, Q0.3 Ejetor 25, Q0.4 Ejetor 50, Q0.5 Lampada Pronto, Q0.6 Lampada Esgotado, Q0.7 Lampada Sem Troco | `examples/ambientes/venda.ladproj` |
| **Controle de nível PI** (`nivel_pi`) | I0.0 Automatico, I0.1 Nivel Alto, I0.2 Nivel Baixo; N0 nível, N2 setpoint; o programa escreve a válvula em N1 | Q0.0 Bomba Alimentacao, Q0.1 Bomba Consumo, Q0.2 Alarme Alto, Q0.3 Alarme Baixo | `examples/ambientes/nivel_pi.ladproj` |
| **Paletizador de camadas** (`paletizador`) | I0.0 Liga, I0.1 Caixa Entrando, I0.2 Empurrador Recuado, I0.3 Empurrador Avancado, I0.4 Placa Fechada, I0.5 Pilha Alinhada, I0.6 Elevador Embaixo, I0.7 Pallet Presente | Q0.0 Esteira Entrada, Q0.1 Empurrador, Q0.2 Abre Placa, Q0.3 Elevador Desce, Q0.4 Elevador Sobe, Q0.5 Esteira Pallets, Q0.6 Girador, Q0.7 Lampada Completo | `examples/ambientes/paletizador.ladproj` |
| **Forno com rampa e patamar** (`forno_rampa`) | I0.0 Partida, I0.1 Parada (NF), I0.2 Porta Fechada, I0.3 Termostato (NF), I0.4 Fluxo Ventilador; N0 temperatura; o programa escreve o setpoint em N1 | Q0.0 Resistencia 1, Q0.1 Resistencia 2, Q0.2 Ventilador, Q0.3 Trava Porta, Q0.4 Lampada Ciclo, Q0.5 Lampada Fim, Q0.6 Lampada Alarme | `examples/ambientes/forno_rampa.ladproj` |
| **Controle de demanda de energia** (`demanda_energia`) | I0.0 Pulso Sincronismo, I0.1 Pede AC1, I0.2 Pede AC2, I0.3 Pede Compressor, I0.4 Pede Aquecedor, I0.5 Pede Bomba; N0 potência, N1 energia da janela, N2 segundos restantes, N3 contrato | Q0.0 Ar Cond 1, Q0.1 Ar Cond 2, Q0.2 Compressor, Q0.3 Aquecedor, Q0.4 Bomba, Q0.5 Lampada Demanda, Q0.6 Lampada Corte | `examples/ambientes/demanda_energia.ladproj` |
| **Transferência rede/gerador (QTA)** (`gerador_qta`) | I0.0 Rede OK, I0.1 Gerador Girando, I0.2 Gerador Tensao OK, I0.3 KR Fechado, I0.4 KG Fechado, I0.5 Combustivel Baixo, I0.6 Automatico, I0.7 Rearme | Q0.0 Motor Partida, Q0.1 Solenoide Combustivel, Q0.2 Contator KR, Q0.3 Contator KG, Q0.4 Lampada Rede, Q0.5 Lampada Gerador, Q0.6 Lampada Falha, Q0.7 Buzina | `examples/ambientes/gerador_qta.ladproj` |
| **Eclusa de navegação** (`eclusa`) | I0.0 Nivel Igual Montante, I0.1 Nivel Igual Jusante, I0.2 Montante Aberta, I0.3 Montante Fechada, I0.4 Jusante Aberta, I0.5 Jusante Fechada, I0.6 Barco Montante, I0.7 Barco Jusante; N0 nível da câmara (cm), N1 ocupação | Q0.0 Abre Montante, Q0.1 Fecha Montante, Q0.2 Abre Jusante, Q0.3 Fecha Jusante, Q0.4 Valvula Enchimento, Q0.5 Valvula Esvaziamento, Q0.6 Verde Montante, Q0.7 Verde Jusante | `examples/ambientes/eclusa.ladproj` |
| **Lava-rápido de pórtico** (`lava_rapido`) | I0.0 Pagamento OK, I0.1 Carro Posicionado, I0.2 Portico Origem, I0.3 Portico Fim, I0.4 Emergencia (NF); N0 programa pago | Q0.0 Portico Avanca, Q0.1 Portico Recua, Q0.2 Agua, Q0.3 Shampoo, Q0.4 Escovas, Q0.5 Cera, Q0.6 Secador, Q0.7 Semaforo Verde | `examples/ambientes/lava_rapido.ladproj` |
| **Separação por altura** (`separacao_altura`) | I0.0 Liga, I0.1 Sensor Baixo, I0.2 Sensor Alto, I0.3 Encoder (1 pulso a cada 20 px), I0.4 Fim Altas, I0.5 Fim Baixas; o registrador N5 aparece sob a esteira | Q0.0 Esteira Entrada, Q0.1 Desviador, Q0.2 Esteira Altas, Q0.3 Esteira Baixas, Q0.4 Emissor, Q0.5 Luz Operando | `examples/ambientes/separacao_altura.ladproj` |
| **Pick & place XY** (`pick_place`) | I0.0 Liga, I0.1 Em Posicao, I0.2 Z Em Cima, I0.3 Z Embaixo, I0.4 Peca Presa, I0.5 Peca Na Coleta, I0.6 Pallet Presente; N0/N1 posição dos eixos (mm) | Q0.0 Esteira Pecas, Q0.1 Z Desce, Q0.2 Ventosa, Q0.3 Esteira Pallets, Q0.4 Luz Operando; o programa escreve os destinos X/Y em N10/N11 | `examples/ambientes/pick_place.ladproj` |
| **Armazém automático** (`armazem`) | I0.0 Liga, I0.1 Em Posicao, I0.2 Garfo Centro, I0.3 Garfo Estendido, I0.4 Caixa Na Entrada, I0.5 Saida Livre, I0.6 Garfo Em Cima, I0.7 Garfo Embaixo; N1 célula pedida pelo operador | Q0.0 Esteira Entrada, Q0.1 Garfo Avanca, Q0.2 Garfo Sobe, Q0.3 Esteira Saida, Q0.4 Luz Cheio, Q0.5 Luz Operando; o programa escreve o destino (0 a 16) em N10 | `examples/ambientes/armazem.ladproj` |
| **Separação por peso** (`separacao_peso`) | I0.0 Liga, I0.1 Caixa Na Balanca, I0.2 Peso Estavel, I0.3 Caixa No Transferidor; N0 peso (g); a fila N20–N24 aparece no painel | Q0.0 Esteira Entrada, Q0.1 Esteira Balanca, Q0.2 Esteira Desvio, Q0.3 Transfere Leves, Q0.4 Transfere Pesadas, Q0.5 Emissor, Q0.6 Luz Operando | `examples/ambientes/separacao_peso.ladproj` |
| **Convergência de esteiras** (`convergencia`) | I0.0 Liga, I0.1 Caixa No Batente A, I0.2 Caixa No Batente B, I0.3 Fila A Longa, I0.4 Fila B Longa, I0.5 Juncao Ocupada | Q0.0 Esteira A, Q0.1 Esteira B, Q0.2 Esteira Principal, Q0.3 Libera A, Q0.4 Libera B, Q0.5 Emissores, Q0.6 Luz Operando, Q0.7 Luz Fila Longa | `examples/ambientes/convergencia.ladproj` |
| **Estação de montagem** (`montagem`) | I0.0 Liga, I0.1 Base Na Estacao, I0.2 Tampa Pronta, I0.3 Braco Na Tampa, I0.4 Braco Na Base, I0.5 Z Em Cima, I0.6 Z Embaixo | Q0.0 Esteira Bases, Q0.1 Libera Base, Q0.2 Esteira Tampas, Q0.3 Braco Avanca, Q0.4 Z Desce, Q0.5 Garra, Q0.6 Emissores, Q0.7 Luz Operando | `examples/ambientes/montagem.ladproj` |
| **Simulador de E/S e BCD** (`simulador_es`) | uma botoeira por entrada do controlador (I0.0–I1.7); tipo trocável: pulsador NA/NF ou chave NA/NF; thumbwheel BCD em N0 | uma lâmpada por saída do controlador (Q0.0–Q1.7); display BCD de N1 | `examples/ambientes/simulador_es.ladproj` |

Os processos usam no máximo 8 entradas e 8 saídas digitais, como a placa. Grandezas numéricas (nível, peso, temperatura, posição, preços, receitas) vão e voltam pelos registradores N (`input_words()`/`advance_words()`), como as entradas e saídas analógicas de um CLP. O
**Simulador de E/S** é a exceção: ele implementa `configure(n_inputs,
n_outputs, n_words)` e refaz os pontos sempre que o controlador do projeto
muda (ESP32: 8/8; SLC 5/05: 16/16; Arduino UNO: 8/8...). A thumbwheel e o
display usam `input_words()` e `advance_words()`, que escrevem e leem
registradores N; o BCD exige ao menos 2 registradores N. Grandezas analógicas do processo (pressão, temperatura, nível, vazão) chegam ao CLP como em instalações reais com entradas digitais: pressostatos e termostatos com diferencial, chaves de nível e fluxômetros de pulso.

## Estilos de lógica

Cada ambiente pede um jeito diferente de pensar o programa:

| Ambiente | Estilo de lógica | O que o exemplo usa |
|---|---|---|
| Silo, garrafas | Partida/parada com selo e memória de estado | selo, OTL/OTU, RTO, CTU |
| Semáforo | Sequência por tempo | cadeia de TON |
| Partida estrela-triângulo reversível | Intertravamento e tempo morto | K1/K4 e K2/K3 cruzados, espera do motor parado, tempo morto de 150 ms pelos auxiliares |
| Prensa bimanual | Lógica de segurança | simultaneidade de 0,5 s, anti-repetição, válvulas redundantes e monitoramento do carretel |
| Furadeira | Sequência por etapas (Grafcet) com laço | quebra-cavaco por posição em N0, contagem da vida da broca, troca detectada por N1 |
| Passagem de nível em linha dupla | Memória de sentido por via | lógica repetida para cada via, OU para o alerta, E para o painel OUTRO TREM |
| Estacionamento de dois pisos | Contagem e detecção de sentido | bordas, ADD/SUB por piso, ordem dos laços da rampa |
| Separação de peças configurável | Registrador de deslocamento de palavras (FIFO) | MOV em cadeia, código da peça, EQU com o tipo escolhido |
| Detecção de gás analógica | Votação degradável e gestão de alarmes | mediana, discordância, votação 2 de 3 que vira 1 de 2, purga temporizada |
| Dosagem por receita | Setpoint com tara e correção | tara, alvo bruto, dois cortes antecipados adaptativos, rejeito rastreado |
| Estufa com irrigação | Controle por faixas com histerese | LES/GRT com OTL/OTU, LIM na hora do dia, bloqueio da bomba |
| Ponte rolante com guincho | Posicionamento e sequência de transporte | encoder pelo sentido, tabela de estações, etapas E0–E8 |
| Máquina de venda | Máquina de estados com dinheiro e registradores | crédito, preços em N, tecla com handshake, troco com a maior moeda |
| Controle de nível PI | Malha fechada contínua | P + I em inteiros a cada 200 ms, saída 0..100%, integração condicional |
| Paletizador | Contadores aninhados | caixas → filas → camadas, MEQ no ACC para a amarração |
| Forno com rampa e patamar | Gerador de perfil e controle proporcional ao tempo | setpoint em décimos a cada 100 ms, PWM com o ACC do temporizador, antecipação |
| Controle de demanda | Projeção e corte por prioridade | média prevista da janela, estágios, rodízio, tempo máximo desligado/mínimo ligado |
| Transferência rede/gerador | Supervisão com filtros e retentativas | filtros de tempo, 3 tentativas com bloqueio, intertravamento pelos auxiliares |
| Eclusa | Permissivos e equalização | duas sequências espelhadas, permissivo em cada saída |
| Lava-rápido | Receita como máscara de bits | tabela programa → máscara, MEQ e MUL por 2 para percorrer as passadas |
| Separação por altura | Rastreamento sincronizado pelo encoder | registrador de deslocamento em N5 (MUL por 2 a cada pulso), marca na borda de descida, janela de bits no desviador |
| Pick & place XY | Coordenadas calculadas e eixos por setpoint | índice → linha/coluna com DIV/MUL/SUB, destino em N10/N11, espera antes de olhar Em_Posicao |
| Armazém automático | Mapa de ocupação | um bit por célula em N20, primeira célula livre com MEQ, etapas com transições em ordem inversa |
| Separação por peso | Fila FIFO de palavras | classe por faixa de peso, entrada no primeiro lugar vazio e avanço da fila com MOV em cadeia |
| Convergência de esteiras | Arbitragem entre filas | zona da junção livre, alternância das filas, batente selado até a caixa sair, TON de fila longa |
| Estação de montagem | Duas sequências em paralelo | etapas do braço em N3, garra sem sensor (TON), batente liberado pelo bit Montada |
| Compressores, misturador, elevador, portão | Alternância, dosagem, chamadas, fins de curso | ver os comentários de cada exemplo |

Cada ambiente também detecta erros de lógica e mostra **alarmes**, por exemplo:
produto derramado, verdes simultâneos, colisão no cruzamento, motor comandado
nos dois sentidos, portão descendo sobre o veículo ou motor forçando o fim de curso.

## Modelos físicos

A física é integrada com passo fixo, igual ao período de varredura e em tempo
virtual, então os resultados são reproduzíveis. As utilidades comuns ficam em
`ladderide/envs/physics.py`.

| Ambiente | Fenômeno | Modelo | Efeito na lógica |
|---|---|---|---|
| Silo | Esteira | aceleração 2,4 m/s², desaceleração 4 m/s² (inércia) | a caixa passa ~4,5 cm do ponto em que o motor desliga |
| Silo | Fotocélula | feixe físico interrompido pela caixa inteira | o feixe continua interrompido enquanto a caixa cheia sai, e é preciso memorizar "caixa cheia" |
| Silo | Válvula | abre em 0,15 s e fecha em 0,10 s | a vazão não começa nem para no mesmo instante |
| Silo | Vazão | Torricelli: Q ∝ √(nível do silo) | o tempo de enchimento varia com o nível do silo |
| Silo | Queda do produto | atraso de transporte de 0,35 s | o produto ainda cai depois de a válvula fechar, e a caixa termina com 101–107% |
| Silo | Abastecimento | reabastece de 20% a 90% (fora do CLP) | o nível do silo oscila |
| Semáforo | Veículos | IDM (Intelligent Driver Model), 50 km/h, a = 1,5 m/s², b = 2 m/s², T = 1,2 s | aceleração gradual e fila saindo a cada ~2 s |
| Semáforo | Amarelo | segue se precisar de mais de 3,5 m/s² para parar (zona de dilema) | o amarelo e o vermelho geral precisam dar tempo de o cruzamento esvaziar |
| Semáforo | Vermelho repentino | só passa quem fisicamente não consegue parar (mais de 8 m/s²) | a falta de amarelo causa colisões |
| Semáforo | Pedestres | 1,3 m/s (~10 s para atravessar), carros param diante deles | a travessia precisa terminar antes do verde conflitante; há alarme de atropelamento |
| Portão | Folha | rampa de 0,3 s, freio do motor (~1,5% de deslocamento), sobe 8 s e desce 7 s (gravidade) | o portão passa um pouco do fim de curso |
| Portão | Fins de curso | histerese (98/96,5% e 2/3,5%) | um contato não "pisca" na borda |
| Portão | Reversão | inverter acima de 3%/s é falha mecânica | é preciso parar e esperar antes de reabrir |
| Portão | Veículo | batente na altura do teto, com velocidade de impacto | a fotocélula é obrigatória |
| Elevador | Cabine | 0,5 m/s, partida 0,6 m/s², freio 2 m/s² (para em ~6 cm) | o sensor de andar atua 10 cm antes do nível e a cabine para a ~4 cm |
| Elevador | Porta | operador abre em 1,5 s; o fechador (mola) fecha em 2,5 s; sem sensor de porta | é preciso esperar com temporizador antes de mover a cabine |
| Elevador | Segurança | andar com porta aberta, abrir fora do andar, passar do último andar, chamada esperando mais de 60 s | alarmes de lógica |
| Garrafas | Esteiras | inércia (garrafas ~4,5 px, caixas ~6 px de deslocamento) | sensores com janela para a parada |
| Garrafas | Enchimento | 0,25 L/s com válvula de 0,10/0,08 s; 0,5 L ou 1 L | o tempo de enchimento depende do tamanho; a inspeção aceita 92–103% |
| Garrafas | Rejeitor e caixas | cilindro de 0,2 s; 6 garrafas por caixa | rejeitar no ponto certo e contar com CTU |
| Compressores | Reservatório | pressão integra (vazão dos compressores − consumo √p); válvula de segurança em 140 psi | ciclo de 100 a 120 psi depende do consumo |
| Compressores | Motores | rampa de 1,5 s; mais de 6 partidas/min desarma o térmico, que rearma em 30 s | alternar o líder, escalonar partidas e assumir na falha |
| Compressores | Condensado | acumula com o ar comprimido; o dreno remove água e perde ar | dreno temporizado |
| Misturador | Bombas e fluxômetros | 4 L/s, rampa de 0,5 s, 1 pulso por litro | dosagem por contador; a bomba ainda gira um pouco ao desligar |
| Misturador | Temperatura | aquecimento proporcional ao volume, perdas para o ambiente, termostato 40/39 °C | aquecer só com agitação e resistência coberta |
| Misturador | Lote | receita 40 L A + 30 L B (±3%), 4 s de agitação para homogeneizar | lote fora da receita, frio ou mal misturado é rejeitado |

Os programas de `examples/ambientes/` já tratam esses efeitos: memória de
caixa cheia no silo, tempos de engenharia de tráfego e janela de pedestres no
semáforo, espera de 0,6 s antes de reabrir o portão, porta temporizada no elevador, enchimento por RTO na linha de garrafas, líder alternado no ar comprimido e dosagem por contador no misturador.

## Uso na IDE

1. No painel **Ambiente** (Ctrl+E, embaixo do diagrama), escolha o processo. A escolha fica salva no projeto.
2. **Criar símbolos no projeto** adiciona os nomes dos pontos de E/S (Start, Valvula...).
3. **Abrir programa exemplo** carrega uma solução pronta.
4. Simule (F5) e clique nos botões desenhados no ambiente. As entradas que pertencem
   ao ambiente ficam bloqueadas no painel de E/S; as demais continuam disponíveis.

Botões marcados como **NF** (Stop, Parar) leem 1 quando soltos, como na indústria.
Por isso o programa usa contato **NA** (XIC) para eles.

## Como funciona

```
          a cada varredura (tempo virtual, determinístico)
 ┌──────────────┐  entradas (sensores + botões)  ┌───────────┐
 │  Environment │ ─────────────────────────────▶ │ Simulador │
 │ (física, por │                                │ (LadderVM)│
 │    nomes)    │ ◀───────────────────────────── │           │
 └──────────────┘  saídas Q (step(dt, out))      └───────────┘
        ▲  EnvironmentPlant traduz nomes ⇄ bits (I0.x / Q0.x)
        │
   EnvironmentPanel / EnvironmentView: desenho genérico (paint) e cliques (controls)
```

- `ladderide/envs/base.py`: `Environment` (contrato), `IOPoint`, `EnvironmentPlant` (nomes ⇄ bits).
- `ladderide/envs/registry.py`: registro (`@register`) e descoberta automática.
- `ladderide/envs/draw.py`: primitivas de desenho (lâmpada, botão, sensor, motor, etiqueta de endereço).
- `ladderide/sim/simulator.py`: protocolo `Plant`. O simulador chama `input_bits()` antes
  e `advance(dt, saídas)` depois de cada varredura.
- `ladderide/ui/env_panel.py`: painel genérico. Ele não conhece nenhum ambiente específico.

Como o processo avança junto com as varreduras, em tempo virtual, a simulação é
reproduzível e pode ser testada sem interface (`desktop/tests/test_envs.py`).

## Criando um ambiente novo

Crie um arquivo em `desktop/src/ladderide/envs/builtin/` (para entrar na IDE) **ou** em
`%USERPROFILE%\.ladderide\ambientes\` (sem alterar a IDE). Ele é carregado
automaticamente na próxima abertura. Um plugin com erro não derruba a IDE: o erro
aparece no painel Ambiente.

```python
from PySide6.QtCore import QPointF, QRectF
from ladderide.envs import BUTTON, Environment, IOPoint, register
from ladderide.envs import draw


@register
class Tanque(Environment):
    id = "tanque"                      # unico; salvo no projeto
    name = "Tanque com bomba"
    description = "Ligue a bomba ate o sensor de nivel alto e desligue no nivel baixo."
    example = ""                       # opcional: projeto em examples/
    size = (640, 420)                  # coordenadas usadas em paint()/controls()
    inputs = [IOPoint("LIGA", "I0.0", "Liga", "Botao liga", BUTTON),
              IOPoint("ALTO", "I0.1", "Nivel_Alto"),
              IOPoint("BAIXO", "I0.2", "Nivel_Baixo")]
    outputs = [IOPoint("BOMBA", "Q0.0", "Bomba")]

    def reset(self):                   # estado inicial (partida a frio)
        self.nivel = 10.0

    def step(self, dt_ms, out):        # fisica: out = {"BOMBA": bool}
        taxa = 8.0 if out["BOMBA"] else -3.0
        self.nivel = min(100.0, max(0.0, self.nivel + taxa * dt_ms / 1000))

    def sensors(self):                 # valor fisico dos sensores (antes de NA/NF)
        return {"ALTO": self.nivel >= 90, "BAIXO": self.nivel <= 20}

    def alarms(self):                  # opcional
        return ["Tanque transbordando"] if self.nivel >= 100 and self.out["BOMBA"] else []

    def controls(self):                # areas clicaveis -> chave da entrada
        return {"LIGA": (20, 20, 120, 28)}

    def paint(self, p):                # QPainter ja escalado para self.size
        draw.push_button(p, QRectF(20, 20, 120, 28), "LIGA I0.0", self.is_pressed("LIGA"), draw.GREEN)
        p.fillRect(QRectF(300, 380 - 3 * self.nivel, 120, 3 * self.nivel), draw.STEEL)
        draw.lamp(p, QPointF(460, 60), 10, self.out["BOMBA"], draw.GREEN)
```

Regras do contrato:

- `kind` das entradas: `sensor` (o processo decide via `sensors()`), `button` (pulsador,
  ativo enquanto pressionado) ou `switch` (chave com trava). `normally_closed=True` inverte
  o nível lido pelo CLP.
- Controles que não são entradas (por exemplo, colocar um veículo) usam `on_control()`.
- `step()` recebe `dt_ms` em tempo virtual. Não use relógio real nem números
  aleatórios sem semente (`random.Random(semente)`), para a simulação continuar reproduzível.
- Escreva um teste de malha fechada em `desktop/tests/test_envs.py`: o programa
  exemplo deve rodar sem alarmes, e uma lógica errada deve disparar o alarme esperado.
