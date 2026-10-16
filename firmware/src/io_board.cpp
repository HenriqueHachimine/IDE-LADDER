#include "io_board.h"

#include <Arduino.h>

#include "board_config.h"

static uint16_t last_inputs;

static void latch_pulse(void)
{
    /* RCK do 595 copia o registrador para as saidas na borda de subida;
     * SH/LD do 165 em 0 captura as entradas paralelas. */
    digitalWrite(PIN_SR_LATCH, LOW);
    delayMicroseconds(1);
    digitalWrite(PIN_SR_LATCH, HIGH);
}

static uint16_t shift(uint16_t outputs)
{
    uint16_t inputs = 0;
    for (uint8_t i = 0; i < 8; i++) {
        bool level = digitalRead(PIN_165_QH);
        bool active = INPUT_ACTIVE_LOW ? !level : level;
        if (active)
            inputs |= (uint16_t)(1u << IN_MAP[i]);
        bool on = (outputs >> OUT_MAP[i]) & 1u;
        digitalWrite(PIN_595_SER, (RELAY_ACTIVE_LOW ? !on : on) ? HIGH : LOW);
        digitalWrite(PIN_SR_CLK, HIGH);
        delayMicroseconds(1);
        digitalWrite(PIN_SR_CLK, LOW);
    }
    return inputs;
}

void io_board_begin(void)
{
    pinMode(PIN_595_OE, OUTPUT);
    digitalWrite(PIN_595_OE, HIGH); /* saidas do 595 em alta impedancia */
    pinMode(PIN_SR_LATCH, OUTPUT);
    pinMode(PIN_SR_CLK, OUTPUT);
    pinMode(PIN_595_SER, OUTPUT);
    pinMode(PIN_165_QH, INPUT);
    digitalWrite(PIN_SR_CLK, LOW);
    digitalWrite(PIN_SR_LATCH, HIGH);
    shift(0);
    latch_pulse();
    digitalWrite(PIN_595_OE, LOW); /* so agora os reles recebem comando (todos desligados) */
}

uint16_t io_board_transfer(uint16_t outputs)
{
    /* 1o pulso: captura as entradas atuais no 165 (o 595 relatcha o mesmo
     * conteudo da varredura anterior, sem alterar os reles). */
    latch_pulse();
    uint16_t inputs = shift(outputs);
    latch_pulse(); /* aplica as novas saidas */
    last_inputs = inputs;
    return inputs;
}

uint16_t io_board_last_inputs(void)
{
    return last_inputs;
}
