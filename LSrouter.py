# Link State Routing — Dijkstra
# Mỗi router flood LSP (Link State Packet) chứa danh sách neighbor + cost của mình.
# Nhận LSP từ router khác → cập nhật topology → chạy Dijkstra → cập nhật forwarding table.
# Sequence number trên LSP đảm bảo chỉ xử lý gói mới hơn, tránh flood vòng lặp.

from router import Router
from packet import Packet
import json


class LSrouter(Router):
    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)
        self.heartbeat_time = heartbeat_time
        self.last_time = 0
        self.topology = {}        # Bản đồ toàn mạng: {router: {neighbor: cost}}
        self.sequences = {}       # Seq mới nhất đã xử lý: {router: seq}
        self.neighbor_map = {}    # {port: neighbor_addr}
        self.neighbor_costs = {}  # {neighbor_addr: cost}
        self.forwarding_table = {}  # {dst: out_port}
        self.seq = 0              # Sequence counter cho LSP của chính mình

    def handle_packet(self, port, packet):
        if packet.is_traceroute:
            if packet.dst_addr in self.forwarding_table:
                self.send(self.forwarding_table[packet.dst_addr], packet)
        else:
            msg = json.loads(packet.content)
            src, seq, links = msg["src"], int(msg["seq"]), msg["links"]

            # Chỉ xử lý LSP mới hơn, bỏ qua gói cũ/trùng
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
        if self.addr not in self.topology:
            self.topology[self.addr] = {}
        self.topology[self.addr][endpoint] = cost
        self.run_dijkstra()
        self.broadcast_lsp()

    def handle_remove_link(self, port):
        endpoint = self.neighbor_map.pop(port, None)
        if endpoint is not None:
            self.neighbor_costs.pop(endpoint, None)
            if self.addr in self.topology:
                self.topology[self.addr].pop(endpoint, None)
            # Không xóa topology[endpoint] — router kia tự broadcast LSP mới khi nó
            # detect link fail. Xóa ở đây gây race condition.
        self.run_dijkstra()
        self.broadcast_lsp()

    def broadcast_lsp(self):
        """Tăng seq, cập nhật topology của mình, flood LSP ra tất cả neighbor."""
        self.seq += 1
        self.sequences[self.addr] = self.seq
        self.topology[self.addr] = dict(self.neighbor_costs)
        content = json.dumps({"src": self.addr, "seq": self.seq, "links": self.neighbor_costs})
        for p in self.links:
            self.send(p, Packet(Packet.ROUTING, self.addr, None, content))

    def run_dijkstra(self):
        """Chạy Dijkstra trên topology, trace ngược parents để xây forwarding_table."""
        distances = {self.addr: 0}
        parents = {}
        unvisited = set(self.topology.keys()) | {self.addr}

        while unvisited:
            u = min(unvisited, key=lambda x: distances.get(x, float("inf")))
            if distances.get(u, float("inf")) == float("inf"):
                break
            unvisited.remove(u)
            for v, cost in self.topology.get(u, {}).items():
                new_dist = distances[u] + cost
                if new_dist < distances.get(v, float("inf")):
                    distances[v] = new_dist
                    parents[v] = u

        # Trace ngược từ dst về self.addr để tìm first-hop, rồi map sang port
        new_table = {}
        addr_to_port = {a: p for p, a in self.neighbor_map.items()}
        for dst in distances:
            if dst == self.addr:
                continue
            curr = dst
            while parents.get(curr) is not None and parents[curr] != self.addr:
                curr = parents[curr]
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