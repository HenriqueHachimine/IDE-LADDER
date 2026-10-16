#ifndef MODBUS_RTU_H
#define MODBUS_RTU_H

#include <stddef.h>
#include <stdint.h>

#include "plc_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Escravo Modbus RTU SOMENTE LEITURA para supervisorios (RS-485).
 *   FC01 coils           0..n_outputs-1  -> saidas logicas Q
 *   FC02 discrete inputs 0..n_inputs-1   -> entradas I
 *   FC04 input registers 0 estado, 1-2 contagem de varreduras (u32, palavra alta primeiro),
 *                        100+2n ACC do temporizador n (u32), 200+2n ACC do contador n (i32)
 * Demais funcoes: excecao 01. A transferencia de programas NAO usa Modbus. */

typedef struct {
    uint8_t addr;
    uint32_t t35_us;          /* silencio que delimita quadros (3,5 caracteres) */
    uint64_t last_byte_us;
    uint16_t len;
    uint8_t overflow;
    uint8_t buf[256];
} mb_rtu_t;

void mb_init(mb_rtu_t *mb, uint8_t addr, uint32_t baud);
void mb_rx_byte(mb_rtu_t *mb, uint8_t byte, uint64_t now_us);
/* Se um quadro terminou (silencio >= t3,5), processa e escreve a resposta em out.
 * Retorna o tamanho da resposta (0 = nada a enviar). */
size_t mb_poll(mb_rtu_t *mb, uint64_t now_us, const plc_t *plc, uint8_t *out, size_t cap);
/* Processa um quadro completo (exposto para testes). */
size_t mb_process(uint8_t addr, const uint8_t *req, size_t len, const plc_t *plc, uint8_t *out, size_t cap);

#ifdef __cplusplus
}
#endif

#endif /* MODBUS_RTU_H */
