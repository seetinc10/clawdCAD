"""Quick test: generate a macro with all new tools (structural + interior)."""
import sys
sys.path.insert(0, r"C:\clawdbotCAD")

from agent.macro_generator import MacroBuilder

mb = MacroBuilder(r"C:\clawdbotCAD\output\test_interior.FCStd")

# Structural
mb.create_concrete_slab("Slab", 40, 30)
mb.create_post_layout(40, 30)
mb.create_wall_girts(40, 30)
mb.create_wainscot(40, 30)
mb.create_wall_panels(40, 30, color="tan")
mb.create_roof_trusses(40, 30)
mb.create_purlins(40, 30)
mb.create_ridge_cap(40, 30)
mb.create_roof_panels(40, 30, color="charcoal")
mb.create_overhead_door("OH_Door", "front", 15, 10, 10, 40, 30)
mb.create_walk_door("Walk_Door", "right", 5, 3, 6.67, 40, 30)

# Interior
mb.create_room("Great_Room", 0, 0, 20, 16, 9, room_type="great_room")
mb.create_room("Kitchen", 0, 16, 14, 14, 9, room_type="kitchen")
mb.create_kitchen_fixtures("Kitchen", 0, 16, 14, 14, layout="L")
mb.create_room("Master_Bed", 20, 0, 14, 14, 9, room_type="bedroom")
mb.create_room("Master_Bath", 20, 14, 10, 8, 9, room_type="bathroom")
mb.create_bathroom_fixtures("Master_Bath", 20, 14, 10, 8, has_tub=True)
mb.create_room("Bedroom_2", 30, 14, 10, 12, 9, room_type="bedroom")
mb.create_room("Bath_2", 30, 26, 6, 4, 9, room_type="bathroom")
mb.create_bathroom_fixtures("Bath_2", 30, 26, 6, 4, has_tub=False)
mb.create_room("Laundry", 20, 22, 6, 8, 9, room_type="laundry")

macro = mb.build_macro()
print(f"Macro generated: {len(macro)} chars, {len(macro.splitlines())} lines")

# Syntax check
compile(macro, "test_interior_macro.py", "exec")
print("Syntax check: PASSED")

path = mb.write_macro(r"C:\clawdbotCAD\output\test_interior_macro.py")
print(f"Written to: {path}")
