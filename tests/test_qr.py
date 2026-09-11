#!/usr/bin/env python3
"""
test_qr.py  --  Regression tests for the QR encoder. stdlib unittest, no dependencies.

The encoder was developed against the `qrcode` package and verified byte-identical across
1,971 symbols (versions 1-10, every mask, byte mode, EC level M). That library is NOT a
dependency of this tree, so the golden matrix below -- captured from that verified state --
is what guards against regressions here, alongside structural and spec-value checks.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options_desk import qr  # noqa: E402

URL = "http://100.101.102.103:8787/"

#: Captured from the reference-verified encoder. Version 3, EC level M, byte mode.
GOLDEN = [
    "11111110110010000100101111111", "10000010001000001111001000001",
    "10111010010011011101001011101", "10111010110110111000101011101",
    "10111010111011101100101011101", "10000010101111110011101000001",
    "11111110101010101010101111111", "00000000101100100100000000000",
    "10001011101011111111011111001", "10010100011000000000111011111",
    "01110010111101110010111000001", "00100101010001011110011100011",
    "00010111111001000111000100010", "01110101110001101100111011011",
    "11010011111110001100011110101", "01000001110010100101101010011",
    "01110111001011111110100001010", "11000001101110000000101010011",
    "00011011001111110010000101101", "00110100110011011111010100011",
    "11000011101001000111111111001", "00000000110111101110100010001",
    "11111110111110001011101011101", "10000010011000100110100010011",
    "10111010110001111011111110011", "10111010011111000111100101110",
    "10111010010111010010000101011", "10000010011001111001111100011",
    "11111110100001100001110010010",
]


def as_rows(matrix):
    return ["".join(str(v) for v in row) for row in matrix]


class TestGolden(unittest.TestCase):
    def test_matches_reference_verified_output(self):
        self.assertEqual(as_rows(qr.encode(URL)), GOLDEN)

    def test_deterministic(self):
        self.assertEqual(qr.encode(URL), qr.encode(URL))


class TestSpecValues(unittest.TestCase):
    def test_format_strings_match_iso(self):
        """ISO/IEC 18004 Annex C, error-correction level M."""
        known = [0x5412, 0x5125, 0x5E7C, 0x5B4B, 0x45F9, 0x40CE, 0x4F97, 0x4AA0]
        for mask, want in enumerate(known):
            self.assertEqual(qr._format_bits(mask), want, f"mask {mask}")

    def test_block_layouts_sum_to_their_data_capacity(self):
        for version, (data_cw, _ec, layout) in qr._SPEC.items():
            total = sum(count * size for count, size in layout)
            self.assertEqual(total, data_cw, f"version {version}")

    def test_galois_field_is_consistent(self):
        for a in (1, 2, 57, 128, 255):
            for b in (1, 3, 99, 200):
                self.assertEqual(qr._mul(a, b), qr._mul(b, a))
        self.assertEqual(qr._mul(0, 123), 0)


class TestStructure(unittest.TestCase):
    def test_size_follows_version(self):
        for text, version in (("a", 1), ("a" * 20, 2), ("a" * 40, 3), ("a" * 200, 10)):
            m = qr.encode(text)
            self.assertEqual(len(m), version * 4 + 17, text[:8])
            self.assertTrue(all(len(row) == len(m) for row in m))

    def test_finder_patterns_in_three_corners(self):
        m = qr.encode(URL)
        n = len(m)
        for oy, ox in ((0, 0), (0, n - 7), (n - 7, 0)):
            self.assertTrue(all(m[oy][ox + i] for i in range(7)), "top edge")
            self.assertTrue(all(m[oy + 6][ox + i] for i in range(7)), "bottom edge")
            self.assertTrue(all(m[oy + i][ox] for i in range(7)), "left edge")
            self.assertTrue(all(m[oy + i][ox + 6] for i in range(7)), "right edge")
            self.assertEqual(m[oy + 1][ox + 1], 0, "separator ring")
            self.assertEqual(m[oy + 3][ox + 3], 1, "inner block")
        # The fourth corner must NOT have one -- that is how a scanner finds orientation.
        self.assertFalse(all(m[n - 7][n - 7 + i] for i in range(7)))

    def test_timing_patterns_alternate(self):
        m = qr.encode(URL)
        for i in range(8, len(m) - 8):
            self.assertEqual(m[6][i], 1 if i % 2 == 0 else 0, f"row timing at {i}")
            self.assertEqual(m[i][6], 1 if i % 2 == 0 else 0, f"col timing at {i}")

    def test_dark_module_is_set(self):
        m = qr.encode(URL)
        self.assertEqual(m[len(m) - 8][8], 1)

    def test_every_module_is_decided(self):
        m = qr.encode("a" * 100)
        self.assertTrue(all(v in (0, 1) for row in m for v in row))


class TestCapacity(unittest.TestCase):
    def test_longest_supported_payload(self):
        self.assertEqual(len(qr.encode("a" * 213)), 57)          # version 10

    def test_beyond_capacity_raises(self):
        with self.assertRaises(ValueError) as e:
            qr.encode("a" * 400)
        self.assertIn("version 10", str(e.exception))

    def test_utf8_counts_as_bytes_not_characters(self):
        """A multi-byte character must consume its bytes, or the symbol overruns silently."""
        text = "₹" * 60                                     # rupee sign, 3 bytes each
        m = qr.encode(text)
        self.assertGreaterEqual(len(m), 4 * 6 + 17)              # 180 bytes needs version 6+


class TestRender(unittest.TestCase):
    def test_plain_render_has_a_light_quiet_zone(self):
        out = qr.render(URL, quiet=2, color=False)
        lines = out.split("\n")
        # Polarity matters: a negative image with a dark quiet zone will not scan.
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "")
        self.assertEqual(lines[-1].strip(), "")
        self.assertIn("█", out)

    def test_plain_render_dimensions(self):
        m = qr.encode(URL)
        lines = qr.render(URL, quiet=2, color=False).split("\n")
        self.assertEqual(len(lines), len(m) + 4)                 # quiet zone top and bottom
        self.assertEqual(len(lines[0]), (len(m) + 4) * 2)        # two chars per module

    def test_colour_render_sets_both_fg_and_bg(self):
        out = qr.render(URL, color=True)
        # Both must be explicit or the code inverts under one terminal theme.
        self.assertIn("\033[38;5;16m", out)
        self.assertIn("\033[48;5;231m", out)
        self.assertIn("▀", out)

    def test_colour_render_halves_the_line_count(self):
        m = qr.encode(URL)
        lines = qr.render(URL, quiet=2, color=True).split("\n")
        self.assertEqual(len(lines), (len(m) + 4 + 1) // 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
