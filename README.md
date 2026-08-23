*This project has been created as part of the 42 curriculum by scamlett.*

# Fly-in

## Description

Fly-in routes drones across a network of connected
zones, from a start hub to an end hub, in as few simulation turns as
possible.

A map.txt file describes the network as a graph: zones are the nodes,
connections are bidirectional edges. Every zone has a type that decides
what it costs to fly into it: **normal** (1 turn), **priority** (1 turn,
but preferred when routes tie), **restricted** (2 turns, during which the
drone sits out on the connection) and **blocked** (no entry at all).

Each turn is printed as one line naming every drone that moved.
The run can also be watched in a pygame window.

## Instructions

Requires **Python 3.10 or later**.

```bash
make install                                     # create venv, install deps
make run MAP=maps/easy/01_linear_path.txt        # change the map to try different scenarios
make run-no-gui                                  # text output only for testing
```


## Algorithm and implementation strategy

The obvious approach is to compute a route for each drone and then walk
each drone along it. That turns out to be both slower and worse: routes
computed in advance cannot know about congestion that has not happened
yet, so drones would have to be re-routed whenever they meet traffic. 

The subject's rules about drones moving out of a zone freeing up capacity for that same turn are also hard to implement in a forward search, because the search has to know about the future state of the zone before it can decide whether a drone can enter it.

This implementation inverts it. Dijkstra's algorithm is run once,
**backwards** from the goal, producing a table of the remaining cost in
turns from every zone to the goal:

```
distances = {goal: 0, gate: 1, junction: 2, start: 3, ...}
```

Every drone then routes itself, one step at a time: **move to whichever
neighbouring zone has the lowest remaining cost and is not currently
full.** No drone owns a route, so congestion needs no replanning : a
drone whose preferred zone is full simply takes the next best one, or
waits, and picks up again from wherever it ends up.

At equal remaining cost, a priority zone is chosen over a normal one. 
Blocked zones are dropped from the graph when it is built.

### Loop / deadlock prevention

- A drone only ever moves to a zone with a strictly
lower remaining cost, so that cost falls every single time it moves. It
therefore reaches the goal in at most `distances[start]` moves and can
never circle, backtrack, or oscillate between two zones.

- Drones are moved in order of how close they are
to the goal, nearest first. Consider the drone closest to the goal: the
zone it wants is closer still, so it can only be occupied by drones that
are closer than it: and those have already been moved out of the way
this turn. That drone therefore always has a step available, so at least
one drone moves every turn and the fleet always makes progress. This is
also exactly the rule the subject states, that "drones moving out of a
zone free up capacity for that same turn": processing nearest-first makes
that behaviour automatic rather than something that has to be
special-cased.

Because deadlock is impossible, a turn in which nothing at all moves
means something is wrong, and the engine raises an error.
The same goes for an unreachable goal, which is detected by Dijkstra's 
search returning no path from the start.


## Visual representation

The Pygame window draws the network from the coordinates in the map file
and animates the fleet across it.
The visualizer is not required to run the simulation, but it is highly recommended 
to see the algorithm in action and enhance the user's understanding of the simulation:

*   **Zones** are circles, coloured by the map's `color=` tag or, failing
    that, by zone type (blue normal, orange restricted, cyan priority,
    grey blocked, green start, red goal). A capacity above one is shown
    as `[n]` above the zone; blocked zones are drawn hollow with a cross
    through them, so an unusable zone is unmistakable at a glance.
*   **Connections** are lines, labelled `xN` when they carry more than
    one drone at a time.
*   **Drones** are numbered dots that slide between zones rather than
    jumping, and are fanned out so a stack of them in one zone stays
    countable.
*   **Delivered drones stay in the goal.** They are not removed on
    arrival; they park inside the goal circle, dimmed to show they are
    at rest, each keeping the slot it landed in. Start and goal are drawn
    larger than an ordinary zone so they have room for the fleet, and the
    parked drones sit on a golden-angle spiral that fills the circle
    evenly from the middle out. The picture therefore accounts for every
    drone at every moment, and the goal visibly fills as the run proceeds.
*   **The side panel** carries the turn counter, the delivered count, the
    playback mode and speed, the controls and a list of the movements in
    the current turn.
*   **Playback starts on your terms.** The window opens with the map laid
    out and nothing moving, offering a choice between playing through and
    stepping one turn at a time. 
    Speed is adjustable while playing, and `R` restarts the run at any point.


### Visualizer controls


| Key       | Action                                       |
|-----------|----------------------------------------------|
| `SPACE`   | Play / pause / step                           |
| `S`       | Switch between automatic and stepping         |
| `R`       | Restart the run from the beginning            |
| `↑` / `↓` | Faster / slower                               |
| `ESC`/`Q` | Close the window                              |


## Example without GUI

Input : `maps/easy/01_linear_path.txt`:

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

Output:

```
D1-waypoint1
D1-waypoint2 D2-waypoint1
D1-goal D2-waypoint2
D2-goal
```

## Performance

The algorithm is fast enough to handle the largest maps in the test suite, and the number of turns is always at or below the target, as shown in the table below. The implementation therefore meets the requirements for the **bonus points.**


| Map | Drones | Result | Target |
|-----|--------|--------|--------|
| Easy : linear path | 2 | **4** | ≤ 6 |
| Easy : simple fork | 4 | **4** | ≤ 8 |
| Easy : basic capacity | 4 | **4** | ≤ 6 |
| Medium : dead end trap | 5 | **8** | ≤ 12 |
| Medium : circular loop | 6 | **15** | ≤ 15 |
| Medium : priority puzzle | 5 | **7** | ≤ 12 |
| Hard : maze nightmare | 8 | **13** | ≤ 30 |
| Hard : capacity hell | 12 | **16** | ≤ 35 |
| Hard : ultimate challenge | 15 | **26** | ≤ 45 |
| Challenger : the impossible dream | 25 | **43** | ≤ 45 |


## Resources

*   [Dijkstra's algorithm](https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm)
    : the shortest-path search, run once backwards from the goal.
*   [`heapq`](https://docs.python.org/3/library/heapq.html) : the binary
    heap used as Dijkstra's priority queue.
*   [Python `dataclasses`](https://docs.python.org/3/library/dataclasses.html)
    : the value types for zones, connections and turn results.
*   [Python `decorators`](https://docs.python.org/3/glossary.html#term-decorator)
*   [pygame documentation](https://www.pygame.org/docs/) 

### AI usage

AI was used in a responsible manner as a tutor and to assist in algorithm implementation, error handling and unit testing. All code is understood by the author.

