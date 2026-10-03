# Annotated hexdump — one complete request/response

Captured with `./bcurl -v localhost:9000/index.html` against `./bserve ./www 9000`.
All three frames below are real bytes from that exchange (see `README.md` to
reproduce). Field boundaries are marked `|`.

## Frame 1 — client → server: HEADERS (request)

```
00 00 31 | 01 | 01 | 00
```
| Bytes | Field | Value |
|---|---|---|
| `00 00 31` | Length | `0x000031` = 49 payload bytes follow |
| `01` | Type | `0x01` = HEADERS |
| `01` | Flags | `0x01` = END_STREAM set → GET has no body, nothing follows this frame |
| `00` | Reserved | `0x00` |

Payload (49 bytes), four header entries back-to-back:

```
01 00 03 47 45 54
```
- `01` → Index 1 = `:method` (static table, no name bytes sent)
- `00 03` → ValueLen = 3
- `47 45 54` → `"GET"`

```
02 00 0b 2f 69 6e 64 65 78 2e 68 74 6d 6c
```
- `02` → Index 2 = `:path`
- `00 0b` → ValueLen = 11
- `2f 69 6e 64 65 78 2e 68 74 6d 6c` → `"/index.html"`

```
04 00 0e 6c 6f 63 61 6c 68 6f 73 74 3a 39 30 30 30
```
- `04` → Index 4 = `host`
- `00 0e` → ValueLen = 14
- `...` → `"localhost:9000"`

```
05 00 09 62 63 75 72 6c 2f 31 2e 30
```
- `05` → Index 5 = `user-agent`
- `00 09` → ValueLen = 9
- `62 63 75 72 6c 2f 31 2e 30` → `"bcurl/1.0"`

6 + 14 + 17 + 12 = 49 bytes, matching the frame's declared Length. No
`:method`/`:path` would have been a 400; here both are present and well-formed.

## Frame 2 — server → client: HEADERS (response)

```
00 00 25 | 01 | 00 | 00
```
| Bytes | Field | Value |
|---|---|---|
| `00 00 25` | Length | `0x25` = 37 payload bytes |
| `01` | Type | HEADERS |
| `00` | Flags | END_STREAM **not** set → a DATA frame follows with the body |
| `00` | Reserved | `0x00` |

Payload (37 bytes):

```
03 00 03 32 30 30
```
- Index 3 = `:status`, ValueLen 3, Value `"200"`

```
06 00 09 74 65 78 74 2f 68 74 6d 6c
```
- Index 6 = `content-type`, ValueLen 9, Value `"text/html"`

```
07 00 03 31 38 35
```
- Index 7 = `content-length`, ValueLen 3, Value `"185"`

```
0a 00 0a 62 73 65 72 76 65 2f 31 2e 30
```
- Index 10 = `server`, ValueLen 10, Value `"bserve/1.0"`

6 + 12 + 6 + 13 = 37 bytes. `content-length: 185` is the contract the next
frame's payload must satisfy exactly.

## Frame 3 — server → client: DATA (response body)

```
00 00 b9 | 02 | 01 | 00
```
| Bytes | Field | Value |
|---|---|---|
| `00 00 b9` | Length | `0xb9` = 185 — matches `content-length` above |
| `02` | Type | DATA |
| `01` | Flags | END_STREAM set → last (only) DATA frame of this response |
| `00` | Reserved | `0x00` |

Payload: 185 raw bytes, the literal contents of `www/index.html`:

```
00000000  3c 21 64 6f 63 74 79 70 65 20 68 74 6d 6c 3e 0a  |<!doctype html>.|
00000010  3c 68 74 6d 6c 3e 0a 3c 68 65 61 64 3e 3c 74 69  |<html>.<head><ti|
...
000000b0  3c 2f 68 74 6d 6c 3e 0a                          |</html>.|
```

(Full dump omitted for length — it is exactly the bytes of `www/index.html`,
no transformation, since `DATA` payload is raw body bytes per §4.2 of
`SPEC.md`.)

After this frame, `bcurl` closes the socket (one request per invocation) and
exits `0`, since `:status` was `200`. Had `:status` been `≥ 400`, it would
have exited `1` after still printing the body to stdout.
