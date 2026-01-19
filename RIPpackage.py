import struct
import socket


class RIPEntry:
    def __init__(self, afi=2, route_tag=0, ip='0.0.0.0', mask='0.0.0.0', next_hop='0.0.0.0', metric=1):
        self.afi = afi
        self.route_tag = route_tag
        self.ip = ip
        self.mask = mask
        self.next_hop = next_hop
        self.metric = metric

    def pack(self):
        # Convertim adresele in bytes
        ip_bytes = socket.inet_aton(self.ip)
        mask_bytes = socket.inet_aton(self.mask)
        next_hop_bytes = socket.inet_aton(self.next_hop)

        # Impachetare in format RIPv2 (20 octeti)
        # ! - ordinea octetilor de retea (format big-endian)
        # H - 2 octeti (unsigned short) pentru AFI si route tag
        # 4s - 4 octeti (string) pentru adrese IP
        # I - 4 octeti (unsigned int) pentru metrica
        return struct.pack('!HH4s4s4sI',
                           self.afi,
                           self.route_tag,
                           ip_bytes,
                           mask_bytes,
                           next_hop_bytes,
                           self.metric)

    def unpack(data):
        # Despachetam cei 20 de octeti
        afi, route_tag, ip_bytes, mask_bytes, next_hop_bytes, metric = struct.unpack('!HH4s4s4sI', data)
        return RIPEntry(
            afi=afi,
            route_tag=route_tag,
            ip=socket.inet_ntoa(ip_bytes),
            mask=socket.inet_ntoa(mask_bytes),
            next_hop=socket.inet_ntoa(next_hop_bytes),
            metric=metric
        )

    def __str__(self):
        return f"   -> Network: {self.ip}/{self.mask} | Metric: {self.metric} | NextHop: {self.next_hop}"

class RIPpackage:
    def __init__(self, command = 2, version = 2):
        self.command = command
        self.version = version
        self.zero = 0
        self.entries = []

    def add_entry(self, entry: RIPEntry):
        self.entries.append(entry)

    def pack(self):
        # Impachetare antetul RIP (4 octeti)
        # ! - ordinea octetilor de retea
        # B - 1 octet (unsigned byte) pentru comanda
        # B - 1 octet (unsigned byte) pentru versiune
        # H - 2 octeti (unsigned byte) pentru zero field
        # b'' - byte string
        header = struct.pack('!BBH', self.command, self.version, self.zero)
        body = b''.join(entry.pack() for entry in self.entries)
        return header + body

    @staticmethod
    def unpack(data):
        # Extragem Headerul (primii 4 octeti)
        command, version, zero = struct.unpack('!BBH', data[:4])
        pkg = RIPpackage(command, version)

        # Extragem intrarile (restul pachetului, cate 20 octeti)
        # Trecem peste header (4 bytes)
        entries_data = data[4:]
        entry_size = 20

        for i in range(0, len(entries_data), entry_size):
            chunk = entries_data[i: i + entry_size]
            if len(chunk) == entry_size:
                entry = RIPEntry.unpack(chunk)
                pkg.add_entry(entry)

        return pkg

    def __str__(self):
        cmd_str = "RESPONSE" if self.command == 2 else "REQUEST"
        result = f"[RIPv{self.version} Packet] Command: {cmd_str}\n"
        for entry in self.entries:
            result += str(entry) + "\n"
        return result


