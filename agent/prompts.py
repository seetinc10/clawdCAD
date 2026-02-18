"""System prompts and tool definitions for the post-frame building agent."""

SYSTEM_PROMPT = """\
You are an expert post-frame (pole barn) building designer. You produce \
architectural designs in FreeCAD by calling the provided tools.

UNITS: You ALWAYS work in FEET and INCHES. All tool parameters accept feet \
unless the parameter name explicitly says "inches". When reporting dimensions \
to the user, use the format: 24'-0" x 40'-0".

POST-FRAME CONSTRUCTION RULES:
- Posts are the primary structural members, set in the ground or on concrete piers.
- Standard post spacing is 8' on center. Adjust only when the user specifies.
- Common post sizes: 6x6 (standard), 4x6 or 8x8 for heavy loads.
- Standard embedment depth: 4' (frost line dependent).
- Girts are horizontal members nailed to posts; they carry wall sheathing.
- Trusses span the full building width, bearing directly on the posts.
- Common truss spacing: 2' on center for residential, 4' for agricultural.
- Roof pitch: 4:12 is standard for post-frame. 3:12 to 6:12 is typical range.
- Eave heights: 10' is standard for shops, 12'-14' for equipment storage.
- Concrete slab: 4" thick is standard, 6" for heavy equipment areas.
- Overhead doors: 10'x10' for single vehicle, 12'x12' or 14'x14' for equipment.
- Walk doors: 3'x6'8" standard.
- Windows: 3'x4' is common, sill at 3' above grade.

EXTERIOR CLADDING:
- Wall panels: Steel rib panels on all 4 walls. Available colors: charcoal, \
red, green, tan, white, blue, brown, galvalume.
- Roof panels: Steel rib panels on both slopes. Same color options.
- Default: charcoal roof, charcoal or tan walls. Let user pick if they mention \
color preference.

INTERIOR BUILDOUT (for barndominium / post-frame homes):
When the user requests a home, residence, barndominium, or living space:
- Ask how many bedrooms and bathrooms they want (suggest 2-3 bed / 2 bath as default).
- Suggest a great room / open kitchen / open concept layout as the default.
- ALWAYS use the generate_floor_plan tool to create the interior layout. This tool \
uses an architectural layout engine with proper zoning (public/private/service), \
adjacency rules (kitchen next to great room, master bath next to master bedroom), \
a split-bedroom pattern, hallways, and doors.
- Do NOT manually place rooms with create_room for residential layouts. The layout \
engine handles all room placement, fixtures, hallways, and interior walls automatically.
- You can still use create_room and create_interior_wall for manual corrections \
during the review phase if the layout engine output needs adjustment.
- Standard room sizes (for reference during review):
  * Master bedroom: 14'x14' to 16'x16' with attached master bath
  * Bedrooms: 10'x12' to 12'x14'
  * Master bathroom: 8'x10' (tub + shower)
  * Bathroom: 5'x8' to 6'x9' (shower only for secondary baths)
  * Great room / living area: 16'x20' to 20'x24'
  * Kitchen: 10'x12' to 14'x16', L or U shaped with island
  * Laundry: 6'x8'
  * Mudroom: 6'x8' near entry
  * Walk-in closet: 6'x6' to 8'x8'
  * Pantry: 4'x6'
- Interior wall height is typically 9' (use a dropped ceiling below the trusses).

CRITICAL COORDINATE RULES:
- The building origin is (0, 0). X runs along the building LENGTH, Y runs along WIDTH.
- ALL rooms MUST fit within the building footprint: x >= 0, y >= 0, \
x + room_width <= building_length, y + room_depth <= building_width.
- NEVER place a room outside the building boundary. If a 30'x40' building has \
length=40 (X) and width=30 (Y), then all room coordinates must satisfy: \
0 <= x, x + room_width <= 40, 0 <= y, y + room_depth <= 30.
- Plan the floor layout on a grid BEFORE calling create_room. Sketch out X and Y \
positions so rooms tile within the footprint without overlapping or going out of bounds.
- Room widths and depths should add up to fill the building. For a 30'x40' building, \
if you split it into a 20' section and a 20' section along X, the rooms in each \
section must fit within 0-20' and 20-40' respectively.
- Do NOT stack rooms linearly (room1 at y=0, room2 at y=16, room3 at y=32...) \
as this will exceed the building width. Instead, arrange rooms in a 2D grid.

DESIGN PROCESS (follow this order - call ALL relevant tools):
1. Create the concrete slab.
2. Create the post layout.
3. Create wall girts on all four walls.
4. Create wainscot panels (lower wall sheathing).
5. Create wall panels (steel rib exterior cladding).
6. Create roof trusses.
7. Create roof purlins.
8. Create ridge cap.
9. Create roof panels (steel rib roof cladding).
10. Add openings (overhead doors, walk doors, windows) per user request.
11. If the user requested interior buildout / home:
    a. Call generate_floor_plan with bedroom/bathroom counts and options.
       The layout engine handles room placement, hallways, doors, and fixtures automatically.
    b. If the review reveals layout issues, use create_room and create_interior_wall \
       to make manual corrections.

IMPORTANT: Do NOT ask for confirmation on the structural design. When the user \
gives a request like "design me a 30x40 shop", immediately proceed through ALL \
structural steps. However, for interior buildout, briefly state your suggested \
layout (e.g. "I'll create a 3-bed/2-bath with open great room and kitchen") \
and then proceed without waiting for confirmation.

IMPORTANT: Do NOT call save_document or export_step. The system handles saving \
automatically after you finish all tool calls.

Always report what you created after each step so the user can follow along.

IMAGE / FLOOR PLAN INPUT:
If the user attaches an image (floor plan sketch, napkin drawing, photo of a plan, \
reference photo of a building), analyze it carefully:
- Identify the overall building dimensions (estimate if not labeled).
- Identify room layouts, door/window positions, and any labeled rooms.
- Identify the building shape (rectangular post-frame).
- Map what you see to the available tools and replicate the design as closely as possible.
- If dimensions are not labeled, estimate based on room proportions and standard sizes.
- If it's a photo of an existing building, estimate dimensions and features from the image.
- Describe what you see in the image before starting the design so the user can confirm \
your interpretation.
- Then proceed through the full design process using the tools.

SELF-REVIEW:
After you finish all tool calls, the system will render your design in FreeCAD and \
capture screenshots (isometric, top/plan, and front elevation views). These screenshots \
will be sent back to you for review. When reviewing:
- Check the ISOMETRIC VIEW for overall shape, roof, wall panels, and proportions.
- Check the TOP VIEW (plan) for room layout, overlapping walls, gaps between rooms, \
and correct positioning.
- Check the FRONT VIEW (elevation) for door/window placement, eave height, and roof pitch.
- If everything looks correct, respond with "REVIEW PASSED" and a brief summary.
- If you see errors (overlapping geometry, missing rooms, wrong placement, floating \
objects, incorrect proportions), describe the issues and call the appropriate tools \
to add the missing or corrected elements. The system will regenerate the macro and \
re-render. You get up to 2 review rounds.
"""


TOOL_DEFINITIONS = [
    {
        "name": "create_post_layout",
        "description": (
            "Generate the full post layout for a rectangular post-frame building. "
            "Posts are placed at each corner and evenly spaced along each wall. "
            "All dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Total building length in feet (along X axis).",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Total building width in feet (along Y axis).",
                },
                "post_spacing_ft": {
                    "type": "number",
                    "description": "On-center post spacing in feet. Default 8.",
                    "default": 8,
                },
                "height_ft": {
                    "type": "number",
                    "description": "Above-grade post height in feet. Default 10.",
                    "default": 10,
                },
                "size_inches": {
                    "type": "number",
                    "description": "Post cross-section size in inches (e.g. 6 for 6x6). Default 6.",
                    "default": 6,
                },
                "embed_ft": {
                    "type": "number",
                    "description": "Below-grade embedment depth in feet. Default 4.",
                    "default": 4,
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_wall_girts",
        "description": (
            "Create horizontal girts on all four walls. "
            "Girts are horizontal framing members that run between posts. "
            "All dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet.",
                },
                "wall_height_ft": {
                    "type": "number",
                    "description": "Total wall height in feet. Default 10.",
                    "default": 10,
                },
                "girt_spacing_ft": {
                    "type": "number",
                    "description": "Vertical spacing between girts in feet. Default 2.",
                    "default": 2,
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_roof_trusses",
        "description": (
            "Create evenly spaced gable trusses along the building length. "
            "All dimensions in FEET. Pitch is rise per 12 inches of run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet (truss span).",
                },
                "truss_spacing_ft": {
                    "type": "number",
                    "description": "On-center truss spacing in feet. Default 2.",
                    "default": 2,
                },
                "eave_height_ft": {
                    "type": "number",
                    "description": "Eave height in feet. Default 10.",
                    "default": 10,
                },
                "pitch": {
                    "type": "number",
                    "description": "Roof pitch as X:12 (just provide X). Default 4.",
                    "default": 4,
                },
                "overhang_ft": {
                    "type": "number",
                    "description": "Eave overhang in feet. Default 1.",
                    "default": 1,
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_overhead_door",
        "description": (
            "Create an overhead/garage door opening in a wall. "
            "Dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for this door.",
                },
                "wall": {
                    "type": "string",
                    "enum": ["front", "back", "left", "right"],
                    "description": "Which wall to place the door on.",
                },
                "position_ft": {
                    "type": "number",
                    "description": "Position along the wall from left corner, in feet.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Door width in feet. Default 10.",
                    "default": 10,
                },
                "height_ft": {
                    "type": "number",
                    "description": "Door height in feet. Default 10.",
                    "default": 10,
                },
            },
            "required": ["name", "wall", "position_ft"],
        },
    },
    {
        "name": "create_walk_door",
        "description": "Create a standard walk-through door opening. Dimensions in FEET.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for this door.",
                },
                "wall": {
                    "type": "string",
                    "enum": ["front", "back", "left", "right"],
                    "description": "Which wall.",
                },
                "position_ft": {
                    "type": "number",
                    "description": "Position along wall in feet.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Width in feet. Default 3.",
                    "default": 3,
                },
                "height_ft": {
                    "type": "number",
                    "description": "Height in feet. Default 6.67 (6'8\").",
                    "default": 6.67,
                },
            },
            "required": ["name", "wall", "position_ft"],
        },
    },
    {
        "name": "create_window",
        "description": "Create a window opening in a wall. Dimensions in FEET.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name.",
                },
                "wall": {
                    "type": "string",
                    "enum": ["front", "back", "left", "right"],
                    "description": "Which wall.",
                },
                "position_ft": {
                    "type": "number",
                    "description": "Position along wall in feet.",
                },
                "sill_height_ft": {
                    "type": "number",
                    "description": "Sill height above grade in feet. Default 3.",
                    "default": 3,
                },
                "width_ft": {
                    "type": "number",
                    "description": "Window width in feet. Default 3.",
                    "default": 3,
                },
                "height_ft": {
                    "type": "number",
                    "description": "Window height in feet. Default 4.",
                    "default": 4,
                },
            },
            "required": ["name", "wall", "position_ft"],
        },
    },
    {
        "name": "create_concrete_slab",
        "description": "Create a concrete floor slab. Dimensions in FEET, thickness in INCHES.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name.",
                },
                "length_ft": {
                    "type": "number",
                    "description": "Slab length in feet.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Slab width in feet.",
                },
                "thickness_inches": {
                    "type": "number",
                    "description": "Slab thickness in inches. Default 4.",
                    "default": 4,
                },
            },
            "required": ["name", "length_ft", "width_ft"],
        },
    },
    {
        "name": "create_wainscot",
        "description": (
            "Create wainscot (lower wall sheathing panels) on all four walls. "
            "Typically 3'-4' tall. Dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet.",
                },
                "wainscot_height_ft": {
                    "type": "number",
                    "description": "Wainscot height in feet. Default 4.",
                    "default": 4,
                },
                "thickness_inches": {
                    "type": "number",
                    "description": "Panel thickness in inches. Default 0.5.",
                    "default": 0.5,
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_purlins",
        "description": (
            "Create roof purlins (2x4) running along building length on both slopes. "
            "Dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet.",
                },
                "eave_height_ft": {
                    "type": "number",
                    "description": "Eave height in feet. Default 10.",
                    "default": 10,
                },
                "pitch": {
                    "type": "number",
                    "description": "Roof pitch (X:12). Default 4.",
                    "default": 4,
                },
                "purlin_spacing_ft": {
                    "type": "number",
                    "description": "Purlin spacing along slope in feet. Default 2.",
                    "default": 2,
                },
                "overhang_ft": {
                    "type": "number",
                    "description": "Eave overhang in feet. Default 1.",
                    "default": 1,
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_ridge_cap",
        "description": "Create a ridge cap along the roof peak. Dimensions in FEET.",
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet.",
                },
                "eave_height_ft": {
                    "type": "number",
                    "description": "Eave height in feet. Default 10.",
                    "default": 10,
                },
                "pitch": {
                    "type": "number",
                    "description": "Roof pitch (X:12). Default 4.",
                    "default": 4,
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_interior_wall",
        "description": "Create an interior partition wall. Dimensions in FEET.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name.",
                },
                "start_x_ft": {
                    "type": "number",
                    "description": "Start X in feet.",
                },
                "start_y_ft": {
                    "type": "number",
                    "description": "Start Y in feet.",
                },
                "end_x_ft": {
                    "type": "number",
                    "description": "End X in feet.",
                },
                "end_y_ft": {
                    "type": "number",
                    "description": "End Y in feet.",
                },
                "height_ft": {
                    "type": "number",
                    "description": "Wall height in feet. Default 10.",
                    "default": 10,
                },
                "thickness_inches": {
                    "type": "number",
                    "description": "Wall thickness in inches. Default 5.5.",
                    "default": 5.5,
                },
            },
            "required": ["name", "start_x_ft", "start_y_ft", "end_x_ft", "end_y_ft"],
        },
    },
    {
        "name": "create_roof_panels",
        "description": (
            "Create steel rib roof panels on both slopes. "
            "Dimensions in FEET. Covers the entire roof area."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet.",
                },
                "eave_height_ft": {
                    "type": "number",
                    "description": "Eave height in feet. Default 10.",
                    "default": 10,
                },
                "pitch": {
                    "type": "number",
                    "description": "Roof pitch (X:12). Default 4.",
                    "default": 4,
                },
                "overhang_ft": {
                    "type": "number",
                    "description": "Eave overhang in feet. Default 1.",
                    "default": 1,
                },
                "color": {
                    "type": "string",
                    "description": "Panel color: charcoal, red, green, tan, white, blue, brown, galvalume. Default charcoal.",
                    "default": "charcoal",
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_wall_panels",
        "description": (
            "Create steel rib wall panels on all four exterior walls. "
            "Dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "building_length_ft": {
                    "type": "number",
                    "description": "Building length in feet.",
                },
                "building_width_ft": {
                    "type": "number",
                    "description": "Building width in feet.",
                },
                "wall_height_ft": {
                    "type": "number",
                    "description": "Wall height in feet. Default 10.",
                    "default": 10,
                },
                "color": {
                    "type": "string",
                    "description": "Panel color: charcoal, red, green, tan, white, blue, brown, galvalume. Default charcoal.",
                    "default": "charcoal",
                },
            },
            "required": ["building_length_ft", "building_width_ft"],
        },
    },
    {
        "name": "create_room",
        "description": (
            "Create an interior room with floor and 4 walls. "
            "Position is relative to building origin (0,0). Dimensions in FEET. "
            "Use for bedrooms, bathrooms, closets, laundry, utility, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for the room (e.g. 'Master_Bedroom').",
                },
                "x_ft": {
                    "type": "number",
                    "description": "X position of room's southwest corner in feet.",
                },
                "y_ft": {
                    "type": "number",
                    "description": "Y position of room's southwest corner in feet.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Room width (X direction) in feet.",
                },
                "depth_ft": {
                    "type": "number",
                    "description": "Room depth (Y direction) in feet.",
                },
                "height_ft": {
                    "type": "number",
                    "description": "Room/ceiling height in feet. Default 9.",
                    "default": 9,
                },
                "room_type": {
                    "type": "string",
                    "description": "Room type for color coding: bedroom, bathroom, kitchen, living, great_room, laundry, closet, utility, office, pantry, mudroom.",
                    "default": "room",
                },
            },
            "required": ["name", "x_ft", "y_ft", "width_ft", "depth_ft"],
        },
    },
    {
        "name": "create_kitchen_fixtures",
        "description": (
            "Create kitchen cabinets, countertops, and island inside a room. "
            "Position is the room's origin. Dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name (e.g. 'Kitchen').",
                },
                "x_ft": {
                    "type": "number",
                    "description": "X position of kitchen area in feet.",
                },
                "y_ft": {
                    "type": "number",
                    "description": "Y position of kitchen area in feet.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Kitchen width in feet.",
                },
                "depth_ft": {
                    "type": "number",
                    "description": "Kitchen depth in feet.",
                },
                "layout": {
                    "type": "string",
                    "description": "Cabinet layout: L, U, or galley. Default L.",
                    "default": "L",
                },
            },
            "required": ["name", "x_ft", "y_ft", "width_ft", "depth_ft"],
        },
    },
    {
        "name": "create_bathroom_fixtures",
        "description": (
            "Create bathroom fixtures (toilet, vanity, tub or shower) inside a room. "
            "Position is the room's origin. Dimensions in FEET."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name (e.g. 'Master_Bath').",
                },
                "x_ft": {
                    "type": "number",
                    "description": "X position of bathroom in feet.",
                },
                "y_ft": {
                    "type": "number",
                    "description": "Y position of bathroom in feet.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Bathroom width in feet.",
                },
                "depth_ft": {
                    "type": "number",
                    "description": "Bathroom depth in feet.",
                },
                "has_tub": {
                    "type": "boolean",
                    "description": "True for bathtub, false for shower stall. Default true.",
                    "default": True,
                },
            },
            "required": ["name", "x_ft", "y_ft", "width_ft", "depth_ft"],
        },
    },
    {
        "name": "generate_floor_plan",
        "description": (
            "Algorithmically generate a complete interior floor plan layout. "
            "Uses architectural zoning (public/private/service), adjacency rules, "
            "and a split-bedroom pattern to place all rooms with hallways and doors. "
            "Creates all rooms, fixtures, hallways, and interior walls in one call. "
            "MUST call create_post_layout first so building dimensions are set. "
            "For barndominiums and residential interiors, ALWAYS prefer this tool "
            "over placing rooms manually with create_room. "
            "When the user uploads a floor plan photo, extract room dimensions "
            "and pass them via room_overrides so the engine matches the reference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "num_bedrooms": {
                    "type": "integer",
                    "description": "Number of bedrooms including master. Default 3.",
                    "default": 3,
                },
                "num_bathrooms": {
                    "type": "integer",
                    "description": "Number of bathrooms including master bath. Default 2.",
                    "default": 2,
                },
                "open_concept": {
                    "type": "boolean",
                    "description": (
                        "True for open great room + kitchen + dining room layout "
                        "(no walls between them). Default true."
                    ),
                    "default": True,
                },
                "has_pantry": {
                    "type": "boolean",
                    "description": "Include a pantry adjacent to kitchen. Default true.",
                    "default": True,
                },
                "has_laundry": {
                    "type": "boolean",
                    "description": "Include a laundry room. Default true.",
                    "default": True,
                },
                "has_mudroom": {
                    "type": "boolean",
                    "description": "Include a mudroom near the entry. Default true.",
                    "default": True,
                },
                "has_dining": {
                    "type": "boolean",
                    "description": (
                        "Include a separate dining room (between great room and kitchen). "
                        "Default false (dining is merged into great room)."
                    ),
                    "default": False,
                },
                "room_overrides": {
                    "type": "object",
                    "description": (
                        "Optional per-room dimension overrides extracted from a reference "
                        "photo. Keys are room names (e.g. 'Master_Bedroom', 'Kitchen'). "
                        "Values are objects with 'width' and 'depth' (in feet), or 'area' (sqft). "
                        "Example: {\"Kitchen\": {\"width\": 14, \"depth\": 16}, "
                        "\"Master_Bedroom\": {\"area\": 200}}"
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "save_document",
        "description": "Save the FreeCAD document (handled automatically, but call to signal completion).",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Output file path.",
                },
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "get_building_summary",
        "description": "Get a summary of all building components created so far.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _anthropic_to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function-calling format.

    Anthropic uses::

        {"name": "...", "description": "...", "input_schema": {...}}

    OpenAI uses::

        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    result = []
    for t in tools:
        oai_tool = {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        result.append(oai_tool)
    return result


TOOL_DEFINITIONS_OPENAI = _anthropic_to_openai_tools(TOOL_DEFINITIONS)
