#ifndef PLC_RUNTIME_H
#define PLC_RUNTIME_H

#include <stddef.h>
#include <stdint.h>

#include "ladder_vm.h"
#include "ldp_frame.h"
#include "ldp_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Logica do dispositivo independente de hardware: estados STOP/RUN/
 * PROGRAM_LOADING/FAULT, carga transacional de programas, ciclo de varredura,
 * watchdog e protocolo LDP. O mesmo codigo roda no ESP32 (firmware/src) e no PC
 * (firmware/test/host/virtual_device.c), onde e exercitado pelos testes.
 *
 * Concorrencia: as funcoes nao sao reentrantes. No ESP32 todas as chamadas
 * sao feitas sob o mesmo mutex (ver firmware/src/main.cpp). */

typedef struct {
    uint16_t (*read_inputs)(void *ctx);                    /* mascara logica, bit k = Ik */
    void (*write_outputs)(void *ctx, uint16_t mask);       /* bit k = rele k energizado */
    int (*storage_load)(void *ctx, uint8_t *buf, size_t cap, size_t *len); /* 0 ok, 1 vazio, <0 erro */
    int (*storage_save)(void *ctx, const uint8_t *buf, size_t len);        /* 0 ok; deve ser atomico */
    void (*send)(void *ctx, const uint8_t *data, size_t len);
    uint64_t (*micros)(void *ctx);                          /* relogio monotonico */
    void *ctx;
} plc_hal_t;

typedef struct {
    uint8_t n_inputs;
    uint8_t n_outputs;
    uint16_t scan_period_ms;
    uint32_t watchdog_us;      /* duracao maxima de uma varredura antes de FAULT */
    uint8_t autorun;           /* entra em RUN no boot se houver programa valido */
    uint8_t allow_sim_inputs;  /* aceita SIM_SET_INPUTS (somente dispositivo virtual) */
    const char *fw_version;
    const char *hw_id;
} plc_config_t;

typedef struct {
    plc_hal_t hal;
    plc_config_t cfg;
    uint8_t state;
    uint8_t fault;

    /* programa ativo */
    uint8_t active_buf[LV_MAX_IMAGE_SIZE];
    size_t active_len;
    lv_program_t prog;
    uint8_t has_program;
    lv_vm_t vm;
    uint8_t test_mode;

    /* transferencia */
    uint8_t staging[LV_MAX_IMAGE_SIZE];
    uint32_t load_size;
    uint32_t load_crc;
    uint32_t load_received;
    uint8_t load_validated;
    uint32_t load_last_ms;

    /* varredura */
    uint8_t run_first;
    uint64_t last_scan_us;
    uint32_t rem_us;
    uint16_t inputs;
    uint16_t q_logical;
    uint16_t q_commanded;
    uint32_t last_exec_us;
    uint32_t max_exec_us;
    uint32_t max_interval_us;
    uint32_t overruns;
    uint64_t boot_us;
    uint16_t sim_inputs;
    uint8_t sim_inputs_active;

    /* protocolo */
    ldp_parser_t parser;
    int last_seq;
    uint8_t last_type;
    size_t last_resp_len;
    uint8_t last_resp[LDP_MAX_PAYLOAD + LDP_OVERHEAD];
    uint8_t payload[LDP_MAX_PAYLOAD];
} plc_t;

void plc_init(plc_t *plc, const plc_hal_t *hal, const plc_config_t *cfg);
/* Uma varredura: le entradas, executa (em RUN), escreve saidas, mede tempos. */
void plc_scan(plc_t *plc);
/* Bytes recebidos do Desktop. Respostas saem por hal.send. */
void plc_rx(plc_t *plc, const uint8_t *data, size_t len);
/* Manutencao periodica (timeout da sessao de carga). */
void plc_poll(plc_t *plc);

uint16_t plc_safe_outputs(const plc_t *plc);
/* Instantaneo do estado (formato de READ_VARS/TEST_SCAN). Retorna o tamanho. */
size_t plc_snapshot(const plc_t *plc, uint8_t *buf, size_t cap);

#ifdef __cplusplus
}
#endif

#endif /* PLC_RUNTIME_H */
