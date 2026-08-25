#!/usr/bin/env python3
"""
qr.py  --  A minimal QR encoder so the phone URL can be scanned instead of typed. stdlib only.

Byte mode, error-correction level M, versions 1-10 (up to 213 bytes) -- comfortably more than
any `http://100.x.y.z:8787/` URL needs. Written out rather than pulled from PyPI because this
tree has no dependencies, and verified module-for-module against the `qrcode` package.

Reference: ISO/IEC 18004. The parts that matter here are the codeword layout tables, a
Reed-Solomon encoder over GF(256), the eight mask patterns and their penalty scoring.
"""

# --- tables (error-correction level M, versions 1-10) --------------------------------
# (data codewords total, EC codewords per block, [(block count, data codewords per block), ...])
_SPEC = {
    1:  (16,  10, [(1, 16)]),
    2:  (28,  16, [(1, 28)]),
    3:  (44,  26, [(1, 44)]),
    4:  (64,  18, [(2, 32)]),
    5:  (86,  24, [(2, 43)]),
    6:  (108, 16, [(4, 27)]),
    7:  (124, 18, [(4, 31)]),
    8:  (154, 22, [(2, 38), (2, 39)]),
    9:  (182, 22, [(3, 36), (2, 37)]),
    10: (216, 26, [(4, 43), (1, 44)]),
}

#: Row/column centres of the alignment patterns, per version.
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_ECC_M_BITS = 0b00           # level M's two-bit indicator in the format string
_FORMAT_MASK = 0b101010000010010
_MODE_BYTE = 0b0100


# --- GF(256) for Reed-Solomon ---------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:            # QR's primitive polynomial x^8 + x^4 + x^3 + x^2 + 1
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _mul(a, b):
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]


def _generator(n):
    """Generator polynomial for n error-correction codewords."""
    poly = [1]
    for i in range(n):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        poly = nxt
    return poly


def _ec_codewords(data, n):
    """Reed-Solomon remainder: the EC codewords for one block."""
    gen = _generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j, g in enumerate(gen):
                rem[i + j] ^= _mul(g, coef)
    return rem[len(data):]


# --- bit stream -----------------------------------------------------------------------

class _Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, length):
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self):
        return len(self.bits)


def _pick_version(nbytes):
    for v in sorted(_SPEC):
        total, ec, blocks = _SPEC[v]
        count_bits = 8 if v < 10 else 16
        if (4 + count_bits + nbytes * 8) <= total * 8:
            return v
    raise ValueError(f"{nbytes} bytes is beyond this encoder (max "
                     f"{_SPEC[10][0]} codewords at version 10-M)")


def _encode_data(payload, version):
    total_data = _SPEC[version][0]
    bits = _Bits()
    bits.put(_MODE_BYTE, 4)
    bits.put(len(payload), 8 if version < 10 else 16)
    for b in payload:
        bits.put(b, 8)
    # Terminator, then pad to a whole codeword, then the fixed alternating pad bytes.
    bits.put(0, min(4, total_data * 8 - len(bits)))
    while len(bits) % 8:
        bits.bits.append(0)
    codewords = [int("".join(str(b) for b in bits.bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]
    for pad in _cycle_pads(total_data - len(codewords)):
        codewords.append(pad)
    return codewords


def _cycle_pads(n):
    pads = (0xEC, 0x11)
    return [pads[i % 2] for i in range(max(0, n))]


def _interleave(codewords, version):
    """Split into blocks, append each block's EC, then interleave both as the spec requires."""
    _total, ec_per_block, layout = _SPEC[version]
    blocks, pos = [], 0
    for count, size in layout:
        for _ in range(count):
            blocks.append(codewords[pos:pos + size])
            pos += size
    ecs = [_ec_codewords(b, ec_per_block) for b in blocks]

    out = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_per_block):
        for e in ecs:
            out.append(e[i])
    return out


# --- module placement -------------------------------------------------------------------

def _blank(size):
    return [[None] * size for _ in range(size)]


def _place_finders(m, size):
    for oy, ox in ((0, 0), (0, size - 7), (size - 7, 0)):
        for y in range(-1, 8):
            for x in range(-1, 8):
                py, px = oy + y, ox + x
                if not (0 <= py < size and 0 <= px < size):
                    continue
                inner = 2 <= y <= 4 and 2 <= x <= 4
                ring = y in (0, 6) and 0 <= x <= 6 or x in (0, 6) and 0 <= y <= 6
                m[py][px] = 1 if (inner or ring) else 0


def _place_timing(m, size):
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        if m[6][i] is None:
            m[6][i] = bit
        if m[i][6] is None:
            m[i][6] = bit


def _place_alignment(m, version, size):
    centres = _ALIGN[version]
    for cy in centres:
        for cx in centres:
            # Skip the three corners already occupied by finder patterns.
            if (cy, cx) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    m[cy + dy][cx + dx] = 1 if max(abs(dy), abs(dx)) != 1 else 0


def _reserve_format(m, size):
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = 0
        if m[i][8] is None:
            m[i][8] = 0
    for i in range(8):
        m[8][size - 1 - i] = 0
        m[size - 1 - i][8] = 0
    # The always-dark module is reserved as 0 here and only set dark in _place_format. Mask
    # scoring happens before format info is written, so leaving it dark during scoring would
    # bias the penalty by one module and can tip which mask wins.
    m[size - 8][8] = 0


def _reserve_version(m, version, size):
    """
    Claim the two version-information blocks (v7+) as zeros.

    Same reasoning as the format block: these are written after the mask is chosen, so they
    must be zero while scoring or every mask is judged against bits that are not yet decided.
    """
    if version < 7:
        return
    for i in range(18):
        m[i // 3][size - 11 + i % 3] = 0
        m[size - 11 + i % 3][i // 3] = 0


def _place_version(m, version, size):
    if version < 7:
        return
    bits = version << 12
    while bits.bit_length() >= 13:          # BCH(18,6), generator 0x1F25
        bits ^= 0x1F25 << (bits.bit_length() - 13)
    value = (version << 12) | bits
    for i in range(18):
        bit = (value >> i) & 1
        m[i // 3][size - 11 + i % 3] = bit
        m[size - 11 + i % 3][i // 3] = bit


def _place_data(m, data, size):
    bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
    idx, upward, col = 0, True, size - 1
    while col > 0:
        if col == 6:                 # the vertical timing column is skipped entirely
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if m[row][c] is None:
                    m[row][c] = bits[idx] if idx < len(bits) else 0
                    idx += 1
        upward = not upward
        col -= 2


_MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _is_function(version, size, r, c):
    """True where a module is structural and must not be masked."""
    if r == 6 or c == 6:
        return True
    if r < 9 and c < 9:
        return True
    if r < 9 and c >= size - 8:
        return True
    if r >= size - 8 and c < 9:
        return True
    if version >= 7 and (r < 6 and c >= size - 11 or c < 6 and r >= size - 11):
        return True
    centres = _ALIGN[version]
    for cy in centres:
        for cx in centres:
            if (cy, cx) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            if abs(r - cy) <= 2 and abs(c - cx) <= 2:
                return True
    return False


def _apply_mask(m, version, size, mask):
    out = [row[:] for row in m]
    fn = _MASKS[mask]
    for r in range(size):
        for c in range(size):
            if not _is_function(version, size, r, c) and fn(r, c):
                out[r][c] ^= 1
    return out


def _format_bits(mask):
    value = (_ECC_M_BITS << 3) | mask
    bits = value << 10
    while bits.bit_length() >= 11:          # BCH(15,5), generator 0x537
        bits ^= 0x537 << (bits.bit_length() - 11)
    return ((value << 10) | bits) ^ _FORMAT_MASK


def _place_format(m, size, mask):
    """
    Write the 15 format bits into their two copies.

    The two copies are NOT transposes of each other -- the column-8 copy runs top-to-bottom
    from bit 0 and the row-8 copy runs right-to-left from bit 0, each with its own skip around
    the timing module. Writing one as the transpose of the other produces a symbol whose data
    region is perfectly correct and which no scanner will read.
    """
    fmt = _format_bits(mask)
    for i in range(15):
        bit = (fmt >> i) & 1
        # Copy 1: column 8, downward from the top-left, skipping the timing row.
        if i < 6:
            m[i][8] = bit
        elif i < 8:
            m[i + 1][8] = bit
        else:
            m[size - 15 + i][8] = bit
        # Copy 2: row 8, leftward from the right edge, then across the top-left.
        if i < 8:
            m[8][size - 1 - i] = bit
        elif i < 9:
            m[8][15 - i] = bit
        else:
            m[8][14 - i] = bit
    m[size - 8][8] = 1              # the module that is always dark


def _penalty(m, size):
    score = 0
    # Rule 1: runs of five or more same-coloured modules in a row or column.
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for v in line[1:]:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, v
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    # Rule 3: the finder-like 1:1:3:1:1 pattern with four light modules either side.
    pats = ([1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1])
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            if line[i:i + 11] in pats:
                score += 40
    # Rule 4: deviation from an even split of dark and light.
    # The ratio must stay a float until after the comparison with 50. Flooring the percentage
    # first (dark*100 // total) shifts the result a whole band at the boundaries -- a 45.01%
    # ratio scores 10 instead of 0 -- which silently changes which mask wins.
    dark = sum(sum(row) for row in m)
    percent = dark / float(size * size)
    score += int(abs(percent * 100 - 50) / 5) * 10
    return score


def encode(text, mask=None):
    """
    Return the QR matrix for `text` as a list of rows of 0/1 (1 = dark).

    `mask` forces a specific pattern instead of choosing by penalty score -- used by the
    tests to compare placement against a reference encoder independently of mask selection.
    """
    payload = text.encode("utf-8")
    version = _pick_version(len(payload))
    size = version * 4 + 17

    data = _interleave(_encode_data(payload, version), version)

    base = _blank(size)
    _place_finders(base, size)
    _place_alignment(base, version, size)
    _place_timing(base, size)
    _reserve_version(base, version, size)
    _reserve_format(base, size)
    _place_data(base, data, size)

    # Score each mask on the symbol WITHOUT format information, then write the format bits
    # into the winner. Format modules are mask-independent noise for scoring purposes, and
    # including them is what makes independent implementations disagree on the chosen mask.
    candidates = range(8) if mask is None else [mask]
    best, best_score, best_mask = None, None, 0
    for mk in candidates:
        cand = _apply_mask(base, version, size, mk)
        score = _penalty(cand, size)
        if best_score is None or score < best_score:
            best, best_score, best_mask = cand, score, mk
    _place_format(best, size, best_mask)
    _place_version(best, version, size)
    return best


# --- terminal rendering -----------------------------------------------------------------

def render(text, quiet=2, color=True):
    """
    The QR as text, two modules per character cell using a half-block glyph.

    Foreground AND background are set explicitly on every cell, so it scans the same on a
    light or dark terminal -- a QR drawn with the terminal's own colours is unreadable in
    whichever theme inverts it.

    With color=False (a pipe or a log file) it falls back to doubled block characters, which
    still scans from a monospaced terminal and does not embed escape sequences in a file.
    """
    m = encode(text)
    size = len(m)
    pad = [[0] * (size + quiet * 2) for _ in range(quiet)]
    grid = pad + [[0] * quiet + row + [0] * quiet for row in m] + pad

    if not color:
        # Two characters per module keeps the aspect ratio roughly square in a terminal.
        # 1 is a DARK module, so 1 -> blocks and 0 -> spaces. Inverting these produces a
        # negative image with a dark quiet zone, which no scanner will read.
        return "\n".join("".join("\u2588\u2588" if v else "  " for v in row) for row in grid)

    white, black = "\033[38;5;231m", "\033[38;5;16m"
    bg_white, bg_black = "\033[48;5;231m", "\033[48;5;16m"
    lines = []
    for y in range(0, len(grid), 2):
        top = grid[y]
        bottom = grid[y + 1] if y + 1 < len(grid) else [0] * len(top)
        out = []
        for x in range(len(top)):
            fg = black if top[x] else white
            bg = bg_black if bottom[x] else bg_white
            out.append(f"{fg}{bg}▀")
        lines.append("".join(out) + "\033[0m")
    return "\n".join(lines)
