"""Command-line entry point for the Fly-in drone routing simulation.

Reads a map file, routes every drone from the start hub to the end hub,
and prints one line per simulation turn in the format the subject
requires::

    D1-waypoint1
    D1-waypoint2 D2-waypoint1
    D1-goal D2-waypoint2
    D2-goal

Only those turn lines go to standard output, so the result can be piped
into another program or diffed directly. The run summary is written to
standard error, where it is still visible in a terminal but stays out of
the machine-readable stream.

Usage::

    python3 main.py maps/easy/01_linear_path.txt
    python3 main.py maps/hard/02_capacity_hell.txt --no-gui
"""

from __future__ import annotations

import argparse
import sys

from graph import Graph
from parser import MapParser, ParseError
from simulation import RoutingError, Simulation, TurnResult


class FlyInApp:
    """Wires the parser, the graph, the simulation and the display together."""

    def __init__(self, argv: list[str] | None = None) -> None:
        """Parse command-line arguments."""
        self.args = self.build_parser().parse_args(argv)

    @staticmethod
    def build_parser() -> argparse.ArgumentParser:
        """Describe the command-line interface."""
        parser = argparse.ArgumentParser(
            description="Route a fleet of drones across a network of zones.",
        )
        parser.add_argument("mapfile", help="path to the map file (.txt)")
        parser.add_argument(
            "--no-gui",
            action="store_true",
            help="skip the pygame window and print the turns only",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="break into pdb before the simulation starts",
        )
        return parser

    def run(self) -> int:
        """Run the whole program, returning 0 on success or 1 on failure.

        Any expected failure — a bad file, a bad map, an unreachable
        goal — is printed as a plain message instead of a traceback.
        """
        if self.args.debug:
            import pdb

            pdb.set_trace()  # noqa: T100  (intentional debug entry point)

        try:
            map_data = MapParser(self.args.mapfile).parse()
        except OSError as error:
            return self.fail(f"cannot read {self.args.mapfile!r}: {error}")
        except ParseError as error:
            return self.fail(f"{self.args.mapfile}: {error}")

        graph = Graph(map_data)
        try:
            simulation = Simulation(graph, map_data.nb_drones)
            results = simulation.run()
        except RoutingError as error:
            return self.fail(str(error))

        for result in results:
            print(result)
        self.report(simulation, results)

        if not self.args.no_gui:
            self.visualize(graph, map_data.nb_drones)
        return 0

    def visualize(self, graph: Graph, nb_drones: int) -> int:
        """Open the pygame window on the same map.

        pygame is imported here, not at the top of the file, so that
        ``--no-gui`` still works when it is not installed.
        """
        try:
            from visualizer import Visualizer
        except ImportError as error:
            return self.fail(
                f"pygame is required for the visualizer ({error}); "
                f"re-run with --no-gui"
            )
        Visualizer(graph, nb_drones).run()
        return 0

    @staticmethod
    def report(
        simulation: Simulation, results: list[TurnResult]
    ) -> None:
        """Write the run summary to standard error: turn count, plus the
        cheapest single-drone route as a baseline to compare against."""
        nb_drones = len(simulation.drones)
        moves = sum(len(result.moves) for result in results)
        turns = len(results)
        print(
            f"{nb_drones} drones delivered in {turns} turns "
            f"({moves} moves, {moves / turns:.1f} per turn, "
            f"{moves / nb_drones:.1f} per drone)",
            file=sys.stderr,
        )

        graph = simulation.graph
        route = graph.shortest_path(graph.start, simulation.distances)
        if route is not None:
            print(
                f"cheapest single-drone route "
                f"({simulation.distances[graph.start]} turns): "
                f"{' -> '.join(route)}",
                file=sys.stderr,
            )

    @staticmethod
    def fail(message: str) -> int:
        """Print an error and return 1, for ``return self.fail(...)``."""
        print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(FlyInApp().run())
