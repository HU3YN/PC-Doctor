/*
 * The parts of the SHT31 temperature/humidity sensor driver that are pure
 * arithmetic: the CRC-8 the sensor puts after each value, and turning its raw
 * 16-bit numbers into degrees and percent. The I2C traffic itself is in
 * src/main.cpp; keeping the maths here (no Arduino includes) lets it be unit
 * tested on a PC.
 *
 * What the sensor sends back after a measurement command - 6 bytes:
 *
 *   byte 0  temperature, high byte
 *   byte 1  temperature, low byte
 *   byte 2  CRC-8 of bytes 0-1
 *   byte 3  humidity, high byte
 *   byte 4  humidity, low byte
 *   byte 5  CRC-8 of bytes 3-4
 *
 * Source: Sensirion SHT3x-DIS datasheet, sections 4.4 (single shot mode),
 * 4.12 (checksum) and 4.13 (conversion of signal output).
 */
#ifndef PCD_SHT31_H
#define PCD_SHT31_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* I2C address with the ADDR pin low (the default on breakout boards), and
 * with it pulled high. */
#define PCD_SHT31_ADDR_DEFAULT 0x44u
#define PCD_SHT31_ADDR_ALT 0x45u

/* Single-shot measurement, high repeatability, clock stretching off. The
 * sensor does not hold the bus while it measures; we wait and then read. */
#define PCD_SHT31_CMD_MEASURE_MSB 0x24u
#define PCD_SHT31_CMD_MEASURE_LSB 0x00u

/* Soft reset, so a sensor left in periodic mode by other code starts clean. */
#define PCD_SHT31_CMD_RESET_MSB 0x30u
#define PCD_SHT31_CMD_RESET_LSB 0xA2u

/* A high-repeatability measurement takes at most 15 ms (datasheet table 4).
 * 20 ms leaves a margin. */
#define PCD_SHT31_MEASURE_WAIT_MS 20u

#define PCD_SHT31_FRAME_SIZE 6u

typedef enum {
    PCD_SHT31_OK = 0,
    PCD_SHT31_BAD_ARG,
    PCD_SHT31_BAD_TEMP_CRC,
    PCD_SHT31_BAD_HUMIDITY_CRC
} pcd_sht31_result_t;

/*
 * Sensirion CRC-8: polynomial 0x31 (x^8 + x^5 + x^4 + 1), start value 0xFF,
 * no reflection, no final XOR. Datasheet example: crc8({0xBE, 0xEF}) == 0x92.
 */
uint8_t pcd_sht31_crc8(const uint8_t *data, size_t len);

/* T [degC] = -45 + 175 * raw / 65535, returned in 0.01 degC, rounded to
 * nearest. Range: -4500 (raw 0) to 13000 (raw 65535). */
int16_t pcd_sht31_temp_centi_c(uint16_t raw);

/* RH [%] = 100 * raw / 65535, returned in 0.01 %, rounded to nearest.
 * Range: 0 to 10000. */
uint16_t pcd_sht31_humidity_centi_pct(uint16_t raw);

/*
 * Checks BOTH checksums of a 6-byte frame, then converts. Nothing is written
 * to the outputs unless both checksums are right: a reading with one bad half
 * came off a noisy bus and is not worth trusting at all.
 */
pcd_sht31_result_t pcd_sht31_parse_frame(const uint8_t *frame, size_t len, int16_t *temp_centi_c,
                                         uint16_t *humidity_centi_pct);

#ifdef __cplusplus
}
#endif

#endif /* PCD_SHT31_H */
