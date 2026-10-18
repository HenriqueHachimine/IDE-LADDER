/* Arduino.h minimo para rodar os exemplos da placa no PC (simulador da IDE).
 *
 * Implementa so o que os exemplos usam: pinos digitais, tempo, Serial. Os
 * pinos dos registradores de deslocamento sao ligados a um 74HC595 e a um
 * 74HC165 simulados no nivel de clock/latch (arduino_sim.cpp), com a
 * permutacao e a polaridade de board_config.h. Nao e o core do ESP32:
 * Wi-Fi, FreeRTOS, interrupcoes e perifericos nao existem aqui.
 */
#ifndef ARDUINO_SIM_ARDUINO_H
#define ARDUINO_SIM_ARDUINO_H

#include <math.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HIGH 0x1
#define LOW 0x0
#define INPUT 0x01
#define OUTPUT 0x03
#define INPUT_PULLUP 0x05
#define INPUT_PULLDOWN 0x09
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2
#define SERIAL_8N1 0x800001c

typedef bool boolean;
typedef uint8_t byte;

void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);
int digitalRead(uint8_t pin);
unsigned long millis(void);
unsigned long micros(void);
void delay(unsigned long ms);
void delayMicroseconds(unsigned int us);
void yield(void);

class HardwareSerial {
public:
    explicit HardwareSerial(int index) : index_(index) {}
    void begin(unsigned long baud, uint32_t config = SERIAL_8N1, int8_t rx = -1, int8_t tx = -1);
    void end() {}
    void setRxBufferSize(size_t) {}
    void setDebugOutput(bool) {}
    void setTimeout(unsigned long ms) { timeout_ = ms; }
    int available();
    int read();
    int peek();
    size_t readBytes(uint8_t *buf, size_t len);
    size_t readBytes(char *buf, size_t len) { return readBytes((uint8_t *)buf, len); }
    void flush() {}
    size_t write(uint8_t c) { return write(&c, 1); }
    size_t write(const uint8_t *buf, size_t len);
    size_t write(const char *s) { return write((const uint8_t *)s, strlen(s)); }
    size_t print(const char *s) { return write(s); }
    size_t print(char c) { return write((uint8_t)c); }
    size_t print(int v, int base = DEC) { return print((long)v, base); }
    size_t print(unsigned int v, int base = DEC) { return print((unsigned long)v, base); }
    size_t print(long v, int base = DEC);
    size_t print(unsigned long v, int base = DEC);
    size_t print(long long v, int base = DEC) { return print((long)v, base); }
    size_t print(unsigned long long v, int base = DEC) { return print((unsigned long)v, base); }
    size_t print(double v, int digits = 2);
    size_t println() { return write("\r\n"); }
    template <typename T> size_t println(T v) { size_t n = print(v); return n + println(); }
    template <typename T> size_t println(T v, int fmt) { size_t n = print(v, fmt); return n + println(); }
    size_t printf(const char *fmt, ...) __attribute__((format(printf, 2, 3)));
    operator bool() const { return true; }

private:
    int index_;
    unsigned long timeout_ = 1000;
};

extern HardwareSerial Serial;   /* USB-serial: ligada ao monitor serial da IDE */
extern HardwareSerial Serial2;  /* RS-485: nao conectada no simulador */

void setup(void);
void loop(void);

#endif
