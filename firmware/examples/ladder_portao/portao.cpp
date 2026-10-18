// Portao de garagem - codigo C++ gerado pela LadderIDE 1.0.0 a partir do diagrama LADDER
//
// Gerado direto do diagrama (nao precisa compilar antes). O ESP32 executa o
// mesmo programa compilado em bytecode (imagem LDRB) pelo interpretador do
// firmware; este arquivo mostra a mesma logica em C++: mesma ordem das redes e
// mesma semantica de temporizadores e contadores.
// Situacao: 0 erro(s), 0 aviso(s).

#ifdef ARDUINO
#include <Arduino.h>
#endif
#include <stdint.h>

// ---------------------------------------------------------------------------
// Runtime minimo: mesma semantica do interpretador do ESP32
// (docs/ladder-specification.md). Tempos em milissegundos.
// ---------------------------------------------------------------------------
struct Timer {
    uint32_t pre;                     // preset (ms)
    uint32_t acc;                     // tempo acumulado (ms)
    bool en, tt, dn;                  // habilitado, temporizando, concluido
};

struct Counter {
    int32_t pre;                      // preset
    bool down;                        // true = CTD (decrescente)
    int32_t acc;                      // valor atual
    bool dn, ov, un, prev;            // concluido, estouro, subfluxo, memoria de borda
};

static inline uint32_t sat_add(uint32_t acc, uint32_t dt, uint32_t pre) {
    return dt >= pre - acc ? pre : acc + dt;
}

// Retardo na energizacao: DN liga quando a entrada fica ligada por PRE ms.
static inline void TON(Timer &t, bool in, uint32_t dt) {
    bool prev = t.en;
    t.en = in;
    if (in) {
        if (prev && !t.dn) t.acc = sat_add(t.acc, dt, t.pre);
        t.dn = t.acc >= t.pre;
        t.tt = !t.dn;
    } else {
        t.acc = 0; t.dn = false; t.tt = false;
    }
}

// Retardo na desenergizacao: DN desliga PRE ms depois que a entrada desliga.
static inline void TOF(Timer &t, bool in, uint32_t dt) {
    bool prev = t.en;
    t.en = in;
    if (in) {
        t.acc = 0; t.dn = true; t.tt = false;
    } else if (t.dn) {
        if (!prev) t.acc = sat_add(t.acc, dt, t.pre);
        if (t.acc >= t.pre) { t.dn = false; t.tt = false; }
        else t.tt = true;
    } else {
        t.tt = false;
    }
}

// Retentivo: acumula enquanto a entrada esta ligada e so zera com RES.
static inline void RTO(Timer &t, bool in, uint32_t dt) {
    bool prev = t.en;
    t.en = in;
    if (in) {
        if (prev && !t.dn) t.acc = sat_add(t.acc, dt, t.pre);
        t.dn = t.acc >= t.pre;
        t.tt = !t.dn;
    } else {
        t.tt = false;
    }
}

static inline void counter_reset(Counter &c) {
    c.acc = c.down ? c.pre : 0;
    c.dn = c.down ? c.acc <= 0 : c.acc >= c.pre;
    c.ov = false; c.un = false;
}

// Contador crescente: soma 1 na borda de subida da entrada.
static inline void CTU(Counter &c, bool in) {
    bool edge = in && !c.prev;
    c.prev = in;
    if (edge) { if (c.acc == INT32_MAX) c.ov = true; else c.acc++; }
    c.dn = c.acc >= c.pre;
}

// Contador decrescente: subtrai 1 na borda de subida da entrada.
static inline void CTD(Counter &c, bool in) {
    bool edge = in && !c.prev;
    c.prev = in;
    if (edge) { if (c.acc == INT32_MIN) c.un = true; else c.acc--; }
    c.dn = c.acc <= 0;
}

static inline void RES(Timer &t) { t.acc = 0; t.en = false; t.tt = false; t.dn = false; }
static inline void RES(Counter &c) { counter_reset(c); }

// ---------------------------------------------------------------------------
// Imagem de E/S: 8 entradas, 8 saidas (reles), 64 memorias
// ---------------------------------------------------------------------------
static bool I[8];  // entradas (lidas no inicio da varredura)
static bool Q[8];  // saidas (aplicadas no fim da varredura)
static bool M[64];  // memorias internas
static Timer T[1] = {{600u, 0u, false, false, false}};  // presets em ms
static bool FIRST_SCAN = true;       // 1 so na primeira varredura
static bool CLOCK_1S = true;         // relogio de 1 s (500 ms ligado)
static uint32_t clock_phase = 0;

// Variaveis (nome do simbolo -> endereco do CLP)
static bool &Abrir = I[0];                // I0.0 - Botao ABRIR (NA)
static bool &Fechar = I[1];               // I0.1 - Botao FECHAR (NA)
static bool &Parar = I[2];                // I0.2 - Botao PARAR (NF: le 1 quando solto)
static bool &Fim_Curso_Aberto = I[3];     // I0.3 - LS1: portao totalmente aberto
static bool &Fim_Curso_Fechado = I[4];    // I0.4 - LS2: portao totalmente fechado
static bool &Fotocelula = I[5];           // I0.5 - Veiculo/obstaculo sob o portao
static bool &Motor_Sobe = Q[0];           // Q0.0 - Motor no sentido de abrir
static bool &Motor_Desce = Q[1];          // Q0.1 - Motor no sentido de fechar
static bool &Lampada_Entreaberto = Q[2];  // Q0.2 - Lampada ENTREABERTO
static bool &Lampada_Aberto = Q[3];       // Q0.3 - Lampada ABERTO
static bool &Lampada_Fechado = Q[4];      // Q0.4 - Lampada FECHADO
static Timer &Espera_Reversao = T[0];     // T0 TON 600 ms - 0,6 s parado antes de reabrir

// Partida a frio (STOP -> RUN): zera memorias, saidas, temporizadores e contadores.
void plc_start() {
    for (int k = 0; k < 8; k++) I[k] = false;
    for (int k = 0; k < 8; k++) Q[k] = false;
    for (int k = 0; k < 64; k++) M[k] = false;
    for (int k = 0; k < 1; k++) RES(T[k]);
    FIRST_SCAN = true;
    clock_phase = 0;
}

// Uma varredura: le as entradas, executa as redes em ordem e devolve as saidas.
// dt_ms = tempo desde a varredura anterior (ignorado na primeira).
uint16_t plc_scan(uint16_t inputs, uint32_t dt_ms) {
    uint32_t dt = FIRST_SCAN ? 0 : dt_ms;
    if (!FIRST_SCAN) clock_phase = (clock_phase + dt % 1000u) % 1000u;
    CLOCK_1S = clock_phase < 500u;
    for (int k = 0; k < 8; k++) I[k] = (inputs >> k) & 1u;

    // ===== Rede 0 - Abrir (selo); reabre sozinho depois da espera da fotocelula =====
    Motor_Sobe = (Abrir || Motor_Sobe || Espera_Reversao.dn) && Parar && !Fim_Curso_Aberto && !Motor_Desce;

    // ===== Rede 1 - Fechar (selo) com intertravamento; a fotocelula para o motor =====
    Motor_Desce = (Fechar || Motor_Desce) && Parar && !Fim_Curso_Fechado && !Motor_Sobe && !Fotocelula;

    // ===== Rede 2 - Veiculo detectado: espera o portao parar antes de reabrir =====
    TON(Espera_Reversao, Fotocelula && !Fim_Curso_Aberto && !Motor_Desce && !Motor_Sobe, dt);

    // ===== Rede 3 - Sinalizacao =====
    Lampada_Entreaberto = !Fim_Curso_Aberto && !Fim_Curso_Fechado;

    // ===== Rede 4 =====
    Lampada_Aberto = Fim_Curso_Aberto;

    // ===== Rede 5 =====
    Lampada_Fechado = Fim_Curso_Fechado;

    FIRST_SCAN = false;
    uint16_t outputs = 0;
    for (int k = 0; k < 8; k++) if (Q[k]) outputs |= (uint16_t)(1u << k);
    return outputs;
}

#ifdef ARDUINO
// Uso como sketch para a placa (compile junto com firmware/src/io_board.cpp, que
// faz a leitura das entradas e o acionamento dos reles). Exemplo nao validado
// na placa: o caminho oficial e transferir o programa pela IDE.
#include "io_board.h"

static const uint32_t SCAN_PERIOD_MS = 10;

void setup() {
    io_board_begin();
    plc_start();
}

void loop() {
    static uint32_t last = millis();
    static uint16_t outputs = 0;
    uint32_t now = millis();
    if (now - last < SCAN_PERIOD_MS) return;
    uint32_t dt = now - last;
    last = now;
    uint16_t inputs = io_board_transfer(outputs);  // aplica saidas e le entradas
    outputs = plc_scan(inputs, dt);
}
#endif
