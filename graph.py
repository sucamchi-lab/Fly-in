"""The zone network and pathfinding algorithm.

Graph builds a simple adjacency list from the parsed map and
runs Dijkstra's algorithm over it, backwards from the goal. That
gives every zone its remaining cost to the goal, so a drone can just
look at its neighbours and step toward whichever is closest to the goal.

Entering a normal or priority zone costs 1 turn, a restricted zone costs
2, and blocked zones are skipped.
"""

import heapq

from parser import Connection, MapData


class Graph:
    """An undirected graph of zones with pathfinding."""

    def __init__(self, map_data: MapData) -> None:
        """Build a graph from the parsed map data."""
        self.zones = map_data.zones
        self.connections = map_data.connections
        self.start = map_data.start_zone
        self.end = map_data.end_zone

        self._neighbors: dict[str, list[str]] = {
            name: [] for name in self.zones}
        self._links: dict[tuple[str, str], Connection] = {}

        for connection in self.connections:
            zone_a = self.zones[connection.zone_a]
            zone_b = self.zones[connection.zone_b]
            if zone_a.is_blocked() or zone_b.is_blocked():
                continue
            self._neighbors[zone_a.name].append(zone_b.name)
            self._neighbors[zone_b.name].append(zone_a.name)
            self._links[connection.key()] = connection

    def neighbors(self, zone_name: str) -> list[str]:
        """Names of the zones directly reachable from a zone."""
        return self._neighbors.get(zone_name, [])

    def link(self, zone_a: str, zone_b: str) -> Connection | None:
        """The connection joining two zones, or None if there isn't one."""
        key = (zone_a, zone_b) if zone_a < zone_b else (zone_b, zone_a)
        return self._links.get(key)

    def distances_to_goal(self) -> dict[str, int]:
        """Cost in turns from every zone to the end hub.
        Dijkstra's algorithm runs backwards from the goal.
        Unreachable zones are skipped.
        """
        distances: dict[str, int] = {self.end: 0}
        queue: list[tuple[int, str]] = [(0, self.end)]

        while queue:
            distance, current = heapq.heappop(queue)
            if distance > distances[current]:
                continue  # A shorter route to `current` was already found.

            step_cost = self.zones[current].entry_cost()
            new_distance = distance + step_cost
            for neighbor in self.neighbors(current):
                known = distances.get(neighbor)
                if known is None or new_distance < known:
                    distances[neighbor] = new_distance
                    heapq.heappush(queue, (new_distance, neighbor))

        return distances

    def route_rank(
        self, zone_name: str, distances: dict[str, int]
    ) -> tuple[int, bool]:
        """Sort key for picking next move: lowest cost first, priority
        zones breaking ties."""
        return (distances[zone_name], not self.zones[zone_name].is_priority())
