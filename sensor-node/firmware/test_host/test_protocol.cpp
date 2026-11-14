/*
 * Host tests for the code that has no Arduino dependency: CRC-8, CRC-16,
 * SHT31 conversion and the packet encoder/decoder. Build and run with `make`
 * in this folder.
 *
 * The expected bytes and checksums below were worked out separately (Python,
 * from the published definitions), not by running this C code, so a mistake
 * in the C cannot quietly agree with itself.
 */
#include <cmath>
#include <cstring>

#include "mini_test.h"
#include "pcd_protocol.h"
#include "pcd_sht31.h"

/* ---- CRC-8 (SHT31) ------------------------------------------------------- */

TEST(crc8_datasheet_example_beef_is_92)
{
    const uint8_t data[2] = {0xBE, 0xEF};
    CHECK_EQ(pcd_sht31_crc8(data, 2), 0x92);
}

TEST(crc8_standard_check_value)
{
    /* Same parameters as the catalogued CRC-8/NRSC-5: check value 0xF7. */
    CHECK_EQ(pcd_sht31_crc8((const uint8_t *)"123456789", 9), 0xF7);
}

TEST(crc8_other_known_values)
{
    const uint8_t zeros[2] = {0x00, 0x00};
    const uint8_t ones[2] = {0xFF, 0xFF};
    CHECK_EQ(pcd_sht31_crc8(zeros, 2), 0x81);
    CHECK_EQ(pcd_sht31_crc8(ones, 2), 0xAC);
    CHECK_EQ(pcd_sht31_crc8(zeros, 0), 0xFF); /* nothing fed in: the start value */
    CHECK_EQ(pcd_sht31_crc8(NULL, 2), 0xFF);  /* must not crash */
}

TEST(crc8_catches_every_single_bit_error_in_every_word)
{
    /* All 65536 possible sensor words, all 16 single-bit flips each. */
    long missed = 0;
    for (uint32_t word = 0; word <= 0xFFFF; word++) {
        uint8_t good[2] = {(uint8_t)(word >> 8), (uint8_t)word};
        uint8_t crc = pcd_sht31_crc8(good, 2);
        for (int bit = 0; bit < 16; bit++) {
            uint8_t bad[2] = {good[0], good[1]};
            bad[bit / 8] ^= (uint8_t)(1u << (bit % 8));
            if (pcd_sht31_crc8(bad, 2) == crc) {
                missed++;
            }
        }
    }
    CHECK_EQ(missed, 0);
}

/* ---- SHT31 conversion ---------------------------------------------------- */

TEST(sht31_temperature_known_values)
{
    CHECK_EQ(pcd_sht31_temp_centi_c(0x0000), -4500); /* -45.00 C, bottom of range */
    CHECK_EQ(pcd_sht31_temp_centi_c(0xFFFF), 13000); /* 130.00 C, top of range */
    CHECK_EQ(pcd_sht31_temp_centi_c(0x6666), 2500);  /* 0x6666/65535 = 0.4 exactly */
    CHECK_EQ(pcd_sht31_temp_centi_c(0x8000), 4250);  /* 42.50 C */
    CHECK_EQ(pcd_sht31_temp_centi_c(0x6000), 2063);  /* 20.626 C rounds to 20.63 */
}

TEST(sht31_humidity_known_values)
{
    CHECK_EQ(pcd_sht31_humidity_centi_pct(0x0000), 0);
    CHECK_EQ(pcd_sht31_humidity_centi_pct(0xFFFF), 10000); /* 100.00 % */
    CHECK_EQ(pcd_sht31_humidity_centi_pct(0x6666), 4000);  /* 40.00 % */
    CHECK_EQ(pcd_sht31_humidity_centi_pct(0x8000), 5000);  /* 50.00 % */
    CHECK_EQ(pcd_sht31_humidity_centi_pct(0x6000), 3750);
}

TEST(sht31_conversion_matches_datasheet_formula_for_every_raw_value)
{
    /* The integer maths must stay within half a hundredth of the datasheet's
     * floating-point formula, and must never go backwards as raw rises. */
    long bad = 0;
    int prev_t = -100000;
    int prev_h = -1;
    for (uint32_t raw = 0; raw <= 0xFFFF; raw++) {
        double t = (-45.0 + 175.0 * raw / 65535.0) * 100.0;
        double h = (100.0 * raw / 65535.0) * 100.0;
        int got_t = pcd_sht31_temp_centi_c((uint16_t)raw);
        int got_h = pcd_sht31_humidity_centi_pct((uint16_t)raw);
        if (std::fabs(got_t - t) > 0.5001 || std::fabs(got_h - h) > 0.5001) {
            bad++;
        }
        if (got_t < prev_t || got_h < prev_h) {
            bad++;
        }
        prev_t = got_t;
        prev_h = got_h;
    }
    CHECK_EQ(bad, 0);
}

TEST(sht31_frame_good)
{
    /* 25.00 C (0x6666, crc 0x93) and 50.00 % (0x8000, crc 0xA2). */
    const uint8_t frame[6] = {0x66, 0x66, 0x93, 0x80, 0x00, 0xA2};
    int16_t t = 0;
    uint16_t h = 0;
    CHECK_EQ(pcd_sht31_parse_frame(frame, 6, &t, &h), PCD_SHT31_OK);
    CHECK_EQ(t, 2500);
    CHECK_EQ(h, 5000);
}

TEST(sht31_frame_datasheet_word_in_both_halves)
{
    const uint8_t frame[6] = {0xBE, 0xEF, 0x92, 0xBE, 0xEF, 0x92};
    int16_t t = 0;
    uint16_t h = 0;
    CHECK_EQ(pcd_sht31_parse_frame(frame, 6, &t, &h), PCD_SHT31_OK);
    /* 0xBEEF = 48879. Worked through the datasheet formulas (section 4.13):
     *   T  = -45 + 175 * 48879 / 65535 = -45 + 130.52300 = 85.52300 C -> 8552
     *   RH =       100 * 48879 / 65535 =                    74.58457 % -> 7458
     * Both round DOWN to the nearest hundredth (.523 and .457 are below .5).
     * The integer code gives the same: (17500 * 48879 + 32767) / 65535 =
     * 13052 (truncated), minus 4500 = 8552; (10000 * 48879 + 32767) / 65535 =
     * 7458. An earlier version of this test expected 8559 and 7459, which
     * matches no reading of the formula (dividing by 65536 instead gives
     * 85.521 and 74.583, still 8552 and 7458) - the test was wrong, not the
     * conversion. */
    CHECK_EQ(t, 8552);
    CHECK_EQ(h, 7458);
}

TEST(sht31_frame_bad_temperature_crc_is_rejected_and_outputs_untouched)
{
    const uint8_t frame[6] = {0x66, 0x66, 0x94, 0x80, 0x00, 0xA2};
    int16_t t = 1111;
    uint16_t h = 2222;
    CHECK_EQ(pcd_sht31_parse_frame(frame, 6, &t, &h), PCD_SHT31_BAD_TEMP_CRC);
    CHECK_EQ(t, 1111);
    CHECK_EQ(h, 2222);
}

TEST(sht31_frame_bad_humidity_crc_is_rejected_and_outputs_untouched)
{
    /* The temperature half is fine; the second checksum must still be checked. */
    const uint8_t frame[6] = {0x66, 0x66, 0x93, 0x80, 0x00, 0xA3};
    int16_t t = 1111;
    uint16_t h = 2222;
    CHECK_EQ(pcd_sht31_parse_frame(frame, 6, &t, &h), PCD_SHT31_BAD_HUMIDITY_CRC);
    CHECK_EQ(t, 1111);
    CHECK_EQ(h, 2222);
}

TEST(sht31_frame_stuck_bus_patterns_are_rejected)
{
    /* A bus stuck high reads all 0xFF, stuck low all 0x00. Neither has a
     * valid checksum, which is exactly why the sensor uses 0xFF as the CRC
     * start value. */
    const uint8_t high[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    const uint8_t low[6] = {0, 0, 0, 0, 0, 0};
    int16_t t = 0;
    uint16_t h = 0;
    CHECK(pcd_sht31_parse_frame(high, 6, &t, &h) != PCD_SHT31_OK);
    CHECK(pcd_sht31_parse_frame(low, 6, &t, &h) != PCD_SHT31_OK);
}

TEST(sht31_frame_bad_arguments)
{
    const uint8_t frame[6] = {0x66, 0x66, 0x93, 0x80, 0x00, 0xA2};
    int16_t t = 0;
    uint16_t h = 0;
    CHECK_EQ(pcd_sht31_parse_frame(NULL, 6, &t, &h), PCD_SHT31_BAD_ARG);
    CHECK_EQ(pcd_sht31_parse_frame(frame, 5, &t, &h), PCD_SHT31_BAD_ARG);
    CHECK_EQ(pcd_sht31_parse_frame(frame, 7, &t, &h), PCD_SHT31_BAD_ARG);
    CHECK_EQ(pcd_sht31_parse_frame(frame, 6, NULL, &h), PCD_SHT31_BAD_ARG);
    CHECK_EQ(pcd_sht31_parse_frame(frame, 6, &t, NULL), PCD_SHT31_BAD_ARG);
}

/* ---- CRC-16 -------------------------------------------------------------- */

TEST(crc16_standard_check_value)
{
    CHECK_EQ(pcd_crc16((const uint8_t *)"123456789", 9), 0x29B1);
    CHECK_EQ(pcd_crc16((const uint8_t *)"", 0), 0xFFFF);
    CHECK_EQ(pcd_crc16(NULL, 5), 0xFFFF);
}

/* ---- Packet -------------------------------------------------------------- */

static pcd_reading_t golden_reading()
{
    pcd_reading_t r;
    r.flags = PCD_FLAG_TEMP_VALID | PCD_FLAG_HUMIDITY_VALID;
    r.node_id = 0xA1B2C3D4u;
    r.seq = 0x01020304u;
    r.uptime_ms = 12345678u; /* 0x00BC614E */
    r.temp_centi_c = 2345;
    r.humidity_centi_pct = 4567;
    return r;
}

/* The same bytes are hard-coded in receiver/tests/test_packet.py. */
static const uint8_t GOLDEN[PCD_PACKET_SIZE] = {
    0x50, 0x44, 0x01, 0x03, 0xD4, 0xC3, 0xB2, 0xA1, 0x04, 0x03, 0x02,
    0x01, 0x4E, 0x61, 0xBC, 0x00, 0x29, 0x09, 0xD7, 0x11, 0x10, 0xF2};

static const uint8_t GOLDEN_NEGATIVE[PCD_PACKET_SIZE] = {
    0x50, 0x44, 0x01, 0x01, 0xD4, 0xC3, 0xB2, 0xA1, 0x04, 0x03, 0x02,
    0x01, 0x4E, 0x61, 0xBC, 0x00, 0x2E, 0xFB, 0x00, 0x00, 0x6B, 0x81};

TEST(packet_size_is_22)
{
    CHECK_EQ(PCD_PACKET_SIZE, 22);
    CHECK_EQ(sizeof(GOLDEN), 22);
}

TEST(packet_encode_matches_golden_bytes)
{
    pcd_reading_t r = golden_reading();
    uint8_t buf[PCD_PACKET_SIZE];
    std::memset(buf, 0xEE, sizeof(buf));
    CHECK_EQ(pcd_packet_encode(&r, buf, sizeof(buf)), PCD_PACKET_SIZE);
    CHECK(std::memcmp(buf, GOLDEN, sizeof(GOLDEN)) == 0);
}

TEST(packet_encode_negative_temperature_matches_golden_bytes)
{
    pcd_reading_t r = golden_reading();
    uint8_t buf[PCD_PACKET_SIZE];
    r.flags = PCD_FLAG_TEMP_VALID;
    r.temp_centi_c = -1234; /* 0xFB2E as two's complement */
    r.humidity_centi_pct = 0;
    CHECK_EQ(pcd_packet_encode(&r, buf, sizeof(buf)), PCD_PACKET_SIZE);
    CHECK(std::memcmp(buf, GOLDEN_NEGATIVE, sizeof(GOLDEN_NEGATIVE)) == 0);
}

TEST(packet_encode_refuses_small_buffer_and_writes_nothing)
{
    pcd_reading_t r = golden_reading();
    uint8_t buf[PCD_PACKET_SIZE];
    std::memset(buf, 0xEE, sizeof(buf));
    CHECK_EQ(pcd_packet_encode(&r, buf, PCD_PACKET_SIZE - 1), 0);
    CHECK_EQ(pcd_packet_encode(NULL, buf, sizeof(buf)), 0);
    CHECK_EQ(pcd_packet_encode(&r, NULL, sizeof(buf)), 0);
    for (size_t i = 0; i < sizeof(buf); i++) {
        CHECK_EQ(buf[i], 0xEE);
    }
}

TEST(packet_encode_does_not_write_past_22_bytes)
{
    pcd_reading_t r = golden_reading();
    uint8_t buf[PCD_PACKET_SIZE + 8];
    std::memset(buf, 0xEE, sizeof(buf));
    CHECK_EQ(pcd_packet_encode(&r, buf, sizeof(buf)), PCD_PACKET_SIZE);
    for (size_t i = PCD_PACKET_SIZE; i < sizeof(buf); i++) {
        CHECK_EQ(buf[i], 0xEE);
    }
}

TEST(packet_round_trip_extreme_values)
{
    const int16_t temps[] = {-32768, -4500, -1, 0, 1, 13000, 32767};
    const uint32_t words[] = {0u, 1u, 0x7FFFFFFFu, 0x80000000u, 0xFFFFFFFFu};
    for (size_t t = 0; t < sizeof(temps) / sizeof(temps[0]); t++) {
        for (size_t w = 0; w < sizeof(words) / sizeof(words[0]); w++) {
            pcd_reading_t in;
            pcd_reading_t out;
            uint8_t buf[PCD_PACKET_SIZE];
            in.flags = (uint8_t)(w & 3u);
            in.node_id = words[w];
            in.seq = words[(w + 1) % 5];
            in.uptime_ms = words[(w + 2) % 5];
            in.temp_centi_c = temps[t];
            in.humidity_centi_pct = (uint16_t)(words[w] & 0xFFFFu);
            std::memset(&out, 0, sizeof(out));
            CHECK_EQ(pcd_packet_encode(&in, buf, sizeof(buf)), PCD_PACKET_SIZE);
            CHECK_EQ(pcd_packet_decode(buf, sizeof(buf), &out), PCD_DECODE_OK);
            CHECK_EQ(out.flags, in.flags);
            CHECK_EQ(out.node_id, in.node_id);
            CHECK_EQ(out.seq, in.seq);
            CHECK_EQ(out.uptime_ms, in.uptime_ms);
            CHECK_EQ(out.temp_centi_c, in.temp_centi_c);
            CHECK_EQ(out.humidity_centi_pct, in.humidity_centi_pct);
        }
    }
}

TEST(packet_decode_golden)
{
    pcd_reading_t out;
    CHECK_EQ(pcd_packet_decode(GOLDEN_NEGATIVE, PCD_PACKET_SIZE, &out), PCD_DECODE_OK);
    CHECK_EQ(out.temp_centi_c, -1234);
    CHECK_EQ(out.flags, PCD_FLAG_TEMP_VALID);
    CHECK_EQ(out.node_id, 0xA1B2C3D4u);
    CHECK_EQ(out.seq, 0x01020304u);
    CHECK_EQ(out.uptime_ms, 12345678u);
}

TEST(packet_decode_rejects_wrong_length_magic_version)
{
    pcd_reading_t out;
    uint8_t buf[PCD_PACKET_SIZE + 1];
    std::memcpy(buf, GOLDEN, PCD_PACKET_SIZE);
    buf[PCD_PACKET_SIZE] = 0;
    CHECK_EQ(pcd_packet_decode(buf, 0, &out), PCD_DECODE_BAD_LENGTH);
    CHECK_EQ(pcd_packet_decode(buf, PCD_PACKET_SIZE - 1, &out), PCD_DECODE_BAD_LENGTH);
    CHECK_EQ(pcd_packet_decode(buf, PCD_PACKET_SIZE + 1, &out), PCD_DECODE_BAD_LENGTH);
    CHECK_EQ(pcd_packet_decode(NULL, PCD_PACKET_SIZE, &out), PCD_DECODE_BAD_ARG);
    CHECK_EQ(pcd_packet_decode(buf, PCD_PACKET_SIZE, NULL), PCD_DECODE_BAD_ARG);

    buf[0] = 0x51;
    CHECK_EQ(pcd_packet_decode(buf, PCD_PACKET_SIZE, &out), PCD_DECODE_BAD_MAGIC);
    buf[0] = 0x50;
    buf[2] = 2;
    CHECK_EQ(pcd_packet_decode(buf, PCD_PACKET_SIZE, &out), PCD_DECODE_BAD_VERSION);
}

TEST(packet_crc_catches_every_single_bit_error)
{
    /* Flip each of the 176 bits in turn; none may decode as a good packet. */
    int accepted = 0;
    for (size_t bit = 0; bit < PCD_PACKET_SIZE * 8; bit++) {
        uint8_t buf[PCD_PACKET_SIZE];
        pcd_reading_t out;
        std::memcpy(buf, GOLDEN, sizeof(buf));
        buf[bit / 8] ^= (uint8_t)(1u << (bit % 8));
        if (pcd_packet_decode(buf, sizeof(buf), &out) == PCD_DECODE_OK) {
            accepted++;
        }
    }
    CHECK_EQ(accepted, 0);
}

TEST(packet_crc_catches_every_byte_swap_of_different_bytes)
{
    int accepted = 0;
    for (size_t i = 0; i + 1 < PCD_PACKET_SIZE; i++) {
        uint8_t buf[PCD_PACKET_SIZE];
        pcd_reading_t out;
        std::memcpy(buf, GOLDEN, sizeof(buf));
        if (buf[i] == buf[i + 1]) {
            continue;
        }
        uint8_t tmp = buf[i];
        buf[i] = buf[i + 1];
        buf[i + 1] = tmp;
        if (pcd_packet_decode(buf, sizeof(buf), &out) == PCD_DECODE_OK) {
            accepted++;
        }
    }
    CHECK_EQ(accepted, 0);
}

int main()
{
    return mini_test::run_all();
}
