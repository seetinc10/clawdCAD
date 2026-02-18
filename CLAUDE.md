# CLAUDE.md - Project Guide for AI Assistants

## Project Overview

ClawdCAD is a Python application that uses LLM agents to generate FreeCAD 3D
models of post-frame (pole barn) buildings from natural language descriptions.
The project runs on Windows and targets FreeCAD 1.0+.

## Architecture

### Core Pipeline

```
User prompt -> LLM agent (agent.py) -> Tool calls -> MacroBuilder (macro_generator.py)
                                           |
                                    Layout Engine (layout_engine.py)
                                           |
                                    FreeCAD Python macro -> .FCStd 3D model
```

### Key Files

- **`agent/agent.py`** - Main agent loop. Handles LLM API calls (Anthropic,
  DeepSeek, OpenAI, Grok), tool dispatch via `_execute_tool()`, and the
  self-review cycle. The `generate_floor_plan` tool at ~line 246 bridges the
  layout engine to the macro builder.

- **`agent/layout_engine.py`** - Pure-Python algorithmic floor plan generator.
  No FreeCAD dependency. Produces a `FloorPlan` dataclass with rooms, hallways,
  doors, and walls. See "Layout Engine" section below for details.

- **`agent/macro_generator.py`** - `MacroBuilder` class that accumulates
  FreeCAD Python macro code. Key methods: `create_room()`, `create_interior_wall()`,
  `create_kitchen_fixtures()`, `create_bathroom_fixtures()`. Uses `ft()` helper
  to convert feet to mm.

- **`agent/prompts.py`** - System prompt and tool definitions (JSON schema).
  The `generate_floor_plan` tool definition has 6 params: `num_bedrooms`,
  `num_bathrooms`, `open_concept`, `has_pantry`, `has_laundry`, `has_mudroom`.

- **`config.py`** - Default settings (API keys loaded from `.env`).

- **`templates/post_frame_defaults.json`** - Default building parameters.

## Layout Engine (`agent/layout_engine.py`)

### Dataclasses

- `RoomSpec` - Room request before placement (name, zone, target area, constraints)
- `PlacedRoom` - Room with final coordinates (x, y, width, depth in feet)
- `HallwaySegment` - Corridor with position and orientation
- `DoorPlacement` - Door with position, width, swing direction, clearance status
- `WallSegment` - Interior wall segment (start/end coordinates)
- `FloorPlan` - Complete layout result (rooms + hallways + doors + walls + metadata)

### Generation Phases

1. **Zone strip allocation** (`_allocate_zone_strips`) - Splits building into
   `[Master wing | Hallway | Center | Hallway | Secondary wing]` along X axis.
   Strip widths computed from zone areas / building width.

2. **Room packing** - Three zone-specific packers:
   - `_pack_center_zone()` - Great room + kitchen side-by-side or stacked,
     service rooms in back strip
   - `_pack_private_wing()` - Bedrooms front row, bath/closet back row
   - `_squarified_treemap()` - Generic fallback (Bruls/Huizing/van Wijk)

3. **Adjacency improvement** (`_improve_adjacency`) - Hill-climbing swaps
   same-zone rooms. Scoring: mandatory=+10/-20, strong=+3, prohibited=-50.

3b. **Plumbing clustering** (`_cluster_plumbing`) - Hill-climbing swaps wet
    rooms to minimise Manhattan distance to centroid. Bonuses for back-to-back
    bathrooms (+5), kitchen near bathroom (+3), shared wet walls (+2).

4. **Hallway generation** (`_add_wing_hallways`) - Zone-boundary vertical
   hallways created in phase 1. Secondary wing gets horizontal internal hallway
   if depth > 24' with 3+ rooms. Dead-end avoidance via T-junction extension
   to nearest zone-boundary hallway. Master suite has NO internal hallway.

4b. **Connectivity check** (`_ensure_connectivity`) - BFS flood-fill from
    hallways. Reports unreachable rooms in metadata.

5. **Door placement** (`_place_doors`) - IRC-compliant widths: 36" for
   entry/mudroom/great room/kitchen, 32" for bedrooms/bathrooms/laundry,
   28" for closets/pantries. Positioned 6" from wall corners. Swing direction:
   into smaller room; hallway doors always swing inward.

5b. **Swing clearance** (`_check_swing_clearances`) - Quarter-circle AABB
    collision detection between door swing arcs. Resolves by flipping swing
    direction or marking `swing_clear=False`.

6. **Wall generation** (`_generate_wall_segments`) - Interior walls on shared
   room edges, split around door openings. Skips exterior edges and
   open-concept great room/kitchen boundary.

### Adjacency Rules

```python
ADJACENCY_RULES = {
    ("Kitchen", "Great_Room"):          "mandatory",
    ("Kitchen", "Pantry"):              "mandatory",
    ("Master_Bedroom", "Master_Bathroom"): "mandatory",
    ("Kitchen", "Laundry"):             "strong",
    ("Kitchen", "Mudroom"):             "strong",
    ("Mudroom", "Laundry"):             "strong",
    ("kitchen", "bedroom"):             "prohibited",
    ("bathroom", "kitchen"):            "prohibited",
}
```

### Coordinate System

- Origin: (0, 0) at front-left corner of building
- X axis: building length (left to right)
- Y axis: building width (front to back)
- All dimensions in feet (MacroBuilder converts to mm)

## Testing

```bash
python test_layout_engine.py   # 22 tests covering all layout phases
python test_interior.py        # Interior macro generation + syntax check
python test_build.py           # Structural build tests
```

Tests are standalone scripts (no pytest required). Each prints PASSED/FAILED
with a summary count at the end.

### Layout Engine Tests (22)

- Room program parsing (standard and minimal configs)
- No overlaps and all rooms in bounds across multiple building sizes
- Room, hallway, door, and wall counts
- Open concept validation
- Split-bedroom pattern (master/secondary separation)
- Kitchen-great room adjacency
- Master bed-bath adjacency
- Fill ratio across building sizes
- Bedroom/bathroom count correctness
- MacroBuilder integration (syntax check)
- Hallway dead-end avoidance
- Room connectivity (all rooms reachable)
- IRC-compliant door sizes
- Door swing directions
- Door positions within bounds
- Plumbing score in metadata
- Wet room clustering radius

## Development Guidelines

- **Pure Python** - The layout engine has zero external dependencies (no numpy,
  no FreeCAD). Keep it that way for testability.
- **Units** - Layout engine works in feet. MacroBuilder converts to mm via `ft()`.
- **No LLM for room placement** - The `generate_floor_plan` tool uses the
  deterministic layout engine. The LLM only decides *what* rooms to include.
- **Windows-first** - The project runs on Windows. Avoid Unix-specific paths
  or shell commands. Use ASCII in console output (no Unicode symbols).
- **Aspect ratios** - Rooms should stay below 2.5:1. The treemap packer and
  zone-specific packers enforce this.
- **Tolerance** - Shared wall detection uses 0.5' tolerance for floating-point
  rounding. Overlap detection uses the same.

## Common Tasks

### Adding a new room type

1. Add template in `_make_templates()` in `layout_engine.py`
2. Set `zone`, `is_wet`, `fixtures`, and adjacency rules
3. Add to `ADJACENCY_RULES` if needed
4. Update `parse_room_program()` to include it
5. Add door width in `DOOR_WIDTHS` if non-standard
6. Update `_should_have_door()` rules if needed
7. Add test cases in `test_layout_engine.py`

### Modifying zone layout

Zone allocation is in `_allocate_zone_strips()`. The split-bedroom pattern
is hardcoded: `[Master | Hall | Center | Hall | Secondary]`. To change this,
modify the strip-building loop and update `_pack_*` methods accordingly.

### Changing door/hallway rules

- Door widths: `DOOR_WIDTHS` dict in `LayoutEngine` class
- Door-to-room rules: `_should_have_door()` static method
- Hallway width: `self._hallway_width_ft` in `__init__` (default 3.5')
- Wing hallway trigger: depth > 24' and 3+ rooms in `_add_wing_hallways()`
