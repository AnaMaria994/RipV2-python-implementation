import socket
import threading
import ipaddress
import time
import psutil
from RIPv2Implementation.RIPpackage import RIPpackage, RIPEntry

MULTICAST_GROUP = "224.0.0.9"
MULTICAST_PORT = 520

UPDATE_INTERVAL = 5 # Standard RFC 30s, 5 e pentru testare
ROUTE_TIMEOUT = 5 # Standard RFC 180s, 5 e pentru testare
GARBAGE_COLLECTION = 5 # Standard RFC 120s, 5 e pentru testare

BUFFER_SIZE = 1024

# Retelele pe care le ignoram (loopback si interfata NAT)
IGNORED_NETWORKS = ["127.", "10."]


class RoutingTable:
    def __init__(self):
        self.table = {} # Cheia va fi (ip, mask), Valoarea va fi {metric, next_hop, timestamp, ...}
        self.lock = threading.Lock() # Mai multe fire de executie vor citi/scrie simultan acest tabel

    def add_local_route(self, ip, mask):
        with self.lock:
            dest_key = (ip, mask)

            self.table[dest_key] = {
                'metric': 0,
                'next_hop': "0.0.0.0",
                'timestamp': time.time(),
                'garbage_collection': False,
                'is_local': True
            }

    def update(self, entry, sender_ip):
        # Implementare Bellman-Ford
        with self.lock:
            dest_key = (entry.ip, entry.mask)

            # Ignoram rutele locale invatate din interfete
            if dest_key in self.table and self.table[dest_key].get('is_local', False):
                return

            # Calculam metrica noua (Adaugam un hop pentru fiecare router trecut)
            new_metric = entry.metric + 1

            # Definim infinitul ca fiind 16
            if new_metric > 16:
                new_metric = 16

            # Daca ruta noua e valida, o 'invatam'
            if dest_key not in self.table:
                if new_metric < 16:
                    print(f"[+] Ruta NOUA invatata: {entry.ip}/{entry.mask} via {sender_ip} (Metric: {new_metric})")
                    self.add_route(dest_key, new_metric, sender_ip)
                return

            current_route = self.table[dest_key]

            # Rastauram ruta daca era in GC si am primit o actualizare valida
            if current_route.get('garbage_collection', False) and new_metric < 16:
                print(f"[*] Ruta RESTAURATA: {entry.ip}/{entry.mask} via {sender_ip} (Metric: {new_metric})")
                self.add_route(dest_key, new_metric, sender_ip)
                return

            # Actualizam ruta daca am gasit un drum mai bun
            if new_metric < current_route['metric']:
                print(
                    f"[*] Ruta ACTUALIZATA (drum mai bun): {entry.ip}/{entry.mask} via {sender_ip} (Metric vechi: {current_route['metric']} -> Nou: {new_metric})")
                self.add_route(dest_key, new_metric, sender_ip)

            # Actualizam din acelasi next-hop (modificare sau refresh a topologiei)
            elif current_route['next_hop'] == sender_ip:
                self.table[dest_key]['timestamp'] = time.time()

                if current_route['metric'] != new_metric:
                    print(f"[*] Ruta ACTUALIZATA (schimbare topologie): {entry.ip}/{entry.mask} Metric: {new_metric}")
                    self.table[dest_key]['metric'] = new_metric

                    # Marcam pentru GC daca ruta a devenit inaccesibila
                    if new_metric >= 16:
                        self.table[dest_key]['garbage_collection'] = True
                        self.table[dest_key]['gc_timestamp'] = time.time()

    def add_route(self, key, metric, next_hop):
        self.table[key] = {
            'metric': metric,
            'next_hop': next_hop,
            'timestamp': time.time(),
            'garbage_collection': False
        }

    def check_timeouts(self):
        with self.lock:
            current_time = time.time()
            to_delete = []

            for dest_key, route in self.table.items():
                # Ignoram rutele locale
                if route.get('is_local', False):
                    continue

                # Stergem rutele care ai fost in GC prea mult timp
                if route.get('garbage_collection', False):
                    gc_time = route.get('gc_timestamp', current_time)

                    if current_time - gc_time > GARBAGE_COLLECTION:
                        print(f"[-] Ruta STEARSA (Garbage Collection): {dest_key[0]}/{dest_key[1]}")
                        to_delete.append(dest_key)

                # Marcam timeout pentru GC
                elif current_time - route['timestamp'] > ROUTE_TIMEOUT:
                    print(f"[!] Ruta TIMEOUT: {dest_key[0]}/{dest_key[1]} (Metric -> 16)")
                    route['metric'] = 16
                    route['garbage_collection'] = True
                    route['gc_timestamp'] = current_time

            for key in to_delete:
                del self.table[key]

    def get_entries(self):
        with self.lock:
            return dict(self.table)

    def __str__(self):
        with self.lock:
            output = "\n=== TABELA DE RUTARE CURENTA ===\n"
            # < aliniere stanga
            output += f"{'Network':<18} {'Mask':<18} {'Next Hop':<15} {'Metric':<10} {'Age (sec)':<10}\n"
            output += "-" * 85 + "\n"

            current_time = time.time()
            # Sorted pentru o consistenta a rutelor in tabel cand acestea sunt afisate
            for (ip, mask), data in sorted(self.table.items()):
                age = int(current_time - data['timestamp'])

                if data.get('is_local'):
                    status = "LOCAL"
                    age = "-"
                elif data.get('garbage_collection'):
                    status = "GC"
                else:
                    status = "OK"

                output += f"{ip:<18} {mask:<18} {data['next_hop']:<15} {data['metric']:<10} {age:<10} {status:<10}\n"

            if not self.table:
                output += "(gol)\n"

            return output


def get_interfaces_info():
    interfaces = []

    # psutil pentru a gasi toate retelele si adresele sale
    for iface_name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            # Procesam doar adresele IPv4
            if addr.family == socket.AF_INET:
                # Ignoram NAT si loopback
                if any(addr.address.startswith(prefix) for prefix in IGNORED_NETWORKS):
                    continue

                # Extragem datele legate de IPv4
                ip_obj = ipaddress.IPv4Address(addr.address)
                mask_obj = ipaddress.IPv4Address(addr.netmask)

                # Normalizam adresa de retea - extragem adresa de retea avand adresa unui router
                network = ipaddress.IPv4Network(f"{ip_obj}/{mask_obj}", strict=False)
                interfaces.append({
                    'name': iface_name,
                    'ip': str(addr.address),
                    'mask': str(addr.netmask),
                    'network_str': str(network.network_address),
                    'network_obj': network # Obiect tip retea pentru comparatii
                })
    return interfaces

# Firul (background) care periodic trimite pachete RIP la vecini
def sender_thread(routing_table, sock):
    print("[Sender Thread] Pornit...")
    last_cleanup = time.time()

    # Rulam la infinit fiind daemon, se inchide odata cu programul principal
    while True:
        current_time = time.time()

        # Eliminare periodica a rutelor expirate
        if current_time - last_cleanup > UPDATE_INTERVAL:
            routing_table.check_timeouts()
            last_cleanup = current_time

        # Extragem interfetele + tabelul de rutare curent
        interfaces = get_interfaces_info()
        current_table = routing_table.get_entries()

        # Trimitem update de la fiecare interfata
        for iface in interfaces:
            sender_ip = iface['ip']
            sender_network = iface['network_obj']

            packet = RIPpackage(command=2, version=2)

            for (r_ip, r_mask), data in current_table.items():
                route_network = ipaddress.IPv4Network(f"{r_ip}/{r_mask}", strict=False)

                # Nu promovam reteaua inapoi catre aceeasi interfata (split horizon - eliminare bucle)
                if route_network == sender_network:
                    continue

                # Extragem metrica care va fi promovata
                out_metric = data['metric']
                next_hop_ip = ipaddress.IPv4Address(data['next_hop']) if data['next_hop'] != "0.0.0.0" else None

                # Split horizon cu poison reverse
                # Daca am invatat ruta de la un vecin pe aceasta interfata, anuntam metrica 16
                if next_hop_ip and next_hop_ip in sender_network:
                    packet.add_entry(RIPEntry(ip=r_ip, mask=r_mask, next_hop="0.0.0.0", metric=16))
                else:
                    # Promovare normala in caz contrar
                    packet.add_entry(RIPEntry(ip=r_ip, mask=r_mask, next_hop="0.0.0.0", metric=out_metric))

            # Daca avem rute de promovat, trimitem pachete
            if packet.entries:
                try:
                    # Setam interfata de la care trimitem
                    # IP_MULTICAST_IF specifica interfata pentru pachetele multicast
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(sender_ip))
                    sock.sendto(packet.pack(), (MULTICAST_GROUP, MULTICAST_PORT))

                    print(f" -> Trimitere update pe {iface['name']} ({len(packet.entries)} rute)")
                except Exception as e:
                    print(f"Eroare trimitere de la {sender_ip}: {e}")

        print(routing_table)
        time.sleep(UPDATE_INTERVAL)


# Functia principala unde este setat si rulat ruterul RIP
def main():
    print("=" * 60)
    print(f"Update Interval: {UPDATE_INTERVAL}s")
    print(f"Route Timeout: {ROUTE_TIMEOUT}s")
    print(f"Garbage Collection: {GARBAGE_COLLECTION}s")
    print("=" * 60)
    print("Start Router (Multicast Receiver)...")

    # Cream socket UDP
    router = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # SOL_SOCKET - aplicam optiunea pentru insasi socket
    # SO_REUSEADDR permite conectarea mai multor programe la acelasi port
    router.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Time To Live
    # IP_MULTICAST_TTL=1 inseamna ca pachetele multicast ajung doar in reteaua locala
    # TTL=1 inseamna ca pachetele se termina dupa un salt
    router.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

    # Facem bind la portul 520 pe toate interfetele
    # Permite sa primim pachete RIP
    router.bind(('0.0.0.0', MULTICAST_PORT))

    interfaces = get_interfaces_info()
    print(f"\nInterfete gasite: {[(i['name'], i['ip']) for i in interfaces]}")
    print(f"Alaturare la grupul multicast {MULTICAST_GROUP}...\n")

    # Alaturare grup multicast pe fiecare interfata
    for iface in interfaces:
        try:
            # Cream structura cererii de aderare (Multicast request)
            mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton(iface['ip'])

            # IP_ADD_MEMBERSHIP - alaturare grupului
            router.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            print(f"Alaturat pe {iface['name']} ({iface['ip']})")
        except Exception as e:
            print(f"Nu s-a putut alatura pe {iface['ip']}: {e}")

    print("\n=== Router Gata ===\n")

    my_routing_table = RoutingTable()

    print("\n[Init] Adaugare interfete locale la tabela de rutare...")
    for iface in interfaces:
        my_routing_table.add_local_route(iface['network_str'], iface['mask'])
        print(f" + Rutele locale adaugate: {iface['network_str']}/{iface['mask']}")

    # Creare si pornire a firului de executie care trimite pachetele
    # daemon=True inseamna ca firul deexecutie se va inchide automat cand programul principal se inchide
    sender = threading.Thread(target=sender_thread, args=(my_routing_table, router))
    sender.daemon = True
    sender.start()

    # Bucla principala de receive
    while True:
        try:
            # Ruterul asteapta pentru un pachet RIP (se blocheaza pana primeste unul)
            msg, neighbour = router.recvfrom(BUFFER_SIZE)

            # Extragem adresa IP a expeditorului
            sender_ip = neighbour[0]

            # Ignoram pachetele de la noi insine
            my_ips = [iface['ip'] for iface in get_interfaces_info()]
            if sender_ip in my_ips:
                continue

            rip_packet = RIPpackage.unpack(msg)

            # Implementarea data gestioneaza doar cereri tip 2
            if rip_packet.command == 2:  # Doar RESPONSE-urile contin actualizari
                print(f"\n[PRIMIT de la {sender_ip}]")
                print(f"Mesaj RIP cu {len(rip_packet.entries)} rute.")

                my_interfaces = get_interfaces_info()
                my_networks = [iface['network_str'] for iface in my_interfaces]

                # Procesam fiecare intrare
                for entry in rip_packet.entries:
                    if entry.ip in my_networks:
                        print(f"  - Ignoram reteaua proprie: {entry.ip}/{entry.mask}")
                        continue

                    # Ignoram metricile invalide
                    if entry.metric > 16:
                        continue

                    print(f"  * Procesare: {entry.ip}/{entry.mask} metric={entry.metric}")
                    my_routing_table.update(entry, sender_ip)
        except KeyboardInterrupt:
            print("\n\nOprire router...")
            break
        except Exception as e:
            print(f"Eroare: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
