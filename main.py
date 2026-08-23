"""Command-line entry point for the Fly-in drone routing simulation.

Reads a map file, routes every drone from the start hub to the end hub,
and prints one line per simulation turn.
"""

import argparse
import sys

from graph import Graph
from parser import MapParser, ParseError
from simulation import RoutingError, Simulation, TurnResult


class FlyIn:
    """Entry point for the Fly-in drone routing simulation."""

    def __init__(self, argv: list[str] | None = None) -> None:
        """Parse command-line arguments."""
        parser = argparse.ArgumentParser()
        parser.add_argument("mapfile")
        parser.add_argument("--no-gui", action="store_true")
        parser.add_argument("--debug", action="store_true")
        self.args = parser.parse_args(argv)

    def run(self) -> None:
        """Run the whole program with error handling and optional debugging."""
        if self.args.debug:
            import pdb
            pdb.set_trace()

        try:
            map_data = MapParser(self.args.mapfile).parse()
        except OSError as error:
            sys.exit(f"error: cannot read {self.args.mapfile!r}: {error}")
        except ParseError as error:
            sys.exit(f"error: {self.args.mapfile}: {error}")

        graph = Graph(map_data)
        try:
            simulation = Simulation(graph, map_data.nb_drones)
            results = simulation.run()
        except RoutingError as error:
            sys.exit(f"error: {error}")

        for result in results:
            print(result)
        self.report(simulation, results)

        if not self.args.no_gui:
            self.visualize(graph, map_data.nb_drones)

    @staticmethod
    def visualize(graph: Graph, nb_drones: int) -> None:
        """Open the pygame window."""
        try:
            from visualizer import Visualizer
        except ImportError:
            sys.exit("error: pygame is required for the visualizer")
        Visualizer(graph, nb_drones).run()

    @staticmethod
    def report(simulation: Simulation, results: list[TurnResult]) -> None:
        """Write the summary to standard error."""
        nb_drones = len(simulation.drones)
        turns = len(results)
        print(
            f"{nb_drones} drones delivered in {turns} turns",
            file=sys.stderr,
        )


if __name__ == "__main__":
    FlyIn().run()
