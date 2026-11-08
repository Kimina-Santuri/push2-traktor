"""Track titles from Traktor, which sends no text over MIDI.

Traktor's Broadcasting streams the mix to an Icecast server and tags the stream with the track it counts as playing.
This module is a stand-in Icecast server on 127.0.0.1 that keeps only those tags and throws the audio away. Traktor
sends them as Ogg Vorbis comment headers (a new one per track) or, with some servers, as an admin metadata request;
both are handled.

Traktor: Preferences > Broadcasting > Server: address 127.0.0.1, port 8000, mount /traktor, any password,
format Ogg Vorbis at the lowest bitrate. The bridge switches broadcasting on.
"""
import re
import socket
import struct
import threading
import urllib.parse

PORT = 8000


def vorbis_comments(packet):
    """{'ARTIST': ..., 'TITLE': ...} from a Vorbis comment header packet (starts with 03 'vorbis')."""
    try:
        p = 7
        n = struct.unpack_from("<I", packet, p)[0]
        p += 4 + n
        count = struct.unpack_from("<I", packet, p)[0]
        p += 4
        out = {}
        for _ in range(min(count, 64)):
            n = struct.unpack_from("<I", packet, p)[0]
            p += 4
            key, _, value = packet[p:p + n].decode("utf-8", "replace").partition("=")
            out[key.upper()] = value
            p += n
        return out
    except struct.error:
        return {}


class OggPackets:
    """Feed it stream bytes; it yields complete Ogg packets."""

    def __init__(self):
        self.buf = b""
        self.packet = b""

    def feed(self, data):
        self.buf += data
        while True:
            i = self.buf.find(b"OggS")
            if i < 0:
                self.buf = self.buf[-3:]
                return
            if len(self.buf) < i + 27:
                self.buf = self.buf[i:]
                return
            nseg = self.buf[i + 26]
            if len(self.buf) < i + 27 + nseg:
                self.buf = self.buf[i:]
                return
            lacing = self.buf[i + 27:i + 27 + nseg]
            body = i + 27 + nseg
            if len(self.buf) < body + sum(lacing):
                self.buf = self.buf[i:]
                return
            p = body
            for seg in lacing:
                self.packet += self.buf[p:p + seg]
                p += seg
                if seg < 255:
                    yield self.packet
                    self.packet = b""
            self.buf = self.buf[p:]


class NowPlaying(threading.Thread):
    """Calls on_title("Artist - Title") whenever Traktor announces a new track."""

    def __init__(self, on_title, port=PORT):
        super().__init__(daemon=True)
        self.on_title, self.port = on_title, port
        self.last = None

    def announce(self, tags):
        artist, title = tags.get("ARTIST", "").strip(), tags.get("TITLE", "").strip()
        text = " - ".join(t for t in (artist, title) if t)
        if text and text != self.last:
            self.last = text
            self.on_title(text)

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self.port))
        except OSError as e:
            print("Track titles off: port %d busy (%s)" % (self.port, e))
            return
        srv.listen(4)
        print("Track titles: listening on 127.0.0.1:%d" % self.port)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        with conn:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 16384:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            request, _, rest = head.partition(b"\r\n\r\n")
            line = request.split(b"\r\n")[0].decode("latin-1")
            if line.startswith("GET /admin/metadata"):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(line.split()[1]).query)
                song = q.get("song", [""])[0]
                artist, sep, title = song.partition(" - ")
                self.announce({"ARTIST": artist, "TITLE": title} if sep else {"TITLE": song})
                conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: text/xml\r\n\r\n<?xml version=\"1.0\"?>"
                             b"<iceresponse><message>Metadata update successful</message><return>1</return>"
                             b"</iceresponse>")
                return
            if not re.match(r"(SOURCE|PUT) ", line):
                conn.sendall(b"HTTP/1.0 404 Not Found\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
            ogg = OggPackets()
            data = rest
            while True:
                for packet in ogg.feed(data):
                    if packet[:7] == b"\x03vorbis":
                        self.announce(vorbis_comments(packet))
                data = conn.recv(65536)
                if not data:
                    return
