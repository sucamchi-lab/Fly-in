"""Parsing of Fly-in map files.

A map file describes the drone network: how many drones to route, the
zones (nodes) they fly through, and the connections (edges) between
those zones. This module turns such a file into the :class:`MapData`
value object that the rest of the program works with.

The file format is::

    nb_drones: 5

    start_hub: hub 0 0 [color=green]
    end_hub:   goal 10 10 [color=yellow]
    hub:       roof1 3 4 [zone=restricted color=red]
    connection: hub-roof1
    connection: hub-roof2 [max_link_capacity=2]

Lines starting with ``#`` and blank lines are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ParseError(Exception):
    """Raised when a map file does not respect the expected format.

    Carries the offending line number so the user gets a message that
    points straight at the problem. Line number 0 means the error
    concerns the file as a whole (e.g. a missing ``start_hub``).
    """

    def __init__(self, line_num: int, message: str) -> None:
        """Store the location and build the human-readable message.

        Args:
            line_num: 1-based line number, or 0 for whole-file errors.
            message: Description of what is wrong.
        """
        super().__init__(
            f"line {line_num}: {message}" if line_num
            else message
        )
        self.line_num = line_num
        self.message = message


@dataclass(frozen=True)
class Zone:
    """A zone (node) of the drone network.

    Attributes:
        name: Unique identifier. Contains no dashes and no spaces.
        x: Horizontal coordinate, used only for display.
        y: Vertical coordinate, used only for display.
        zone_type: One of ``normal``, ``blocked``, ``restricted`` or
            ``priority``.
        max_drones: How many drones may occupy the zone at once. Ignored
            for the start and end hubs, which are unlimited.
        color: Display colour from the map file, if any.
        is_start: True for the single ``start_hub`` zone.
        is_end: True for the single ``end_hub`` zone.
    """

    name: str
    x: int
    y: int
    zone_type: str = "normal"
    max_drones: int = 1
    color: str | None = None
    is_start: bool = False
    is_end: bool = False

    @property
    def entry_cost(self) -> int:
        """Number of turns a drone needs to enter this zone.

        Restricted zones take 2 turns; every other reachable zone takes
        1. Blocked zones are never entered, so they have no meaningful
        cost — callers must check :attr:`is_blocked` first.
        """
        return 2 if self.zone_type == "restricted" else 1

    @property
    def is_blocked(self) -> bool:
        """True if drones may neither enter nor pass through this zone."""
        return self.zone_type == "blocked"

    @property
    def is_priority(self) -> bool:
        """True if pathfinding should prefer this zone on equal cost."""
        return self.zone_type == "priority"

    @property
    def is_hub(self) -> bool:
        """True for the start and end zones, which have no capacity limit."""
        return self.is_start or self.is_end


@dataclass(frozen=True)
class Connection:
    """A bidirectional link between two zones.

    Attributes:
        zone_a: Name of one endpoint.
        zone_b: Name of the other endpoint.
        max_link_capacity: How many drones may be traversing this link
            at the same time.
    """

    zone_a: str
    zone_b: str
    max_link_capacity: int = 1

    @property
    def key(self) -> tuple[str, str]:
        """Endpoint names in sorted order, for use as a dict key.

        Connections are bidirectional, so ``a-b`` and ``b-a`` must map to
        the same entry in any lookup table.
        """
        return (self.zone_a, self.zone_b) if self.zone_a < self.zone_b \
            else (self.zone_b, self.zone_a)


@dataclass
class MapData:
    """Everything a map file describes, after parsing.

    Attributes:
        nb_drones: How many drones must be routed.
        zones: Every zone, keyed by name.
        connections: Every connection, in file order.
        start_zone: Name of the zone all drones start in.
        end_zone: Name of the zone all drones must reach.
    """

    nb_drones: int = 0
    zones: dict[str, Zone] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    start_zone: str = ""
    end_zone: str = ""


class MapParser:
    """Reads a map file and validates it into a :class:`MapData`.

    Each line is matched against the three shapes the format allows —
    the ``nb_drones`` header, a zone definition, or a connection — and
    anything else is rejected. Validation that needs the whole file
    (exactly one start hub, no duplicate connections, ...) happens as
    lines are consumed or in a final pass.

    Typical use::

        map_data = MapParser("maps/easy/01_linear_path.txt").parse()
    """

    #: Matches ``hub: name x y`` with an optional ``[...]`` metadata block.
    _ZONE_RE = re.compile(
        r"(start_hub|end_hub|hub):\s+(\S+)\s+(-?\d+)\s+(-?\d+)"
        r"(?:\s+\[(.*)\])?\s*$"
    )
    #: Matches ``connection: a-b`` with an optional ``[...]`` metadata block.
    _CONNECTION_RE = re.compile(
        r"connection:\s+(\S+?)-(\S+?)(?:\s+\[(.*)\])?\s*$"
    )
    #: A single ``key=value`` pair inside a metadata block.
    _META_RE = re.compile(r"(\w+)=(\S+)")

    VALID_ZONE_TYPES = frozenset(
        {"normal", "blocked", "restricted", "priority"}
    )

    def __init__(self, filepath: str) -> None:
        """Prepare a parser for a given file. Nothing is read yet.

        Args:
            filepath: Path to the ``.txt`` map file.
        """
        self.filepath = filepath
        self._data = MapData()
        self._seen_links: set[tuple[str, str]] = set()

    def parse(self) -> MapData:
        """Read the file and return its validated contents.

        Returns:
            The parsed map.

        Raises:
            ParseError: If the file breaks any rule of the format.
            OSError: If the file cannot be read (missing, no permission).
        """
        with open(self.filepath, "r", encoding="utf-8") as handle:
            lines = handle.readlines()

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            self._parse_line(line, line_num)

        self._validate()
        return self._data

    def _parse_line(self, line: str, line_num: int) -> None:
        """Dispatch one non-empty, non-comment line to its handler.

        Args:
            line: The stripped line.
            line_num: 1-based line number, for error messages.

        Raises:
            ParseError: If the line matches none of the known shapes.
        """
        if line.startswith("nb_drones:"):
            self._parse_nb_drones(line, line_num)
            return

        zone_match = self._ZONE_RE.fullmatch(line)
        if zone_match:
            self._parse_zone(zone_match, line_num)
            return

        connection_match = self._CONNECTION_RE.fullmatch(line)
        if connection_match:
            self._parse_connection(connection_match, line_num)
            return

        raise ParseError(line_num, f"unrecognised line: {line!r}")

    def _parse_nb_drones(self, line: str, line_num: int) -> None:
        """Handle the ``nb_drones: <n>`` header.

        Args:
            line: The stripped line.
            line_num: 1-based line number, for error messages.

        Raises:
            ParseError: If it appears twice, or the value is not a
                positive integer.
        """
        if self._data.nb_drones:
            raise ParseError(line_num, "nb_drones is defined more than once")

        value = line[len("nb_drones:"):].strip()
        if not value.isdigit() or int(value) < 1:
            raise ParseError(
                line_num,
                f"nb_drones must be a positive integer, got {value!r}",
            )
        self._data.nb_drones = int(value)

    def _parse_zone(self, match: re.Match[str], line_num: int) -> None:
        """Build a :class:`Zone` from a matched zone definition.

        Args:
            match: Result of matching :attr:`_ZONE_RE`.
            line_num: 1-based line number, for error messages.

        Raises:
            ParseError: On a duplicate name, a dash in the name, a second
                start/end hub, or invalid metadata.
        """
        prefix, name = match.group(1), match.group(2)
        metadata = self._parse_metadata(
            match.group(5), line_num,
            allowed={"zone", "color", "max_drones"},
        )

        # The connection syntax uses `a-b`, so a dash in a name would
        # make connections ambiguous.
        if "-" in name:
            raise ParseError(line_num, f"zone name {name!r} contains a dash")
        if name in self._data.zones:
            raise ParseError(line_num, f"duplicate zone name {name!r}")

        zone_type = metadata.get("zone", "normal")
        if zone_type not in self.VALID_ZONE_TYPES:
            raise ParseError(
                line_num,
                f"unknown zone type {zone_type!r} (expected one of "
                f"{', '.join(sorted(self.VALID_ZONE_TYPES))})",
            )

        is_start, is_end = prefix == "start_hub", prefix == "end_hub"
        for flag, existing, label in (
            (is_start, self._data.start_zone, "start_hub"),
            (is_end, self._data.end_zone, "end_hub"),
        ):
            if flag and existing:
                raise ParseError(
                    line_num, f"{label} is defined more than once"
                )

        self._data.zones[name] = Zone(
            name=name,
            x=int(match.group(3)),
            y=int(match.group(4)),
            zone_type=zone_type,
            # Hubs hold every drone, so their max_drones is accepted but
            # deliberately ignored, as the subject requires.
            max_drones=self._capacity(metadata, "max_drones", line_num),
            color=metadata.get("color"),
            is_start=is_start,
            is_end=is_end,
        )
        if is_start:
            self._data.start_zone = name
        elif is_end:
            self._data.end_zone = name

    def _parse_connection(
        self, match: re.Match[str], line_num: int
    ) -> None:
        """Build a :class:`Connection` from a matched connection line.

        Args:
            match: Result of matching :attr:`_CONNECTION_RE`.
            line_num: 1-based line number, for error messages.

        Raises:
            ParseError: If an endpoint is unknown, the two endpoints are
                the same zone, the link is a duplicate, or the metadata
                is invalid.
        """
        zone_a, zone_b = match.group(1), match.group(2)
        metadata = self._parse_metadata(
            match.group(3), line_num, allowed={"max_link_capacity"},
        )

        for name in (zone_a, zone_b):
            if name not in self._data.zones:
                raise ParseError(
                    line_num, f"connection to undefined zone {name!r}"
                )
        if zone_a == zone_b:
            raise ParseError(
                line_num, f"zone {zone_a!r} cannot connect to itself"
            )

        connection = Connection(
            zone_a=zone_a,
            zone_b=zone_b,
            max_link_capacity=self._capacity(
                metadata, "max_link_capacity", line_num
            ),
        )
        # `a-b` and `b-a` describe the same link, so compare sorted keys.
        if connection.key in self._seen_links:
            raise ParseError(
                line_num, f"duplicate connection {zone_a}-{zone_b}"
            )
        self._seen_links.add(connection.key)
        self._data.connections.append(connection)

    def _parse_metadata(
        self, block: str | None, line_num: int, allowed: set[str]
    ) -> dict[str, str]:
        """Split a ``[key=value key=value]`` block into a dict.

        Tags may appear in any order. Every tag must be a ``key=value``
        pair drawn from ``allowed``: anything else is a syntax error
        rather than something to ignore silently, so typos in a map file
        surface immediately.

        Args:
            block: Text between the brackets, or None if there was no
                metadata block at all.
            line_num: 1-based line number, for error messages.
            allowed: Keys that are meaningful in this context.

        Returns:
            The parsed tags. Empty if there was no metadata.

        Raises:
            ParseError: On an unknown key or on text that is not a
                ``key=value`` pair.
        """
        if not block:
            return {}

        metadata: dict[str, str] = {}
        for token in block.split():
            pair = self._META_RE.fullmatch(token)
            if pair is None:
                raise ParseError(
                    line_num, f"malformed metadata tag {token!r}"
                )
            key, value = pair.group(1), pair.group(2)
            if key not in allowed:
                raise ParseError(
                    line_num,
                    f"unknown metadata key {key!r} (expected one of "
                    f"{', '.join(sorted(allowed))})",
                )
            metadata[key] = value
        return metadata

    @staticmethod
    def _capacity(
        metadata: dict[str, str], key: str, line_num: int
    ) -> int:
        """Read a capacity tag, defaulting to 1 when absent.

        Args:
            metadata: Already-parsed metadata tags.
            key: Which tag to read (``max_drones`` or
                ``max_link_capacity``).
            line_num: 1-based line number, for error messages.

        Returns:
            The capacity, always at least 1.

        Raises:
            ParseError: If the value is not a positive integer.
        """
        raw = metadata.get(key)
        if raw is None:
            return 1
        if not raw.isdigit() or int(raw) < 1:
            raise ParseError(
                line_num, f"{key} must be a positive integer, got {raw!r}"
            )
        return int(raw)

    def _validate(self) -> None:
        """Check the rules that only make sense once the file is fully read.

        Raises:
            ParseError: If ``nb_drones``, ``start_hub`` or ``end_hub`` is
                missing.
        """
        if not self._data.nb_drones:
            raise ParseError(0, "missing nb_drones directive")
        if not self._data.start_zone:
            raise ParseError(0, "missing start_hub definition")
        if not self._data.end_zone:
            raise ParseError(0, "missing end_hub definition")
