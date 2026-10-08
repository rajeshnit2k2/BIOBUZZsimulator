from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
import sys
import threading

# Initialize the 3D App instance
app = Ursina(title="FTC 3D Hardware Game Sandbox", borderless=False)
window.size = (1000, 750)
window.fps_counter.enabled = False

# -------------------------------------------------------------
# GAME ENVIRONMENT (Roblox-style Baseplate)
# -------------------------------------------------------------
ground = Entity(
    model='plane',
    scale=(100, 1, 100),
    color=color.dark_gray,
    texture='white_cube',
    texture_scale=(100, 100),
    collider='mesh'
)

sky = Sky(color=color.light_gray)
sun = DirectionalLight(y=15, z=-10, rotation=(45, 30, 0))
ambient = AmbientLight(color=color.rgba(100, 100, 100, 255))


# -------------------------------------------------------------
# DETAILED MECHANICAL ASSEMBLIES
# -------------------------------------------------------------
class ComplexDCMotor(Entity):
    """Detailed planetary gearmotor matching real FTC hardware shapes."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 1. Main Motor cylindrical body barrel
        self.motor_body = Entity(
            parent=self,
            model='cylinder',
            scale=(0.8, 1.4, 0.8),
            color=color.light_gray,
            y=0.7,
            texture='white_cube'
        )

        # 2. Rear Wire Terminal Cap
        self.rear_cap = Entity(
            parent=self,
            model='cylinder',
            scale=(0.8, 0.15, 0.8),
            color=color.dark_gray,
            y=0.0
        )
        self.wire_stub = Entity(
            parent=self.rear_cap,
            model='cube',
            scale=(0.15, 0.3, 0.3),
            color=color.red,
            z=-0.2,
            y=-0.1
        )

        # 3. Black Planetary Gearbox Sleeve
        self.gearbox = Entity(
            parent=self,
            model='cylinder',
            scale=(0.82, 0.6, 0.82),
            color=color.black,
            y=1.5
        )

        # 4. Front Mounting Flange Face Plate (Hex Profile)
        self.face_plate = Entity(
            parent=self,
            model='cylinder',
            scale=(0.85, 0.1, 0.85),
            color=color.gray,
            y=1.8,
            resolution=6
        )

        # 5. ROTATING DRIVE SHAFT ASSEMBLY
        self.rotating_group = Entity(parent=self, y=1.85)

        self.shaft_collar = Entity(
            parent=self.rotating_group,
            model='cylinder',
            scale=(0.25, 0.15, 0.25),
            color=color.dark_gray,
            y=0.05
        )
        self.main_shaft = Entity(
            parent=self.rotating_group,
            model='cylinder',
            scale=(0.14, 0.7, 0.14),
            color=color.orange,
            y=0.4
        )
        self.d_flat = Entity(
            parent=self.main_shaft,
            model='cube',
            scale=(0.15, 1.0, 0.05),
            color=color.gold,
            z=0.05
        )

    def spin(self, speed):
        self.rotating_group.rotation_y += speed * time.dt


class ComplexServo(Entity):
    """An angular smart servo with mounting brackets and a rotating horn."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 1. Main Plastic Molded Body Case
        self.case = Entity(
            parent=self,
            model='cube',
            scale=(1.2, 1.0, 0.8),
            color=color.dark_gray,
            y=0.5
        )
        # 2. Side Mounting Flanges
        self.flange_left = Entity(
            parent=self,
            model='cube',
            scale=(0.3, 0.08, 0.8),
            color=color.dark_gray,
            position=(-0.75, 0.7, 0)
        )
        self.flange_right = Entity(
            parent=self,
            model='cube',
            scale=(0.3, 0.08, 0.8),
            color=color.dark_gray,
            position=(0.75, 0.7, 0)
        )

        # 3. ROTATING SERVO HORN ASSEMBLY
        self.rotating_horn = Entity(parent=self, position=(0, 1.0, 0))
        self.gear_spline = Entity(
            parent=self.rotating_horn,
            model='cylinder',
            scale=(0.3, 0.15, 0.3),
            color=color.gold,
            y=0.05
        )
        self.horn_arm = Entity(
            parent=self.rotating_horn,
            model='cube',
            scale=(1.0, 0.06, 0.25),
            color=color.light_gray,
            y=0.12
        )

    def spin(self, speed):
        self.rotating_horn.rotation_y += (speed * 0.4) * time.dt


# -------------------------------------------------------------
# WORLD OBJECT PLACEMENT
# -------------------------------------------------------------
hardware_assembly = ComplexDCMotor(position=(0, 0, 4))
active_mode = "MOTOR"
is_running = False


def update_hardware_type(new_type):
    global hardware_assembly, active_mode
    pos = hardware_assembly.position
    destroy(hardware_assembly)

    if new_type == "MOTOR":
        hardware_assembly = ComplexDCMotor(position=pos)
        active_mode = "MOTOR"
    elif new_type == "SERVO":
        hardware_assembly = ComplexServo(position=pos)
        active_mode = "SERVO"
    else:
        hardware_assembly = Entity(position=pos)
        active_mode = "NONE"


# -------------------------------------------------------------
# ROBLOX-STYLE INTERACTIVE FLOOR PADS
# -------------------------------------------------------------
start_pad = Button(
    text='[ RUN MOTOR ]',
    color=color.green,
    scale=(1.6, 0.1, 0.8),
    position=(-1.2, 0.01, 2.0),
    on_click=lambda: set_device_state(True)
)

stop_pad = Button(
    text='[ EMERGENCY STOP ]',
    color=color.red,
    scale=(1.6, 0.1, 0.8),
    position=(1.2, 0.01, 2.0),
    on_click=lambda: set_device_state(False)
)


def set_device_state(state):
    global is_running
    is_running = state
    if state:
        start_pad.blink(color.white, duration=0.15)
    else:
        stop_pad.blink(color.white, duration=0.15)


# -------------------------------------------------------------
# FIRST PERSON CHARACTER CONTROLLER
# -------------------------------------------------------------
player = FirstPersonController(position=(0, 0, 0), speed=5)
player.cursor.enabled = True

camera.position = (0, 1.8, 0)
camera.rotation = (10, 0, 0)

Text(
    text="FTC SANDBOX | Move: WASD | Look: Mouse | Click floor pads to test hardware",
    position=(-0.45, 0.46),
    color=color.black
)


# -------------------------------------------------------------
# STREAM DATA INPUT BACKPIPE (From Tkinter Control Hub)
# -------------------------------------------------------------
def read_input_stream():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        command = line.strip()

        if command == "START":
            set_device_state(True)
        elif command == "STOP":
            set_device_state(False)
        elif "CONFIG_MOTOR" in command:
            update_hardware_type("MOTOR")
        elif "CONFIG_SERVO" in command:
            update_hardware_type("SERVO")
        elif "CONFIG_NONE" in command:
            update_hardware_type("NONE")


input_thread = threading.Thread(target=read_input_stream, daemon=True)
input_thread.start()


# -------------------------------------------------------------
# RUNTIME ENGINE RENDERING TICK LOOP
# -------------------------------------------------------------
def update():
    if is_running and active_mode != "NONE":
        hardware_assembly.spin(speed=350)


app.run()