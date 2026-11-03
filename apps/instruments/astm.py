"""Protocole ASTM utilisé par les automates de laboratoire (GeneXpert, BD MGIT…).

- Couche basse ASTM E1381 / CLSI LIS1 : ENQ / ACK / NAK / EOT, trames STX…ETX|ETB + checksum.
- Couche message ASTM E1394 / CLSI LIS2 : enregistrements H, P, O, R, Q, C, L séparés par CR.

Le module est indépendant de Django : `Session` fonctionne sur n'importe quel lien
offrant `read(n)` / `write(data)` (socket TCP, port série…).
"""
import logging
import socket
from datetime import datetime

log = logging.getLogger("mycogen.instruments")

ENQ, ACK, NAK, EOT, STX, ETX, ETB, CR, LF = b"\x05", b"\x06", b"\x15", b"\x04", b"\x02", b"\x03", b"\x17", b"\r", b"\n"
MAX_FRAME_TEXT = 240


# ---------------------------------------------------------------------------
# Couche basse (E1381)
# ---------------------------------------------------------------------------

def checksum(body: bytes) -> bytes:
    """Somme modulo 256 des octets du numéro de trame jusqu'à ETX/ETB inclus, en 2 caractères hexa."""
    return f"{sum(body) % 256:02X}".encode()


def build_frames(message: str):
    """Découpe un message en trames ASTM : chaque enregistrement commence une nouvelle trame
    (ETB si l'enregistrement continue dans la trame suivante, ETX sinon)."""
    frames = []
    n = 0
    for record in [r for r in message.split("\r") if r]:
        data = (record + "\r").encode("latin-1")
        chunks = [data[i:i + MAX_FRAME_TEXT] for i in range(0, len(data), MAX_FRAME_TEXT)]
        for i, chunk in enumerate(chunks):
            n += 1
            body = str(n % 8).encode() + chunk + (ETX if i == len(chunks) - 1 else ETB)
            frames.append(STX + body + checksum(body) + CR + LF)
    return frames


def parse_frame(frame: bytes):
    """Valide une trame complète (STX … CR LF). Retourne (texte, est_dernière) ou lève ValueError."""
    if not frame.startswith(STX):
        raise ValueError("STX manquant")
    end_pos = max(frame.rfind(ETX), frame.rfind(ETB))
    if end_pos < 2:
        raise ValueError("ETX/ETB manquant")
    body = frame[1:end_pos + 1]
    expected = frame[end_pos + 1:end_pos + 3]
    if checksum(body).upper() != expected.upper():
        raise ValueError(f"checksum invalide ({expected!r} ≠ {checksum(body)!r})")
    return body[1:-1].decode("latin-1"), frame[end_pos:end_pos + 1] == ETX


class Session:
    """Dialogue ASTM sur un lien. `on_message(texte) -> texte_réponse | None` est appelé à chaque EOT."""

    def __init__(self, link, on_message, name="astm"):
        self.link = link
        self.on_message = on_message
        self.name = name
        self.buffer = b""

    def _read(self, n=1):
        while len(self.buffer) < n:
            chunk = self.link.read(4096)
            if chunk is None:  # délai dépassé
                raise TimeoutError
            if chunk == b"":
                raise ConnectionError("connexion fermée")
            self.buffer += chunk
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def _read_until_lf(self):
        data = b""
        while not data.endswith(LF):
            data += self._read(1)
            if len(data) > 64 * 1024:
                raise ValueError("trame trop longue")
        return data

    def run(self):
        """Boucle de réception ; se termine quand la connexion est fermée."""
        while True:
            try:
                c = self._read(1)
            except TimeoutError:
                continue
            if c == ENQ:
                self.link.write(ACK)
                message = self._receive_message()
                if message is None:
                    continue
                reply = self.on_message(message)
                if reply:
                    self.send(reply)
            # tout autre octet hors session (EOT, ACK isolés…) est ignoré

    def _receive_message(self):
        parts = []
        while True:
            try:
                c = self._read(1)
            except TimeoutError:
                log.warning("%s : délai dépassé en cours de message, abandon", self.name)
                return None
            if c == EOT:
                return "".join(parts)
            if c == STX:
                raw = STX + self._read_until_lf()
                try:
                    text, _last = parse_frame(raw)
                except ValueError as exc:
                    log.warning("%s : trame rejetée (%s)", self.name, exc)
                    self.link.write(NAK)
                    continue
                parts.append(text)
                self.link.write(ACK)
            elif c == ENQ:  # réémission
                self.link.write(ACK)

    def send(self, message: str, retries=6):
        """Émet un message (rôle « sender ») : ENQ, trames, EOT."""
        self.link.write(ENQ)
        if self._wait_ack() is not True:
            log.warning("%s : pas d'ACK à l'ENQ, message non envoyé", self.name)
            self.link.write(EOT)
            return False
        for frame in build_frames(message):
            for _ in range(retries):
                self.link.write(frame)
                if self._wait_ack():
                    break
            else:
                self.link.write(EOT)
                return False
        self.link.write(EOT)
        return True

    def _wait_ack(self):
        try:
            c = self._read(1)
        except TimeoutError:
            return None
        return c == ACK


class SocketLink:
    def __init__(self, sock, timeout=15):
        self.sock = sock
        sock.settimeout(timeout)

    def read(self, n):
        try:
            return self.sock.recv(n)
        except socket.timeout:
            return None

    def write(self, data):
        self.sock.sendall(data)


class SerialLink:
    def __init__(self, port):
        self.port = port

    def read(self, n):
        data = self.port.read(1)
        if not data:
            return None
        return data + self.port.read(self.port.in_waiting or 0)

    def write(self, data):
        self.port.write(data)


# ---------------------------------------------------------------------------
# Couche message (E1394)
# ---------------------------------------------------------------------------

class Record(list):
    """Enregistrement ASTM. `rec[n]` = champ n selon la numérotation ASTM (rec[1] = type)."""

    def __init__(self, fields, delimiters):
        super().__init__(fields)
        self.d = delimiters

    @property
    def type(self):
        return self[1][:1] if len(self) > 1 else ""

    def get(self, n, default=""):
        return self[n] if len(self) > n else default

    def component(self, n, c, default=""):
        comps = self.get(n).split(self.d["component"])
        return comps[c].strip() if len(comps) > c else default

    def components(self, n):
        return [x.strip() for x in self.get(n).split(self.d["component"])]


def parse_message(text: str):
    """Analyse un message ASTM E1394 → liste de `Record`."""
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    lines = [ln for ln in text.split("\r") if ln.strip()]
    delims = {"field": "|", "repeat": "\\", "component": "^", "escape": "&"}
    records = []
    for line in lines:
        # Un numéro de trame (0-7) peut subsister en tête si le message a été reçu en mode brut
        if len(line) > 2 and line[0].isdigit() and line[1].isalpha() and line[2] in "|!@#$%":
            line = line[1:]
        if line.startswith("H") and len(line) > 4:
            delims = {"field": line[1], "repeat": line[2], "component": line[3], "escape": line[4]}
        records.append(Record([""] + line.split(delims["field"]), delims))
    return records


def astm_datetime(value):
    value = (value or "").strip()
    for fmt, size in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(value) >= size:
            try:
                return datetime.strptime(value[:size], fmt)
            except ValueError:
                continue
    return None


def header(sender="Mycogen^LIMS"):
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"H|\\^&|||{sender}|||||||P|1394-97|{now}"


def no_information_reply(query_record=None):
    """Réponse à une requête hôte (Q) quand le LIMS n'a pas de demande à transmettre."""
    return "\r".join([header(), "L|1|I"]) + "\r"
