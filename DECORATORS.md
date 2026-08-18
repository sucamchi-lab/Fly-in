# Decorators in this project

A decorator is a function that wraps another function or class to change
how it behaves. It's written with `@name` on the line right above a `def`
or `class`. This file explains the four you'll run into most in Python:
`@dataclass`, `@staticmethod`, `@classmethod` and `@property`.

Two of them (`@dataclass`, `@staticmethod`) are still used in this codebase.
The other two (`@classmethod`, `@property`)
were removed in favor of plain methods, because while learning, code that's
explicit about "this runs a function" is easier to reason about than code
that hides it. They're still explained here in full, since you'll see them
constantly in other people's Python.

---

## `@dataclass` — still used here

**What it does:** looking at the class body, it writes `__init__`,
`__repr__` and `__eq__` for you, based on the annotated fields.

Compare `Zone` in [parser.py](parser.py) as it's written now:

```python
@dataclass(frozen=True)
class Zone:
    name: str
    x: int
    y: int
    zone_type: str = "normal"
    max_drones: int = 1
    color: str | None = None
    is_start: bool = False
    is_end: bool = False
```

...to what you'd have to write by hand without it:

```python
class Zone:
    def __init__(self, name, x, y, zone_type="normal", max_drones=1,
                 color=None, is_start=False, is_end=False):
        self.name = name
        self.x = x
        self.y = y
        self.zone_type = zone_type
        self.max_drones = max_drones
        self.color = color
        self.is_start = is_start
        self.is_end = is_end

    def __repr__(self):
        return (f"Zone(name={self.name!r}, x={self.x!r}, y={self.y!r}, "
                f"zone_type={self.zone_type!r}, ...)")  # and so on

    def __eq__(self, other):
        return (isinstance(other, Zone) and self.name == other.name
                and self.x == other.x and ...)  # every field, every time
```

Every field would have to be typed out three times (assignment, repr,
equality), and every time a field is added or renamed, all three places
have to be updated in sync. `@dataclass` generates all of it from the one
list of fields at the top — that's the entire justification for using it.

**`frozen=True`:** makes instances read-only after creation (assigning to
`some_zone.x = 5` later raises an error) and hashable, so they can be used
as dict keys or put in a set. Used on `Zone` and `Connection` because
nothing should be mutating a zone after the map file has been parsed.
`MapData` is *not* frozen, because the parser builds it up field by field
while reading the file.

**Rule of thumb:** if a class is mostly just a named bundle of values (no
real behavior beyond holding data), it's a `@dataclass` candidate.

---

## `@staticmethod` — still used here

**What it does:** marks a method that doesn't need `self` at all. Python
normally hands every method its instance as the first argument
automatically; `@staticmethod` turns that off. The method becomes, in
effect, a regular function that just happens to live inside the class for
organization.

Example from [parser.py](parser.py):

```python
class MapParser:
    ...
    @staticmethod
    def _parse_int(value: str, line_num: int, field_name: str) -> int:
        try:
            return int(value)
        except ValueError:
            raise ParseError(...) from None
```

`_parse_int` never touches `self._data` or any other instance state — give
it a string, it gives you back an int or raises an error. Same story for
`_split_metadata` here, and for `build_parser`, `report` and `fail` in
[main.py](main.py). None of them need to know *which* `MapParser` or
`FlyInApp` they were called on, so there's no reason to require an
instance to call them.

**How it's called:** both of these work identically —

```python
MapParser._parse_int("5", 1, "nb_drones")   # via the class
self._parse_int("5", 1, "nb_drones")        # via an instance, inside a method
```

**Rule of thumb:** if you never write `self.` inside a method body, it's a
`@staticmethod` candidate — the decorator is just documenting that fact so
nobody has to read the whole method to find out.

---

## `@classmethod` — not used here, but you'll see it everywhere

**What it does:** like `@staticmethod`, except Python *does* still pass one
automatic argument — not the instance, but the **class itself**, by
convention named `cls`.

**What it's actually for**, in two situations:

1. **Alternate constructors.** `__init__` is the *only* way to build an
   instance unless you add more entry points. A classmethod can build and
   return an instance a different way, while still being clearly attached
   to the class:

   ```python
   @dataclass(frozen=True)
   class Zone:
       name: str
       x: int
       y: int
       # ...

       @classmethod
       def from_line(cls, line: str) -> "Zone":
           name, x, y = line.split()
           return cls(name=name, x=int(x), y=int(y))
   ```

   Calling `Zone.from_line("roof1 3 4")` reads as "build a Zone, but from
   a raw line instead of the usual arguments." This is the textbook use
   of `@classmethod`, and a legitimate one — nothing in this project
   needed it, but you'll see this pattern a lot (e.g. `datetime.fromisoformat(...)`).

2. **Code that has to work for subclasses too.** Inside a classmethod,
   `cls` is *whichever class was actually called* — if a subclass calls
   the inherited method, `cls` is the subclass, not the base class. A
   `@staticmethod` or hardcoded class name can't do that.

**Why it's not used in this project:** two methods in
[visualizer.py](visualizer.py) (`zone_color`, `rgb`) used to be
classmethods, but neither builds a new instance and nothing subclasses
`Visualizer`. `cls` was only being used to reach `cls.rgb(...)` and class
constants like `cls.START` — which `self.` does exactly as well from an
instance method. Using `@classmethod` there wasn't wrong, just
unnecessary: a decorator earning no benefit over the simpler option.

---

## `@property` — not used here, but extremely common

**What it does:** lets you call a method *without* parentheses, so it
reads like a plain attribute:

```python
class Zone:
    @property
    def is_blocked(self) -> bool:
        return self.zone_type == "blocked"

zone.is_blocked        # runs the method, no () needed
```

instead of the plain-method version now used in this project:

```python
class Zone:
    def is_blocked(self) -> bool:
        return self.zone_type == "blocked"

zone.is_blocked()      # explicitly a call
```

**What it's for:** two things. First, letting a class start out with a
plain stored attribute and later swap it for a computed value, without
breaking any code elsewhere that reads `obj.thing` — the caller can't
tell the difference. Second, readability: something that conceptually
*is* a fact about the object (like `is_blocked`, or a `Temperature`
class's `.celsius` computed from a stored `.kelvin`) often reads better
without call parens, especially inside an `if`.

**Why it's not used in this project (for now):** `zone.is_blocked` and
`zone.is_blocked()` do exactly the same thing, but only the second one
tells you, just by looking at it, "this runs code." Every property in this
codebase (`entry_cost`, `is_blocked`, `is_priority`, `is_hub`,
`Connection.key`, `Simulation.finished`, `Simulation.delivered_count`,
`Drone.in_flight`, `Mode.label`, `Visualizer.idle`) got converted to a
plain method for exactly that reason — while you're still building the
habit of knowing what's a method call and what's a stored value, removing
the ambiguity is worth more than the slightly nicer syntax.

**Worth reintroducing later, once methods feel automatic** — it's a small
change (add `@property`, drop the `()` at every call site) and a genuinely
useful tool once the underlying idea (a method disguised as an attribute)
isn't a source of confusion anymore.

---

## Quick reference

| Decorator | First automatic argument | Called as | Used in this project for |
|---|---|---|---|
| `@dataclass` | — (applies to the whole class) | `Zone(...)` | `Zone`, `Connection`, `MapData`, `Drone`, `TurnResult` |
| `@staticmethod` | none | `Class.f()` or `instance.f()` | pure helpers: parsing ints, CLI plumbing |
| `@classmethod` | `cls` (the class) | `Class.f()` or `instance.f()` | not used — good for alternate constructors |
| `@property` | `self` | `instance.name` (no parens) | not used — removed for clarity while learning |
