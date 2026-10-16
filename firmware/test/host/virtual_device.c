/* Dispositivo virtual: o runtime do firmware (plc_core + ladder_vm) rodando no
 * PC. Fala LDP pela entrada/saida padrao (binario), grava o programa em um
 * arquivo (no lugar da flash) e aceita SIM_SET_INPUTS para simular entradas.
 * Usado pelos testes de comunicacao do Desktop e para demonstrar a IDE sem placa.
 *
 *   virtual_device <arquivo_programa> [--autorun] [--watchdog-us N]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plc_runtime.h"

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <poll.h>
#include <time.h>
#include <unistd.h>
#endif

static const char *storage_path;
static uint16_t outputs;
static plc_t plc;

static uint64_t host_micros(void *ctx)
{
    (void)ctx;
#ifdef _WIN32
    static LARGE_INTEGER freq;
    LARGE_INTEGER now;
    if (!freq.QuadPart)
        QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&now);
    return (uint64_t)(now.QuadPart / freq.QuadPart) * 1000000u +
           (uint64_t)(now.QuadPart % freq.QuadPart) * 1000000u / (uint64_t)freq.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
#endif
}

static uint16_t host_read_inputs(void *ctx)
{
    (void)ctx;
    return 0; /* entradas vem de SIM_SET_INPUTS */
}

static void host_write_outputs(void *ctx, uint16_t mask)
{
    (void)ctx;
    outputs = mask;
}

static int host_load(void *ctx, uint8_t *buf, size_t cap, size_t *len)
{
    (void)ctx;
    FILE *f = fopen(storage_path, "rb");
    if (!f)
        return 1;
    *len = fread(buf, 1, cap, f);
    int err = ferror(f);
    fclose(f);
    return err ? -1 : 0;
}

static int host_save(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    char tmp[1024];
    snprintf(tmp, sizeof(tmp), "%s.new", storage_path);
    FILE *f = fopen(tmp, "wb");
    if (!f)
        return -1;
    size_t n = fwrite(buf, 1, len, f);
    if (fclose(f) != 0 || n != len)
        return -1;
#ifdef _WIN32
    return MoveFileExA(tmp, storage_path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) ? 0 : -1;
#else
    return rename(tmp, storage_path);
#endif
}

static void host_send(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    fwrite(data, 1, len, stdout);
    fflush(stdout);
}

/* Le bytes disponiveis sem bloquear. Retorna -1 em fim de arquivo. */
static int read_available(uint8_t *buf, int cap)
{
#ifdef _WIN32
    HANDLE h = GetStdHandle(STD_INPUT_HANDLE);
    DWORD avail = 0;
    if (!PeekNamedPipe(h, NULL, 0, NULL, &avail, NULL))
        return -1;
    if (avail == 0)
        return 0;
    DWORD got = 0;
    if (!ReadFile(h, buf, avail < (DWORD)cap ? avail : (DWORD)cap, &got, NULL))
        return -1;
    return (int)got;
#else
    struct pollfd p = {0, POLLIN, 0};
    if (poll(&p, 1, 0) <= 0)
        return 0;
    ssize_t n = read(0, buf, (size_t)cap);
    return n <= 0 ? -1 : (int)n;
#endif
}

static void sleep_ms(unsigned ms)
{
#ifdef _WIN32
    Sleep(ms);
#else
    usleep(ms * 1000u);
#endif
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "uso: %s <arquivo_programa> [--autorun] [--watchdog-us N]\n", argv[0]);
        return 1;
    }
    storage_path = argv[1];
    plc_config_t cfg = {8, 8, 10, 50000, 0, 1, "virtual-1.0.0", "virtual-esp32-relay-x8"};
    for (int k = 2; k < argc; k++) {
        if (strcmp(argv[k], "--autorun") == 0)
            cfg.autorun = 1;
        else if (strcmp(argv[k], "--watchdog-us") == 0 && k + 1 < argc)
            cfg.watchdog_us = (uint32_t)strtoul(argv[++k], NULL, 10);
    }
#ifdef _WIN32
    _setmode(0, _O_BINARY); /* stdin */
    _setmode(1, _O_BINARY); /* stdout */
#endif
    plc_hal_t hal = {host_read_inputs, host_write_outputs, host_load, host_save, host_send, host_micros, NULL};
    plc_init(&plc, &hal, &cfg);
    fprintf(stderr, "dispositivo virtual pronto (estado %u)\n", plc.state);

    uint64_t period = (uint64_t)cfg.scan_period_ms * 1000u;
    uint64_t next = host_micros(NULL);
    uint8_t buf[1024];
    for (;;) {
        uint64_t now = host_micros(NULL);
        if (now >= next) {
            plc_scan(&plc);
            next += period;
            if (now > next + period)
                next = now + period; /* atrasou demais: realinha sem rajada */
        }
        plc_poll(&plc);
        int n = read_available(buf, sizeof(buf));
        if (n < 0)
            break;
        if (n > 0)
            plc_rx(&plc, buf, (size_t)n);
        else
            sleep_ms(1);
    }
    return 0;
}
