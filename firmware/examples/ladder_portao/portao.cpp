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
// Uso como sketch para a placa: Dispositivo > Gravar C++ na placa (ESP32, Arduino UNO ou
// Mega) compila com o io_board da placa escolhida e grava pela USB. Substitui o
// firmware do CLP: para voltar a transferir pela IDE, grave o firmware de novo.
// Monitor serial a 115200 bit/s: mostra cada entrada, saida, temporizador e
// contador que muda. Comandos: s = estado completo, h = ajuda.
#include "io_board.h"

// Impressao no monitor serial. No Arduino UNO/Mega (AVR) o Serial nao tem printf e a
// RAM e pequena (2 KB no UNO): os textos ficam na flash (PSTR/F) e sao formatados aqui.
#if defined(ARDUINO_ARCH_AVR)
#include <stdarg.h>
static void plc_printf_P(const char *fmt, ...) {
    char buf[96];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf_P(buf, sizeof buf, fmt, ap);
    va_end(ap);
    Serial.print(buf);
}
#define PLC_PRINTF(fmt, ...) plc_printf_P(PSTR(fmt), ##__VA_ARGS__)
#define PLC_TEXT(s) F(s)
#else
#define PLC_PRINTF(...) Serial.printf(__VA_ARGS__)
#define PLC_TEXT(s) (s)
#endif

static const uint32_t SCAN_PERIOD_MS = 10;

// Nomes mostrados no monitor serial (endereco e simbolo)
static const char *const IN_LABEL[8] = {"I0.0 Abrir", "I0.1 Fechar", "I0.2 Parar", "I0.3 Fim_Curso_Aberto", "I0.4 Fim_Curso_Fechado", "I0.5 Fotocelula", "I0.6", "I0.7"};
static const char *const OUT_LABEL[8] = {"Q0.0 Motor_Sobe", "Q0.1 Motor_Desce", "Q0.2 Lampada_Entreaberto", "Q0.3 Lampada_Aberto", "Q0.4 Lampada_Fechado", "Q0.5", "Q0.6", "Q0.7"};
static const char *const TIMER_LABEL[1] = {"T0 Espera_Reversao"};

static void stamp() { PLC_PRINTF("[%8lu ms] ", (unsigned long)millis()); }

static void print_help() {
    Serial.println();
    Serial.println(PLC_TEXT("=== Portao de garagem: programa LADDER rodando no ESP32 ==="));
    Serial.println(PLC_TEXT("6 rede(s), varredura a cada 10 ms. Entradas, saidas e temporizadores:"));
    Serial.println(PLC_TEXT("  I0.0 Abrir                Botao ABRIR (NA)"));
    Serial.println(PLC_TEXT("  I0.1 Fechar               Botao FECHAR (NA)"));
    Serial.println(PLC_TEXT("  I0.2 Parar                Botao PARAR (NF: le 1 quando solto)"));
    Serial.println(PLC_TEXT("  I0.3 Fim_Curso_Aberto     LS1: portao totalmente aberto"));
    Serial.println(PLC_TEXT("  I0.4 Fim_Curso_Fechado    LS2: portao totalmente fechado"));
    Serial.println(PLC_TEXT("  I0.5 Fotocelula           Veiculo/obstaculo sob o portao"));
    Serial.println(PLC_TEXT("  Q0.0 Motor_Sobe           Motor no sentido de abrir"));
    Serial.println(PLC_TEXT("  Q0.1 Motor_Desce          Motor no sentido de fechar"));
    Serial.println(PLC_TEXT("  Q0.2 Lampada_Entreaberto  Lampada ENTREABERTO"));
    Serial.println(PLC_TEXT("  Q0.3 Lampada_Aberto       Lampada ABERTO"));
    Serial.println(PLC_TEXT("  Q0.4 Lampada_Fechado      Lampada FECHADO"));
    Serial.println(PLC_TEXT("  T0 Espera_Reversao        TON 600 ms"));
    Serial.println(PLC_TEXT("Cada mudanca aparece aqui. Comandos: s = estado completo | h = ajuda"));
}

static void print_state(uint16_t inputs, uint16_t outputs) {
    stamp();
    Serial.println(PLC_TEXT("estado atual:"));
    for (int k = 0; k < 8; k++)
        PLC_PRINTF("  %-24s  %s\n", IN_LABEL[k], (inputs >> k) & 1u ? "1" : "0");
    for (int k = 0; k < 8; k++)
        PLC_PRINTF("  %-24s  %s\n", OUT_LABEL[k], (outputs >> k) & 1u ? "1 (rele ligado)" : "0");
    PLC_PRINTF("  %-24s  %lu/%lu ms%s\n", TIMER_LABEL[0], (unsigned long)T[0].acc, (unsigned long)T[0].pre, T[0].dn ? " DN" : "");
}

// Compara com a varredura anterior e escreve o que mudou: entradas (causa),
// temporizadores e contadores, e por fim as saidas (efeito).
static void report_changes(uint16_t inputs, uint16_t outputs, bool quiet) {
    static uint16_t last_in = 0, last_out = 0;
    static bool last_tt[1], last_dn[1];
    for (int k = 0; k < 8; k++) {
        bool on = (inputs >> k) & 1u;
        if (!quiet && on != (bool)((last_in >> k) & 1u)) {
            stamp();
            PLC_PRINTF("entrada %s %s\n", IN_LABEL[k], on ? "LIGOU" : "desligou");
        }
    }
    if (!quiet && T[0].tt && !last_tt[0]) {
        stamp();
        PLC_PRINTF("temporizador %s comecou a contar (%lu ms)\n", TIMER_LABEL[0], (unsigned long)T[0].pre);
    }
    if (!quiet && T[0].dn != last_dn[0]) {
        stamp();
        PLC_PRINTF("temporizador %s: DN %s\n", TIMER_LABEL[0], T[0].dn ? "LIGOU" : "desligou");
    }
    last_tt[0] = T[0].tt;
    last_dn[0] = T[0].dn;
    for (int k = 0; k < 8; k++) {
        bool on = (outputs >> k) & 1u;
        if (!quiet && on != (bool)((last_out >> k) & 1u)) {
            stamp();
            PLC_PRINTF("saida   %s %s\n", OUT_LABEL[k], on ? "LIGOU (rele energizado)" : "desligou");
        }
    }
    last_in = inputs;
    last_out = outputs;
}

void setup() {
    io_board_begin();
    Serial.begin(115200);
    delay(300);
    plc_start();
    print_help();
}

void loop() {
    static uint32_t last = millis();
    static uint16_t inputs = 0, outputs = 0;
    static bool started = false;
    while (Serial.available() > 0) {
        int ch = Serial.read();
        if (ch == 's') print_state(inputs, outputs);
        else if (ch == 'h' || ch == '?') print_help();
    }
    uint32_t now = millis();
    if (now - last < SCAN_PERIOD_MS) return;
    uint32_t dt = now - last;
    last = now;
    inputs = io_board_transfer(outputs);  // aplica saidas e le entradas
    outputs = plc_scan(inputs, dt);
    report_changes(inputs, outputs, !started);
    if (!started) print_state(inputs, outputs);  // estado depois da primeira varredura
    started = true;
}
#endif
