/*
 * PC Doctor case-sensor packet, version 1.
 *
 * This header is the single description of what goes over UDP. The Python
 * receiver (receiver/case_sensor/packet.py) mirrors it, and a test compiles
 * this C code and checks that both sides produce the same bytes.
 *
 * Plain C, no Arduino includes, so it builds on a PC for unit tests exactly
 * as it builds for the ESP32.
 *
 * One packet is 22 bytes. All multi-byte fields are little-endian (least
 * significant byte first), which is also the ESP32's native order - but the
 * code writes each byte explicitly, so it does not depend on that.
 *
 *   offset  size  field               meaning
 *   ------  ----  ------------------  ------------------------------------------
 *    0      1     magic[0] = 0x50     'P'. With the next byte, lets the receiver
 *    1      1     magic[1] = 0x44     'D'  throw away stray traffic on the port.
 *    2      1     version  = 1        Layout version. Bump it for any change an
 *                                     old receiver would misread.
 *    3      1     flags               bit 0: temperature field is a real reading
 *                                     bit 1: humidity field is a real reading
 *                                     bits 2-7: 0 for now, receivers ignore them
 *    4      4     node_id   (uint32)  Random number picked at each boot. A new
 *                                     id means the node restarted, so the
 *                                     receiver starts its sequence count again.
 *    8      4     seq       (uint32)  0 for the first sample after boot, then +1
 *                                     per sample (wraps to 0 after 4294967295).
 *                                     Counts samples TAKEN, not packets sent, so
 *                                     gaps at the receiver are real lost data.
 *   12      4     uptime_ms (uint32)  Milliseconds since boot when the sample was
 *                                     taken (wraps after about 49.7 days).
 *   16      2     temp      (int16)   Temperature in 0.01 degC. 2345 = 23.45 degC.
 *   18      2     humidity  (uint16)  Relative humidity in 0.01 %. 4567 = 45.67 %.
 *   20      2     crc16     (uint16)  CRC-16/CCITT-FALSE over bytes 0..19.
 *
 * Why a CRC when UDP already has a checksum: the UDP checksum is weak (16-bit
 * ones' complement sum), and the CRC also proves the sender really speaks this
 * protocol rather than just happening to start with "PD".
 */
#ifndef PCD_PROTOCOL_H
#define PCD_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PCD_MAGIC_0 0x50u /* 'P' */
#define PCD_MAGIC_1 0x44u /* 'D' */
#define PCD_PROTOCOL_VERSION 1u

#define PCD_PACKET_SIZE 22u
#define PCD_CRC_OFFSET 20u /* the CRC covers every byte before this offset */

#define PCD_FLAG_TEMP_VALID 0x01u
#define PCD_FLAG_HUMIDITY_VALID 0x02u

/* The receiver's default port. Unassigned by IANA at the time of writing. */
#define PCD_DEFAULT_PORT 9750u

typedef struct {
    uint8_t flags;
    uint32_t node_id;
    uint32_t seq;
    uint32_t uptime_ms;
    int16_t temp_centi_c;
    uint16_t humidity_centi_pct;
} pcd_reading_t;

typedef enum {
    PCD_DECODE_OK = 0,
    PCD_DECODE_BAD_ARG,
    PCD_DECODE_BAD_LENGTH,
    PCD_DECODE_BAD_MAGIC,
    PCD_DECODE_BAD_VERSION,
    PCD_DECODE_BAD_CRC
} pcd_decode_result_t;

/*
 * CRC-16/CCITT-FALSE: polynomial 0x1021, start value 0xFFFF, no bit
 * reflection, no final XOR. The standard check value is
 * crc16("123456789") == 0x29B1.
 */
uint16_t pcd_crc16(const uint8_t *data, size_t len);

/*
 * Writes one packet into buf. Returns PCD_PACKET_SIZE, or 0 if an argument is
 * NULL or buf_len is too small (nothing is written in that case).
 */
size_t pcd_packet_encode(const pcd_reading_t *reading, uint8_t *buf, size_t buf_len);

/*
 * Checks length, magic, version and CRC, in that order, then fills *out.
 * *out is left untouched unless the result is PCD_DECODE_OK. The firmware
 * does not need this; it exists so the tests can round-trip packets.
 */
pcd_decode_result_t pcd_packet_decode(const uint8_t *buf, size_t len, pcd_reading_t *out);

#ifdef __cplusplus
}
#endif

#endif /* PCD_PROTOCOL_H */
