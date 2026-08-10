"""The zone network, and the pathfinding done on it.

:class:`Graph` wraps the parsed map in the two lookups the simulation
actually needs — "who are my neighbours?" and "which connection joins
these two zones?" — and runs Dijkstra's algorithm over it.

Only one search is ever needed. Rather than computing a route per drone,
the graph is searched **once, backwards from the goal**, producing the
cost in turns from every zone to the goal. Every drone then simply steps
to whichever reachable neighbour has the lowest remaining cost. That
single table is what makes routing cheap: it is computed once, and each
drone's decision afterwards is a scan of its own neighbours.

Edge weights come from the destination zone's type: entering a normal or
priority zone costs 1 turn, entering a restricted zone costs 2, and
blocked zones are removed from the graph entirely so no route can use
them.
"""

from __future__ import annotations

import heapq

from parser import Connection, MapData, Zone


class Graph:
    """An undirected graph of zones, with cost-aware pathfinding.

    Blocked zones are dropped when the adjacency is built, so every
    method below can assume that whatever it returns is flyable.

    Attributes:
        zones: Every zone from the map, keyed by name, including blocked
            ones (the visualizer still draws them).
        connections: Every connection from the map, in file order.
        start: Name of the start hub.
        end: Name of the end hub.
    """

    def __init__(self, map_data: MapData) -> None:
        """Build the adjacency and link lookups from a parsed map.

        Args:
            map_data: The output of :class:`parser.MapParser`.
        """
        self.zones = map_data.zones
        self.connections = map_data.connections
        self.start = map_data.start_zone
        self.end = map_data.end_zone

        self._neighbors: dict[str, list[str]] = {
            name: [] for name in self.zones
        }
        self._links: dict[tuple[str, str], Connection] = {}

        for connection in self.connections:
            zone_a = self.zones[connection.zone_a]
            zone_b = self.zones[connection.zone_b]
            # A link that touches a blocked zone can never be flown, so
            # it is left out of the graph rather than checked repeatedly
            # at every step of the simulation.
            if zone_a.is_blocked or zone_b.is_blocked:
                continue
            self._neighbors[zone_a.name].append(zone_b.name)
            self._neighbors[zone_b.name].append(zone_a.name)
            self._links[connection.key] = connection

    def neighbors(self, zone_name: str) -> list[str]:
        """Return the names of the zones directly reachable from a zone.

        Args:
            zone_name: The zone to look up.

        Returns:
            Neighbour names. Empty if the zone is unknown, blocked, or
            has no flyable link.
        """
        return self._neighbors.get(zone_name, [])

    def link(self, zone_a: str, zone_b: str) -> Connection | None:
        """Return the connection joining two zones, if there is one.

        Args:
            zone_a: One endpoint.
            zone_b: The other endpoint.

        Returns:
            The connection, or None if the two zones are not linked.
        """
        key = (zone_a, zone_b) if zone_a < zone_b else (zone_b, zone_a)
        return self._links.get(key)

    def distances_to_goal(self) -> dict[str, int]:
        """Cost in turns from every zone to the end hub.

        This is Dijkstra's algorithm run backwards from the goal. Because
        the graph is undirected and an edge's weight depends only on
        which zone you are entering, the cost of the step
        ``neighbour -> current`` is simply the entry cost of ``current``,
        which is what the search relaxes on.

        Returns:
            Zone name to remaining cost in turns. Zones from which the
            goal cannot be reached are absent, so a plain ``in`` test
            answers "is this zone usable at all?".
        """
        distances: dict[str, int] = {self.end: 0}
        queue: list[tuple[int, str]] = [(0, self.end)]

        while queue:
            distance, current = heapq.heappop(queue)
            if distance > distances[current]:
                continue  # A shorter route to `current` was already found.

            step_cost = self.zones[current].entry_cost
            new_distance = distance + step_cost
            for neighbor in self.neighbors(current):
                known = distances.get(neighbor)
                if known is None or new_distance < known:
                    distances[neighbor] = new_distance
                    heapq.heappush(queue, (new_distance, neighbor))

        return distances

    def shortest_path(
        self, start: str, distances: dict[str, int]
    ) -> list[str] | None:
        """Walk the cheapest route from a zone to the goal.

        With the distance table in hand there is nothing left to search:
        from each zone, step to the neighbour whose remaining cost is
        lowest. Priority zones win ties, which is how the subject's
        "prefer priority zones" rule is honoured.

        This is used for reporting and for the visualizer's route hints;
        the simulation itself makes the same choice one step at a time so
        that it can react to congestion.

        Args:
            start: Zone to start from.
            distances: Table from :meth:`distances_to_goal`.

        Returns:
            Zone names from ``start`` to the goal inclusive, or None if
            the goal is unreachable.
        """
        if start not in distances:
            return None

        path = [start]
        while path[-1] != self.end:
            current = path[-1]
            closer = [
                n for n in self.neighbors(current)
                if distances.get(n, distances[current]) < distances[current]
            ]
            # A zone with a finite distance always has a neighbour closer
            # to the goal, so this is a guard against a corrupt table
            # rather than an expected outcome.
            if not closer:
                return None
            path.append(
                min(closer, key=lambda n: self.route_rank(n, distances))
            )
        return path

    def route_rank(
        self, zone_name: str, distances: dict[str, int]
    ) -> tuple[int, bool]:
        """Sort key that ranks a candidate next hop, lowest first.

        Args:
            zone_name: The candidate neighbour.
            distances: Table from :meth:`distances_to_goal`.

        Returns:
            Remaining cost first, then whether the zone is *not* a
            priority zone — so that on equal cost, priority zones sort
            ahead of the rest.
        """
        return (distances[zone_name], not self.zones[zone_name].is_priority)

    def zone(self, zone_name: str) -> Zone:
        """Return a zone by name.

        Args:
            zone_name: The zone to look up.

        Returns:
            The zone.

        Raises:
            KeyError: If no zone by that name exists.
        """
        return self.zones[zone_name]
