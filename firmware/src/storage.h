#ifndef STORAGE_H
#define STORAGE_H

#include <stddef.h>
#include <stdint.h>

/* Programa em LittleFS. Gravacao atomica: /prog.new e renomeado sobre /prog.bin;
 * uma queda de energia no meio preserva o programa anterior. */
bool storage_begin(void);
int storage_load(uint8_t *buf, size_t cap, size_t *len); /* 0 ok, 1 vazio, <0 erro */
int storage_save(const uint8_t *buf, size_t len);        /* 0 ok */

#endif /* STORAGE_H */
