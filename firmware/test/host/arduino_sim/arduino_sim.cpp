/* Execucao de um sketch da placa no PC, para o simulador da IDE.
 *
 * Pinos: os GPIOs de board_config.h ligam um 74HC595 (reles) e um 74HC165
 * (entradas) simulados no nivel dos sinais: o 595 desloca SER na borda de
 * subida de CLK e copia para a saida na borda de subida de LATCH (RCK); /OE
 * em 1 deixa as saidas desabilitadas. O 165 carrega as entradas enquanto
 * SH/LD (= LATCH) esta em 0 e desloca na borda de subida de CLK; QH mostra o
 * bit mais significativo. A ordem dos bits segue OUT_MAP/IN_MAP e a
 * polaridade segue RELAY_ACTIVE_LOW/INPUT_ACTIVE_LOW, como em board_config.h:
 * o simulador confere a sequencia de sinais do codigo, nao a fiacao da placa.
 *
 * Comunicacao com a IDE (linhas de texto):
 *   saida   BOOT                      sketch iniciou
 *           SER <hex>                 bytes escritos na Serial
 *           BRD <reles> <oe> <595> <165> <bordas>  estado da placa quando muda (hex)
 *   entrada SER <hex>                 bytes digitados no monitor serial
 *           IN <hex>                  bornes de entrada acionados (bit k = INk+1)
 */
/* cabecalhos do sistema antes do Arduino.h: windows.h tambem define INPUT e boolean */
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOUSER
#define NOGDI
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <poll.h>
#include <time.h>
#include <unistd.h>
#endif

#include "Arduino.h"

#include "board_config.h"

HardwareSerial Serial(0);
HardwareSerial Serial2(2);

/* ------------------------------------------------------------- tempo */
static uint64_t start_us;

static uint64_t now_us(void)
{
#ifdef _WIN32
    static LARGE_INTEGER freq;
    LARGE_INTEGER t;
    if (!freq.QuadPart)
        QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t);
    return (uint64_t)(t.QuadPart / freq.QuadPart) * 1000000u +
           (uint64_t)(t.QuadPart % freq.QuadPart) * 1000000u / (uint64_t)freq.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
#endif
}

static void sleep_ms(unsigned ms)
{
#ifdef _WIN32
    Sleep(ms);
#else
    struct timespec ts = {(time_t)(ms / 1000u), (long)(ms % 1000u) * 1000000L};
    nanosleep(&ts, NULL);
#endif
}

unsigned long millis(void) { return (unsigned long)((now_us() - start_us) / 1000u); }
unsigned long micros(void) { return (unsigned long)(now_us() - start_us); }
void delayMicroseconds(unsigned int) {}

/* -------------------------------------------------- canal com a IDE */
static uint8_t rx_queue[4096];
static size_t rx_head, rx_tail;
static char line[8192];
static size_t line_len;
static uint16_t terminal_inputs;   /* bornes acionados pelo usuario (bit k = canal k) */
static int stdin_closed;

static int hexval(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static void handle_line(const char *s)
{
    if (strncmp(s, "SER ", 4) == 0) {
        for (const char *p = s + 4; p[0] && p[1]; p += 2) {
            int hi = hexval(p[0]), lo = hexval(p[1]);
            if (hi < 0 || lo < 0)
                break;
            size_t next = (rx_tail + 1) % sizeof(rx_queue);
            if (next != rx_head) {
                rx_queue[rx_tail] = (uint8_t)(hi << 4 | lo);
                rx_tail = next;
            }
        }
    } else if (strncmp(s, "IN ", 3) == 0) {
        terminal_inputs = (uint16_t)strtoul(s + 3, NULL, 16);
    }
}

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

static void poll_ide(void)
{
    uint8_t buf[512];
    int n;
    while ((n = read_available(buf, (int)sizeof(buf))) > 0) {
        for (int i = 0; i < n; i++) {
            char c = (char)buf[i];
            if (c == '\n') {
                line[line_len] = 0;
                handle_line(line);
                line_len = 0;
            } else if (c != '\r' && line_len < sizeof(line) - 1) {
                line[line_len++] = c;
            }
        }
    }
    if (n < 0)
        stdin_closed = 1;   /* a IDE fechou: encerra o sketch */
}

static void emit_serial(const uint8_t *data, size_t len)
{
    static const char digits[] = "0123456789abcdef";
    fputs("SER ", stdout);
    for (size_t i = 0; i < len; i++) {
        fputc(digits[data[i] >> 4], stdout);
        fputc(digits[data[i] & 15], stdout);
    }
    fputc('\n', stdout);
    fflush(stdout);
}

/* ------------------------------------------- registradores simulados */
static uint8_t level[64];          /* nivel escrito em cada GPIO */
static uint8_t sr595, st595;       /* registrador de deslocamento e de saida do 595 */
static uint8_t sr165, load165;     /* registrador do 165 e ultimo valor carregado */
static unsigned long clk_edges;

static uint8_t input_level(int channel)
{
    int active = (terminal_inputs >> channel) & 1;
    return (uint8_t)(INPUT_ACTIVE_LOW ? !active : active);
}

static void load_165(void)
{
    /* posicao i (0 = primeiro bit lido em QH = bit 7) traz o canal IN_MAP[i] */
    uint8_t v = 0;
    for (int i = 0; i < 8; i++)
        v |= (uint8_t)(input_level(IN_MAP[i]) << (7 - i));
    sr165 = load165 = v;
}

static uint16_t relays(void)
{
    if (level[PIN_595_OE])          /* /OE = 1: saidas do 595 desabilitadas */
        return 0;
    uint16_t mask = 0;
    for (int i = 0; i < 8; i++) {   /* o bit deslocado na posicao i termina em Q(7-i) */
        int bit = (st595 >> (7 - i)) & 1;
        int on = RELAY_ACTIVE_LOW ? !bit : bit;
        if (on)
            mask |= (uint16_t)(1u << OUT_MAP[i]);
    }
    return mask;
}

static void emit_board(int force)
{
    static uint16_t last_relays = 0xFFFF;
    static uint8_t last_oe = 0xFF, last_st = 0, last_load = 0;
    uint16_t r = relays();
    uint8_t oe = level[PIN_595_OE];
    if (!force && r == last_relays && oe == last_oe && st595 == last_st && load165 == last_load)
        return;
    last_relays = r;
    last_oe = oe;
    last_st = st595;
    last_load = load165;
    printf("BRD %04x %d %02x %02x %lu\n", r, oe, st595, load165, clk_edges);
    fflush(stdout);
}

void pinMode(uint8_t, uint8_t) {}

void digitalWrite(uint8_t pin, uint8_t value)
{
    if (pin >= sizeof(level))
        return;
    value = value ? 1 : 0;
    uint8_t old = level[pin];
    level[pin] = value;
    if (pin == PIN_SR_CLK && !old && value) {            /* borda de subida do clock */
        clk_edges++;
        sr595 = (uint8_t)(sr595 << 1 | level[PIN_595_SER]);
        if (level[PIN_SR_LATCH])                         /* 165 so desloca com SH/LD = 1 */
            sr165 = (uint8_t)(sr165 << 1);
    }
    if (pin == PIN_SR_LATCH) {
        if (!value)
            load_165();                                  /* SH/LD = 0: carga paralela */
        else if (!old)
            st595 = sr595;                               /* RCK: borda de subida */
    }
}

int digitalRead(uint8_t pin)
{
    if (pin == PIN_165_QH) {
        if (!level[PIN_SR_LATCH])
            load_165();
        return (sr165 >> 7) & 1;
    }
    return pin < sizeof(level) ? level[pin] : 0;
}

void yield(void)
{
    poll_ide();
    emit_board(0);
}

void delay(unsigned long ms)
{
    uint64_t end = now_us() + (uint64_t)ms * 1000u;
    do {
        yield();
        if (stdin_closed)
            exit(0);
        uint64_t now = now_us();
        if (now >= end)
            break;
        uint64_t left = (end - now) / 1000u;
        sleep_ms(left > 2 ? 2 : (unsigned)(left ? left : 1));
    } while (now_us() < end);
}

/* ------------------------------------------------------------ Serial */
void HardwareSerial::begin(unsigned long, uint32_t, int8_t, int8_t) {}

int HardwareSerial::available()
{
    if (index_ != 0)
        return 0;
    poll_ide();
    return (int)((rx_tail + sizeof(rx_queue) - rx_head) % sizeof(rx_queue));
}

int HardwareSerial::read()
{
    if (!available())
        return -1;
    uint8_t c = rx_queue[rx_head];
    rx_head = (rx_head + 1) % sizeof(rx_queue);
    return c;
}

int HardwareSerial::peek()
{
    return available() ? rx_queue[rx_head] : -1;
}

size_t HardwareSerial::readBytes(uint8_t *buf, size_t len)
{
    size_t n = 0;
    unsigned long t0 = millis();
    while (n < len && millis() - t0 < timeout_) {
        int c = read();
        if (c < 0) {
            delay(1);
            continue;
        }
        buf[n++] = (uint8_t)c;
    }
    return n;
}

size_t HardwareSerial::write(const uint8_t *buf, size_t len)
{
    if (index_ == 0 && len)
        emit_serial(buf, len);
    return len;
}

size_t HardwareSerial::print(long v, int base)
{
    if (base == DEC) {
        char s[24];
        snprintf(s, sizeof(s), "%ld", v);
        return write(s);
    }
    return print((unsigned long)v, base);
}

size_t HardwareSerial::print(unsigned long v, int base)
{
    char s[72];
    if (base == DEC) {
        snprintf(s, sizeof(s), "%lu", v);
    } else {
        static const char digits[] = "0123456789ABCDEF";
        char tmp[70];
        int n = 0;
        do {
            tmp[n++] = digits[v % (unsigned)base];
            v /= (unsigned)base;
        } while (v && n < 68);
        for (int i = 0; i < n; i++)
            s[i] = tmp[n - 1 - i];
        s[n] = 0;
    }
    return write(s);
}

size_t HardwareSerial::print(double v, int digits)
{
    char s[64];
    snprintf(s, sizeof(s), "%.*f", digits, v);
    return write(s);
}

size_t HardwareSerial::printf(const char *fmt, ...)
{
    char s[1024];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(s, sizeof(s), fmt, ap);
    va_end(ap);
    if (n < 0)
        return 0;
    return write((const uint8_t *)s, (size_t)n < sizeof(s) ? (size_t)n : sizeof(s) - 1);
}

/* -------------------------------------------------------------- main */
int main(void)
{
#ifdef _WIN32
    _setmode(0, _O_BINARY);
    _setmode(1, _O_BINARY);
#endif
    start_us = now_us();
    level[PIN_595_OE] = 1;          /* pull-up presumido: saidas desabilitadas ate o sketch ligar */
    level[PIN_SR_LATCH] = 1;
    puts("BOOT");
    fflush(stdout);
    setup();
    emit_board(1);
    for (;;) {
        uint64_t t0 = now_us();
        loop();
        yield();
        if (stdin_closed)
            return 0;
        if (now_us() - t0 < 1000)   /* loop vazio: nao ocupar 100% de um nucleo do PC */
            sleep_ms(1);
    }
}
