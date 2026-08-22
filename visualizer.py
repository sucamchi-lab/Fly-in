"""Pygame window that plays the simulation back visually.

The network is drawn from the zone coordinates in the map file: zones
are circles coloured by type, connections are lines, and drones are
small numbered dots that slide from zone to zone as the turns advance.

A side panel carries the turn counter, the delivery count, the playback
mode and speed, and the moves made in the current turn.
"""

from __future__ import annotations

import math
from enum import Enum
from os import environ

from graph import Graph
from parser import Zone
from simulation import Drone, RoutingError, Simulation, TurnResult

# Remove pygame message
environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
import pygame  # noqa: E402


Rgb = tuple[int, int, int]


class Mode(Enum):
    """What the window is doing with the simulation right now."""
    READY = "ready"  # opened, waiting for the viewer to choose how to watch
    PLAYING = "playing"
    PAUSED = "paused"
    STEPPING = "step-by-step"  # one turn per key press


class Visualizer:
    """Draws and drives a :class:`Simulation` in a pygame window.

    Builds its own simulation from the graph, so it can restart the run
    on demand instead of being tied to one played-out instance.
    """

    #: Every pixel size in this class is written for a window this tall.
    #: On a bigger screen they are all multiplied up together by px(), so
    #: fullscreen means larger zones, drones and text — not more empty
    #: space around the same small drawing.
    DESIGN_HEIGHT = 750
    PANEL_WIDTH = 280
    ZONE_RADIUS = 18
    HUB_RADIUS = 40  #: Start and goal are drawn larger than an ordinary zone
    DRONE_RADIUS = 8
    EDGE_PADDING = 60
    FPS = 60

    #: Playback speed in turns per second.
    START_SPEED = 1.0
    MIN_SPEED = 0.5
    MAX_SPEED = 4.0
    SPEED_STEP = 0.5

    PARKED_SPACING = 9.0  # Gap between drones parked in the goal.
    GOLDEN_ANGLE = 2.4  # Angle in radians between successive parked drones

    # Colours used throughout the window.
    BACKGROUND: Rgb = (20, 20, 40)
    PANEL: Rgb = (30, 30, 50)
    CARD: Rgb = (44, 44, 70)
    TEXT: Rgb = (220, 220, 220)
    MUTED: Rgb = (150, 150, 160)
    ACCENT: Rgb = (255, 255, 120)
    LINK: Rgb = (80, 80, 120)
    DRONE: Rgb = (255, 220, 0)
    DELIVERED: Rgb = (196, 168, 40)
    START: Rgb = (50, 200, 50)
    END: Rgb = (255, 80, 80)
    FALLBACK: Rgb = (200, 200, 200)

    #: Colour per zone type, used when the map gives no explicit colour.
    ZONE_TYPE_COLORS: dict[str, Rgb] = {
        "normal": (100, 150, 255),
        "restricted": (255, 165, 0),
        "priority": (0, 200, 200),
        "blocked": (128, 128, 128),
    }

    def __init__(self, graph: Graph, nb_drones: int) -> None:
        """Open a fullscreen window and lay the map out on screen."""
        self.graph = graph
        self.nb_drones = nb_drones
        self.running = True
        self.turns_per_second = self.START_SPEED

        pygame.init()
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("Fly-in — drone routing simulation")
        # Never below 1.0: on a screen shorter than the design window the
        # drawing would otherwise shrink instead of merely not growing.
        self.scale = max(1.0, self.screen.get_height() / self.DESIGN_HEIGHT)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, self.px(18))
        self.font_medium = pygame.font.Font(None, self.px(22))
        self.font_large = pygame.font.Font(None, self.px(28))

        self.positions = self._layout()
        # Everything to do with a particular run lives in restart(), so
        # that starting over needs no separate teardown.
        self.restart()

    def px(self, size: float) -> int:
        """Scale a size written for the design window up to this screen."""
        return int(size * self.scale)

    def run(self) -> None:
        """Show the window until the viewer closes it."""
        while self.running:
            elapsed = self.clock.tick(self.FPS) / 1000.0
            self._handle_events()
            self._update(elapsed)
            self._draw()
        pygame.quit()

    def restart(self) -> None:
        """Throw the current run away and set a fresh one up, unstarted.

        Defines the whole of the per-run state, so replaying is just a
        matter of calling this again.
        """
        self.simulation = Simulation(self.graph, self.nb_drones)
        self.last_turn: TurnResult | None = None
        self.error: str | None = None
        self.mode = Mode.READY
        # Drone dots are interpolated between where they were at the end
        # of the previous turn and where they are now, so movement reads
        # as flight rather than teleportation.
        self.previous: dict[int, tuple[float, float]] = {}
        self.progress = 1.0
        # Drone id to the parking slot it took in the goal. Assigned in
        # arrival order and never reassigned, so a drone that has landed
        # keeps its spot instead of shuffling as others arrive.
        self.landed: dict[int, int] = {}

    def idle(self) -> bool:
        """True when the run is over, or has not been started yet."""
        return (
            self.mode is Mode.READY
            or self.error is not None
            or self.simulation.finished()
        )

    # --- Simulation driving ------------------------------------------

    def _handle_events(self) -> None:
        """Apply keyboard and window events to the playback state."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)

    def _handle_key(self, key: int) -> None:
        """Apply a single key press."""
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.running = False
        elif key == pygame.K_r:
            self.restart()
        elif key == pygame.K_UP:
            self.turns_per_second = min(
                self.MAX_SPEED, self.turns_per_second + self.SPEED_STEP
            )
        elif key == pygame.K_DOWN:
            self.turns_per_second = max(
                self.MIN_SPEED, self.turns_per_second - self.SPEED_STEP
            )
        elif key == pygame.K_SPACE:
            self._toggle_play()
        elif key == pygame.K_s:
            self._toggle_stepping()

    def _toggle_play(self) -> None:
        """Handle SPACE: start, pause, resume, or take a single step."""
        if self.simulation.finished() or self.error is not None:
            return  # The run is over; R replays it, SPACE does nothing.
        if self.mode is Mode.STEPPING:
            self._advance()
        elif self.mode is Mode.PLAYING:
            self.mode = Mode.PAUSED
        else:
            # From READY this is what actually starts the run.
            self.mode = Mode.PLAYING

    def _toggle_stepping(self) -> None:
        """Handle S: switch between playing through and stepping."""
        if self.simulation.finished() or self.error is not None:
            return
        self.mode = (
            Mode.PLAYING if self.mode is Mode.STEPPING else Mode.STEPPING
        )

    def _update(self, elapsed: float) -> None:
        """Advance playback by one frame, given seconds since the last one."""
        # The animation runs slightly faster than the turn rate so each
        # hop settles before the next one starts.
        self.progress = min(
            1.0, self.progress + elapsed * self.turns_per_second * 1.5
        )
        if self.mode is Mode.PLAYING and not self.idle():
            if self.progress >= 1.0:
                self._advance()

    def _advance(self) -> None:
        """Step the simulation one turn and start animating into it.

        Where each drone is standing has to be captured *before* the
        turn is played, since that is what the new positions are
        animated from.
        """
        origins = {
            drone.drone_id: self._drone_point(drone)
            for drone in self.simulation.drones
        }
        try:
            self.last_turn = self.simulation.step()
        except RoutingError as failure:
            self.error = str(failure)
            return

        for drone in self.simulation.drones:
            if (
                self.simulation.is_delivered(drone)
                and drone.drone_id not in self.landed
            ):
                self.landed[drone.drone_id] = len(self.landed)

        self.previous = origins
        self.progress = 0.0

    # --- Geometry ----------------------------------------------------

    def _layout(self) -> dict[str, tuple[float, float]]:
        """Scale the map's zone coordinates to pixel positions, keyed by
        zone name."""
        zones = list(self.graph.zones.values())
        if not zones:
            return {}

        min_x, max_x = min(z.x for z in zones), max(z.x for z in zones)
        min_y, max_y = min(z.y for z in zones), max(z.y for z in zones)
        # A map laid out in a straight line has no extent on one axis;
        # clamping to 1 keeps the scale finite.
        span_x, span_y = max(max_x - min_x, 1), max(max_y - min_y, 1)

        padding = self.px(self.EDGE_PADDING)
        width = (
            self.screen.get_width() - self.px(self.PANEL_WIDTH) - 2 * padding
        )
        height = self.screen.get_height() - 2 * padding
        scale = min(width / span_x, height / span_y)
        offset_x = padding + (width - span_x * scale) / 2
        offset_y = padding + (height - span_y * scale) / 2

        return {
            zone.name: (
                offset_x + (zone.x - min_x) * scale,
                offset_y + (zone.y - min_y) * scale,
            )
            for zone in zones
        }

    def _drone_point(self, drone: Drone) -> tuple[float, float]:
        """Where a drone should be drawn right now, before animation.

        A delivered drone is parked in its goal slot. A drone in flight
        sits halfway along the connection it's crossing. Anything else
        is in a zone, nudged off centre so a stack of drones stays
        countable.
        """
        if drone.drone_id in self.landed:
            return self._parked_point(self.landed[drone.drone_id])

        here = self.positions.get(drone.zone, (0.0, 0.0))
        if drone.destination is not None:
            there = self.positions.get(drone.destination, here)
            return ((here[0] + there[0]) / 2, (here[1] + there[1]) / 2)

        slot = drone.drone_id - 1
        step = self.px(7)
        return (
            here[0] + (slot % 4) * step - self.px(10),
            here[1] + (slot // 4) * step - self.px(7),
        )

    def _parked_point(self, slot: int) -> tuple[float, float]:
        """Where a delivered drone rests inside the goal.

        Slots sit on a golden-angle spiral, which fills a disc evenly
        from the centre outwards, so the goal packs neatly however many
        drones end up in it. ``slot`` is the drone's arrival order.
        """
        centre = self.positions.get(self.graph.end, (0.0, 0.0))
        angle = slot * self.GOLDEN_ANGLE
        distance = self._parked_spacing() * math.sqrt(slot)
        return (
            centre[0] + distance * math.cos(angle),
            centre[1] + distance * math.sin(angle),
        )

    def _parked_spacing(self) -> float:
        """Gap between parked drones, tightened when the goal fills up."""
        outermost = math.sqrt(max(self.nb_drones - 1, 1))
        # Squeeze the spiral until the whole fleet fits the hub circle,
        # since that circle no longer grows to meet it.
        room = (
            self.px(self.HUB_RADIUS) - self.px(self.DRONE_RADIUS)
        ) / outermost
        return min(self.px(self.PARKED_SPACING), room)

    def _zone_radius(self, zone: Zone) -> float:
        """The radius to draw a zone at: hubs are bigger than the rest."""
        if zone.is_hub():
            return float(self.px(self.HUB_RADIUS))
        return float(self.px(self.ZONE_RADIUS))

    def _animated_point(self, drone: Drone) -> tuple[float, float]:
        """A drone's position this frame, interpolated toward its target."""
        target = self._drone_point(drone)
        start = self.previous.get(drone.drone_id, target)
        return (
            start[0] + (target[0] - start[0]) * self.progress,
            start[1] + (target[1] - start[1]) * self.progress,
        )

    # --- Drawing -----------------------------------------------------

    def _draw(self) -> None:
        """Render one frame."""
        self.screen.fill(self.BACKGROUND)
        self._draw_connections()
        self._draw_zones()
        self._draw_drones()
        self._draw_panel()
        if self.mode is Mode.READY:
            self._draw_opening_card()
        elif self.error is not None or self.simulation.finished():
            self._draw_closing_card()
        pygame.display.flip()

    def _draw_connections(self) -> None:
        """Draw every link, labelling those that take more than one drone."""
        for connection in self.graph.connections:
            start = self.positions.get(connection.zone_a)
            end = self.positions.get(connection.zone_b)
            if start is None or end is None:
                continue
            pygame.draw.line(
                self.screen, self.LINK, start, end, self.px(2)
            )
            if connection.max_link_capacity > 1:
                self._blit(
                    f"x{connection.max_link_capacity}",
                    (
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2 - self.px(12),
                    ),
                    self.MUTED,
                    centered=True,
                )

    def _draw_zones(self) -> None:
        """Draw every zone as a labelled circle."""
        for name, zone in self.graph.zones.items():
            position = self.positions.get(name)
            if position is None:
                continue
            point = (int(position[0]), int(position[1]))
            color = self.zone_color(zone)
            radius = int(self._zone_radius(zone))

            if zone.is_blocked():
                # Hollow with a cross through it: unmistakably off limits.
                pygame.draw.circle(
                    self.screen, color, point, radius, self.px(2)
                )
                arm = self.px(6)
                for dx in (-1, 1):
                    pygame.draw.line(
                        self.screen, color,
                        (point[0] - arm * dx, point[1] - arm),
                        (point[0] + arm * dx, point[1] + arm),
                        self.px(2),
                    )
            else:
                pygame.draw.circle(self.screen, color, point, radius)
                pygame.draw.circle(
                    self.screen, (255, 255, 255), point, radius, self.px(1)
                )

            self._blit(
                name,
                (position[0], position[1] + radius + self.px(5)),
                self.TEXT,
                centered=True,
            )
            if not zone.is_hub() and zone.max_drones > 1:
                self._blit(
                    f"[{zone.max_drones}]",
                    (position[0], position[1] - radius - self.px(16)),
                    (200, 200, 100),
                    centered=True,
                )

    def _draw_drones(self) -> None:
        """Draw every drone as a numbered dot, including delivered ones
        parked inside the goal."""
        parked_radius = int(
            min(self.px(self.DRONE_RADIUS), self._parked_spacing() * 0.6)
        )
        for drone in self.simulation.drones:
            x, y = self._animated_point(drone)
            point = (int(x), int(y))

            # Parked drones are dimmer than ones still under way, and
            # sized to fit their slot however crowded the goal gets.
            delivered = drone.drone_id in self.landed
            color = self.DELIVERED if delivered else self.DRONE
            radius = (
                parked_radius if delivered else self.px(self.DRONE_RADIUS)
            )

            pygame.draw.circle(self.screen, color, point, radius)
            # A dark rim keeps a drone legible whatever colour the zone
            # underneath it happens to be — a yellow drone parked in a
            # gold goal would otherwise vanish into it.
            pygame.draw.circle(
                self.screen, self.BACKGROUND, point, radius, self.px(1)
            )
            if radius >= self.px(5):
                self._blit(
                    str(drone.drone_id), (x, y), (0, 0, 0), centered=True
                )

    def _draw_panel(self) -> None:
        """Draw the side panel: status, controls and the current turn."""
        panel_width = self.px(self.PANEL_WIDTH)
        left = self.screen.get_width() - panel_width
        pygame.draw.rect(
            self.screen,
            self.PANEL,
            (left, 0, panel_width, self.screen.get_height()),
        )

        total = len(self.simulation.drones)
        indent = left + self.px(20)
        y = self.px(20)
        self._blit("Fly-in", (indent, y), self.TEXT, font=self.font_large)
        y += self.px(40)
        for text in (
            f"Turn: {self.simulation.turn}",
            f"Delivered: {self.simulation.delivered_count()}/{total}",
            f"Mode: {self.mode.value}",
            f"Speed: {self.turns_per_second:.1f} turns/s",
        ):
            self._blit(text, (indent, y), self.TEXT, font=self.font_medium)
            y += self.px(26)

        y += self.px(10)
        for text in (
            "SPACE  play / pause / step",
            "S      play or step mode",
            "R      restart the run",
            "UP/DN  speed",
            "ESC    close",
        ):
            self._blit(text, (indent, y), self.MUTED)
            y += self.px(18)

        if self.last_turn is not None:
            y += self.px(12)
            self._blit(
                "This turn", (indent, y), self.TEXT, font=self.font_medium
            )
            y += self.px(24)
            for move in self.last_turn.moves[:12]:
                self._blit(move, (indent, y), (200, 200, 150))
                y += self.px(16)

    def _draw_opening_card(self) -> None:
        """Offer the two ways to watch, before anything has moved."""
        self._draw_card(
            f"{self.nb_drones} drones, {len(self.graph.zones)} zones",
            [
                ("SPACE", "play it through"),
                ("S", "step one turn at a time"),
            ],
            self.TEXT,
        )

    def _draw_closing_card(self) -> None:
        """Show how the run ended, and offer to play it again."""
        if self.error is not None:
            headline, color = f"Simulation failed: {self.error}", self.END
        else:
            headline = (
                f"All {self.nb_drones} drones delivered "
                f"in {self.simulation.turn} turns"
            )
            color = self.ACCENT
        # No prompt to quit: the final layout stays up for as long as it
        # is wanted, and the window closes when the viewer closes it.
        self._draw_card(headline, [("R", "watch it again")], color)

    def _draw_card(
        self, headline: str, choices: list[tuple[str, str]], color: Rgb
    ) -> None:
        """Draw a centred card over the map: a headline, then a list of
        ``(key, what it does)`` choices underneath."""
        line_height = self.px(24)
        widths = [self.font_large.size(headline)[0] + self.px(60)]
        widths += [
            self.font_medium.size(f"{key}   {text}")[0] + self.px(90)
            for key, text in choices
        ]
        centre_x = (
            self.screen.get_width() - self.px(self.PANEL_WIDTH)
        ) / 2
        # Never wider than the map area, so a long failure message stays
        # inside the window instead of running under the side panel.
        width = min(max(widths), centre_x * 2 - self.px(40))
        height = self.px(70) + line_height * len(choices)
        left = centre_x - width / 2
        top = self.screen.get_height() / 2 - height / 2

        card = pygame.Surface((width, height), pygame.SRCALPHA)
        card.fill((*self.CARD, 240))
        self.screen.blit(card, (left, top))
        pygame.draw.rect(
            self.screen, self.LINK, (left, top, width, height), self.px(1)
        )

        self._blit(
            headline, (centre_x, top + self.px(26)), color,
            font=self.font_large, centered=True,
        )
        y = top + self.px(56)
        for key, description in choices:
            self._blit(
                key, (left + self.px(28), y), self.ACCENT,
                font=self.font_medium,
            )
            self._blit(
                description, (left + self.px(92), y), self.MUTED,
                font=self.font_medium,
            )
            y += line_height

    def _blit(
        self,
        text: str,
        position: tuple[float, float],
        color: Rgb,
        font: pygame.font.Font | None = None,
        centered: bool = False,
    ) -> None:
        """Draw a line of text at ``position`` — its top-left corner, or
        its centre if ``centered``."""
        surface = (font or self.font).render(text, True, color)
        x, y = position
        if centered:
            x -= surface.get_width() / 2
            y -= surface.get_height() / 2
        self.screen.blit(surface, (int(x), int(y)))

    def zone_color(self, zone: Zone) -> Rgb:
        """Pick the colour to draw a zone in: an explicit ``color=`` from
        the map first, then start/goal colours, then the zone type's."""
        if zone.color:
            return self.rgb(zone.color)
        if zone.is_start:
            return self.START
        if zone.is_end:
            return self.END
        return self.ZONE_TYPE_COLORS.get(zone.zone_type, self.FALLBACK)

    def rgb(self, name: str) -> Rgb:
        """Turn a colour name like 'red' into an RGB triple, falling
        back to grey for anything pygame doesn't recognise."""
        try:
            color = pygame.Color(name)
        except ValueError:
            return self.FALLBACK
        return (color.r, color.g, color.b)
