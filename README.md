# BHTTP/1 — bserve + bcurl

A binary, HTTP/2-inspired request/response protocol over a single kept-alive
TCP connection. Full wire format and design rationale: **[SPEC.md](SPEC.md)**.
Byte-by-byte walkthrough of one real request/response: **[hexdump_annotated.md](hexdump_annotated.md)**.

No dependencies — plain Python 3 standard library (`socket`, `struct`-free
manual packing). `bserve` and `bcurl` are executable scripts; `bprotocol.py`
is the shared frame/header codec both import.

## Run it

```sh
./bserve ./www 9000          # terminal 1: serve ./www on port 9000
./bcurl -v localhost:9000/index.html   # terminal 2: fetch it, hexdumping every frame
```

- Body goes to stdout; `-v` sends frame hexdumps to stderr.
- Exit code is `0` for a `2xx` response, `1` for `4xx`/`5xx`.
- The server keeps each connection open and will happily serve more than one
  request on it (`bcurl` only ever sends one request per invocation and then
  closes, as required by the spec, but nothing stops another client from
  pipelining sequential requests on one connection — see `SPEC.md` §2).
- Request a missing file to see a `404`; it does not close the connection.
  Send a malformed frame (wrong starting frame type, bad static-table index,
  truncated header entry) to see a `400`, which *does* close the connection.

## Files

| File | What |
|---|---|
| `SPEC.md` | The protocol spec — deliverable #1 |
| `bserve`, `bcurl`, `bprotocol.py` | The implementation — deliverable #2 |
| `hexdump_annotated.md` | Annotated capture of one full request/response — deliverable #3 |
| `www/` | Sample files served by `bserve` |
