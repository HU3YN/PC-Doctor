/* Packet encode/decode and CRC-16. See pcd_protocol.h for the layout. */
#include "pcd_protocol.h"

uint16_t pcd_crc16(const uint8_t *data, size_t len)
{
    /* Bit-by-bit rather than a 256-entry table: a packet is 20 bytes once a
     * second, so speed is irrelevant and the short version is easy to check
     * against the polynomial by eye. */
    uint16_t crc = 0xFFFFu;
    size_t i;
    int bit;

    if (data == NULL) {
        return crc;
    }
    for (i = 0; i < len; i++) {
        crc = (uint16_t)(crc ^ ((uint16_t)data[i] << 8));
        for (bit = 0; bit < 8; bit++) {
            if (crc & 0x8000u) {
                crc = (uint16_t)((crc << 1) ^ 0x1021u);
            } else {
                crc = (uint16_t)(crc << 1);
            }
        }
    }
    return crc;
}

/* Bytes are written one at a time (instead of copying a struct) so the wire
 * format does not depend on the compiler's padding or the CPU's byte order. */
static void put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
}

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
    p[2] = (uint8_t)((v >> 16) & 0xFFu);
    p[3] = (uint8_t)((v >> 24) & 0xFFu);
}

static uint16_t get_u16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

size_t pcd_packet_encode(const pcd_reading_t *reading, uint8_t *buf, size_t buf_len)
{
    if (reading == NULL || buf == NULL || buf_len < PCD_PACKET_SIZE) {
        return 0;
    }
    buf[0] = PCD_MAGIC_0;
    buf[1] = PCD_MAGIC_1;
    buf[2] = PCD_PROTOCOL_VERSION;
    buf[3] = reading->flags;
    put_u32(&buf[4], reading->node_id);
    put_u32(&buf[8], reading->seq);
    put_u32(&buf[12], reading->uptime_ms);
    /* The cast keeps the two's-complement bit pattern of a negative value. */
    put_u16(&buf[16], (uint16_t)reading->temp_centi_c);
    put_u16(&buf[18], reading->humidity_centi_pct);
    put_u16(&buf[PCD_CRC_OFFSET], pcd_crc16(buf, PCD_CRC_OFFSET));
    return PCD_PACKET_SIZE;
}

pcd_decode_result_t pcd_packet_decode(const uint8_t *buf, size_t len, pcd_reading_t *out)
{
    uint16_t raw_temp;

    if (buf == NULL || out == NULL) {
        return PCD_DECODE_BAD_ARG;
    }
    if (len != PCD_PACKET_SIZE) {
        return PCD_DECODE_BAD_LENGTH;
    }
    if (buf[0] != PCD_MAGIC_0 || buf[1] != PCD_MAGIC_1) {
        return PCD_DECODE_BAD_MAGIC;
    }
    if (buf[2] != PCD_PROTOCOL_VERSION) {
        return PCD_DECODE_BAD_VERSION;
    }
    if (get_u16(&buf[PCD_CRC_OFFSET]) != pcd_crc16(buf, PCD_CRC_OFFSET)) {
        return PCD_DECODE_BAD_CRC;
    }
    out->flags = buf[3];
    out->node_id = get_u32(&buf[4]);
    out->seq = get_u32(&buf[8]);
    out->uptime_ms = get_u32(&buf[12]);
    /* Turn the 16 raw bits back into a signed value without relying on how
     * the compiler converts an out-of-range unsigned number to int16_t. */
    raw_temp = get_u16(&buf[16]);
    if (raw_temp & 0x8000u) {
        out->temp_centi_c = (int16_t)((int32_t)raw_temp - 65536);
    } else {
        out->temp_centi_c = (int16_t)raw_temp;
    }
    out->humidity_centi_pct = get_u16(&buf[18]);
    return PCD_DECODE_OK;
}
