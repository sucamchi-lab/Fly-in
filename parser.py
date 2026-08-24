"""Parsing of map txt files."""

from dataclasses import dataclass, field

ZONE_TYPES = ("normal", "priority", "restricted", "blocked")


class ParseError(Exception):
    """Raised when a map file does not respect the expected format."""

    def __init__(self, line_num: int, message: str) -> None:
        super().__init__(
            f"line {line_num}: {message}" if line_num else message)


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
        if self.zone_a < self.zone_b:
            return (self.zone_a, self.zone_b)
        return (self.zone_b, self.zone_a)


@dataclass
class MapData:
    """Everything a map file describes, after parsing."""
    nb_drones: int = 0
    zones: dict[str, Zone] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    start_zone: str = ""
    end_zone: str = ""


class MapParser:
    """Reads a map file, line by line, into a MapData object."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._data = MapData()
        self._link_keys: set[tuple[str, str]] = set()

    def parse(self) -> MapData:
        """Read the file and return its contents."""
        with open(self.filepath, "r", encoding="utf-8") as handle:
            lines = handle.readlines()

        for num, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            keyword, sep, rest = line.partition(":")
            body, tags = self._split_metadata(rest.strip(), num)
            if keyword == "nb_drones" and sep:
                if self._data.nb_drones:
                    raise ParseError(
                        num, "nb_drones is defined more than once")
                self._data.nb_drones = self._int(body, num, "nb_drones")
            elif keyword in ("start_hub", "end_hub", "hub"):
                self._add_zone(keyword, body, tags, num)
            elif keyword == "connection":
                self._add_connection(body, tags, num)
            else:
                raise ParseError(num, f"unrecognised line: {line!r}")

        self._validate()
        return self._data

    def _add_zone(self, keyword: str, body: str,
                  tags: dict[str, str], num: int) -> None:
        """Handle a start_hub, end_hub or hub line."""
        parts = body.split()
        if len(parts) != 3:
            raise ParseError(num, f"expected 'name x y', got {body!r}")
        name, x, y = parts
        # Connections use `a-b`, so a dash in a name would be ambiguous.
        if "-" in name:
            raise ParseError(num, f"zone name {name!r} contains a dash")
        if name in self._data.zones:
            raise ParseError(num, f"zone {name!r} is defined more than once")

        zone_type = tags.get("zone", "normal")
        if zone_type not in ZONE_TYPES:
            raise ParseError(num, f"unknown zone type {zone_type!r}")

        is_start, is_end = keyword == "start_hub", keyword == "end_hub"
        if (is_start and self._data.start_zone
                or is_end and self._data.end_zone):
            raise ParseError(num, f"{keyword} is defined more than once")

        self._data.zones[name] = Zone(
            name=name,
            x=self._int(x, num, "x", positive=False),
            y=self._int(y, num, "y", positive=False),
            zone_type=zone_type,
            max_drones=self.capacity(tags, "max_drones", num),
            color=tags.get("color"),
            is_start=is_start,
            is_end=is_end)
        if is_start:
            self._data.start_zone = name
        elif is_end:
            self._data.end_zone = name

    def _add_connection(self, body: str,
                        tags: dict[str, str], num: int) -> None:
        """Handle a connection line."""
        parts = body.split("-")
        if len(parts) != 2 or parts[0] == parts[1]:
            raise ParseError(num, f"expected 'a-b' of two zones, got {body!r}")
        for name in parts:
            if name not in self._data.zones:
                raise ParseError(num, f"connection to undefined zone {name!r}")

        link = Connection(parts[0], parts[1],
                          self.capacity(tags, "max_link_capacity", num))
        if link.key() in self._link_keys:
            raise ParseError(
                num, f"connection {body!r} is defined more than once")
        self._link_keys.add(link.key())
        self._data.connections.append(link)

    @staticmethod
    def _split_metadata(rest: str, num: int) -> tuple[str, dict[str, str]]:
        """Pull the optional ``[key=value ...]`` block off the end."""
        body, bracket, tail = rest.partition("[")
        if bracket and not tail.endswith("]"):
            raise ParseError(num, f"unclosed '[' in {rest!r}")
        tags = {}
        for token in tail[:-1].split():
            key, sep, value = token.partition("=")
            if not sep:
                raise ParseError(num, f"expected 'key=value', got {token!r}")
            tags[key] = value
        return body.strip(), tags

    @staticmethod
    def _int(value: str, num: int, name: str, positive: bool = True) -> int:
        """Convert to an int, rejecting zero and negatives by default."""
        try:
            number = int(value)
        except ValueError:
            raise ParseError(num, f"{name} must be an integer") from None
        if positive and number < 1:
            raise ParseError(num, f"{name} must be a positive integer")
        return number

    def capacity(self, tags: dict[str, str], key: str, num: int) -> int:
        """Read a capacity tag, defaulting to 1 when absent."""
        return self._int(tags[key], num, key) if key in tags else 1

    def _validate(self) -> None:
        """Check the rules that need the whole file to be read."""
        if not self._data.nb_drones:
            raise ParseError(0, "missing nb_drones directive")
        if not self._data.start_zone:
            raise ParseError(0, "missing start_hub definition")
        if not self._data.end_zone:
            raise ParseError(0, "missing end_hub definition")
