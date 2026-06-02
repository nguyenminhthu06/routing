# Distance Vector Routing — Bellman-Ford + Poison Reverse
# Mỗi router chỉ biết cost đến neighbor trực tiếp và DV neighbor gửi sang.
# Công thức: dist(self→dst) = min over n [ cost(self→n) + dist(n→dst) ]
# Poison Reverse: báo INFINITY ngược lại cho neighbor nếu đang route qua nó → giảm loop.
# INFINITY = 16 (chuẩn RIP, dùng thay float('inf') vì json không serialize được).

from router import Router
from packet import Packet
import json

INFINITY = 16


class DVrouter(Router):
    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)
        self.heartbeat_time = heartbeat_time
        self.last_time = 0
        self.my_dv = {self.addr: 0}  # DV của mình: {dst: best_cost}
        self.neighbor_dvs = {}        # DV nhận từ neighbor: {port: {dst: cost}}
        self.port_to_addr = {}        # {port: neighbor_addr}
        self.link_costs = {}          # {port: cost}
        self.forwarding_table = {}    # {dst: out_port}

    def handle_packet(self, port, packet):
        if packet.is_traceroute:
            if packet.dst_addr in self.forwarding_table:
                self.send(self.forwarding_table[packet.dst_addr], packet)
        else:
            dv = json.loads(packet.content)
            if self.neighbor_dvs.get(port) != dv:
                self.neighbor_dvs[port] = dv
                if self.update_dv():
                    self.broadcast_dv()

    def handle_new_link(self, port, endpoint, cost):
        self.port_to_addr[port] = endpoint
        self.link_costs[port] = cost
        if self.update_dv():
            self.broadcast_dv()

    def handle_remove_link(self, port):
        self.neighbor_dvs.pop(port, None)
        self.port_to_addr.pop(port, None)
        self.link_costs.pop(port, None)
        if self.update_dv():
            self.broadcast_dv()

    def update_dv(self):
        """Tính lại DV theo Bellman-Ford. Trả về True nếu DV thay đổi."""
        old_dv = dict(self.my_dv)
        self.my_dv = {self.addr: 0}
        self.forwarding_table = {}

        all_dsts = set()
        for dv in self.neighbor_dvs.values():
            all_dsts.update(dv.keys())
        for addr in self.port_to_addr.values():
            all_dsts.add(addr)

        for dst in all_dsts:
            if dst == self.addr:
                continue
            best_cost, best_port = INFINITY, None

            for port, cost_to_n in self.link_costs.items():
                # Nếu dst chính là neighbor trên port này thì cost từ n→dst = 0
                if self.port_to_addr.get(port) == dst:
                    dist_from_n = 0
                else:
                    dist_from_n = self.neighbor_dvs.get(port, {}).get(dst, INFINITY)

                total = min(cost_to_n + dist_from_n, INFINITY)
                if total < best_cost:
                    best_cost, best_port = total, port

            if best_port is not None and best_cost < INFINITY:
                self.my_dv[dst] = best_cost
                self.forwarding_table[dst] = best_port

        return old_dv != self.my_dv

    def broadcast_dv(self):
        """Gửi DV đến tất cả neighbor, áp dụng Poison Reverse."""
        for port in self.links:
            poisoned_dv = {
                dst: (cost if self.forwarding_table.get(dst) != port else INFINITY)
                for dst, cost in self.my_dv.items()
            }
            dst_addr = self.port_to_addr.get(port)
            pkt = Packet(Packet.ROUTING, self.addr, dst_addr, json.dumps(poisoned_dv))
            self.send(port, pkt)

    def handle_time(self, time_ms):
        if time_ms - self.last_time >= self.heartbeat_time:
            self.last_time = time_ms
            self.broadcast_dv()

    def __repr__(self):
        return (f"DVrouter(addr={self.addr}, "
                f"dv={self.my_dv}, "
                f"fwd={self.forwarding_table})")