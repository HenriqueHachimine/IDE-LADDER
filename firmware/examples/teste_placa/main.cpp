/* Exemplo 1 - Teste da placa ESP32 Relay X8 (sem o CLP).
 *
 * Usa as mesmas rotinas de E/S do firmware (src/io_board.cpp) e a mesma
 * configuracao (src/board_config.h): pinos dos registradores 74HC595/74HC165,
 * polaridade e mapeamento bit -> canal. Serve para conferir a placa antes de
 * gravar o firmware do CLP (docs/hardware-test-procedure.md).
 *
 * Monitor serial a 115200 bit/s (pio device monitor). Comandos:
 *   1..8  liga/desliga o rele OUT1..OUT8 (modo manual)
 *   a     desliga todos os reles
 *   c     sequencia: um rele por vez, 0,5 s cada
 *   m     espelho: cada entrada INk aciona o rele OUTk
 *   s     mostra o estado atual (tabela)
 *   h     ajuda
 *
 * Tudo o que acontece aparece no monitor: cada comando recebido, cada troca de
 * modo, cada entrada que muda e cada rele que liga ou desliga, com o tempo
 * desde a partida.
 *
 * Compilar e gravar (na pasta firmware/):
 *   pio run -e exemplo_teste_placa -t upload --upload-port COM5
 * Para voltar ao firmware do CLP:
 *   pio run -e esp32dev -t upload --upload-port COM5
 */
#include <Arduino.h>

#include "board_config.h"
#include "io_board.h"

enum Mode { MANUAL, CHASE, MIRROR };

static Mode mode = MANUAL;
static uint16_t outputs = 0;
static uint16_t inputs = 0;
static uint16_t last_inputs = 0;
static uint16_t last_outputs = 0;
static uint32_t last_step = 0;
static uint8_t chase_index = 0;

static const char *mode_name(Mode m)
{
    return m == CHASE ? "sequencia" : (m == MIRROR ? "espelho" : "manual");
}

/* "[    1234 ms] " no inicio de cada mensagem */
static void stamp()
{
    Serial.printf("[%8lu ms] ", (unsigned long)millis());
}

static void print_bits(const char *label, uint16_t mask, uint8_t count)
{
    Serial.print(label);
    for (uint8_t k = 0; k < count; k++) {
        Serial.print(' ');
        Serial.print((mask >> k) & 1u ? '1' : '.');
    }
    Serial.println();
}

static void print_state()
{
    stamp();
    Serial.printf("estado - modo %s\n", mode_name(mode));
    Serial.println("           1 2 3 4 5 6 7 8");
    print_bits("  IN       ", inputs, BOARD_INPUTS);
    print_bits("  OUT      ", outputs, BOARD_OUTPUTS);
}

static void print_help()
{
    Serial.println();
    Serial.println("=== Teste da placa " HW_ID " ===");
    Serial.printf("595: SER=%d CLK=%d LATCH=%d /OE=%d | 165: QH=%d | reles ativos em %d, entradas ativas em %d\n",
                  PIN_595_SER, PIN_SR_CLK, PIN_SR_LATCH, PIN_595_OE, PIN_165_QH, RELAY_ACTIVE_LOW ? 0 : 1,
                  INPUT_ACTIVE_LOW ? 0 : 1);
    Serial.println("Comandos:");
    Serial.println("  1..8  liga/desliga o rele OUT1..OUT8 (modo manual)");
    Serial.println("  a     desliga todos os reles");
    Serial.println("  c     sequencia: um rele por vez, 0,5 s cada");
    Serial.println("  m     espelho: cada entrada INk aciona o rele OUTk");
    Serial.println("  s     mostra o estado atual");
    Serial.println("  h     esta ajuda");
    Serial.println("Cada entrada que muda e cada rele que liga ou desliga aparece aqui.");
}

static void set_mode(Mode m, const char *what)
{
    if (mode != m) {
        stamp();
        Serial.printf("modo %s -> %s: %s\n", mode_name(mode), mode_name(m), what);
    }
    mode = m;
}

static void handle_command(char c)
{
    if (c == '\r' || c == '\n' || c == ' ')
        return;
    if (c >= '1' && c <= '8') {
        uint8_t k = (uint8_t)(c - '1');
        set_mode(MANUAL, "os reles so mudam pelos comandos 1..8 e a");
        outputs ^= (uint16_t)(1u << k);
        stamp();
        Serial.printf("comando '%c': OUT%d -> %s\n", c, k + 1, (outputs >> k) & 1u ? "ligar" : "desligar");
    } else if (c == 'a') {
        set_mode(MANUAL, "os reles so mudam pelos comandos 1..8 e a");
        outputs = 0;
        stamp();
        Serial.println("comando 'a': desligar todos os reles");
    } else if (c == 'c') {
        stamp();
        Serial.println("comando 'c': sequencia OUT1 -> OUT8, 0,5 s cada (outro comando interrompe)");
        set_mode(CHASE, "um rele por vez");
        chase_index = 0;
        last_step = millis() - 500;          /* primeiro passo ja na proxima volta */
    } else if (c == 'm') {
        stamp();
        Serial.println("comando 'm': espelho - acione as entradas IN1..IN8 para ver os reles seguirem");
        set_mode(MIRROR, "OUTk = INk a cada varredura");
    } else if (c == 's') {
        print_state();
    } else if (c == 'h' || c == '?') {
        print_help();
    } else {
        stamp();
        Serial.printf("comando '%c' desconhecido (h = ajuda)\n", c);
    }
}

/* Escreve cada entrada e cada rele que mudou desde a ultima varredura */
static void report_changes()
{
    for (uint8_t k = 0; k < BOARD_INPUTS; k++) {
        bool on = (inputs >> k) & 1u;
        if (on != (bool)((last_inputs >> k) & 1u)) {
            stamp();
            Serial.printf("entrada IN%d %s\n", k + 1, on ? "LIGOU" : "desligou");
        }
    }
    for (uint8_t k = 0; k < BOARD_OUTPUTS; k++) {
        bool on = (outputs >> k) & 1u;
        if (on != (bool)((last_outputs >> k) & 1u)) {
            stamp();
            Serial.printf("rele    OUT%d %s\n", k + 1, on ? "LIGOU" : "desligou");
        }
    }
    last_inputs = inputs;
    last_outputs = outputs;
}

void setup()
{
    io_board_begin();                       /* reles desligados antes de qualquer outra coisa */
    Serial.begin(LDP_BAUD);
    delay(300);
    print_help();
    stamp();
    Serial.println("io_board_begin(): reles desligados, saidas do 74HC595 habilitadas");
    inputs = io_board_transfer(outputs);
    last_inputs = inputs;
    last_outputs = outputs;
    print_state();
    stamp();
    Serial.println("pronto - digite um comando");
}

void loop()
{
    while (Serial.available() > 0)
        handle_command((char)Serial.read());

    uint32_t now = millis();
    if (mode == CHASE && now - last_step >= 500) {
        outputs = (uint16_t)(1u << chase_index);
        stamp();
        Serial.printf("sequencia: passo %d de %d\n", chase_index + 1, BOARD_OUTPUTS);
        chase_index = (uint8_t)((chase_index + 1) % BOARD_OUTPUTS);
        last_step = now;
    }

    inputs = io_board_transfer(outputs);    /* aplica as saidas e le as entradas */
    if (mode == MIRROR)
        outputs = inputs;

    report_changes();
    delay(SCAN_PERIOD_MS);
}
