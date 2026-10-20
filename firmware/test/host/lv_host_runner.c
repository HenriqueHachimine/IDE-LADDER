/* Executor da VM C no computador, usado pelos testes de equivalencia.
 *
 *   lv_host_runner run <imagem.ldrb>   le linhas "<dt_ms> <entradas_hex>" da
 *                                      entrada padrao e imprime o estado apos
 *                                      cada varredura (mesmo formato de
 *                                      LadderVM.dump_line() no Desktop).
 *   lv_host_runner crc <hex>           imprime CRC-32 e CRC-16/MODBUS dos bytes.
 *
 * Se a imagem for invalida, imprime "ERR <codigo> <indice>" e sai com 2. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ladder_vm.h"
#include "lv_crc.h"

static uint8_t image[LV_MAX_IMAGE_SIZE + 16];

static void print_bits_hex(const uint8_t *bits, unsigned n)
{
    for (unsigned b = 0; b < n; b += 8) {
        unsigned byte = 0;
        for (unsigned k = 0; k < 8 && b + k < n; k++)
            byte |= (unsigned)(bits[b + k] ? 1u : 0u) << k;
        printf("%02x", byte);
    }
}

static void dump(const lv_vm_t *vm)
{
    const lv_program_t *p = vm->prog;
    printf("S=%lu Q=%04x M=", (unsigned long)vm->scan_count, lv_vm_outputs(vm));
    print_bits_hex(vm->m, p->n_markers);
    printf(" T=");
    for (unsigned k = 0; k < p->n_timers; k++) {
        const lv_timer_t *t = &vm->timers[k];
        printf("%s%lu/%x", k ? "," : "", (unsigned long)t->acc, t->en | t->tt << 1 | t->dn << 2);
    }
    printf(" C=");
    for (unsigned k = 0; k < p->n_counters; k++) {
        const lv_counter_t *c = &vm->counters[k];
        printf("%s%ld/%x", k ? "," : "", (long)c->acc, c->dn | c->ov << 1 | c->un << 2 | c->prev << 3);
    }
    printf(" N=");
    for (unsigned k = 0; k < p->n_words; k++)
        printf("%s%ld", k ? "," : "", (long)vm->n[k]);
    printf(" F=%x", vm->math_ov | vm->math_zero << 1 | vm->math_sign << 2);
    printf(" P=");
    for (unsigned b = 0; b < p->n_instr; b += 8) {
        unsigned byte = 0;
        for (unsigned k = 0; k < 8 && b + k < p->n_instr; k++)
            byte |= (unsigned)lv_vm_power(vm, (uint16_t)(b + k)) << k;
        printf("%02x", byte);
    }
    printf("\n");
}

static int cmd_crc(const char *hex)
{
    static uint8_t buf[4096];
    size_t n = strlen(hex) / 2;
    if (n > sizeof(buf))
        return 1;
    for (size_t k = 0; k < n; k++) {
        unsigned v;
        if (sscanf(hex + 2 * k, "%2x", &v) != 1)
            return 1;
        buf[k] = (uint8_t)v;
    }
    printf("%08lx %04x\n", (unsigned long)lv_crc32(0, buf, n), lv_crc16_modbus(0xFFFF, buf, n));
    return 0;
}

static int cmd_run(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "nao foi possivel abrir %s\n", path);
        return 1;
    }
    size_t len = fread(image, 1, sizeof(image), f);
    fclose(f);

    static lv_program_t prog;
    static lv_vm_t vm;
    int32_t err_index;
    lv_image_error_t err = lv_image_validate(image, len, &prog, &err_index);
    if (err != LV_ERR_OK) {
        printf("ERR %d %ld\n", (int)err, (long)err_index);
        return 2;
    }
    printf("OK\n");
    lv_vm_init(&vm, &prog);

    char line[128];
    while (fgets(line, sizeof(line), stdin)) {
        unsigned long dt, inputs;
        if (sscanf(line, "%lu %lx", &dt, &inputs) != 2)
            continue;
        lv_vm_scan(&vm, (uint16_t)inputs, (uint32_t)dt);
        dump(&vm);
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 3 && strcmp(argv[1], "run") == 0)
        return cmd_run(argv[2]);
    if (argc == 3 && strcmp(argv[1], "crc") == 0)
        return cmd_crc(argv[2]);
    fprintf(stderr, "uso: %s run <imagem> | crc <hex>\n", argv[0]);
    return 1;
}
