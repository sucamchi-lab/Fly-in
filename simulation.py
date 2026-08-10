"""The turn-by-turn drone routing engine.

Routing here is *reactive* rather than planned. No drone is handed a
fixed itinerary at the start; instead every drone, on every turn, steps
to whichever neighbouring zone has the lowest remaining cost to the goal
and is not currently full. The remaining-cost table comes from a single
backwards Dijkstra run (see :mod:`graph`), so each decision is just a
scan of the current zone's neighbours.

Two properties make this both correct and fast:

*   **It cannot loop.** A drone only ever moves to a zone strictly closer
    to the goal, so its remaining cost falls every time it moves.
*   **It cannot deadlock.** Drones are moved nearest-the-goal first. The
    drone closest to the goal always has a free step available — the
    zone ahead of it can only be held by drones that are closer still,
    and those have already moved out this turn. Congestion therefore
    resolves itself instead of requiring detours, backtracking or
    tie-breaking heuristics.

Capacity is tracked in two places. Zone occupancy is a running count
held across turns, and a drone crossing toward a restricted zone
*reserves* its destination slot the moment it leaves — the subject
requires such a drone to land on schedule, so the space it will need
must not be handed to anyone else meanwhile. Link occupancy is rebuilt
each turn, since a link is only busy for the duration of a crossing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from graph import Graph


class RoutingError(Exception):
    """Raised when the drones cannot all be delivered."""


@dataclass
class Drone:
    """One drone, and where it currently is.

    A drone is in exactly one of three states: sitting in a zone, in
    flight along a connection toward a restricted zone, or delivered.

    Attributes:
        drone_id: 1-based identifier, matching the ``D<ID>`` in the
            output.
        zone: The zone the drone occupies. While in flight this is the
            zone it departed from, which is what the output needs to
            name the connection it is on.
        destination: The restricted zone being flown to, or None when
            the drone is not in flight.
        arrival_in: Turns left before the drone must land. Only
            meaningful while in flight.
    """

    drone_id: int
    zone: str
    destination: str | None = None
    arrival_in: int = 0

    @property
    def in_flight(self) -> bool:
        """True while the drone is on a connection between two zones."""
        return self.destination is not None

    def land(self) -> str:
        """Complete a crossing, moving the drone into its destination.

        Returns:
            The zone just landed in.

        Raises:
            RoutingError: If called on a drone that is not in flight.
        """
        if self.destination is None:
            raise RoutingError(f"D{self.drone_id} is not in flight")
        self.zone = self.destination
        self.destination = None
        return self.zone


@dataclass
class TurnResult:
    """What happened during one simulation turn.

    Attributes:
        turn: 1-based turn number.
        moves: Movement tokens in the subject's format, one per drone
            that moved. A drone that stayed put is simply absent.
    """

    turn: int
    moves: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Render the turn as the single output line the subject asks for."""
        return " ".join(self.moves)


class Simulation:
    """Moves a fleet of drones from the start hub to the end hub.

    Call :meth:`step` to advance one turn, or :meth:`run` to play the
    whole simulation out. The visualizer drives the former; the
    command-line output uses the latter.

    Attributes:
        graph: The zone network being flown.
        distances: Remaining cost in turns from each zone to the goal.
        drones: Every drone, in ID order.
        turn: How many turns have elapsed.
    """

    #: A simulation needing more turns than this is assumed to be stuck.
    MAX_TURNS = 10_000

    def __init__(self, graph: Graph, nb_drones: int) -> None:
        """Place every drone at the start hub, ready to fly.

        Args:
            graph: The zone network, already built from a parsed map.
            nb_drones: How many drones to route.

        Raises:
            RoutingError: If the goal cannot be reached from the start,
                which would make the simulation unwinnable.
        """
        self.graph = graph
        self.distances = graph.distances_to_goal()
        if graph.start not in self.distances:
            raise RoutingError(
                f"no route from {graph.start!r} to {graph.end!r}"
            )

        self.drones = [
            Drone(drone_id=i, zone=graph.start)
            for i in range(1, nb_drones + 1)
        ]
        self.turn = 0
        # Occupancy of each zone, carried across turns. Hubs are counted
        # too, purely so the bookkeeping has no special cases; their
        # capacity is never actually enforced.
        self._zone_load: dict[str, int] = {graph.start: nb_drones}

    @property
    def delivered_count(self) -> int:
        """How many drones have reached the goal."""
        return sum(1 for drone in self.drones if self.is_delivered(drone))

    @property
    def finished(self) -> bool:
        """True once every drone has reached the goal."""
        return self.delivered_count == len(self.drones)

    def is_delivered(self, drone: Drone) -> bool:
        """Check whether a drone has arrived at the goal.

        Args:
            drone: The drone to check.

        Returns:
            True if it is sitting in the end hub.
        """
        return not drone.in_flight and drone.zone == self.graph.end

    def step(self) -> TurnResult:
        """Advance the simulation by one turn.

        Drones already in flight are handled first: they keep their
        connection busy and land if they are due. The remaining drones
        then move in order of how close they are to the goal, so that a
        drone leaving a zone frees its slot in time for the drone behind
        it to take it — which is exactly the rule the subject states.

        Returns:
            The movements that happened this turn.

        Raises:
            RoutingError: If no drone could move and the fleet is not
                yet delivered, which would mean a deadlock.
        """
        self.turn += 1
        result = TurnResult(turn=self.turn)
        # Rebuilt every turn: a link is only busy while it is being flown.
        link_load: dict[tuple[str, str], int] = {}

        # Settled before any flight lands, because landing *is* a drone's
        # move for the turn — it must not then fly on as well. Sorted
        # nearest the goal first; see the class docstring for why that
        # ordering is what keeps the fleet from deadlocking.
        grounded = sorted(
            (
                drone for drone in self.drones
                if not drone.in_flight and not self.is_delivered(drone)
            ),
            key=lambda drone: self.distances[drone.zone],
        )

        # Flights are resolved first all the same, so that the links they
        # are still occupying are visible to everyone choosing a step.
        for drone in self.drones:
            if drone.destination is not None:
                self._advance_flight(
                    drone, drone.destination, link_load, result
                )

        for drone in grounded:
            target = self._choose_step(drone, link_load)
            if target is not None:
                self._depart(drone, target, link_load, result)

        if not result.moves and not self.finished:
            raise RoutingError(
                f"deadlock on turn {self.turn}: "
                f"{len(self.drones) - self.delivered_count} "
                f"drones cannot move"
            )
        return result

    def run(self) -> list[TurnResult]:
        """Play the simulation to completion.

        Returns:
            One :class:`TurnResult` per turn, in order.

        Raises:
            RoutingError: On deadlock, or if the fleet is somehow still
                flying after :attr:`MAX_TURNS` turns.
        """
        results: list[TurnResult] = []
        while not self.finished:
            if self.turn >= self.MAX_TURNS:
                raise RoutingError(
                    f"gave up after {self.MAX_TURNS} turns"
                )
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

        The destination slot was reserved when the drone departed, so
        landing needs no capacity check — which is what guarantees the
        subject's rule that a drone crossing to a restricted zone can
        never be made to wait on the connection.

        Args:
            drone: A drone that is currently crossing a connection.
            destination: The zone it is crossing toward.
            link_load: Per-turn link usage, updated in place.
            result: The turn being built, appended to on landing.
        """
        self._occupy_link(drone.zone, destination, link_load)
        drone.arrival_in -= 1
        if drone.arrival_in <= 0:
            result.moves.append(f"D{drone.drone_id}-{drone.land()}")

    def _choose_step(
        self, drone: Drone, link_load: dict[tuple[str, str], int]
    ) -> str | None:
        """Pick the best zone for a drone to move into this turn.

        Only zones strictly closer to the goal are considered, which is
        what stops drones from circling. Among those, the closest wins,
        and a priority zone beats a normal one at equal cost.

        Args:
            drone: The drone deciding where to go.
            link_load: Per-turn link usage so far.

        Returns:
            The zone to move into, or None if the drone should wait
            because every useful neighbour is full or its link is busy.
        """
        here = drone.zone
        remaining = self.distances[here]
        candidates = [
            neighbor for neighbor in self.graph.neighbors(here)
            # `.get(..., remaining)` makes zones that cannot reach the
            # goal compare as "no improvement", so they are skipped.
            if self.distances.get(neighbor, remaining) < remaining
            and self._has_room(neighbor)
            and self._link_is_free(here, neighbor, link_load)
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda name: self.graph.route_rank(name, self.distances),
        )

    def _depart(
        self,
        drone: Drone,
        target: str,
        link_load: dict[tuple[str, str], int],
        result: TurnResult,
    ) -> None:
        """Send a drone out of its zone toward ``target``.

        The drone frees its old slot and claims the new one immediately,
        even when the trip takes two turns: reserving the destination up
        front is what lets a restricted-zone crossing be guaranteed to
        land on time.

        Args:
            drone: The drone to move.
            target: The zone it is heading for, already checked for room.
            link_load: Per-turn link usage, updated in place.
            result: The turn being built, appended to.
        """
        origin = drone.zone
        self._occupy_link(origin, target, link_load)
        self._zone_load[origin] -= 1
        self._zone_load[target] = self._zone_load.get(target, 0) + 1

        crossing_turns = self.graph.zone(target).entry_cost
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
        """Check whether another drone fits in a zone.

        Args:
            zone_name: The zone to check.

        Returns:
            True if the zone is a hub (which are unlimited) or is below
            its ``max_drones`` capacity.
        """
        zone = self.graph.zone(zone_name)
        if zone.is_hub:
            return True
        return self._zone_load.get(zone_name, 0) < zone.max_drones

    def _link_is_free(
        self,
        zone_a: str,
        zone_b: str,
        link_load: dict[tuple[str, str], int],
    ) -> bool:
        """Check whether a connection can take one more drone this turn.

        Args:
            zone_a: Zone being left.
            zone_b: Zone being entered.
            link_load: Per-turn link usage so far.

        Returns:
            True if the link exists and is below its
            ``max_link_capacity``.
        """
        connection = self.graph.link(zone_a, zone_b)
        if connection is None:
            return False
        used = link_load.get(connection.key, 0)
        return used < connection.max_link_capacity

    def _occupy_link(
        self,
        zone_a: str,
        zone_b: str,
        link_load: dict[tuple[str, str], int],
    ) -> None:
        """Record that one more drone is using a connection this turn.

        Args:
            zone_a: Zone being left.
            zone_b: Zone being entered.
            link_load: Per-turn link usage, updated in place.
        """
        connection = self.graph.link(zone_a, zone_b)
        if connection is not None:
            link_load[connection.key] = link_load.get(connection.key, 0) + 1
