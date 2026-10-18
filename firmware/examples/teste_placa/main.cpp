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
 *   s     mostra o estado atual
 *   h     ajuda
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
static uint16_t last_inputs = 0xFFFF;
static uint16_t last_outputs = 0xFFFF;
static uint32_t last_step = 0;
static uint8_t chase_index = 0;

static const char *mode_name(Mode m)
{
    return m == CHASE ? "sequencia" : (m == MIRROR ? "espelho" : "manual");
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

static void print_state(uint16_t inputs)
{
    Serial.printf("[%8lu ms] modo %s\n", (unsigned long)millis(), mode_name(mode));
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
    Serial.println("1..8 = alterna OUTk | a = todos desligados | c = sequencia | m = espelho | s = estado | h = ajuda");
}

static void handle_command(char c)
{
    if (c >= '1' && c <= '8') {
        mode = MANUAL;
        outputs ^= (uint16_t)(1u << (c - '1'));
    } else if (c == 'a') {
        mode = MANUAL;
        outputs = 0;
    } else if (c == 'c') {
        mode = CHASE;
        chase_index = 0;
        last_step = 0;
    } else if (c == 'm') {
        mode = MIRROR;
    } else if (c == 's') {
        last_inputs = 0xFFFF;               /* forca a impressao */
    } else if (c == 'h' || c == '?') {
        print_help();
    }
}

void setup()
{
    io_board_begin();                       /* reles desligados antes de qualquer outra coisa */
    Serial.begin(LDP_BAUD);
    delay(300);
    print_help();
}

void loop()
{
    while (Serial.available() > 0)
        handle_command((char)Serial.read());

    uint32_t now = millis();
    if (mode == CHASE && now - last_step >= 500) {
        outputs = (uint16_t)(1u << chase_index);
        chase_index = (uint8_t)((chase_index + 1) % BOARD_OUTPUTS);
        last_step = now;
    }

    uint16_t inputs = io_board_transfer(outputs);   /* aplica as saidas e le as entradas */
    if (mode == MIRROR)
        outputs = inputs;

    if (inputs != last_inputs || outputs != last_outputs) {
        print_state(inputs);
        last_inputs = inputs;
        last_outputs = outputs;
    }
    delay(SCAN_PERIOD_MS);
}
