/* Configuracao da placa ESP32 8 reles (referencia multigcs/esp32_relay_x8_modbus_303e32dc812,
 * MIT (c) 2026 Oliver Dippel). Valores marcados com VERIFICAR devem ser
 * confirmados na placa do grupo (docs/hardware-setup.md). Para outra placa,
 * altere somente este arquivo. */
#ifndef BOARD_CONFIG_H
#define BOARD_CONFIG_H

#include <stdint.h>

#define FW_VERSION "1.0.0"
#define HW_ID "esp32-relay-x8-303e32dc812"

/* Registradores de deslocamento */
#define PIN_595_SER 33   /* dados dos reles */
#define PIN_SR_CLK 26    /* clock compartilhado 74HC595 SCK / 74HC165 CLK */
#define PIN_SR_LATCH 25  /* 74HC595 RCK / 74HC165 SH/LD (VERIFICAR) */
#define PIN_595_OE 13    /* /OE ativo em 0 */
#define PIN_165_QH 27    /* saida serial das entradas */

/* Polaridade: no codigo de referencia o bit enviado ao 595 e invertido e a
 * entrada ativa le 0. VERIFICAR com o teste de reles e de entradas. */
#define RELAY_ACTIVE_LOW 1
#define INPUT_ACTIVE_LOW 1

/* Posicao no registrador -> canal logico (Qk / Ik). */
static const uint8_t OUT_MAP[8] = {7, 6, 5, 4, 3, 2, 1, 0};
static const uint8_t IN_MAP[8] = {6, 4, 2, 0, 1, 3, 5, 7};

#define BOARD_INPUTS 8
#define BOARD_OUTPUTS 8

/* RS-485 (Modbus RTU somente leitura) */
#define MODBUS_ENABLED 1
#define PIN_RS485_RX 18
#define PIN_RS485_TX 19
#define PIN_RS485_DE 32
#define MODBUS_ADDRESS 11
#define MODBUS_BAUD 9600

/* CLP */
#define LDP_BAUD 115200
#define SCAN_PERIOD_MS 10
#define SCAN_WATCHDOG_US 50000
#define AUTORUN_ON_BOOT 0      /* 0 = sempre inicia em STOP (padrao seguro) */

#endif /* BOARD_CONFIG_H */
