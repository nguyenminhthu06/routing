from router import Router
from packet import Packet
import json

class LSrouter(Router):
    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)
        self.heartbeat_time = heartbeat_time
        self.last_time = 0
        self.topology = {}       # {router_addr: {neighbor_addr: cost}}
        self.sequences = {}      # {router_addr: seq_number}
        self.neighbor_map = {}   # {port: addr}
        self.neighbor_costs = {} # {addr: cost}
        self.forwarding_table = {}
        self.seq = 0             # sequence counter cho LSP của chính mình

    def handle_packet(self, port, packet):
        if packet.is_traceroute:
            if packet.dst_addr in self.forwarding_table:
                self.send(self.forwarding_table[packet.dst_addr], packet)
        else:
            msg = json.loads(packet.content)
            src = msg["src"]
            seq = int(msg["seq"])
            links = msg["links"]

            # Chỉ xử lý nếu đây là LSP mới hơn LSP đã lưu
            if src not in self.sequences or seq > self.sequences[src]:
                self.sequences[src] = seq
                self.topology[src] = links

                self.run_dijkstra()

                # Flood tiếp sang tất cả port trừ port nhận vào
                for p in self.links:
                    if p != port:
                        self.send(p, packet)

    def handle_new_link(self, port, endpoint, cost):
        self.neighbor_map[port] = endpoint
        self.neighbor_costs[endpoint] = cost

        # Cập nhật topology của chính mình
        if self.addr not in self.topology:
            self.topology[self.addr] = {}
        self.topology[self.addr][endpoint] = cost

        self.run_dijkstra()
        self.broadcast_lsp()

    def handle_remove_link(self, port):
        endpoint = self.neighbor_map.pop(port, None)
        if endpoint is not None:
            self.neighbor_costs.pop(endpoint, None)

            # Xóa edge trong topology của chính mình
            if self.addr in self.topology:
                self.topology[self.addr].pop(endpoint, None)

            # KHÔNG xóa topology[endpoint] — đó là LSP của router khác,
            # không phải quyền của mình chỉnh sửa. Router kia sẽ tự broadcast
            # LSP mới khi nó detect link fail. Xóa ở đây gây race condition.

        self.run_dijkstra()
        self.broadcast_lsp()

    def broadcast_lsp(self):
        self.seq += 1
        self.sequences[self.addr] = self.seq

        # Cập nhật topology của mình với neighbor_costs hiện tại
        self.topology[self.addr] = dict(self.neighbor_costs)

        content = json.dumps({
            "src": self.addr,
            "seq": self.seq,
            "links": self.neighbor_costs
        })
        for p in self.links:
            self.send(p, Packet(Packet.ROUTING, self.addr, None, content))

    def run_dijkstra(self):
        distances = {self.addr: 0}
        parents = {}
        unvisited = set(self.topology.keys())
        unvisited.add(self.addr)

        while unvisited:
            # Lấy node có khoảng cách nhỏ nhất chưa được thăm
            u = min(unvisited, key=lambda x: distances.get(x, float("inf")))
            if distances.get(u, float("inf")) == float("inf"):
                break
            unvisited.remove(u)

            for v, cost in self.topology.get(u, {}).items():
                new_dist = distances[u] + cost
                if new_dist < distances.get(v, float("inf")):
                    distances[v] = new_dist
                    parents[v] = u

        # Xây forwarding table: trace ngược về first-hop neighbor
        new_table = {}
        addr_to_port = {a: p for p, a in self.neighbor_map.items()}

        for dst in distances:
            if dst == self.addr:
                continue
            # Đi ngược từ dst về đến node ngay sau self.addr
            curr = dst
            while parents.get(curr) is not None and parents[curr] != self.addr:
                curr = parents[curr]
            # curr bây giờ là first-hop neighbor
            if curr in addr_to_port:
                new_table[dst] = addr_to_port[curr]

        self.forwarding_table = new_table

    def handle_time(self, time_ms):
        if time_ms - self.last_time >= self.heartbeat_time:
            self.last_time = time_ms
            self.broadcast_lsp()

    def __repr__(self):
        return (f"LSrouter(addr={self.addr}, "
                f"seq={self.seq}, "
                f"neighbors={list(self.neighbor_costs.keys())}, "
                f"fwd={self.forwarding_table})")