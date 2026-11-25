#!/usr/bin/env python3
"""
Pure-Python ISO/IEC 18004 QR Code encoder (Versions 1-10, Byte Mode) and terminal renderer.
Zero external dependencies.
"""

from typing import Optional
from . import ui

# GF(256) exponent and logarithm tables using primitive polynomial 0x11D
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256


def _init_gf_tables():
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]


_init_gf_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree: int) -> list[int]:
    gen = [1]
    for i in range(degree):
        factor = [1, _GF_EXP[i]]
        nxt = [0] * (len(gen) + 1)
        for j, gj in enumerate(gen):
            nxt[j] ^= _gf_mul(gj, factor[0])
            nxt[j + 1] ^= _gf_mul(gj, factor[1])
        gen = nxt
    return gen


def _rs_encode(data_cw: list[int], ec_count: int) -> list[int]:
    gen = _rs_generator_poly(ec_count)
    msg = list(data_cw) + [0] * ec_count
    for i in range(len(data_cw)):
        coef = msg[i]
        if coef != 0:
            for j in range(1, len(gen)):
                msg[i + j] ^= _gf_mul(gen[j], coef)
    return msg[len(data_cw):]


# Format: version -> ec_level -> (ec_cw_per_block, g1_blocks, g1_data_cw, g2_blocks, g2_data_cw)
_VERSION_TABLE: dict[int, dict[str, tuple[int, int, int, int, int]]] = {
    1: {
        "L": (7, 1, 19, 0, 0),
        "M": (10, 1, 16, 0, 0),
        "Q": (13, 1, 13, 0, 0),
        "H": (17, 1, 9, 0, 0),
    },
    2: {
        "L": (10, 1, 34, 0, 0),
        "M": (16, 1, 28, 0, 0),
        "Q": (22, 1, 22, 0, 0),
        "H": (28, 1, 16, 0, 0),
    },
    3: {
        "L": (15, 1, 55, 0, 0),
        "M": (26, 1, 44, 0, 0),
        "Q": (18, 2, 17, 0, 0),
        "H": (22, 2, 13, 0, 0),
    },
    4: {
        "L": (20, 1, 80, 0, 0),
        "M": (18, 2, 32, 0, 0),
        "Q": (26, 2, 24, 0, 0),
        "H": (16, 4, 9, 0, 0),
    },
    5: {
        "L": (26, 1, 108, 0, 0),
        "M": (24, 2, 43, 0, 0),
        "Q": (18, 2, 15, 2, 16),
        "H": (22, 2, 11, 2, 12),
    },
    6: {
        "L": (18, 2, 68, 0, 0),
        "M": (16, 4, 27, 0, 0),
        "Q": (24, 4, 19, 0, 0),
        "H": (28, 4, 15, 0, 0),
    },
    7: {
        "L": (20, 2, 78, 0, 0),
        "M": (18, 4, 31, 0, 0),
        "Q": (18, 2, 14, 4, 15),
        "H": (26, 4, 13, 1, 14),
    },
    8: {
        "L": (24, 2, 97, 0, 0),
        "M": (22, 2, 38, 2, 39),
        "Q": (22, 4, 18, 2, 19),
        "H": (26, 4, 14, 2, 15),
    },
    9: {
        "L": (30, 2, 116, 0, 0),
        "M": (22, 3, 36, 2, 37),
        "Q": (20, 4, 16, 4, 17),
        "H": (24, 4, 12, 4, 13),
    },
    10: {
        "L": (18, 2, 68, 2, 69),
        "M": (26, 4, 43, 1, 44),
        "Q": (24, 6, 19, 2, 20),
        "H": (28, 6, 15, 2, 16),
    },
}

_ALIGNMENT_CENTERS: dict[int, list[int]] = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

_REMAINDER_BITS: dict[int, int] = {
    1: 0,
    2: 7,
    3: 7,
    4: 7,
    5: 7,
    6: 7,
    7: 0,
    8: 0,
    9: 0,
    10: 0,
}

_EC_LEVEL_BITS: dict[str, int] = {
    "L": 0b01,
    "M": 0b00,
    "Q": 0b11,
    "H": 0b10,
}

_MASK_FUNCTIONS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: ((r // 2) + (c // 3)) % 2 == 0,
    lambda r, c: ((r * c) % 2) + ((r * c) % 3) == 0,
    lambda r, c: (((r * c) % 2) + ((r * c) % 3)) % 2 == 0,
    lambda r, c: (((r + c) % 2) + ((r * c) % 3)) % 2 == 0,
)


def _select_version(byte_len: int, ec_level: str) -> int:
    for version in range(1, 11):
        _, g1_b, g1_dcw, g2_b, g2_dcw = _VERSION_TABLE[version][ec_level]
        total_data_cw = g1_b * g1_dcw + g2_b * g2_dcw
        count_bits = 8 if version <= 9 else 16
        needed_bits = 4 + count_bits + byte_len * 8
        if total_data_cw * 8 >= needed_bits:
            return version
    raise ValueError(
        f"Payload too long ({byte_len} bytes) for QR Versions 1-10 at EC level '{ec_level}'."
    )


def _encode_data_bits(payload: bytes, version: int, ec_level: str) -> list[int]:
    ec_cw_per_block, g1_b, g1_dcw, g2_b, g2_dcw = _VERSION_TABLE[version][ec_level]
    total_data_cw = g1_b * g1_dcw + g2_b * g2_dcw
    total_data_bits = total_data_cw * 8

    bits: list[int] = []

    def push_bits(val: int, width: int):
        for shift in range(width - 1, -1, -1):
            bits.append((val >> shift) & 1)

    # Byte mode indicator: 0100
    push_bits(0b0100, 4)
    count_bits = 8 if version <= 9 else 16
    push_bits(len(payload), count_bits)
    for b in payload:
        push_bits(b, 8)

    # Terminator (up to 4 zero bits)
    terminator_len = min(4, total_data_bits - len(bits))
    bits.extend([0] * terminator_len)

    # Pad to byte boundary
    while len(bits) % 8 != 0:
        bits.append(0)

    # Convert to codewords and pad alternating 0xEC, 0x11
    data_cw = []
    for i in range(0, len(bits), 8):
        byte_val = 0
        for b in bits[i : i + 8]:
            byte_val = (byte_val << 1) | b
        data_cw.append(byte_val)

    pad_bytes = (0xEC, 0x11)
    pad_idx = 0
    while len(data_cw) < total_data_cw:
        data_cw.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    # Split into Group 1 and Group 2 blocks & compute Reed-Solomon EC codewords
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    offset = 0
    for _ in range(g1_b):
        blk = data_cw[offset : offset + g1_dcw]
        offset += g1_dcw
        data_blocks.append(blk)
        ec_blocks.append(_rs_encode(blk, ec_cw_per_block))
    for _ in range(g2_b):
        blk = data_cw[offset : offset + g2_dcw]
        offset += g2_dcw
        data_blocks.append(blk)
        ec_blocks.append(_rs_encode(blk, ec_cw_per_block))

    # Interleave data codewords, then EC codewords
    interleaved: list[int] = []
    max_data_len = max(len(b) for b in data_blocks)
    for idx in range(max_data_len):
        for blk in data_blocks:
            if idx < len(blk):
                interleaved.append(blk[idx])
    for idx in range(ec_cw_per_block):
        for ec_blk in ec_blocks:
            interleaved.append(ec_blk[idx])

    out_bits: list[int] = []
    for cw in interleaved:
        for shift in range(7, -1, -1):
            out_bits.append((cw >> shift) & 1)
    out_bits.extend([0] * _REMAINDER_BITS[version])
    return out_bits


def _compute_format_bits(ec_level: str, mask_id: int) -> int:
    data = (_EC_LEVEL_BITS[ec_level] << 3) | mask_id
    rem = data << 10
    while rem.bit_length() >= 11:
        rem ^= 0x537 << (rem.bit_length() - 11)
    return ((data << 10) | rem) ^ 0x5412


def _compute_version_bits(version: int) -> int:
    rem = version << 12
    while rem.bit_length() >= 13:
        rem ^= 0x1F25 << (rem.bit_length() - 13)
    return (version << 12) | rem


def _build_base_matrix(version: int) -> tuple[list[list[bool]], list[list[bool]]]:
    size = 17 + 4 * version
    matrix = [[False] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r: int, c: int, val: bool):
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = val
            is_func[r][c] = True

    def draw_finder(top: int, left: int):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top + dr, left + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_func(r, c, False)
                elif dr in (0, 6) or dc in (0, 6):
                    set_func(r, c, True)
                elif 2 <= dr <= 4 and 2 <= dc <= 4:
                    set_func(r, c, True)
                else:
                    set_func(r, c, False)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    # Alignment patterns
    centers = _ALIGNMENT_CENTERS[version]
    for cr in centers:
        for cc in centers:
            if is_func[cr][cc]:
                continue
            # Also verify 5x5 doesn't overlap finder + separator
            overlaps = False
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    if is_func[cr + dr][cc + dc]:
                        overlaps = True
                        break
                if overlaps:
                    break
            if overlaps:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    dark = max(abs(dr), abs(dc)) != 1
                    set_func(cr + dr, cc + dc, dark)

    # Timing patterns
    for i in range(8, size - 8):
        dark = (i % 2) == 0
        if not is_func[6][i]:
            set_func(6, i, dark)
        if not is_func[i][6]:
            set_func(i, 6, dark)

    # Dark module
    set_func(4 * version + 9, 8, True)

    # Reserve format info areas
    for c in [0, 1, 2, 3, 4, 5, 7, 8]:
        is_func[8][c] = True
    for r in [7, 5, 4, 3, 2, 1, 0]:
        is_func[r][8] = True
    for r in range(size - 7, size):
        is_func[r][8] = True
    for c in range(size - 8, size):
        is_func[8][c] = True

    # Version info for Versions >= 7
    if version >= 7:
        ver_bits = _compute_version_bits(version)
        for i in range(6):
            for j in range(3):
                bit = bool((ver_bits >> (i * 3 + j)) & 1)
                set_func(size - 11 + j, i, bit)
                set_func(i, size - 11 + j, bit)

    return matrix, is_func


def _place_data_bits(matrix: list[list[bool]], is_func: list[list[bool]], data_bits: list[int]):
    size = len(matrix)
    bit_idx = 0
    total_bits = len(data_bits)
    col = size - 1
    upward = True

    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if not is_func[r][c]:
                    if bit_idx < total_bits:
                        matrix[r][c] = bool(data_bits[bit_idx])
                        bit_idx += 1
                    else:
                        matrix[r][c] = False
        upward = not upward
        col -= 2


def _apply_format_info(matrix: list[list[bool]], ec_level: str, mask_id: int):
    size = len(matrix)
    fmt = _compute_format_bits(ec_level, mask_id)

    # Strip 1 (top-left): bits 14..7 along row 8, bits 6..0 along col 8
    top_left_row8_cols = [0, 1, 2, 3, 4, 5, 7, 8]
    for idx, c in enumerate(top_left_row8_cols):
        matrix[8][c] = bool((fmt >> (14 - idx)) & 1)
    top_left_col8_rows = [7, 5, 4, 3, 2, 1, 0]
    for idx, r in enumerate(top_left_col8_rows):
        matrix[r][8] = bool((fmt >> (6 - idx)) & 1)

    # Strip 2 (bottom-left & top-right): bits 14..8 along col 8, bits 7..0 along row 8
    for idx in range(7):
        matrix[size - 1 - idx][8] = bool((fmt >> (14 - idx)) & 1)
    for idx in range(8):
        matrix[8][size - 8 + idx] = bool((fmt >> (7 - idx)) & 1)


def _penalty_score(matrix: list[list[bool]]) -> int:
    size = len(matrix)
    penalty = 0

    # Rule 1: 5+ consecutive same-color modules in rows and columns
    for r in range(size):
        row = matrix[r]
        run_color = row[0]
        run_len = 1
        for c in range(1, size):
            if row[c] == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    penalty += 3 + (run_len - 5)
                run_color = row[c]
                run_len = 1
        if run_len >= 5:
            penalty += 3 + (run_len - 5)

    for c in range(size):
        run_color = matrix[0][c]
        run_len = 1
        for r in range(1, size):
            if matrix[r][c] == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    penalty += 3 + (run_len - 5)
                run_color = matrix[r][c]
                run_len = 1
        if run_len >= 5:
            penalty += 3 + (run_len - 5)

    # Rule 2: 2x2 blocks of same color
    for r in range(size - 1):
        row0 = matrix[r]
        row1 = matrix[r + 1]
        for c in range(size - 1):
            val = row0[c]
            if row0[c + 1] == val and row1[c] == val and row1[c + 1] == val:
                penalty += 3

    # Rule 3: Finder-like 1:1:3:1:1 pattern with 4 light modules before or after
    pat_a = (False, False, False, False, True, False, True, True, True, False, True)
    pat_b = (True, False, True, True, True, False, True, False, False, False, False)
    if size >= 11:
        for r in range(size):
            row = matrix[r]
            for c in range(size - 10):
                seg = tuple(row[c : c + 11])
                if seg == pat_a or seg == pat_b:
                    penalty += 40
        for c in range(size):
            col_vals = [matrix[r][c] for r in range(size)]
            for r in range(size - 10):
                seg = tuple(col_vals[r : r + 11])
                if seg == pat_a or seg == pat_b:
                    penalty += 40

    # Rule 4: Proportion of dark modules relative to 50%
    dark_count = sum(1 for row in matrix for cell in row if cell)
    percent = (dark_count * 100.0) / (size * size)
    prev_5 = int(percent // 5) * 5
    next_5 = prev_5 + 5
    penalty += (min(abs(prev_5 - 50), abs(next_5 - 50)) // 5) * 10

    return penalty


def generate_qr_matrix(data: str, ec_level: str = "M") -> list[list[bool]]:
    """
    Generate an ISO/IEC 18004 QR code boolean matrix (True = dark module, False = light module).
    Supports Versions 1-10 in Byte mode and EC levels L, M, Q, H.
    """
    ec = ec_level.upper()
    if ec not in _EC_LEVEL_BITS:
        raise ValueError(f"Invalid error correction level '{ec_level}'. Expected one of L, M, Q, H.")

    payload = data.encode("utf-8")
    version = _select_version(len(payload), ec)
    data_bits = _encode_data_bits(payload, version, ec)

    base_matrix, is_func = _build_base_matrix(version)
    _place_data_bits(base_matrix, is_func, data_bits)
    size = len(base_matrix)

    best_matrix: Optional[list[list[bool]]] = None
    best_penalty: Optional[int] = None

    for mask_id, mask_fn in enumerate(_MASK_FUNCTIONS):
        candidate = [row[:] for row in base_matrix]
        for r in range(size):
            for c in range(size):
                if not is_func[r][c] and mask_fn(r, c):
                    candidate[r][c] = not candidate[r][c]
        _apply_format_info(candidate, ec, mask_id)
        score = _penalty_score(candidate)
        if best_penalty is None or score < best_penalty:
            best_penalty = score
            best_matrix = candidate

    assert best_matrix is not None
    return best_matrix


def render_qr_terminal(
    matrix: list[list[bool]],
    quiet_zone: int = 3,
    invert: bool = False,
    use_ansi: Optional[bool] = None,
    compact: bool = False,
) -> str:
    """
    Render a QR boolean matrix for terminal display.
    - Default ANSI mode (`compact=False`): gapless full-cell 256-color background spaces ('  ' per module),
      eliminating horizontal line-spacing gaps that break Android camera QR scanners.
    - Compact / non-ANSI mode (`compact=True` or `use_ansi=False`): Unicode half-block glyphs ('█', '▀', '▄', ' ').
    """
    if quiet_zone < 0:
        raise ValueError("quiet_zone must be >= 0")

    size = len(matrix)
    padded_width = size + quiet_zone * 2
    padded: list[list[bool]] = []
    empty_row = [False] * padded_width

    for _ in range(quiet_zone):
        padded.append(empty_row[:])
    for row in matrix:
        padded.append(([False] * quiet_zone) + row[:] + ([False] * quiet_zone))
    for _ in range(quiet_zone):
        padded.append(empty_row[:])

    ansi = ui.Colors.ENABLED if use_ansi is None else use_ansi

    if ansi and not compact:
        dark_bg = "\033[48;5;231m" if invert else "\033[48;5;16m"
        light_bg = "\033[48;5;16m" if invert else "\033[48;5;231m"
        lines: list[str] = []
        for row in padded:
            parts: list[str] = []
            run_val = row[0]
            run_len = 1
            for cell in row[1:]:
                if cell == run_val:
                    run_len += 1
                else:
                    parts.append(f"{dark_bg if run_val else light_bg}{'  ' * run_len}")
                    run_val = cell
                    run_len = 1
            parts.append(f"{dark_bg if run_val else light_bg}{'  ' * run_len}\033[0m")
            lines.append("".join(parts))
        return "\n".join(lines)

    glyphs = {
        (True, True): "█",
        (True, False): "▀",
        (False, True): "▄",
        (False, False): " ",
    }

    lines = []
    for r in range(0, len(padded), 2):
        top_row = padded[r]
        bot_row = padded[r + 1] if (r + 1) < len(padded) else empty_row
        chars = []
        for c in range(padded_width):
            t = top_row[c]
            b = bot_row[c]
            if invert and not ansi:
                t = not t
                b = not b
            chars.append(glyphs[(t, b)])
        line = "".join(chars)
        if ansi:
            prefix = "\033[38;5;231;48;5;16m" if invert else "\033[38;5;16;48;5;231m"
            lines.append(f"{prefix}{line}\033[0m")
        else:
            lines.append(line)

    return "\n".join(lines)


def render_qr_string(
    data: str,
    ec_level: str = "M",
    quiet_zone: int = 3,
    invert: bool = False,
    use_ansi: Optional[bool] = None,
    compact: bool = False,
) -> str:
    """Convenience helper to encode data and render the QR code for terminal display."""
    matrix = generate_qr_matrix(data, ec_level=ec_level)
    return render_qr_terminal(
        matrix,
        quiet_zone=quiet_zone,
        invert=invert,
        use_ansi=use_ansi,
        compact=compact,
    )
