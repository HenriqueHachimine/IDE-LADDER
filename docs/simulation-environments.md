# Ambientes de simulação

Os ambientes são processos físicos animados (silo, semáforo, portão...)
controlados pelo programa LADDER durante a simulação offline. Eles são
**plugins**: o simulador e a interface conhecem apenas um contrato genérico,
e cada ambiente fica em um arquivo independente.

## Ambientes incluídos

| Ambiente | Entradas | Saídas | Exemplo |
|---|---|---|---|
| **Silo de envase** (`silo`) | I0.0 Start, I0.1 Stop (NF), I0.2 sensor de presença, I0.3 sensor de nível | Q0.0 motor da esteira, Q0.1 válvula, Q0.2 RUN, Q0.3 FILL, Q0.4 FULL | `examples/ambientes/silo.ladproj` |
| **Semáforo de cruzamento** (`semaforo`) | I0.0/I0.1 botões de pedestre, I0.2/I0.3 sensores de carro | Q0.0–Q0.2 vermelho/amarelo/verde NS, Q0.3 pedestre NS, Q0.4–Q0.6 vermelho/amarelo/verde LO, Q0.7 pedestre LO | `examples/ambientes/semaforo.ladproj` |
| **Portão de garagem** (`portao`) | I0.0 Abrir, I0.1 Fechar, I0.2 Parar (NF), I0.3 LS1 aberto, I0.4 LS2 fechado, I0.5 fotocélula | Q0.0 sobe, Q0.1 desce, Q0.2 entreaberto, Q0.3 aberto, Q0.4 fechado | `examples/ambientes/portao.ladproj` |

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

Os programas de `examples/ambientes/` já tratam esses efeitos: memória de
caixa cheia no silo, tempos de engenharia de tráfego e janela de pedestres no
semáforo, e espera de 0,6 s antes de reabrir o portão.

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
