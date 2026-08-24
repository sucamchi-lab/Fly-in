"""The turn-by-turn routing engine.
Every turn, each drone looks at its neighbouring zones and steps
to whichever is closest to the goal and has room.

This keeps drones from looping (they only ever move closer to the goal)
and from deadlocking: drones closest to the goal move first each turn,
so the zone ahead of them is always freed up in time.

Zone occupancy is tracked across turns. A drone crossing to a restricted
zone reserves its landing spot the moment it leaves, so it's guaranteed
to land on schedule. Link occupancy is rebuilt every turn, since a link
is only busy while a drone is actually crossing it.
"""

from dataclasses import dataclass, field

from graph import Graph


class RoutingError(Exception):
    """Raised when the drones cannot all be delivered.
    Inherits from Exception so it can be caught and reported to the user.
    """


@dataclass
class Drone:
    """One drone, its current state and destination."""

    drone_id: int
    zone: str
    destination: str | None = None
    arrival_in: int = 0

    def in_flight(self) -> bool:
        """True while the drone is crossing a connection."""
        return self.destination is not None

    def land(self) -> str:
        """Finish a crossing and move the drone into its destination."""
        if self.destination is None:
            raise RoutingError(f"D{self.drone_id} is not in flight")
        self.zone = self.destination
        self.destination = None
        return self.zone


@dataclass
class TurnResult:
    """What happened during one turn: each drone's move."""
    moves: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return " ".join(self.moves)


class Simulation:
    """Moves a fleet of drones from the start hub to the end hub.

    Call :meth:`step` to advance one turn, or :meth:`run` to play the
    whole simulation out. The visualizer uses the former; the
    command-line output uses the latter.
    """

    #: A simulation needing more turns than this is assumed to be stuck.
    MAX_TURNS = 10000

    def __init__(self, graph: Graph, nb_drones: int) -> None:
        """Place every drone at the start hub, ready to fly."""
        self.graph = graph
        self.distances = graph.distances_to_goal()
        if graph.start not in self.distances:
            raise RoutingError(
                f"no route from {graph.start!r} to {graph.end!r}")

        self.drones = [
            Drone(drone_id=i, zone=graph.start)
            for i in range(1, nb_drones + 1)
        ]
        self.turn = 0
        # Occupancy of each zone, carried across turns.
        self._zone_load: dict[str, int] = {graph.start: nb_drones}

    def delivered_count(self) -> int:
        """How many drones have reached the goal."""
        return sum(1 for drone in self.drones if self.is_delivered(drone))

    def finished(self) -> bool:
        """True once every drone has reached the goal."""
        return self.delivered_count() == len(self.drones)

    def is_delivered(self, drone: Drone) -> bool:
        """True if a drone is sitting in the end hub."""
        return not drone.in_flight() and drone.zone == self.graph.end

    def step(self) -> TurnResult:
        """Advance the simulation by one turn.

        Drones already in flight are handled first: they keep their
        connection busy and land if they are due. The rest then move in
        order of how close they are to the goal, so a drone leaving a
        zone frees its slot in time for the drone behind it.
        """
        self.turn += 1
        result = TurnResult()
        # Rebuilt every turn: a link is only busy while it is being flown.
        link_load: dict[tuple[str, str], int] = {}

        # Settled before any flight lands, because landing *is* a drone's
        # move for the turn : it must not then fly on as well.
        # Sorted nearest the goal first.
        grounded = sorted(
            (
                drone for drone in self.drones
                if not drone.in_flight() and not self.is_delivered(drone)
            ),
            key=lambda drone: self.distances[drone.zone])

        # Flights are resolved first all the same, so that the links they
        # are still occupying are visible to everyone choosing a step.
        for drone in self.drones:
            if drone.destination is not None:
                self._advance_flight(
                    drone, drone.destination, link_load, result)

        for drone in grounded:
            target = self._choose_step(drone, link_load)
            if target is not None:
                self._depart(drone, target, link_load, result)

        if not result.moves and not self.finished():
            raise RoutingError(
                f"deadlock on turn {self.turn}: "
                f"{len(self.drones) - self.delivered_count()} "
                f"drones cannot move")
        return result

    def run(self) -> list[TurnResult]:
        """Play the simulation to completion, one TurnResult per turn."""
        results: list[TurnResult] = []
        while not self.finished():
            if self.turn >= self.MAX_TURNS:
                raise RoutingError(f"gave up after {self.MAX_TURNS} turns")
            results.append(self.step())
        return results

    def _advance_flight(
        self,
        drone: Drone,
        destination: str,
        link_load: dict[tuple[str, str], int],
        result: TurnResult,
    ) -> None:
        """Keep an in-flight drone's connection busy, and land it if due.

        The destination slot was already reserved on departure, so
        landing needs no capacity check.
        """
        self._occupy_link(drone.zone, destination, link_load)
        drone.arrival_in -= 1
        if drone.arrival_in <= 0:
            result.moves.append(f"D{drone.drone_id}-{drone.land()}")

    def _choose_step(
        self, drone: Drone, link_load: dict[tuple[str, str], int]
    ) -> str | None:
        """Pick the best zone for a drone to move into this turn, or None
        if it should wait.

        Only zones strictly closer to the goal are considered, so drones
        never circle. Among those, the closest wins, priority zones
        breaking ties.
        """
        here = drone.zone
        remaining = self.distances[here]
        candidates = [
            neighbor for neighbor in self.graph.neighbors(here)
            # skip zones that are further from the goal, full, or busy
            if self.distances.get(neighbor, remaining) < remaining
            and self._has_room(neighbor)
            and self._link_is_free(here, neighbor, link_load)
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda name: self.graph.route_rank(name, self.distances))

    def _depart(
        self,
        drone: Drone,
        target: str,
        link_load: dict[tuple[str, str], int],
        result: TurnResult,
    ) -> None:
        """Send a drone from origin to target, reserving the landing slot"""
        origin = drone.zone
        self._occupy_link(origin, target, link_load)
        self._zone_load[origin] -= 1
        self._zone_load[target] = self._zone_load.get(target, 0) + 1

        crossing_turns = self.graph.zone(target).entry_cost()
        if crossing_turns == 1:
            drone.zone = target
            result.moves.append(f"D{drone.drone_id}-{target}")
        else:
            # The departure turn is the first of the crossing, so only
            # the remaining turns are counted down.
            drone.destination = target
            drone.arrival_in = crossing_turns - 1
            result.moves.append(f"D{drone.drone_id}-{origin}-{target}")

    def _has_room(self, zone_name: str) -> bool:
        """True if a zone is start/end or below its capacity."""
        zone = self.graph.zone(zone_name)
        if zone.is_hub():
            return True
        return self._zone_load.get(zone_name, 0) < zone.max_drones

    def _link_is_free(
        self,
        zone_a: str,
        zone_b: str,
        link_load: dict[tuple[str, str], int],
    ) -> bool:
        """True if the connection exists and has room for one more drone."""
        connection = self.graph.link(zone_a, zone_b)
        if connection is None:
            return False
        used = link_load.get(connection.key(), 0)
        return used < connection.max_link_capacity

    def _occupy_link(
        self,
        zone_a: str,
        zone_b: str,
        link_load: dict[tuple[str, str], int],
    ) -> None:
        """Record that one more drone is using a connection this turn."""
        connection = self.graph.link(zone_a, zone_b)
        if connection is not None:
            key = connection.key()
            link_load[key] = link_load.get(key, 0) + 1
