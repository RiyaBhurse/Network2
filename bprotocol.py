#!/usr/bin/env python3
"""Shared binary framing codec for bserve/bcurl. See SPEC.md for the wire format."""

FRAME_HEADER_LEN = 6

TYPE_HEADERS = 0x01
TYPE_DATA = 0x02

FLAG_END_STREAM = 0x01

STATIC_TABLE = {
    1: ":method",
    2: ":path",
    3: ":status",
    4: "host",
    5: "user-agent",
    6: "content-type",
    7: "content-length",
    8: "accept",
    9: "connection",
    10: "server",
}
NAME_TO_INDEX = {v: k for k, v in STATIC_TABLE.items()}


class FrameError(ValueError):
    pass


def pack_frame_header(length, type_, flags, reserved=0):
    if length > 0xFFFFFF:
        raise FrameError(f"payload too large for 24-bit length: {length}")
    return length.to_bytes(3, "big") + bytes([type_ & 0xFF, flags & 0xFF, reserved & 0xFF])


def unpack_frame_header(b):
    if len(b) != FRAME_HEADER_LEN:
        raise FrameError("short frame header")
    length = int.from_bytes(b[0:3], "big")
    type_ = b[3]
    flags = b[4]
    reserved = b[5]
    return length, type_, flags, reserved


def encode_headers(pairs):
    """pairs: list of (name:str, value:str|bytes) -> payload bytes."""
    out = bytearray()
    for name, value in pairs:
        vbytes = value if isinstance(value, (bytes, bytearray)) else str(value).encode("ascii")
        idx = NAME_TO_INDEX.get(name)
        if idx is not None:
            out.append(idx)
        else:
            nbytes = name.encode("ascii")
            if len(nbytes) > 0xFF:
                raise FrameError("header name too long")
            out.append(0)
            out.append(len(nbytes))
            out.extend(nbytes)
        if len(vbytes) > 0xFFFF:
            raise FrameError("header value too long")
        out.extend(len(vbytes).to_bytes(2, "big"))
        out.extend(vbytes)
    return bytes(out)


def decode_headers(payload):
    """payload bytes -> list of (name:str, value:bytes). Raises FrameError on malformed input."""
    i = 0
    n = len(payload)
    result = []
    while i < n:
        idx = payload[i]
        i += 1
        if idx == 0:
            if i >= n:
                raise FrameError("truncated literal name length")
            namelen = payload[i]
            i += 1
            if i + namelen > n:
                raise FrameError("truncated literal name")
            try:
                name = payload[i:i + namelen].decode("ascii")
            except UnicodeDecodeError:
                raise FrameError("non-ascii header name")
            i += namelen
        else:
            if idx not in STATIC_TABLE:
                raise FrameError(f"unknown static table index {idx}")
            name = STATIC_TABLE[idx]
        if i + 2 > n:
            raise FrameError("truncated value length")
        vlen = int.from_bytes(payload[i:i + 2], "big")
        i += 2
        if i + vlen > n:
            raise FrameError("truncated value")
        value = payload[i:i + vlen]
        i += vlen
        result.append((name, value))
    return result


def recv_exact(sock, nbytes):
    """Read exactly nbytes or return None on a clean EOF with zero bytes read so far."""
    buf = bytearray()
    while len(buf) < nbytes:
        chunk = sock.recv(nbytes - len(buf))
        if not chunk:
            if len(buf) == 0:
                return None
            raise ConnectionError("unexpected EOF mid-frame")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock):
    """Read one frame (header consumed regardless of type). Returns (type, flags, payload) or None on clean EOF."""
    header = recv_exact(sock, FRAME_HEADER_LEN)
    if header is None:
        return None
    length, type_, flags, _reserved = unpack_frame_header(header)
    payload = recv_exact(sock, length) if length else b""
    if payload is None:
        raise ConnectionError("unexpected EOF mid-frame")
    return type_, flags, payload


def read_known_frame(sock, known_types):
    """Read frames, silently skipping any whose type is not in known_types.

    This is the forward-compatibility rule from the spec: a receiver that meets
    a frame type it does not know MUST skip it cleanly rather than erroring.
    """
    while True:
        frame = read_frame(sock)
        if frame is None:
            return None
        type_, _flags, _payload = frame
        if type_ in known_types:
            return frame
        # unknown type: already fully consumed by read_frame, just keep going


def send_frame(sock, type_, flags, payload, reserved=0):
    header = pack_frame_header(len(payload), type_, flags, reserved)
    sock.sendall(header + payload)


def hexdump(data, indent=""):
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        hexpart = f"{hexpart:<47}"
        asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{off:08x}  {hexpart}  |{asciipart}|")
    return "\n".join(lines)
