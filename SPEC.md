# BHTTP/1 — a binary HTTP-in-miniature

**Status:** draft 1.0 · **Scope:** one TCP connection, GET-only, static files.

## 1. Why this shape

HTTP/1.1 is text, CRLF-delimited, and ambiguous enough that real servers spend
thousands of lines just tokenizing it. HTTP/2 fixed that by putting everything
in **frames**: a fixed-size header that always tells you how many bytes come
next and what kind of thing they are, followed by a type-specific payload.
We borrow that idea but shrink it, because our protocol doesn't need HTTP/2's
hardest problem — multiplexing many concurrent streams over one connection.
We do need one connection kept open across many sequential requests
(request N+1 doesn't start until response N has fully arrived), so we can drop
the 31-bit stream ID entirely and spend those bits elsewhere, or not at all.

## 2. Connection model

- One TCP connection per client, opened once.
- Requests and responses are strictly sequential and un-pipelined: the client
  sends one request frame, reads the full response, *then* may send the next
  request on the **same** connection. The client never opens a second socket.
- The server keeps the connection open after replying and loops back to read
  the next request frame, until the client closes its end (clean EOF).

## 3. Frame header (6 bytes, fixed, every frame)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                 Length (24)                  |  Type (8)     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   Flags (8)   |  Reserved (8) |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Field    | Width | Meaning |
|----------|-------|---------|
| Length   | 24 bit | Size of the payload that follows, in bytes. Does **not** include this 6-byte header. |
| Type     | 8 bit  | What the payload is. `0x01` = HEADERS, `0x02` = DATA. All other values reserved. |
| Flags    | 8 bit  | Bitfield, meaning depends on Type. Only bit 0 is defined: `END_STREAM` (0x01) — no further frame belongs to this message. Bits 1–7 are reserved, must be sent as 0, and MUST be ignored (not rejected) by a receiver. |
| Reserved | 8 bit  | Must be sent as `0x00`. A receiver MUST ignore its value. This is the slot a v2 would use to add a stream identifier for multiplexing, without changing the shape of this header. |

**Why these widths, and why they differ from HTTP/2's 24/8/8/31:**

- **Length stays 24 bits.** HTTP/2 picked this because it bounds the memory a
  receiver must buffer for one frame (16 MiB-1) while staying large enough that
  ordinary payloads (headers, a typical file) fit in a single frame without
  fragmentation bookkeeping. That trade-off is unchanged here, so we keep it.
- **Type stays 8 bits.** We use two values today. 256 possible values costs
  nothing extra (it's a whole byte either way) and leaves 254 free for a v2 —
  e.g. a SETTINGS frame, a PUT/POST body frame, a PING for keep-alive probing.
- **We shrink 31-bit Stream ID down to an 8-bit Reserved byte.** HTTP/2 needs a
  stream ID because many requests are in flight at once on one connection and
  frames from different streams interleave; the ID is how a receiver
  re-assembles them. This protocol is strictly sequential — one message
  in flight at a time — so there is nothing to disambiguate. We still reserve
  a byte (not zero bytes) rather than deleting the field outright, specifically
  so a future version can reintroduce a (small) stream ID without reshaping
  every frame already in the wild. That is the whole point of a reserved
  field: it's free real estate you promise not to interpret yet.
- **Total header is 6 bytes**, not 9. Smaller fixed overhead per frame, and it
  still starts with the same "how much, what kind" shape that makes framing
  self-describing regardless of payload contents.

**Forward-compatibility rule (non-negotiable):** a receiver that reads a frame
header with a `Type` it does not recognize MUST read exactly `Length` bytes of
payload and discard them, then continue reading the next frame on the
connection. It MUST NOT treat an unknown type as an error. This is what lets a
v2 introduce new frame types — e.g. a PUSH or a PING — that an old v1 peer
simply skips over instead of crashing or misframing the rest of the stream.
Both `bserve` and `bcurl` implement this (see `read_known_frame` in
`bprotocol.py`).

## 4. Frame types

### 4.1 HEADERS (`0x01`)

Payload is a sequence of header entries, back-to-back, filling the frame
exactly (no padding, no count prefix — the receiver parses until it has
consumed `Length` bytes). Carries the request line and the response status
line as pseudo-headers alongside real headers, uniformly.

Each entry:

```
+--------+--------------------------+----------------+-----------+
| 1 byte | [1 byte][N bytes]        | 2 bytes        | M bytes   |
| Index  | NameLen + Name (if idx=0)| ValueLen (BE)  | Value     |
+--------+--------------------------+----------------+-----------+
```

- `Index` (1 byte): if nonzero, it's a lookup into the **static table**
  below — the name is implied, nothing else is sent for it. If zero, a
  **literal** name follows: 1 byte length + that many ASCII bytes.
- `ValueLen` (2 bytes, big-endian) + `Value`: always present, always literal.
  Values are opaque bytes (this project sends ASCII).

This is deliberately HPACK's first two mechanisms and nothing more: *indexed
header field* (send one byte, mean a whole name) and *literal header field
with new name* (send the name out-of-band when it isn't common enough to
deserve a slot). We skip HPACK's third mechanism — the dynamic table a peer
builds up across requests — because that's a stateful cache-eviction protocol
in its own right and out of scope for an evening.

**Static table** (10 entries — the names this project actually sends; add
more in a v2 by extending the table, which is why `Index` has 255 values
available and we only use 10):

| Index | Name | Used by |
|-------|------|---------|
| 1 | `:method`        | request |
| 2 | `:path`           | request |
| 3 | `:status`         | response |
| 4 | `host`            | request |
| 5 | `user-agent`      | request |
| 6 | `content-type`    | response |
| 7 | `content-length`  | response |
| 8 | `accept`          | request (unused by this client, reserved for a richer one) |
| 9 | `connection`      | reserved |
| 10 | `server`         | response |

Any header name outside this table (there are none in this project, but a
custom client could send one) is sent as a literal with `Index = 0`.

`END_STREAM` on a HEADERS frame means: no DATA frame follows for this message
(e.g. a 404 with an empty body, or any response whose Content-Length is 0).

### 4.2 DATA (`0x02`)

Payload is raw body bytes, exactly `Length` of them, no further structure.
`END_STREAM` set means this is the last DATA frame for the current message
(this project never splits a body across more than one DATA frame — a v2
that wants files bigger than 16 MiB-1 would clear `END_STREAM` on all but the
last DATA frame of that body).

## 5. Message semantics

**Request** = exactly one HEADERS frame, `END_STREAM` set (GET has no body).
Required pseudo-headers: `:method` (must be `GET`), `:path` (absolute, e.g.
`/index.html`; empty or `/` maps to `index.html`). `host` and `user-agent` are
sent but not required by the server.

**Response** = one HEADERS frame (`:status` + `content-type` +
`content-length` + `server`), followed by one DATA frame unless the body is
empty, in which case `END_STREAM` is set on the HEADERS frame instead.

**Status codes used:** `200` (file found, body attached), `404` (no such file
under the root, including any path that would escape the root via `..` —
normalized and rejected before the filesystem ever sees it), `400` (the
request frame itself was unparseable: wrong starting frame type, truncated
header entry, an `Index` outside the static table, missing `:method`/`:path`,
or `:method` other than `GET`). On a `400`, the server sends the error
response and then closes the connection — once framing itself is suspect,
the server can no longer trust where the next frame header begins, so it
cannot safely keep reading on that connection. `404` does **not** close the
connection; it's a normal, well-framed answer and the connection stays alive
for the next request (see §2).

**Client exit codes:** `bcurl` exits `0` for `2xx`/`3xx` (only `2xx` is
produced by this server) and non-zero (`1`) for `4xx`/`5xx`, matching the
Unix convention that scripts can branch on.

## 6. What's explicitly out of scope (and left for a v2)

POST/PUT bodies, a dynamic header table (HPACK's third mechanism), request
pipelining (more than one in-flight request per connection), multiplexing
(hence no real stream ID, just the reserved byte), TLS, chunked/streamed
responses of unknown length. None of these require changing the frame header
shape — that is the test this spec was designed against.
