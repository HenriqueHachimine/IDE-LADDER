#ifndef IO_BOARD_H
#define IO_BOARD_H

#include <stdint.h>

/* Acesso as E/S fisicas da placa (74HC595 para reles, 74HC165 para entradas).
 * Separa o mapeamento fisico do modelo logico (bit k = Ik / Qk). */

/* Configura os pinos com /OE desativado, carrega "todos desligados" e so
 * entao habilita as saidas. Chamar antes de qualquer outra inicializacao. */
void io_board_begin(void);

/* Desloca as saidas e le as entradas no mesmo ciclo. Retorna a mascara de entradas. */
uint16_t io_board_transfer(uint16_t outputs);

uint16_t io_board_last_inputs(void);

#endif /* IO_BOARD_H */
