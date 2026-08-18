*This project has been created as part of the 42 curriculum by scamlett.*

# Fly-in — drone routing simulation

## Description

Fly-in routes a fleet of autonomous drones across a network of connected
zones, from a start hub to an end hub, in as few simulation turns as
possible.

A map file describes the network as a graph: zones are the nodes,
connections are bidirectional edges. Every zone has a type that decides
what it costs to fly into it — **normal** (1 turn), **priority** (1 turn,
but preferred when routes tie), **restricted** (2 turns, during which the
drone sits out on the connection) and **blocked** (no entry at all).
Zones and connections both carry capacity limits, so drones queue,
spread out across parallel routes, and wait when there is nowhere to go.

Each turn is printed as one line naming every drone that moved, and the
run can also be watched in a pygame window.

## Instructions

```bash
make install                                     # create venv, install deps
make run MAP=maps/easy/01_linear_path.txt        # with the pygame window
make run-no-gui MAP=maps/hard/02_capacity_hell.txt   # text output only for testing
```

`maps/tests/` holds small single-purpose maps for checking one rule at a
time by hand — a blocked zone, a restricted zone, a capacity split, a
map where start and goal are directly connected, and so on.

Without a `MAP=`, the easy linear map is used. The program can also be
called directly:

```bash
python3 main.py maps/medium/02_circular_loop.txt --no-gui
```

Turn lines go to **standard output** and nothing else does, so the result
can be piped or diffed. The summary goes to standard error, where it is
still visible in a terminal:

```
5 drones delivered in 7 turns (22 moves, 3.1 per turn, 4.4 per drone)
cheapest single-drone route (4 turns): start -> fast_junction -> fast_path -> merge_point -> goal
```

The second line is the floor the fleet is working against — one drone
alone, with the map to itself. The gap between it and the turn count is
entirely the cost of congestion.

### Visualizer controls

The window opens **waiting**, showing the map and a card offering the two
ways to watch. Nothing moves until you pick one.

| Key       | Action                                       |
|-----------|----------------------------------------------|
| `SPACE`   | Play / pause, or advance one turn in step mode |
| `S`       | Switch between playing through and stepping   |
| `R`       | Restart the run from the beginning            |
| `↑` / `↓` | Faster / slower (0.5–20 turns per second)     |
| `ESC`/`Q` | Close the window                              |

When the last drone lands, the finished layout stays on screen. There is
no prompt to quit: press `R` to watch it again, or close the window when
you are done looking at it.

## Algorithm and implementation strategy

### One search, not one search per drone

The obvious approach is to compute a route for each drone and then walk
each drone along it. That turns out to be both slower and worse: routes
computed in advance cannot know about congestion that has not happened
yet, so drones have to be pulled off their route and re-planned whenever
they meet traffic, and the bookkeeping for that is where bugs live.

This implementation inverts it. **Dijkstra's algorithm is run once,
backwards from the goal**, producing a table of the remaining cost in
turns from every zone to the goal:

```
distances = {goal: 0, gate: 1, junction: 2, start: 3, ...}
```

Because the graph is undirected and an edge's weight depends only on
which zone you are *entering*, searching backwards is exactly as valid as
searching forwards — the cost of the step `neighbour → current` is simply
the entry cost of `current`.

Every drone then routes itself, one step at a time: **move to whichever
neighbouring zone has the lowest remaining cost and is not currently
full.** No drone owns a route, so congestion needs no replanning — a
drone whose preferred zone is full simply takes the next best one, or
waits, and picks up again from wherever it ends up.

Priority zones are honoured as a tie-break: at equal remaining cost, a
priority zone is chosen over a normal one. Blocked zones are dropped from
the graph when it is built, so no route can accidentally use one.

### Why this cannot loop or deadlock

Two properties fall out of the design, which is the main reason it was
chosen:

**It cannot loop.** A drone only ever moves to a zone with a *strictly*
lower remaining cost, so that cost falls every single time it moves. It
therefore reaches the goal in at most `distances[start]` moves and can
never circle, backtrack, or oscillate between two zones.

**It cannot deadlock.** Drones are moved in order of how close they are
to the goal, nearest first. Consider the drone closest to the goal: the
zone it wants is closer still, so it can only be occupied by drones that
are closer than it — and those have already been moved out of the way
this turn. That drone therefore always has a step available, so at least
one drone moves every turn and the fleet always makes progress. This is
also exactly the rule the subject states, that "drones moving out of a
zone free up capacity for that same turn": processing nearest-first makes
that behaviour automatic rather than something that has to be
special-cased.

Because deadlock is impossible, a turn in which nothing at all moves
means something is wrong, and the engine raises an error rather than
spinning. The same goes for an unreachable goal, which is detected up
front from the distance table.

### Capacity, and the restricted-zone guarantee

Two kinds of capacity are tracked, and they behave differently:

*   **Zone occupancy** is a running count carried across turns.
*   **Connection occupancy** is rebuilt every turn, because a connection
    is only busy while it is being crossed.

The subtle case is the restricted zone. The subject says a drone crossing
toward one *must* arrive on schedule and may not wait on the connection.
So when a drone sets off, it **reserves its destination slot
immediately** — two turns before it will actually be standing there. That
one decision is what makes the guarantee hold: the space cannot be given
to anyone else in the meantime, so the landing never needs a capacity
check and can never fail.

## Project structure

| File | Responsibility |
|------|----------------|
| `main.py` | `FlyIn` — command line, output, error reporting |
| `parser.py` | `MapParser` and the `Zone` / `Connection` / `MapData` types |
| `graph.py` | `Graph` — adjacency, Dijkstra, route extraction |
| `simulation.py` | `Simulation`, `Drone`, `TurnResult` — the turn engine |
| `visualizer.py` | `Visualizer` — the pygame window |

Every module is built around a class, and the data types are dataclasses,
`Zone` and `Connection` being frozen since a map does not change once
read.

## Visual representation

The pygame window draws the network from the coordinates in the map file
and animates the fleet across it:

*   **Zones** are circles, coloured by the map's `color=` tag or, failing
    that, by zone type (blue normal, orange restricted, cyan priority,
    grey blocked, green start, red goal). A capacity above one is shown
    as `[n]` above the zone; blocked zones are drawn hollow with a cross
    through them, so an unusable zone is unmistakable at a glance.
*   **Connections** are lines, labelled `xN` when they carry more than
    one drone at a time.
*   **Drones** are numbered dots that slide between zones rather than
    jumping, and are fanned out so a stack of them in one zone stays
    countable. Each carries a dark rim so it stays legible whatever
    colour the zone beneath it happens to be. A drone crossing toward a
    restricted zone is drawn **out on the connection itself** — the
    two-turn cost becomes something you watch happen instead of
    something you infer from the text.
*   **Delivered drones stay in the goal.** They are not removed on
    arrival; they park inside the goal circle, dimmed to show they are
    at rest, each keeping the slot it landed in. The goal grows to hold
    them, packing them on a golden-angle spiral so they fill it evenly
    from the middle out. The picture therefore accounts for every drone
    at every moment, and the goal visibly fills as the run proceeds.
*   **The side panel** carries the turn counter, the delivered count, the
    playback mode and speed, the controls, a legend for the zone types
    and a list of the movements in the current turn.
*   **Playback starts on your terms.** The window opens with the map laid
    out and nothing moving, offering a choice between playing through and
    stepping one turn at a time — so the shape of the network and the
    starting positions can be read before drones begin covering them up.
    Stepping is what makes a congested map legible: you can stop on the
    turn a queue forms and see which constraint caused it. Speed is
    adjustable while playing, and `R` restarts the run at any point.
*   **The end is not a dead end.** When the last drone lands the finished
    layout simply stays up, with no prompt to quit — you can study it for
    as long as you like, replay the run, or close the window when you are
    ready.

## Example

Input — `maps/easy/01_linear_path.txt`:

```
nb_drones: 2

start_hub: start 0 0 [color=green]
hub: waypoint1 1 0 [color=blue]
hub: waypoint2 2 0 [color=blue]
end_hub: goal 3 0 [color=red]

connection: start-waypoint1
connection: waypoint1-waypoint2
connection: waypoint2-goal
```

Output — `python3 main.py maps/easy/01_linear_path.txt --no-gui`:

```
D1-waypoint1
D1-waypoint2 D2-waypoint1
D1-goal D2-waypoint2
D2-goal
```

D2 sets off one turn behind D1 because `waypoint1` holds a single drone,
and moves into it on the very turn D1 vacates it.

A map with a restricted zone shows the two-turn crossing explicitly —
the drone is named on the *connection* first, then in the zone:

```
D1-start-slow_zone     # turn 1: out on the connection
D1-slow_zone           # turn 2: landed
D1-goal                # turn 3
```

## Performance


| Map | Drones | Result | Target |
|-----|--------|--------|--------|
| Easy — linear path | 2 | **4** | ≤ 6 |
| Easy — simple fork | 4 | **4** | ≤ 8 |
| Easy — basic capacity | 4 | **4** | ≤ 6 |
| Medium — dead end trap | 5 | **8** | ≤ 12 |
| Medium — circular loop | 6 | **15** | ≤ 15 |
| Medium — priority puzzle | 5 | **7** | ≤ 12 |
| Hard — maze nightmare | 8 | **13** | ≤ 30 |
| Hard — capacity hell | 12 | **16** | ≤ 35 |
| Hard — ultimate challenge | 15 | **26** | ≤ 45 |
| Challenger — the impossible dream | 25 | **43** | ≤ 45 |


Every one of these runs was verified against the subject's rules —
zone and connection capacities, the two-turn restricted crossing, blocked
zones, and every drone actually arriving — by replaying the printed
output rather than by trusting the engine's own counters.

## Resources

*   [Dijkstra's algorithm](https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm)
    — the shortest-path search, run once backwards from the goal.
*   [`heapq`](https://docs.python.org/3/library/heapq.html) — the binary
    heap used as Dijkstra's priority queue.
*   [Python `dataclasses`](https://docs.python.org/3/library/dataclasses.html)
    — the value types for zones, connections and turn results.
*   [pygame documentation](https://www.pygame.org/docs/) 

### AI usage

AI was used in a responsible manner as a tutor and to assist in algorithm generation, error handling, unit testing and README.md formatting. All code has been fully reviewed and is understood by the author.

