"""Parsing of Fly-in map files.

A map file describes the drone network: how many drones to route, the
zones (nodes) they fly through, and the connections (edges) between
those zones.

The file format is::

    nb_drones: 5

    start_hub: hub 0 0 [color=green]
    end_hub:   goal 10 10 [color=yellow]
    hub:       roof1 3 4 [zone=restricted color=red]
    connection: hub-roof1
    connection: hub-roof2 [max_link_capacity=2]

Lines starting with # and blank lines are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class ParseError(Exception):
    """Raised when a map file does not respect the expected format."""

    def __init__(self, line_num: int, message: str) -> None:
        super().__init__(
            f"line {line_num}: {message}" if line_num else message
        )
        self.line_num = line_num
        self.message = message


@dataclass(frozen=True)
class Zone:
    """A zone (node) of the drone network."""

    name: str
    x: int
    y: int
    zone_type: str = "normal"
    max_drones: int = 1
    color: str | None = None
    is_start: bool = False
    is_end: bool = False

    def entry_cost(self) -> int:
        """Turns needed to enter this zone: 2 for restricted, else 1."""
        return 2 if self.zone_type == "restricted" else 1

    def is_blocked(self) -> bool:
        return self.zone_type == "blocked"

    def is_priority(self) -> bool:
        return self.zone_type == "priority"

    def is_hub(self) -> bool:
        return self.is_start or self.is_end


@dataclass(frozen=True)
class Connection:
    """A bidirectional link between two zones."""

    zone_a: str
    zone_b: str
    max_link_capacity: int = 1

    def key(self) -> tuple[str, str]:
        """Endpoint names sorted, so ``a-b`` and ``b-a`` share a key."""
        return (self.zone_a, self.zone_b) if self.zone_a < self.zone_b \
            else (self.zone_b, self.zone_a)


@dataclass
class MapData:
    """Everything a map file describes, after parsing."""

    nb_drones: int = 0
    zones: dict[str, Zone] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    start_zone: str = ""
    end_zone: str = ""


class MapParser:
    """Reads a map file, line by line, into a :class:`MapData`.

    Typical use::

        map_data = MapParser("maps/easy/01_linear_path.txt").parse()
    """

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._data = MapData()

    def parse(self) -> MapData:
        """Read the file and return its contents.

        Raises:
            ParseError: If the file breaks the format.
            OSError: If the file cannot be read.
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
        """Split off the ``keyword:`` prefix and dispatch on it."""
        keyword, sep, rest = line.partition(":")
        rest = rest.strip()

        if not sep:
            raise ParseError(line_num, f"unrecognised line: {line!r}")
        elif keyword == "nb_drones":
            self._parse_nb_drones(rest, line_num)
        elif keyword in ("start_hub", "end_hub", "hub"):
            self._parse_zone(keyword, rest, line_num)
        elif keyword == "connection":
            self._parse_connection(rest, line_num)
        else:
            raise ParseError(line_num, f"unrecognised line: {line!r}")

    def _parse_nb_drones(self, value: str, line_num: int) -> None:
        if self._data.nb_drones:
            raise ParseError(line_num, "nb_drones is defined more than once")
        self._data.nb_drones = self._parse_positive_int(
            value, line_num, "nb_drones"
        )

    def _parse_zone(self, keyword: str, rest: str, line_num: int) -> None:
        """Handle a ``start_hub:``, ``end_hub:`` or ``hub:`` line."""
        body, metadata = self._split_metadata(rest, line_num)
        parts = body.split()
        if len(parts) != 3:
            raise ParseError(
                line_num, f"expected 'name x y', got {body!r}"
            )
        name, x, y = parts

        # Connections use `a-b`, so a dash in a name would be ambiguous.
        if "-" in name:
            raise ParseError(line_num, f"zone name {name!r} contains a dash")

        is_start = keyword == "start_hub"
        is_end = keyword == "end_hub"
        if is_start and self._data.start_zone:
            raise ParseError(line_num, "start_hub is defined more than once")
        if is_end and self._data.end_zone:
            raise ParseError(line_num, "end_hub is defined more than once")

        self._data.zones[name] = Zone(
            name=name,
            x=self._parse_int(x, line_num, "x"),
            y=self._parse_int(y, line_num, "y"),
            zone_type=metadata.get("zone", "normal"),
            max_drones=self._metadata_positive_int(
                metadata, "max_drones", line_num
            ),
            color=metadata.get("color"),
            is_start=is_start,
            is_end=is_end,
        )
        if is_start:
            self._data.start_zone = name
        elif is_end:
            self._data.end_zone = name

    def _parse_connection(self, rest: str, line_num: int) -> None:
        """Handle a ``connection:`` line."""
        body, metadata = self._split_metadata(rest, line_num)
        parts = body.split("-")
        if len(parts) != 2:
            raise ParseError(line_num, f"expected 'a-b', got {body!r}")
        zone_a, zone_b = parts

        for name in (zone_a, zone_b):
            if name not in self._data.zones:
                raise ParseError(
                    line_num, f"connection to undefined zone {name!r}"
                )
        if zone_a == zone_b:
            raise ParseError(
                line_num, f"zone {zone_a!r} cannot connect to itself"
            )

        self._data.connections.append(Connection(
            zone_a=zone_a,
            zone_b=zone_b,
            max_link_capacity=self._metadata_positive_int(
                metadata, "max_link_capacity", line_num
            ),
        ))

    @staticmethod
    def _split_metadata(
        rest: str, line_num: int
    ) -> tuple[str, dict[str, str]]:
        """Pull the optional ``[key=value ...]`` block off the end.

        Returns the remaining text and the tags as a dict. Tokens
        without an ``=`` are ignored.
        """
        if "[" not in rest:
            return rest.strip(), {}

        body, _, tail = rest.partition("[")
        if not tail.endswith("]"):
            raise ParseError(line_num, f"unclosed '[' in {rest!r}")
        tail = tail[:-1]

        metadata: dict[str, str] = {}
        for token in tail.split():
            if "=" in token:
                key, value = token.split("=", 1)
                metadata[key] = value
        return body.strip(), metadata

    @staticmethod
    def _parse_int(value: str, line_num: int, field_name: str) -> int:
        try:
            return int(value)
        except ValueError:
            raise ParseError(
                line_num, f"{field_name} must be an integer, got {value!r}"
            ) from None

    def _parse_positive_int(
        self, value: str, line_num: int, field_name: str
    ) -> int:
        number = self._parse_int(value, line_num, field_name)
        if number < 1:
            raise ParseError(
                line_num,
                f"{field_name} must be a positive integer, got {value!r}",
            )
        return number

    def _metadata_positive_int(
        self, metadata: dict[str, str], key: str, line_num: int
    ) -> int:
        """Read a capacity tag from metadata, defaulting to 1 when absent."""
        raw = metadata.get(key)
        return self._parse_positive_int(raw, line_num, key) if raw else 1

    def _validate(self) -> None:
        """Check the rules that need the whole file to be read."""
        if not self._data.nb_drones:
            raise ParseError(0, "missing nb_drones directive")
        if not self._data.start_zone:
            raise ParseError(0, "missing start_hub definition")
        if not self._data.end_zone:
            raise ParseError(0, "missing end_hub definition")
