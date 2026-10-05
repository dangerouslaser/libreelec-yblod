"""Independent scalar oracle for the project's observed RGB8 tunnel layout.

This validates a byte/bit transport contract, not Dolby colour correctness or
certification. No captured pixel values are used as expected answers. Bits are
placed one at a time; CoreELEC memory is addressed byte by byte rather than
reshaped/reversed with the production NumPy decoder.

RGB: R holds C bits4..11; G holds I bits4..11; B low4 holds I bits0..3,
B high4 holds C bits0..3. Even/odd pixels carry P/T from the same even-x site.
CoreELEC's logical memory byte sequence is G,B,R; each 8-byte memory word is
reversed. The supplied buffer must begin at a word boundary. Independent row
strips additionally require a row stride divisible by8.
"""


def code(value):
    if type(value) is not int or not 0 <= value < 4096:
        raise ValueError("12-bit integer code required")
    return value


def pixel_rgb(intensity, chroma):
    intensity, chroma = code(intensity), code(chroma)
    channels = [0, 0, 0]
    for bit in range(12):
        i_bit = (intensity // (2**bit)) % 2
        c_bit = (chroma // (2**bit)) % 2
        if bit < 4:
            channels[2] += i_bit * 2**bit + c_bit * 2**(bit+4)
        else:
            channels[1] += i_bit * 2**(bit-4)
            channels[0] += c_bit * 2**(bit-4)
    return bytes(channels)


def rgb_frame(rows):
    if not rows or not rows[0] or len(rows[0]) % 2 or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("nonempty rectangular even-width frame required")
    output = bytearray()
    for row in rows:
        for x, triple in enumerate(row):
            if len(triple) != 3:
                raise ValueError("I/P/T triple required")
            for value in triple:
                code(value)
            chroma = row[x-x%2][1 if x%2 == 0 else 2]
            output.extend(pixel_rgb(triple[0], chroma))
    return bytes(output)


def _read_pixel(byte_at, pixel):
    """byte_at accepts RGB channel positions; reconstruct individual bits."""
    r, g, b = [byte_at(pixel*3+channel) for channel in range(3)]
    intensity, chroma = 0, 0
    for bit in range(12):
        if bit < 4:
            i_bit, c_bit = (b // 2**bit) % 2, (b // 2**(bit+4)) % 2
        else:
            i_bit, c_bit = (g // 2**(bit-4)) % 2, (r // 2**(bit-4)) % 2
        intensity += i_bit * 2**bit
        chroma += c_bit * 2**bit
    return intensity, chroma


def decode_rgb(raw):
    if not raw or len(raw) % 3:
        raise ValueError("complete RGB pixels required")
    return [_read_pixel(raw.__getitem__, pixel) for pixel in range(len(raw)//3)]


def decode_ce(raw):
    if not raw or len(raw) % 24:
        raise ValueError("complete RGB pixels and 64-bit memory words required")

    def byte_at(rgb_index):
        pixel, channel = divmod(rgb_index, 3)
        # Logical bytes are G,B,R: RGB channel positions map to2,0,1.
        logical = pixel*3 + (2, 0, 1)[channel]
        physical = (logical//8)*8 + (7-logical%8)
        return raw[physical]

    return [_read_pixel(byte_at, pixel) for pixel in range(len(raw)//3)]


def ce_frame(rows):
    """Synthetic memory fixture writer; literal tests independently guard it."""
    rgb = rgb_frame(rows)
    if len(rgb) % 8:
        raise ValueError("complete 64-bit words required")
    output = bytearray(len(rgb))
    for index, value in enumerate(rgb):
        pixel, channel = divmod(index, 3)
        logical = pixel*3 + (2, 0, 1)[channel]
        output[(logical//8)*8 + 7-logical%8] = value
    return bytes(output)


def signed_parts(candidate, reference):
    candidate, reference = code(candidate), code(reference)
    high = candidate//16 - reference//16
    low = candidate%16 - reference%16
    return {"delta12": candidate-reference, "delta_high8": high,
            "weighted_high8": 16*high, "delta_low4": low}


def co_sited_position(row, stored_x, channel):
    if channel not in ("I", "P", "T") or min(row, stored_x) < 0:
        raise ValueError("nonnegative frame coordinates and I/P/T required")
    if channel == "P" and stored_x % 2 or channel == "T" and not stored_x % 2:
        raise ValueError("wrong alternating transport slot")
    return row, stored_x if channel == "I" else stored_x-stored_x%2
