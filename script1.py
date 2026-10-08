"""
FTC Robot Builder + Simulator + BIOBUZZ (FTC 2026-27) event  (Ursina)
=====================================================================
Three tabs at the top of the screen:

PRACTICE      Drive your robot on the BIOBUZZ field with no clock.
ROBOT BUILD   Build your robot from 40 parts (catalog with pictures on the left).
BIOBUZZ EVENT A 12-team qualifier: play 5 full matches (30s AUTO, 8s transition,
              2:00 TELEOP) with an AI partner against 2 AI opponents. The other
              matches are simulated and the rankings table updates after each match.

BIOBUZZ in this sim (rules from the TechnoBlades team page, technoblades.pages.dev)
  * Launch Pollen/Nectar into your half of the central Hive. When the upward Cell
    is heavy enough it TIPS (+20), dumps its pieces and the other Cell becomes the target.
  * Each tip lets your human player add a Nectar. At 1:00 left the Flowers open and
    all remaining Nectar comes in. Nectar may only go in Flowers then (G410).
  * A Flower is owned by the alliance whose Nectar is on top: 2 pts per piece inside,
    +5 Bottom Nectar bonus. Garden 1 each, Upward Cell 2 each, Park 5, Leave 3.
  * Max 4 pieces carried (G407), no opponent Nectar (G408), no ramming the Hive (G417).
  * RP: Win 3 / Tie 1, SWARM (leave+park >= 16) 1, POLLINATOR 4+ tips 1, 7+ tips 1.
  The exact field geometry and Hive tip weight aren't published on that page, so the
  values marked (est.) in the BIOBUZZ section are estimates - edit them to match.

Install:  pip install ursina
Run:      python ftc_hub_simulator.py

DRIVING (practice + match TELEOP)
  W A S D drive + strafe (strafe needs 4 mecanum/omni wheels)   Q / E turn
  SPACE launch into your Hive (needs a Launcher)   V intake on/off, or claw grab
  F fill the Flower in front of you (needs a Slide raised above 21.5in, or an Arm)
  G drop a piece (e.g. in your Garden)   Up/Down lift   N human player Nectar (practice)
  TAB OpMode (practice)   R reset field   C Wi-Fi   T touch sensor   H spin hub
  1/2/3/4 camera: overview / follow / driver station / wiring bench   B build mode

BUILD CONTROLS
  Left click place   R/T/F rotate   M mirror   X/Delete delete   G pick up
  Up/Down move slides   Ctrl+Z or U undo   Esc deselect
  Right-drag orbit, scroll zoom, middle-drag pan
"""

from ursina import *
from ursina.shaders import lit_with_shadows_shader, unlit_shader
from panda3d.core import (NodePath, PerspectiveLens, PNMImage, TransparencyAttrib,
                          Camera as PandaCamera, Texture as PandaTexture)
import math
import random
import json
from pathlib import Path

app = Ursina(title='FTC Robot Builder + Simulator', borderless=False)
window.color = color.Color(.55, .64, .74, 1)

# Real-time shadows look nicer but crash some weaker / software GPUs.
# Set SHADOWS = True if your graphics card handles it.
SHADOWS = False
# Merge the static geometry of each part into one mesh (much faster).
FLATTEN = not SHADOWS

soft_light_shader = Shader(name='soft_light_shader', language=Shader.GLSL, vertex='''
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 p3d_Vertex;
in vec4 p3d_Color;
in vec3 p3d_Normal;
in vec2 p3d_MultiTexCoord0;
out vec2 texcoord;
out vec3 world_normal;
out vec4 vcol;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    texcoord = p3d_MultiTexCoord0;
    world_normal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);
    vcol = p3d_Color;
}
''', fragment='''
#version 140
uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;
in vec2 texcoord;
in vec3 world_normal;
in vec4 vcol;
out vec4 fragColor;
void main() {
    vec3 n = normalize(world_normal);
    vec3 L = normalize(vec3(0.35, 0.85, -0.45));
    float light = 0.42 + 0.58 * max(dot(n, L), 0.0) + 0.12 * max(n.y, 0.0);
    vec4 c = texture(p3d_Texture0, texcoord) * p3d_ColorScale * vcol;
    fragColor = vec4(c.rgb * light, c.a);
}
''')

SH = lit_with_shadows_shader if SHADOWS else soft_light_shader


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def C(r, g, b, a=255):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


ORANGE = C(235, 110, 25)
DARK = C(32, 33, 36)
BLACK = C(15, 15, 15)
GOLD = C(212, 175, 55)
SILVER = C(195, 195, 200)
ALU = C(172, 177, 184)
WHITE_JST = C(242, 242, 236)
YELLOW = C(232, 192, 40)


def box(parent, pos, scl, col, rot=(0, 0, 0)):
    return Entity(parent=parent, model='cube', position=pos, scale=scl,
                  rotation=rot, color=col, shader=SH)


_CYL_CACHE = {}


def cyl_mesh(res, radius, height):
    """Y-axis cylinder with proper normals. (Ursina's Cylinder() leaks hidden
    helper entities on every call and has no normals, so we build our own.)"""
    key = (res, round(radius, 5), round(height, 5))
    if key not in _CYL_CACHE:
        v, n, tris = [], [], []
        y0, y1 = -height / 2, height / 2
        for i in range(res):
            a0, a1 = 2 * math.pi * i / res, 2 * math.pi * (i + 1) / res
            p0 = (math.cos(a0) * radius, math.sin(a0) * radius)
            p1 = (math.cos(a1) * radius, math.sin(a1) * radius)
            am = (a0 + a1) / 2
            sn = Vec3(math.cos(am), 0, math.sin(am))
            k = len(v)
            v += [Vec3(p0[0], y0, p0[1]), Vec3(p1[0], y0, p1[1]), Vec3(p1[0], y1, p1[1]), Vec3(p0[0], y1, p0[1])]
            n += [sn] * 4
            tris += [k, k + 2, k + 1, k, k + 3, k + 2]
            k = len(v)
            v += [Vec3(0, y1, 0), Vec3(p0[0], y1, p0[1]), Vec3(p1[0], y1, p1[1])]
            n += [Vec3(0, 1, 0)] * 3
            tris += [k, k + 2, k + 1]
            k = len(v)
            v += [Vec3(0, y0, 0), Vec3(p0[0], y0, p0[1]), Vec3(p1[0], y0, p1[1])]
            n += [Vec3(0, -1, 0)] * 3
            tris += [k, k + 1, k + 2]
        _CYL_CACHE[key] = (v, n, tris)
    v, n, tris = _CYL_CACHE[key]
    return Mesh(vertices=v, triangles=tris, normals=n)


def cyl(parent, pos, radius, height, col, axis='y', rot=(0, 0, 0), res=20):
    # Cylinders are always built along Y and rotated onto the wanted axis
    # (Cylinder's own `direction` argument skews the mesh in newer Ursina).
    holder = Entity(parent=parent, position=pos, rotation=rot)
    turn = {'x': (0, 0, 90), 'y': (0, 0, 0), 'z': (90, 0, 0)}[axis]
    Entity(parent=holder, model=cyl_mesh(res, radius, height), rotation=turn, color=col, shader=SH)
    return holder


def ball(parent, pos, scl, col, lit=True):
    return Entity(parent=parent, model='sphere', position=pos, scale=scl,
                  color=col, shader=SH if lit else unlit_shader)


def label(parent, txt, pos, scl, col=color.white, rot=(0, 0, 0),
          origin=(0, 0), billboard=False, font=None):
    kw = dict(parent=parent, text=txt, position=pos, scale=scl, color=col,
              rotation=rot, origin=origin, billboard=billboard)
    if font:
        kw['font'] = font
    t = Text(**kw)
    t.setTwoSided(True)
    return t


def lerp_ang(a, b, t):
    d = (b - a + 180) % 360 - 180
    return a + d * t


# ----------------------------------------------------------------------------
# Control Hub   (real size ~143 x 103 x 29 mm -> built at 1.43 x 0.24 x 1.03)
# ----------------------------------------------------------------------------
class ControlHub(Entity):
    def __init__(self, title='CONTROL HUB', callouts=False, flip_labels=False, lid_color=ORANGE, **kw):
        super().__init__(**kw)
        lid = (90, 180, 0) if flip_labels else (90, 0, 0)
        W, H, D = 1.43, .24, 1.03
        self.W, self.H, self.D = W, H, D
        self.ports = {}

        def port(name, pos):
            self.ports[name] = Entity(parent=self, position=pos)

        # rounded body: two crossed boxes + corner cylinders
        box(self, (0, 0, 0), (W - .08, H, D), DARK)
        box(self, (0, 0, 0), (W, H, D - .08), DARK)
        for sx in (-1, 1):
            for sz in (-1, 1):
                cyl(self, (sx * (W / 2 - .04), 0, sz * (D / 2 - .04)), .04, H, DARK)

        # orange lid + recessed center panel + vent slots
        box(self, (0, H / 2 + .012, 0), (W - .1, .025, D - .1), lid_color)
        box(self, (0, H / 2 + .026, .05), (W - .5, .006, D - .55), C(205, 92, 18) if lid_color == ORANGE else C(78, 78, 86))
        for k in range(7):
            box(self, (-.35 + k * .1, H / 2 + .027, -.3), (.05, .006, .14), C(60, 30, 10))

        # mounting holes
        for sx in (-1, 1):
            for sz in (-1, 1):
                cyl(self, (sx * (W / 2 - .12), H / 2 + .027, sz * (D / 2 - .12)),
                    .035, .01, BLACK, res=12)

        # FRONT (-z): 4 motor power ports + 4 encoder JSTs
        for i in range(4):
            x = -.48 + i * .32
            box(self, (x, -.03, -D / 2 - .02), (.18, .1, .05), BLACK)
            box(self, (x - .04, -.03, -D / 2 - .046), (.05, .05, .006), C(150, 30, 30))
            box(self, (x + .04, -.03, -D / 2 - .046), (.05, .05, .006), C(40, 40, 40))
            box(self, (x, .07, -D / 2 - .015), (.12, .05, .04), WHITE_JST)
            label(self, f'M{i}', (x, H / 2 + .03, -D / 2 + .1), 2.2, BLACK, rot=lid)
            port(f'm{i}', (x, -.03, -D / 2 - .05))
            port(f'enc{i}', (x, .07, -D / 2 - .04))

        # BACK (+z): 6 servo headers (3 gold pins each)
        for i in range(6):
            x = -.55 + i * .22
            box(self, (x, .02, D / 2 + .03), (.14, .09, .07), BLACK)
            for p in range(3):
                cyl(self, (x - .04 + p * .04, .085, D / 2 + .03), .009, .06, GOLD, res=6)
            label(self, f'S{i}', (x, H / 2 + .03, D / 2 - .1), 2.2, BLACK, rot=lid)
            port(f's{i}', (x, .02, D / 2 + .07))

        # LEFT (-x): 4x I2C, 4x digital, 2x analog JSTs
        jst_cols = [C(242, 242, 236)] * 4 + [C(225, 235, 245)] * 4 + [C(245, 230, 220)] * 2
        for i, c in enumerate(jst_cols):
            box(self, (-W / 2 - .015, 0, -.4 + i * .09), (.04, .05, .07), c)
            name = ['i2c0', 'i2c1', 'i2c2', 'i2c3', 'dig0', 'dig1', 'dig2', 'dig3', 'an0', 'an1'][i]
            port(name, (-W / 2 - .04, 0, -.4 + i * .09))

        # RIGHT (+x): XT30, USB-C, USB-A, HDMI, RS485
        box(self, (W / 2 + .03, 0, -.33), (.06, .09, .14), YELLOW)          # XT30
        port('xt30', (W / 2 + .07, 0, -.33))
        box(self, (W / 2 + .01, .03, -.13), (.02, .035, .09), SILVER)       # USB-C
        box(self, (W / 2 + .015, 0, .04), (.03, .06, .13), SILVER)          # USB-A
        box(self, (W / 2 + .012, -.005, .22), (.025, .05, .15), C(45, 45, 48))  # HDMI
        box(self, (W / 2 + .03, 0, .39), (.06, .08, .1), BLACK)              # RS485

        # status LED with glow halo
        self.led = ball(self, (.5, H / 2 + .045, .32), .07, color.green, lit=False)
        self.halo = ball(self, (.5, H / 2 + .045, .32), .16,
                         color.Color(0, 1, 0, .25), lit=False)

        label(self, title, (0, H / 2 + .032, .05), 3.2, BLACK, rot=lid)

        if callouts:
            tag = dict(scl=6, col=color.white, billboard=True)
            label(self, 'Motor + encoder ports 0-3', (0, .35, -D / 2 - .25), **tag)
            label(self, 'Servo ports 0-5', (0, .35, D / 2 + .25), **tag)
            label(self, 'I2C / Digital / Analog', (-W / 2 - .45, .3, 0), **tag)
            label(self, 'XT30 / USB / HDMI / RS485', (W / 2 + .5, .3, 0), **tag)
            label(self, 'Status LED', (.5, .45, .32), **tag)

    def set_status(self, connected, state, t):
        if not connected:
            c = color.red if int(t * 4) % 2 == 0 else C(70, 0, 0)
        elif state == 'RUNNING':
            c = color.lime if int(t * 6) % 2 == 0 else C(0, 110, 0)
        elif state == 'INIT':
            c = C(255, 200, 0)
        else:
            c = C(0, 140, 255)
        self.led.color = c
        self.halo.color = color.Color(c.r, c.g, c.b, .25)


# ----------------------------------------------------------------------------
# Driver Hub (tablet)
# ----------------------------------------------------------------------------
class DriverHub(Entity):
    def __init__(self, **kw):
        super().__init__(**kw)
        W, H, D = 1.5, .95, .09
        body = C(28, 28, 30)
        box(self, (0, 0, 0), (W - .09, H, D), body)
        box(self, (0, 0, 0), (W, H - .09, D), body)
        for sx in (-1, 1):
            for sy in (-1, 1):
                cyl(self, (sx * (W / 2 - .045), sy * (H / 2 - .045), 0), .045, D, body, axis='z')

        sw, shh = W - .16, H - .14
        self.screen = Entity(parent=self, model='quad', position=(0, 0, -D / 2 - .002),
                             scale=(sw, shh), color=C(10, 18, 40))
        Entity(parent=self, model='quad', position=(0, shh / 2 - .04, -D / 2 - .004),
               scale=(sw, .08), color=C(235, 110, 25))
        label(self, 'DRIVER HUB  |  TeleOp', (-sw / 2 + .03, shh / 2 - .04, -D / 2 - .006),
              1.3, color.black, origin=(-.5, 0))
        self.wifi = label(self, 'WiFi', (sw / 2 - .1, shh / 2 - .04, -D / 2 - .006),
                          1.3, color.black, origin=(0, 0))

        self.tel = Text(parent=self, text='', font='VeraMono.ttf', origin=(-.5, .5),
                        position=(-sw / 2 + .03, shh / 2 - .1, -D / 2 - .006),
                        scale=.95, color=color.white)

        # big INIT / START / STOP button on screen
        self.btn = Entity(parent=self, model='circle', position=(sw / 2 - .15, -shh / 2 + .15, -D / 2 - .005),
                          scale=.18, color=C(0, 140, 255))
        self.btn_txt = label(self, 'INIT', (sw / 2 - .15, -shh / 2 + .15, -D / 2 - .007), 1.2, color.white)

        # physical buttons (power + volume on top edge), USB port bottom
        box(self, (.45, H / 2 + .01, 0), (.12, .03, .05), C(60, 60, 60))
        box(self, (.25, H / 2 + .01, 0), (.08, .03, .05), C(60, 60, 60))
        box(self, (.15, H / 2 + .01, 0), (.08, .03, .05), C(60, 60, 60))
        box(self, (-.4, -H / 2 - .005, 0), (.1, .02, .04), SILVER)

        # kickstand
        box(self, (0, -.15, D / 2 + .22), (.9, .05, .55), C(45, 45, 48), rot=(-55, 0, 0))

        self.antenna = Entity(parent=self, position=(0, H / 2 + .1, 0))

    def set_state_button(self, state, connected):
        if not connected:
            self.btn.color, self.btn_txt.text = C(150, 30, 30), 'NO RC'
        elif state == 'STOPPED':
            self.btn.color, self.btn_txt.text = C(0, 140, 255), 'INIT'
        elif state == 'INIT':
            self.btn.color, self.btn_txt.text = C(30, 170, 60), 'START'
        else:
            self.btn.color, self.btn_txt.text = C(200, 40, 40), 'STOP'
        self.wifi.color = color.black if connected else color.red


# ----------------------------------------------------------------------------
# Gamepad
# ----------------------------------------------------------------------------
class Gamepad(Entity):
    def __init__(self, **kw):
        super().__init__(**kw)
        shell = C(40, 42, 46)
        box(self, (0, 0, 0), (.75, .1, .38), shell)
        for sx in (-1, 1):
            ball(self, (sx * .36, -.01, -.1), (.28, .12, .4), shell)
            box(self, (sx * .27, .03, .2), (.2, .05, .06), C(70, 70, 75))  # bumpers

        def stick(x, z):
            cyl(self, (x, .055, z), .075, .02, C(20, 20, 20))
            piv = Entity(parent=self, position=(x, .06, z))
            cyl(piv, (0, .035, 0), .02, .07, C(25, 25, 25), res=10)
            cyl(piv, (0, .08, 0), .055, .025, C(55, 55, 60))
            return piv

        self.lp = stick(-.18, .03)
        self.rp = stick(.12, -.1)

        # D-pad
        box(self, (-.3, .06, .06), (.13, .02, .04), C(25, 25, 25))
        box(self, (-.3, .06, .06), (.04, .02, .13), C(25, 25, 25))

        # ABXY
        self.face = {}
        for name, (dx, dz), c in [('Y', (0, .055), C(240, 200, 40)), ('A', (0, -.055), C(60, 190, 60)),
                                  ('X', (-.055, 0), C(50, 110, 230)), ('B', (.055, 0), C(220, 50, 50))]:
            self.face[name] = cyl(self, (.3 + dx, .06, .06 + dz), .025, .025, c, res=12)

        cyl(self, (0, .055, .1), .03, .015, C(200, 200, 200), res=12)  # center button

    def show(self, f, s, t):
        self.lp.rotation = (f * 25, 0, -s * 25)
        self.rp.rotation = (0, 0, -t * 25)


# ----------------------------------------------------------------------------
# Cables (multi-strand, with a travelling signal pulse)
# ----------------------------------------------------------------------------
class Cable:
    def __init__(self, pts, colors, radius=.016, pulse_col=color.cyan):
        self.pts = [Vec3(*p) for p in pts]
        self.root = Entity()
        for i, c in enumerate(colors):
            off = Vec3(0, i * radius * 2.1, 0)
            for a, b in zip(self.pts, self.pts[1:]):
                a2, b2 = a + off, b + off
                L = distance(a2, b2)
                if L < 1e-4:
                    continue
                seg = Entity(parent=self.root, position=(a2 + b2) / 2)
                seg.look_at(b2)
                cyl(seg, (0, 0, 0), radius, L, c, axis='z', res=8)
            for q in self.pts[1:-1]:
                ball(self.root, q + off, radius * 2, c)
        self.seg_len = [distance(a, b) for a, b in zip(self.pts, self.pts[1:])]
        self.total = sum(self.seg_len) or 1
        self.pulse = ball(scene, self.pts[0], radius * 4, pulse_col, lit=False)
        self.pulse.enabled = False
        self.u = random.random()

    def point_at(self, u):
        d = u * self.total
        for (a, b), L in zip(zip(self.pts, self.pts[1:]), self.seg_len):
            if d <= L and L > 0:
                return lerp(a, b, d / L)
            d -= L
        return self.pts[-1]

    def update(self, dt, active, reverse=False, speed=.7):
        self.pulse.enabled = active
        if active:
            self.u = (self.u + dt * speed) % 1
            self.pulse.position = self.point_at(1 - self.u if reverse else self.u)


# ----------------------------------------------------------------------------
# Wiring bench - Control Hub wired to battery, switch, motors, servo, sensors
# (laid out like a typical "Control Hub wiring reference" diagram)
# ----------------------------------------------------------------------------
JST4 = [BLACK, C(200, 30, 30), WHITE_JST, C(40, 90, 220)]
SERVO3 = [BLACK, C(200, 30, 30), WHITE_JST]
POWER2 = [C(200, 30, 30), BLACK]


class WiringBench(Entity):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cables = {}
        self.readouts = {}
        top_y = .02

        self.hub = ControlHub(parent=self, title='CONTROL HUB', position=(0, .14, 0), rotation_y=180, flip_labels=True)

        def tag(name, pos, reading=False):
            label(self, name, pos, 3.6, color.white, billboard=True)
            if reading:
                self.readouts[name] = label(self, '', Vec3(*pos) + Vec3(0, -.11, 0), 3.2,
                                            C(120, 255, 160), billboard=True)
        label(self, 'CONTROL HUB WIRING', (0, .75, 0), 6, color.white, billboard=True)

        # --- power: slim battery -> switch cable & bracket -> XT30 ---
        box(self, (-2.0, .07, .55), (.75, .12, .5), C(28, 28, 30))
        box(self, (-2.0, .135, .55), (.6, .01, .3), C(200, 30, 30))
        label(self, '12V SLIM', (-2.0, .145, .55), 3, color.white, rot=(90, 0, 0))
        tag('Slim Battery', (-2.0, .4, .55))
        box(self, (-1.15, .06, .95), (.3, .1, .12), C(60, 60, 65))      # bracket
        self.switch = box(self, (-1.15, .14, .95), (.08, .08, .05), C(210, 30, 30))
        tag('Switch Cable + Bracket', (-1.15, .4, .95))

        # --- Core Hex motor (lift) ---
        cyl(self, (-1.9, .2, -.25), .17, .28, C(45, 45, 50), axis='x', res=6)
        self.core_shaft = Entity(parent=self, position=(-2.12, .2, -.25))
        cyl(self.core_shaft, (0, 0, 0), .035, .18, SILVER, axis='x', res=6)
        box(self.core_shaft, (-.07, .05, 0), (.02, .1, .02), ORANGE)    # marker to show spin
        tag('Core Hex Motor', (-1.9, .55, -.25), True)

        # --- HD Hex motor (drive) ---
        cyl(self, (-1.95, .2, -.9), .13, .22, C(150, 150, 158), axis='x', res=6)   # gearbox
        cyl(self, (-1.62, .2, -.9), .12, .45, C(20, 20, 22), axis='x')            # motor can
        cyl(self, (-1.38, .2, -.9), .06, .05, C(60, 60, 60), axis='x')            # encoder cap
        self.hd_shaft = Entity(parent=self, position=(-2.13, .2, -.9))
        cyl(self.hd_shaft, (0, 0, 0), .035, .16, SILVER, axis='x', res=6)
        box(self.hd_shaft, (-.06, .05, 0), (.02, .1, .02), ORANGE)
        tag('HD Hex Motor', (-1.7, .55, -.9), True)

        # --- Smart Robot Servo (claw) ---
        box(self, (-.45, .2, -1.05), (.4, .36, .2), C(22, 22, 24))
        box(self, (-.45, .2, -1.05), (.52, .04, .2), C(22, 22, 24))     # mounting ears
        self.horn = Entity(parent=self, position=(-.55, .4, -1.05))
        cyl(self.horn, (0, 0, 0), .04, .04, WHITE_JST)
        box(self.horn, (0, .02, 0), (.3, .02, .05), WHITE_JST)
        tag('Smart Robot Servo', (-.45, .7, -1.05), True)

        # --- Potentiometer (lift position) ---
        box(self, (.5, .06, -1.05), (.24, .08, .24), C(30, 30, 34))
        self.knob = Entity(parent=self, position=(.5, .14, -1.05))
        cyl(self.knob, (0, 0, 0), .07, .08, WHITE_JST)
        box(self.knob, (0, .045, .04), (.015, .01, .06), BLACK)
        tag('Potentiometer', (.5, .42, -1.05), True)

        # --- sensors on the right side ---
        def board(z, col=C(30, 30, 34)):
            return box(self, (2.0, .04, z), (.35, .04, .3), col)

        board(.85)
        self.color_led = ball(self, (2.0, .08, .85), .07, color.white, lit=False)
        for dx in (-.08, .08):
            ball(self, (2.0 + dx, .07, .78), .035, color.white, lit=False)
        tag('Color Sensor V2', (2.0, .38, .85), True)

        board(.35)
        box(self, (2.0, .07, .35), (.12, .03, .07), C(5, 5, 5))
        self.beam = Entity(parent=self, model='cube', position=(2.0, .07, .35),
                           scale=(.02, .02, .01), color=color.Color(1, .2, .2, .5))
        tag('2m Distance Sensor', (2.0, .38, .35), True)

        board(-.15)
        cyl(self, (2.0, .07, -.15), .09, .03, C(60, 60, 64))
        self.touch_btn = cyl(self, (2.0, .1, -.15), .06, .05, C(200, 30, 30))
        tag('Touch Sensor', (2.0, .38, -.15), True)

        board(-.65)
        self.mag_led = ball(self, (2.08, .07, -.72), .03, C(60, 0, 0), lit=False)
        self.magnet = box(self, (2.0, .08, -.65), (.12, .06, .1), C(200, 40, 40))
        tag('Magnetic Limit Switch', (2.0, .38, -.65), True)

        # --- cables (world space, routed down to the table and along it) ---
        o = self.world_position
        hp = lambda n: self.hub.ports[n].world_position

        def route(a, b, out):
            a1 = a + out * .18
            a2 = Vec3(a1.x + out.x * .12, o.y + top_y, a1.z + out.z * .12)
            b = o + Vec3(*b)
            b1 = Vec3(lerp(a2.x, b.x, .8), o.y + top_y, lerp(a2.z, b.z, .8) + .001)
            return [a, a1, a2, b1, b]

        L, R, F, B = Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 0, -1), Vec3(0, 0, 1)
        self.cables['battery'] = Cable([o + Vec3(-1.62, .08, .6), o + Vec3(-1.45, top_y, .8),
                                        o + Vec3(-1.3, .07, .95)], POWER2, pulse_col=YELLOW)
        self.cables['switch'] = Cable(route(hp('xt30'), (-1.0, .08, .95), L), POWER2, pulse_col=YELLOW)
        self.cables['hd'] = Cable(route(hp('m0'), (-1.36, .14, -.9), B), POWER2, pulse_col=color.lime)
        self.cables['hd_enc'] = Cable(route(hp('enc0'), (-1.36, .26, -.9), B), JST4, radius=.01)
        self.cables['core'] = Cable(route(hp('m1'), (-1.75, .3, -.25), B), POWER2, pulse_col=color.lime)
        self.cables['servo'] = Cable(route(hp('s0'), (-.45, .1, -.93), F), SERVO3, radius=.012)
        self.cables['pot'] = Cable(route(hp('an0'), (.5, .06, -.92), R), JST4[:3], radius=.01)
        self.cables['color'] = Cable(route(hp('i2c0'), (1.82, .05, .85), R), JST4, radius=.01)
        self.cables['dist'] = Cable(route(hp('i2c1'), (1.82, .05, .35), R), JST4, radius=.01)
        self.cables['touch'] = Cable(route(hp('dig0'), (1.82, .05, -.15), R), JST4, radius=.01)
        self.cables['mag'] = Cable(route(hp('dig1'), (1.82, .05, -.65), R), JST4, radius=.01)

        self.timer = 0

    def update_bench(self, dt, d):
        """d: dict of live robot values."""
        on = d['connected']
        self.hub.set_status(on, d['state'], d['clock'])
        self.hd_shaft.rotation_x += d['drive'] * 900 * dt
        self.core_shaft.rotation_x += d['lift_in'] * 600 * dt
        self.horn.rotation_y = lerp(0, 90, 1 - d['claw_amt'])
        self.knob.rotation_y = d['lift_frac'] * 270
        self.touch_btn.y = .085 if d['touch'] else .1
        self.magnet.x = 2.0 if d['mag'] else 2.0 + .35
        self.mag_led.color = color.red if d['mag'] else C(60, 0, 0)
        self.color_led.color = d['color_rgb']
        self.beam.scale_z = max(.01, d['dist_cm'] / 200 * .6)
        self.beam.z = .35 - self.beam.scale_z / 2 - .04

        c = self.cables
        c['battery'].update(dt, True)
        c['switch'].update(dt, True)
        c['hd'].update(dt, abs(d['drive']) > .02, speed=1.2)
        c['hd_enc'].update(dt, abs(d['drive']) > .02, reverse=True)
        c['core'].update(dt, abs(d['lift_in']) > .02, speed=1.2)
        c['servo'].update(dt, on)
        for n in ('pot', 'color', 'dist', 'touch', 'mag'):
            c[n].update(dt, on, reverse=True)

        self.timer += dt
        if self.timer > .1:
            self.timer = 0
            r = self.readouts
            r['HD Hex Motor'].text = f"power {d['drive']:+.2f}"
            r['Core Hex Motor'].text = f"power {d['lift_in']:+.2f}"
            r['Smart Robot Servo'].text = f"pos {1 - d['claw_amt']:.2f}"
            r['Potentiometer'].text = f"{d['lift_frac'] * 3.3:.2f} V"
            r['Color Sensor V2'].text = d['color_name']
            r['2m Distance Sensor'].text = (f"{d['dist_cm']:.0f} cm" if d['dist_cm'] < 200 else 'out of range')
            r['Touch Sensor'].text = 'PRESSED' if d['touch'] else 'released'
            r['Magnetic Limit Switch'].text = 'TRIGGERED' if d['mag'] else 'clear'


# ----------------------------------------------------------------------------
# PARTS CATALOG
# Every part is a small builder function that creates its geometry under a
# root entity and returns "handles" for anything that moves (wheels, claws...).
# Units: 1 unit = 1 ft. Robot forward is +Z, ground is y = 0.
# ----------------------------------------------------------------------------
HOLE = C(38, 38, 42)
CATEGORIES = ['Structure', 'Wheels', 'Motors & Gears', 'Electronics', 'Sensors', 'Mechanisms']
PARTS = {}
MIRROR = {'mecanum_l': 'mecanum_r', 'mecanum_r': 'mecanum_l'}


def part(pid, name, short, cat, kg, desc):
    def deco(fn):
        PARTS[pid] = dict(id=pid, name=name, short=short, cat=cat, kg=kg, desc=desc, build=fn)
        return fn
    return deco


# ---------------- Structure ----------------
def _uchannel(p, L):
    box(p, (-.034, 0, 0), (.012, .16, L), ALU)                      # web
    for sy in (-1, 1):
        box(p, (0, sy * .074, 0), (.08, .012, L), ALU)               # flanges
    n = max(2, int(L / .12))
    for k in range(n):
        z = -L / 2 + .06 + k * (L - .12) / (n - 1)
        for y in (-.03, .03):
            cyl(p, (-.041, y, z), .016, .004, HOLE, axis='x', res=8)
        cyl(p, (0, .081, z), .016, .004, HOLE, res=8)


@part('uch_432', 'U-Channel 432mm', 'U-Ch 432', 'Structure', .20,
      'Long aluminium U-channel. Great for the side rails of a big chassis.')
def _p(p): _uchannel(p, 1.42)


@part('uch_288', 'U-Channel 288mm', 'U-Ch 288', 'Structure', .14,
      'Medium U-channel with a 24mm hole pattern. The standard chassis rail.')
def _p(p): _uchannel(p, .94)


@part('uch_144', 'U-Channel 144mm', 'U-Ch 144', 'Structure', .08,
      'Short U-channel for cross members, towers and brackets.')
def _p(p): _uchannel(p, .47)


@part('ext_420', '15mm Extrusion 420mm', 'Extrusion', 'Structure', .15,
      'T-slot extrusion. Bolt anything anywhere along its length.')
def _p(p):
    L = 1.38
    box(p, (0, 0, 0), (.05, .05, L), C(185, 188, 196))
    for pos, scl in [((0, .025, 0), (.014, .003, L)), ((0, -.025, 0), (.014, .003, L)),
                     ((.025, 0, 0), (.003, .014, L)), ((-.025, 0, 0), (.003, .014, L))]:
        box(p, pos, scl, HOLE)
    for sz in (-1, 1):
        box(p, (0, 0, sz * L / 2), (.052, .052, .01), BLACK)


@part('plate_deck', 'Polycarbonate Deck Plate', 'Deck Plate', 'Structure', .40,
      'Big flat deck to mount the hubs, battery and mechanisms on.')
def _p(p):
    box(p, (0, 0, 0), (.9, .02, 1.0), C(46, 52, 64))
    for i in range(5):
        for j in range(6):
            cyl(p, (-.36 + i * .18, .011, -.42 + j * .168), .025, .004, C(22, 24, 30), res=8)


@part('plate_flat', 'Flat Bracket Plate', 'Flat Plate', 'Structure', .05,
      'Small aluminium gusset plate with a 3x3 hole grid.')
def _p(p):
    box(p, (0, 0, 0), (.3, .015, .3), ALU)
    for i in range(3):
        for j in range(3):
            cyl(p, (-.1 + i * .1, .008, -.1 + j * .1), .016, .004, HOLE, res=8)


@part('l_bracket', '90 Degree L-Bracket', 'L-Bracket', 'Structure', .03,
      'Joins two pieces at a right angle.')
def _p(p):
    box(p, (0, 0, 0), (.2, .012, .2), ALU)
    box(p, (0, .094, -.094), (.2, .2, .012), ALU)
    for x in (-.05, .05):
        cyl(p, (x, .007, .03), .016, .004, HOLE, res=8)
        cyl(p, (x, .12, -.1), .016, .004, HOLE, axis='z', res=8)


@part('standoff', 'Hex Standoff 75mm', 'Standoff', 'Structure', .01,
      'Spacer post for stacking plates and hubs.')
def _p(p):
    cyl(p, (0, 0, 0), .022, .25, SILVER, res=6)
    for sy in (-1, 1):
        cyl(p, (0, sy * .13, 0), .03, .012, C(60, 60, 64), res=12)


@part('bumper', 'Team Bumper', 'Bumper', 'Structure', .30,
      'Padded bumper bar in team colours. Protects the frame from hits.')
def _p(p):
    box(p, (0, 0, 0), (1.0, .12, .1), C(30, 80, 200))
    for sz in (-1, 1):
        cyl(p, (0, 0, sz * .05), .06, 1.0, C(30, 80, 200), axis='x', res=12)
    label(p, '12345', (0, 0, .112), 5, color.white, rot=(0, 180, 0))
    label(p, '12345', (0, 0, -.112), 5, color.white)


@part('number_plate', 'Team Number Plate', 'Number', 'Structure', .05,
      'Required team number sign. Must be visible from the sides.')
def _p(p):
    box(p, (0, 0, 0), (.6, .2, .015), color.white)
    label(p, '12345', (0, 0, -.009), 7, BLACK)
    label(p, '12345', (0, 0, .009), 7, BLACK, rot=(0, 180, 0))


# ---------------- Wheels (axle along X) ----------------
def _mecanum(p, sg):
    spin = Entity(parent=p)
    cyl(spin, (0, 0, 0), .11, .12, C(45, 45, 48), axis='x')
    for side in (-1, 1):
        cyl(spin, (side * .06, 0, 0), .15, .012, C(205, 205, 212), axis='x')
    for k in range(10):
        h = Entity(parent=spin, rotation_x=k * 36)
        m = Entity(parent=h, position=(0, .145, 0), rotation_y=45 * sg)
        cyl(m, (0, 0, 0), .03, .11, C(32, 32, 34), axis='z', res=8)
    cyl(p, (0, 0, 0), .02, .2, SILVER, axis='x', res=6)
    return {'spin': spin, 'wheel': 'mecanum', 'radius': .175}


@part('mecanum_l', 'Mecanum Wheel (Left)', 'Mecanum L', 'Wheels', .32,
      'Angled rollers let the robot strafe sideways. Use 2 left + 2 right in an X pattern.')
def _p(p): return _mecanum(p, 1)


@part('mecanum_r', 'Mecanum Wheel (Right)', 'Mecanum R', 'Wheels', .32,
      'Mirror image of the left mecanum wheel. Mirror mode swaps them for you.')
def _p(p): return _mecanum(p, -1)


@part('omni', 'Omni Wheel 90mm', 'Omni', 'Wheels', .25,
      'Free-spinning side rollers. Four at 45 degrees make an X-drive.')
def _p(p):
    spin = Entity(parent=p)
    cyl(spin, (0, 0, 0), .1, .1, C(150, 155, 165), axis='x')
    for row, off in ((-.03, 0), (.03, 18)):
        for k in range(10):
            h = Entity(parent=spin, rotation_x=k * 36 + off)
            cyl(h, (row, .135, 0), .028, .07, C(40, 40, 44), axis='z', res=8)
    cyl(p, (0, 0, 0), .02, .18, SILVER, axis='x', res=6)
    return {'spin': spin, 'wheel': 'omni', 'radius': .163}


@part('traction', 'Traction Wheel 90mm', 'Traction', 'Wheels', .20,
      'Grippy rubber tread. Pushes hard but cannot strafe.')
def _p(p):
    spin = Entity(parent=p)
    cyl(spin, (0, 0, 0), .15, .1, C(25, 25, 27), axis='x', res=24)
    cyl(spin, (0, 0, 0), .1, .11, C(170, 172, 180), axis='x', res=24)
    for k in range(5):
        box(spin, (0, 0, 0), (.115, .17, .025), C(120, 124, 132), rot=(k * 36, 0, 0))
    for k in range(16):
        h = Entity(parent=spin, rotation_x=k * 22.5)
        box(h, (0, .15, 0), (.1, .012, .02), C(45, 45, 48))
    cyl(p, (0, 0, 0), .02, .16, SILVER, axis='x', res=6)
    return {'spin': spin, 'wheel': 'traction', 'radius': .156}


@part('compliant', 'Compliant Wheel', 'Compliant', 'Wheels', .10,
      'Soft squishy wheel. Mostly used for intakes, can also drive.')
def _p(p):
    spin = Entity(parent=p)
    cyl(spin, (0, 0, 0), .13, .1, C(60, 175, 80), axis='x', res=24)
    cyl(spin, (0, 0, 0), .05, .11, C(35, 35, 38), axis='x', res=6)
    for k in range(6):
        box(spin, (0, 0, 0), (.104, .2, .02), C(50, 150, 70), rot=(k * 30, 0, 0))
    return {'spin': spin, 'wheel': 'compliant', 'radius': .13}


# ---------------- Motors & Gears ----------------
@part('hd_hex', 'HD Hex Motor + UltraPlanetary', 'HD Hex', 'Motors & Gears', .42,
      'Main drive motor with a stackable gearbox and built-in encoder. Shaft points -X.')
def _p(p):
    cyl(p, (-.1, 0, 0), .07, .14, C(150, 152, 160), axis='x', res=8)
    for k in range(3):
        cyl(p, (-.16 + k * .05, 0, 0), .074, .008, C(95, 95, 100), axis='x', res=8)
    cyl(p, (.08, 0, 0), .062, .22, C(22, 22, 24), axis='x')
    cyl(p, (.2, 0, 0), .045, .03, C(60, 60, 64), axis='x')
    box(p, (.2, .05, 0), (.03, .04, .06), WHITE_JST)
    shaft = Entity(parent=p, position=(-.2, 0, 0))
    cyl(shaft, (0, 0, 0), .022, .08, SILVER, axis='x', res=6)
    box(shaft, (-.02, .02, 0), (.01, .02, .01), ORANGE)
    return {'motor': 'hd', 'shaft': shaft}


@part('core_hex', 'Core Hex Motor', 'Core Hex', 'Motors & Gears', .27,
      'Compact motor with a hex output through both sides. Good for lifts and arms.')
def _p(p):
    box(p, (0, 0, 0), (.13, .17, .17), C(48, 48, 54))
    cyl(p, (0, 0, 0), .095, .135, C(60, 60, 66), axis='x', res=6)
    box(p, (0, .095, -.04), (.05, .025, .06), WHITE_JST)
    shaft = Entity(parent=p)
    cyl(shaft, (0, 0, 0), .022, .22, SILVER, axis='x', res=6)
    box(shaft, (-.1, .02, 0), (.01, .02, .01), ORANGE)
    return {'motor': 'core', 'shaft': shaft}


def _toothed(p, r, teeth, col):
    cyl(p, (0, 0, 0), r, .02, col, axis='x', res=32)
    for k in range(teeth):
        h = Entity(parent=p, rotation_x=k * 360 / teeth)
        box(h, (0, r + .012, 0), (.02, .028, .022), col)
    cyl(p, (0, 0, 0), .026, .024, HOLE, axis='x', res=6)


@part('sprocket', '15 Tooth Sprocket', 'Sprocket', 'Motors & Gears', .03,
      'Chain sprocket for #25 chain. Transfers power between shafts.')
def _p(p): _toothed(p, .09, 15, SILVER)


@part('gear', '72 Tooth Spur Gear', 'Gear 72T', 'Motors & Gears', .06,
      'Large gear for slowing a motor down and adding torque.')
def _p(p):
    _toothed(p, .16, 28, C(210, 212, 220))
    for k in range(5):
        h = Entity(parent=p, rotation_x=k * 72)
        cyl(h, (0, .09, 0), .03, .024, HOLE, axis='x', res=10)


@part('bearing', 'Pillow Block Bearing', 'Bearing', 'Motors & Gears', .03,
      'Supports a spinning shaft so it does not wobble.')
def _p(p):
    box(p, (0, 0, 0), (.06, .05, .2), C(40, 40, 44))
    cyl(p, (0, .04, 0), .05, .06, C(40, 40, 44), axis='x')
    cyl(p, (0, .04, 0), .028, .065, SILVER, axis='x', res=12)


@part('servo', 'Smart Robot Servo', 'Servo', 'Motors & Gears', .06,
      'Programmable servo for claws, flippers and latches. Plugs into a servo port.')
def _p(p):
    box(p, (0, 0, 0), (.13, .12, .066), C(22, 22, 24))
    box(p, (0, .03, 0), (.18, .012, .066), C(22, 22, 24))
    cyl(p, (-.03, .068, 0), .022, .02, WHITE_JST)
    box(p, (-.03, .08, 0), (.1, .012, .022), WHITE_JST)
    label(p, 'SRS', (.02, 0, -.034), 3, color.white)


@part('cr_servo', 'Continuous Rotation Servo', 'CR Servo', 'Motors & Gears', .07,
      'A servo set to spin forever. Handy for small rollers.')
def _p(p):
    box(p, (0, 0, 0), (.13, .12, .066), C(30, 30, 60))
    box(p, (0, .03, 0), (.18, .012, .066), C(30, 30, 60))
    cyl(p, (-.03, .085, 0), .06, .02, C(140, 140, 150), res=16)
    label(p, 'CR', (.02, 0, -.034), 3, color.white)


# ---------------- Electronics ----------------
@part('control_hub', 'Control Hub', 'Control Hub', 'Electronics', .26,
      'The robot brain: Wi-Fi to the Driver Hub, 4 motor ports, 6 servo ports, sensors.')
def _p(p): return {'hub': ControlHub(parent=p, scale=.33)}


@part('expansion_hub', 'Expansion Hub', 'Exp. Hub', 'Electronics', .25,
      'Adds 4 more motor ports and 6 more servo ports. Connects over RS485.')
def _p(p): ControlHub(parent=p, scale=.33, title='EXPANSION HUB', lid_color=C(95, 95, 102))


@part('battery', '12V Slim Battery', 'Battery', 'Electronics', .60,
      'The only legal power source. 3000mAh NiMH.')
def _p(p):
    box(p, (0, 0, 0), (.5, .13, .2), C(28, 28, 30))
    box(p, (0, .066, 0), (.4, .004, .12), C(200, 30, 30))
    label(p, '12V SLIM', (0, .07, 0), 3.5, color.white, rot=(90, 0, 0))
    box(p, (.26, 0, -.03), (.03, .03, .03), C(200, 30, 30))
    box(p, (.26, 0, .03), (.03, .03, .03), BLACK)


@part('switch', 'Switch Cable + Bracket', 'Switch', 'Electronics', .05,
      'Main power switch. Must be easy for field staff to reach.')
def _p(p):
    box(p, (0, 0, 0), (.18, .06, .1), C(70, 70, 76))
    box(p, (0, .045, 0), (.06, .04, .04), C(210, 30, 30))


@part('spm', 'Servo Power Module', 'Servo PM', 'Electronics', .06,
      'Boosts power to up to 6 extra servos.')
def _p(p):
    box(p, (0, 0, 0), (.2, .05, .14), C(25, 25, 28))
    for i in range(6):
        for k in range(3):
            cyl(p, (-.075 + i * .03, .04, -.05 + k * .015), .005, .03, GOLD, res=4)
    label(p, 'SPM', (0, .026, .03), 3, color.white, rot=(90, 0, 0))


@part('sparkmini', 'SPARKmini Motor Controller', 'SPARKmini', 'Electronics', .05,
      'Drives an extra motor from a servo port.')
def _p(p):
    box(p, (0, 0, 0), (.18, .06, .1), C(200, 35, 35))
    for sx in (-1, 1):
        box(p, (sx * .095, 0, 0), (.012, .065, .105), BLACK)
    label(p, 'SPARK', (0, .031, 0), 3, color.white, rot=(90, 0, 0))


# ---------------- Sensors ----------------
@part('color', 'Color Sensor V2', 'Color', 'Sensors', .02,
      'Reads colour and light. Mount it facing down near the claw to see samples.')
def _p(p):
    box(p, (0, 0, 0), (.12, .02, .1), C(30, 30, 34))
    ball(p, (-.025, -.012, 0), .03, color.white, lit=False)
    ball(p, (.025, -.012, 0), .03, color.white, lit=False)
    box(p, (0, .015, -.04), (.05, .02, .02), WHITE_JST)
    return {'color_sensor': True}


@part('dist', '2m Distance Sensor', '2m Dist', 'Sensors', .02,
      'Laser time-of-flight sensor, faces +Z. Measures distance to walls up to 2m.')
def _p(p):
    box(p, (0, 0, 0), (.1, .05, .03), C(20, 20, 24))
    box(p, (0, 0, .016), (.05, .02, .004), C(200, 40, 40))
    box(p, (0, .035, 0), (.04, .02, .02), WHITE_JST)


@part('touch', 'Touch Sensor', 'Touch', 'Sensors', .02,
      'A simple button. Presses when it bumps into something.')
def _p(p):
    box(p, (0, 0, 0), (.1, .04, .08), C(30, 30, 34))
    cyl(p, (0, 0, .05), .03, .03, C(200, 30, 30), axis='z')


@part('mag', 'Magnetic Limit Switch', 'Mag Limit', 'Sensors', .02,
      'Detects a magnet. Used to know when a lift is all the way down.')
def _p(p):
    box(p, (0, 0, 0), (.08, .02, .08), C(30, 30, 34))
    ball(p, (.025, .015, -.025), .02, color.red, lit=False)


@part('pot', 'Potentiometer', 'Pot', 'Sensors', .02,
      'Measures the angle of a shaft. Good for arms.')
def _p(p):
    box(p, (0, 0, 0), (.1, .06, .1), C(30, 30, 34))
    cyl(p, (0, .05, 0), .035, .04, WHITE_JST)
    box(p, (0, .072, .015), (.008, .006, .03), BLACK)


@part('webcam', 'USB Webcam', 'Webcam', 'Sensors', .08,
      'Camera for AprilTags and object detection. Faces +Z.')
def _p(p):
    box(p, (0, 0, 0), (.25, .08, .06), C(25, 25, 28))
    cyl(p, (0, 0, .035), .03, .02, C(55, 55, 60), axis='z')
    ball(p, (0, 0, .044), .04, C(60, 120, 200))
    box(p, (0, -.06, -.01), (.06, .04, .05), C(40, 40, 44))


@part('encoder', 'Through-Bore Encoder', 'Encoder', 'Sensors', .03,
      'Counts shaft rotations very precisely.')
def _p(p):
    cyl(p, (0, 0, 0), .07, .05, C(25, 25, 28), axis='x')
    cyl(p, (0, 0, 0), .025, .055, HOLE, axis='x', res=6)
    box(p, (0, .07, 0), (.03, .02, .04), WHITE_JST)


# ---------------- Mechanisms ----------------
@part('slide', 'Linear Slide Kit', 'Lin. Slide', 'Mechanisms', 1.0,
      'Two-stage lift. Anything you attach to it rides up and down with the carriage.')
def _p(p):
    box(p, (0, .015, 0), (.6, .03, .14), ALU)
    for sx in (-1, 1):
        box(p, (sx * .25, .54, 0), (.06, 1.05, .06), ALU)
        cyl(p, (sx * .25, 1.09, 0), .035, .03, BLACK, axis='x')
    box(p, (0, 1.07, 0), (.56, .04, .06), ALU)
    cyl(p, (.36, .09, 0), .055, .13, C(48, 48, 54), axis='x', res=6)     # spool motor
    car = Entity(parent=p, position=(0, .1, .06))
    for sx in (-1, 1):
        box(car, (sx * .25, .4, 0), (.045, .8, .045), C(150, 155, 162))
    box(car, (0, 0, 0), (.6, .1, .03), C(45, 45, 50))
    car.owner = p
    return {'carriage': car, 'travel': .85, 'base_y': .1}


@part('claw', 'Servo Claw', 'Claw', 'Mechanisms', .25,
      'Two-finger servo claw on a drop-down plate. Grabs samples off the floor.')
def _p(p):
    box(p, (0, -.2, 0), (.08, .4, .02), ALU)
    box(p, (0, -.36, .06), (.4, .05, .1), C(50, 50, 55))
    box(p, (0, -.31, .06), (.12, .06, .07), BLACK)
    fl = box(p, (-.17, -.39, .15), (.035, .14, .16), C(220, 120, 30))
    fr = box(p, (.17, -.39, .15), (.035, .14, .16), C(220, 120, 30))
    grab = Entity(parent=p, position=(0, -.38, .15))
    return {'claw': (fl, fr, .17, .115), 'grab': grab}


@part('intake', 'Roller Intake', 'Intake', 'Mechanisms', .40,
      'Spinning rubber flaps that suck game pieces in.')
def _p(p):
    for sx in (-1, 1):
        box(p, (sx * .27, 0, 0), (.012, .2, .22), ALU)
    spin = Entity(parent=p)
    cyl(spin, (0, 0, 0), .025, .54, SILVER, axis='x', res=6)
    for k in range(6):
        box(spin, (0, 0, 0), (.48, .2, .012), C(40, 150, 220), rot=(k * 30, 0, 0))
    box(p, (.33, 0, 0), (.1, .14, .14), C(48, 48, 54))
    return {'intake': spin}


@part('arm', 'Servo Arm', 'Arm', 'Mechanisms', .20,
      'A pivoting arm with a hook on the end. Points along +Z.')
def _p(p):
    box(p, (0, 0, 0), (.13, .12, .066), C(22, 22, 24))
    box(p, (0, .07, .28), (.06, .04, .6), ALU)
    box(p, (0, .02, .57), (.06, .1, .04), ALU)


@part('launcher', 'Flywheel Launcher + Turret', 'Launcher', 'Mechanisms', .90,
      'Hooded flywheel shooter on a turret. Aims at your Hive Cell using the AprilTags under it.')
def _p(p):
    box(p, (0, .02, 0), (.4, .04, .4), C(45, 45, 50))
    turret = Entity(parent=p, y=.04)
    cyl(turret, (0, .02, 0), .19, .04, C(150, 155, 165), res=24)
    for sx in (-1, 1):
        box(turret, (sx * .13, .2, 0), (.015, .32, .34), ALU)
    for k in range(5):
        e = Entity(parent=turret, position=(0, .16, -.02), rotation_x=-(-30 + k * 25))
        box(e, (0, .17, 0), (.24, .015, .09), C(30, 30, 34))
    fw = Entity(parent=turret, position=(0, .16, -.02))
    cyl(fw, (0, 0, 0), .1, .2, C(60, 175, 80), axis='x', res=20)
    for k in range(4):
        box(fw, (0, 0, 0), (.205, .2, .02), C(45, 140, 65), rot=(k * 45, 0, 0))
    box(turret, (.19, .16, -.02), (.1, .14, .14), C(48, 48, 54))
    box(turret, (0, .07, .14), (.2, .08, .1), C(40, 40, 44))
    return {'turret': turret, 'flywheel': fw}


SERVO_PARTS = ('servo', 'cr_servo', 'claw', 'arm')
MOTOR_PARTS = ('hd_hex', 'core_hex')


def _descendants(e):
    out = []
    for c in list(getattr(e, '_children', [])):
        out.append(c)
        out.extend(_descendants(c))
    return out


def destroy_tree(e):
    """Ursina's destroy() does not remove children, so do it ourselves."""
    if e is None:
        return
    for c in list(getattr(e, '_children', [])):
        destroy_tree(c)
    destroy(e)


def make_part(pid, parent):
    root = Entity(parent=parent)
    handles = PARTS[pid]['build'](root) or {}
    root.pid, root.handles, root.spec_parent = pid, handles, None
    if FLATTEN and not handles:
        try:
            root.flattenStrong()
            # entities whose geometry got merged into the root are no longer needed
            for d in _descendants(root):
                if d.node().getNumParents() == 0:
                    destroy(d)
        except Exception:
            pass
    return root


def instantiate(spec, root, finish=None):
    made = []
    for s in spec:
        idx = s.get('parent', -1)
        owner = made[idx] if 0 <= idx < len(made) else None
        parent = owner.handles['carriage'] if owner is not None and 'carriage' in owner.handles else root
        r = make_part(s['id'], parent)
        r.position, r.rotation = Vec3(*s['pos']), Vec3(*s['rot'])
        r.spec_parent = owner
        if finish:
            finish(r)
        made.append(r)
    return made


def analyze(roots, ref):
    """Stats + rule checks for a list of placed part roots."""
    pids = [r.pid for r in roots]
    cnt = lambda *ids: sum(pids.count(i) for i in ids)
    out = dict(parts=len(roots), kg=sum(PARTS[p]['kg'] for p in pids))
    b = ref.getTightBounds(ref) if roots else None
    lo, hi = (Vec3(b[0]), Vec3(b[1])) if b else (Vec3(0, 0, 0), Vec3(0, 0, 0))
    out['lo'], out['hi'] = lo, hi
    out['size_in'] = (hi - lo) * 12
    out['fits'] = all(v <= 18.05 for v in out['size_in'])
    hubs, exps = cnt('control_hub'), cnt('expansion_hub')
    out['hubs'], out['exps'] = hubs, exps
    out['motors'] = cnt(*MOTOR_PARTS)
    out['servos'] = cnt(*SERVO_PARTS)
    out['motor_ports'] = 4 * (hubs + exps)
    out['servo_ports'] = 6 * (hubs + exps) + 6 * cnt('spm')
    out['battery'] = cnt('battery') > 0
    out['switch'] = cnt('switch') > 0

    ground = []
    for r in roots:
        w = r.handles.get('wheel')
        if w:
            c = ref.getRelativePoint(r, Vec3(0, 0, 0))
            if c.y - r.handles['radius'] <= lo.y + .06:
                ground.append((r, Vec3(c)))
    out['ground'] = ground
    left = any(c.x < -.05 for _, c in ground)
    right = any(c.x > .05 for _, c in ground)
    mec = sum(1 for r, _ in ground if r.handles['wheel'] == 'mecanum')
    omni = sum(1 for r, _ in ground if r.handles['wheel'] == 'omni')
    out['holonomic'] = mec >= 4 or omni >= 4
    if mec >= 4:
        out['drive'] = 'Mecanum (holonomic)'
    elif omni >= 4:
        out['drive'] = 'Omni X-drive (holonomic)'
    elif left and right:
        out['drive'] = 'Tank / skid steer'
    else:
        out['drive'] = 'None'

    problems = []
    if not hubs:
        problems.append('no Control Hub')
    if not out['battery']:
        problems.append('no battery')
    if not out['motors']:
        problems.append('no motors')
    if not (left and right):
        problems.append('needs wheels on both sides')
    if hubs and out['motors'] > out['motor_ports'] + cnt('sparkmini'):
        problems.append('too many motors for the ports')
    out['problems'] = problems
    warnings = []
    if not out['switch']:
        warnings.append('no power switch (required by the rules)')
    if not out['fits']:
        warnings.append('bigger than the 18in sizing cube')
    if out['servos'] > out['servo_ports']:
        warnings.append('more servos than servo ports')
    out['warnings'] = warnings
    out['has'] = {k: cnt(k) for k in ('slide', 'claw', 'intake', 'color', 'dist', 'touch', 'mag', 'webcam', 'arm', 'launcher')}
    return out


def default_spec():
    S = []

    def add(pid, pos, rot=(0, 0, 0), parent=-1):
        S.append(dict(id=pid, pos=list(pos), rot=list(rot), parent=parent))
        return len(S) - 1

    add('uch_288', (-.42, .25, 0))
    add('uch_288', (.42, .25, 0), (0, 180, 0))
    add('uch_288', (0, .25, .51), (0, -90, 0))
    add('uch_288', (0, .25, -.51), (0, 90, 0))
    add('plate_deck', (0, .34, 0))
    for sx, sz, pid in [(-1, 1, 'mecanum_l'), (1, 1, 'mecanum_r'), (-1, -1, 'mecanum_r'), (1, -1, 'mecanum_l')]:
        add(pid, (sx * .56, .175, sz * .33))
        add('hd_hex', (sx * .27, .175, sz * .33), (0, 0 if sx < 0 else 180, 0))
    add('control_hub', (0, .39, -.22))
    add('battery', (.335, .415, 0), (0, 90, 0))
    add('switch', (-.33, .38, .2))
    add('launcher', (0, .35, .1))
    add('webcam', (-.3, .43, -.45))
    add('number_plate', (-.475, .45, .1), (0, 90, 0))
    add('dist', (.3, .25, .57))
    add('touch', (0, .25, -.59), (0, 180, 0))
    s = add('slide', (0, .35, .42))
    add('mag', (-.15, .39, .42))
    add('claw', (0, .05, .025), parent=s)
    add('color', (.13, -.33, .07), parent=s)
    return S


# ----------------------------------------------------------------------------
# Robot built from a parts spec
# ----------------------------------------------------------------------------
class _NoHub(Entity):
    def set_status(self, *a):
        pass


class BuiltRobot(Entity):
    LIFT_MAX = 1.0

    def __init__(self, spec, alliance=None, number=None, **kw):
        super().__init__(**kw)
        self.spec_json = json.dumps(spec)
        self.vel, self.angv = Vec3(0, 0, 0), 0
        self.powers = [0, 0, 0, 0]
        self.lift_h, self.claw_open, self.claw_amt, self.held = 0, True, 1.0, None
        self.store = []

        self.parts = instantiate(spec, self)
        b = self.getTightBounds(self) if self.parts else None
        if b:                                        # sit the lowest point on the floor
            for r in self.parts:
                if r.spec_parent is None:
                    r.y -= b[0].y
        info = analyze(self.parts, self)
        self.info = info
        self.problems = info['problems']
        self.can_drive = not self.problems
        self.can_strafe = info['holonomic']
        self.speed = clamp(.55 + .12 * info['motors'] - .03 * max(0, info['kg'] - 6), .35, 1.25)
        ext = max(abs(info['lo'].x), abs(info['hi'].x), abs(info['lo'].z), abs(info['hi'].z), .3)
        self.wall_lim = 6 - ext

        # wheels: power sign comes from which corner each wheel sits in
        ground = info['ground']
        self.wheels = []
        if ground:
            cx = sum(c.x for _, c in ground) / len(ground)
            cz = sum(c.z for _, c in ground) / len(ground)
            for r, c in ground:
                axis_x = self.getRelativeVector(r, Vec3(1, 0, 0)).x
                self.wheels.append(dict(spin=r.handles['spin'], sx=1 if c.x > cx else -1,
                                        fz=1 if c.z >= cz else -1, dir=1 if axis_x >= 0 else -1, p=0))
            self.wheels.sort(key=lambda w: (-w['fz'], w['sx']))
        self.shafts = [r.handles['shaft'] for r in self.parts if 'shaft' in r.handles]
        self.slides = [r.handles for r in self.parts if 'carriage' in r.handles]
        self.claws = [r.handles for r in self.parts if 'claw' in r.handles]
        self.intakes = [r.handles['intake'] for r in self.parts if 'intake' in r.handles]

        hubs = [r for r in self.parts if 'hub' in r.handles]
        self.has_hub = bool(hubs)
        self.hub = hubs[0].handles['hub'] if hubs else _NoHub(parent=self, y=.4)
        self.grab = self.claws[0]['grab'] if self.claws else Entity(parent=self, position=(0, .1, .6))
        cs = [r for r in self.parts if 'color_sensor' in r.handles]
        self.color_sensor = cs[0] if cs else Entity(parent=self, position=(0, .05, .5))

        # ---- game abilities (BIOBUZZ) ----
        has = info['has']
        launchers = [r.handles for r in self.parts if 'turret' in r.handles]
        self.turret = launchers[0]['turret'] if launchers else None
        self.flywheel = launchers[0]['flywheel'] if launchers else None
        self.has_launcher = self.turret is not None
        self.has_intake = bool(self.intakes)
        self.has_claw = bool(self.claws)
        self.has_slide = bool(self.slides)
        self.finisher = self.has_slide or has.get('arm', 0) > 0
        lo, hi = info['lo'], info['hi']
        self.radius = max(.45, math.hypot(max(-lo.x, hi.x), max(-lo.z, hi.z)) * .82)
        self.reach = hi.z
        self.store, self.intake_on = [], False
        self.launch_cd = self.foul_cd = 0.0
        self.fly_spin = 0.0
        self.ai, self.skill = None, .85
        self.start = Vec3(self.position)
        self.vel_world = Vec3(0, 0, 0)
        self.team, self.number = alliance or 'red', number
        self.deco = Entity(parent=self)
        self.set_alliance(self.team, number)

    # --- driving ---
    def drive(self, f, s, t, dt, enabled):
        if not (enabled and self.can_drive):
            f = s = t = 0
        if not self.can_strafe:
            s = 0
        k = min(1, 8 * dt)
        self.vel = lerp(self.vel, Vec3(s, 0, f), k)
        self.angv = lerp(self.angv, t, k)
        vf, vs, vt = self.vel.z, self.vel.x, self.angv
        raw = [vf - w['sx'] * vt - w['sx'] * w['fz'] * vs for w in self.wheels]
        m = max([1] + [abs(v) for v in raw])
        for w, v in zip(self.wheels, raw):
            w['p'] = v / m
            w['spin'].rotation_x += w['p'] * w['dir'] * 900 * dt
        pw = [w['p'] for w in self.wheels[:4]]
        self.powers = pw + [0] * (4 - len(pw))
        avg = sum(abs(v) for v in raw) / max(1, len(raw))
        for sh in self.shafts:
            sh.rotation_x += avg * 1400 * dt

        self.rotation_y += vt * 150 * self.speed * dt
        self.position += (self.forward * vf + self.right * vs) * 4 * self.speed * dt
        self.x = clamp(self.x, -self.wall_lim, self.wall_lim)
        self.z = clamp(self.z, -self.wall_lim, self.wall_lim)

    def update_mechanisms(self, lift_in, dt, enabled):
        if enabled and self.slides:
            self.lift_h = clamp(self.lift_h + lift_in * .85 * dt, 0, self.LIFT_MAX)
        for sl in self.slides:
            sl['carriage'].y = sl['base_y'] + self.lift_h * sl['travel']
        self.claw_amt = lerp(self.claw_amt, 1 if self.claw_open else 0, min(1, 12 * dt))
        for cl in self.claws:
            fl, fr, xo, xc = cl['claw']
            x = lerp(xc, xo, self.claw_amt)
            fl.x, fr.x = -x, x

    # ---- alliance colours: bumpers + team number ----
    def set_alliance(self, team, number=None):
        self.team, self.number = team, number
        destroy_tree(self.deco)
        self.deco = Entity(parent=self)
        lo, hi = self.info['lo'], self.info['hi']
        col = C(215, 45, 45) if team == 'red' else C(40, 95, 225)
        y, h, t = .18, .14, .06
        cx, cz = (lo.x + hi.x) / 2, (lo.z + hi.z) / 2
        w, l = hi.x - lo.x, hi.z - lo.z
        if w > .2 and l > .2:
            for pos, scl in (((cx, y, lo.z + t / 2), (w * .8, h, t)), ((cx, y, hi.z - t / 2), (w * .5, h, t)),
                             ((lo.x + t / 2, y, cz - l * .05), (t, h, l * .3)), ((hi.x - t / 2, y, cz - l * .05), (t, h, l * .3))):
                box(self.deco, pos, scl, col)
        if number:
            label(self.deco, str(number), (0, hi.y + .55, 0), 6, col, billboard=True)

    # ---- carried pieces (max 4, rule G407) ----
    def stow(self, b):
        b.parent, b.state, b.vel = self, 'stored', Vec3(0, 0, 0)
        self.store.append(b)
        self.layout_store()

    def unstow(self, b):
        self.store.remove(b)
        wp = b.world_position
        b.parent, b.position = scene, wp
        self.layout_store()

    def layout_store(self):
        y = self.info['hi'].y + .22
        for i, b in enumerate(self.store):
            b.position = Vec3(-.45 + i * .3, y, 0)

    def claw_pulse(self):
        if self.claws:
            self.claw_open = False
            invoke(setattr, self, 'claw_open', True, delay=.35)

    def kick_flywheel(self):
        self.fly_spin = 1.0

    def launch_point(self):
        return (self.turret.world_position if self.turret else self.world_position) + Vec3(0, .45, 0)

    def aim_at(self, target, dt):
        if not self.turret:
            return
        par = self.turret.parent
        lp = par.getRelativePoint(scene, target)
        tp = self.turret.getPos(par)
        want = math.degrees(math.atan2(lp.x - tp.x, lp.z - tp.z))
        self.turret.rotation_y = lerp_ang(self.turret.rotation_y, want, min(1, 8 * dt))

    def spin_extras(self, dt):
        if self.flywheel:
            self.fly_spin = max(.25, self.fly_spin - dt * .8)
            self.flywheel.rotation_x += 1500 * self.fly_spin * dt
        if self.intake_on:
            for sp in self.intakes:
                sp.rotation_x += 900 * dt

    def reset_motion(self):
        self.vel, self.angv = Vec3(0, 0, 0), 0
        self.claw_open, self.intake_on = True, False
        self._lastp = Vec3(self.position)

    def release(self):
        for b in list(self.store):
            self.unstow(b)
            b.state = 'field'
            b.y = .3
            if 'game' in globals():
                game.balls_field_add(b)

    def reset(self):
        self.position, self.rotation = (0, 0, -3), (0, 0, 0)
        self.vel, self.angv, self.lift_h, self.claw_open = Vec3(0, 0, 0), 0, 0, True


Robot = BuiltRobot


# ----------------------------------------------------------------------------
# Wi-Fi link visual
# ----------------------------------------------------------------------------
class Link:
    def __init__(self):
        self.connected = True       # user toggle (C key)
        self.ok = True              # toggle AND robot has a Control Hub
        self.packets = []
        self.t_up = self.t_down = 0
        self.ping = 6.0
        self.line = Entity(model=Mesh(vertices=[Vec3(0, 0, 0), Vec3(0, 0, 1)], mode='line', thickness=2),
                           color=color.Color(0, 1, .7, .35))

    @staticmethod
    def arc(a, b, t):
        p = lerp(a, b, t)
        p.y += math.sin(math.pi * t) * 2.0
        return p

    def update(self, a, b, dt, active):
        pts = [self.arc(a, b, i / 24) for i in range(25)]
        self.line.model.vertices = pts
        self.line.model.generate()
        self.line.color = color.Color(0, 1, .7, .35) if self.ok else color.Color(1, 0, 0, .25)
        self.ping = lerp(self.ping, random.uniform(3, 14), .05) if self.ok else 0

        if self.ok:
            self.t_up += dt
            self.t_down += dt
            rate = .07 if active else .3
            if self.t_up > rate:
                self.t_up = 0
                self.packets.append([ball(scene, a, .08, color.cyan, lit=False), 0, True])
            if self.t_down > rate * 2:
                self.t_down = 0
                self.packets.append([ball(scene, b, .08, C(255, 150, 30), lit=False), 0, False])

        for p in self.packets[:]:
            p[1] += dt * 1.4
            if p[1] >= 1:
                destroy(p[0])
                self.packets.remove(p)
                continue
            p[0].position = self.arc(a, b, p[1]) if p[2] else self.arc(b, a, p[1])


# ----------------------------------------------------------------------------
# World: field, samples, driver station, wiring bench
# ----------------------------------------------------------------------------
Entity(model='plane', scale=70, y=-.06, color=C(70, 78, 70))           # floor
field = Entity()
for i in range(6):
    for j in range(6):
        box(field, (-5 + i * 2, -.025, -5 + j * 2), (1.97, .05, 1.97),
            C(96, 96, 102) if (i + j) % 2 else C(88, 88, 95))
for sgn in (-1, 1):
    Entity(parent=field, model='cube', position=(0, .5, sgn * 6.05), scale=(12.2, 1, .04),
           color=color.Color(.8, .88, 1, .25))
    Entity(parent=field, model='cube', position=(sgn * 6.05, .5, 0), scale=(.04, 1, 12.2),
           color=color.Color(.8, .88, 1, .25))
    box(field, (0, 1.02, sgn * 6.05), (12.25, .06, .1), ALU)
    box(field, (sgn * 6.05, 1.02, 0), (.1, .06, 12.25), ALU)
for sx in (-1, 1):
    for sz in (-1, 1):
        box(field, (sx * 6.05, .5, sz * 6.05), (.12, 1.05, .12), ALU)


DS_Z = -8.5
box(scene, (0, 1.0, DS_Z), (6, .08, 1.8), C(120, 90, 60))
for sx in (-1, 1):
    for sz in (-1, 1):
        box(scene, (sx * 2.85, .5, DS_Z + sz * .8), (.08, 1, .08), C(60, 60, 60))

driver_hub = DriverHub(position=(0, 1.55, DS_Z + .1), rotation=(20, 0, 0))
pad = Gamepad(position=(0, 1.12, DS_Z - .55))

cyl(scene, (3.6, 1.15, DS_Z), .5, .22, C(50, 50, 55))
showcase = ControlHub(title='CONTROL HUB', callouts=True, position=(3.6, 1.45, DS_Z), scale=1.1)
spin_showcase = True

BENCH_X = -6.9
box(scene, (BENCH_X, 1.0, DS_Z), (5, .08, 2.8), C(120, 90, 60))
for sx in (-1, 1):
    for sz in (-1, 1):
        box(scene, (BENCH_X + sx * 2.35, .5, DS_Z + sz * 1.25), (.08, 1, .08), C(60, 60, 60))
bench = WiringBench(position=(BENCH_X, 1.04, DS_Z))

link = Link()

sun = DirectionalLight(shadows=SHADOWS)
sun.look_at(Vec3(1, -1.6, 1.2))
AmbientLight(color=color.Color(.55, .55, .6, 1))
Sky()
for _c in ('entity_counter', 'collider_counter'):
    if getattr(window, _c, None):
        getattr(window, _c).enabled = False


# ----------------------------------------------------------------------------
# Part pictures: every part is rendered once into its own image
# ----------------------------------------------------------------------------
def render_part_images(size=128):
    images = {}
    try:
        tnp = NodePath('thumb_scene')
        buf = base.win.makeTextureBuffer('part_images', size, size, to_ram=True)
        buf.setClearColor((.17, .19, .24, 1))
        buf.setSort(-100)
        lens = PerspectiveLens()
        lens.setFov(30)
        lens.setNearFar(.01, 100)
        cam_np = tnp.attachNewNode(PandaCamera('thumb_cam'))
        cam_np.node().setLens(lens)
        buf.makeDisplayRegion().setCamera(cam_np)
        stage = Entity()
        stage.reparentTo(tnp)
        view = Vec3(1.1, .9, 1.6).normalized()
        for pid in PARTS:
            holder = Entity(parent=stage)
            holder.reparentTo(stage)
            make_part(pid, holder)
            lo, hi = holder.getTightBounds(tnp)
            c = (lo + hi) / 2
            r = max((hi - lo).length() / 2, .05)
            cam_np.setPos(c + view * (r / math.sin(math.radians(15))))
            cam_np.lookAt(c)
            base.graphicsEngine.renderFrame()
            base.graphicsEngine.renderFrame()
            img = PNMImage()
            buf.getTexture().store(img)
            tex = PandaTexture(pid)
            tex.load(img)
            images[pid] = Texture(tex)
            destroy_tree(holder)
        destroy_tree(stage)
        base.graphicsEngine.removeWindow(buf)
    except Exception as e:
        print('[warning] could not render part pictures:', e)
    return images


# ----------------------------------------------------------------------------
# Build bay: the 3D workbench where parts are placed
# ----------------------------------------------------------------------------
BAY_POS = Vec3(16, 0, -1)
SAVE_FILE = Path(__file__).with_name('my_robot.json')


class BuildBay(Entity):
    GRID = .05

    def __init__(self, **kw):
        super().__init__(**kw)
        cyl(self, (0, -.3, 0), 3.1, .5, C(42, 45, 52), res=48)
        self.plate = Entity(parent=self, model='cube', position=(0, -.025, 0), scale=(4.4, .05, 4.4),
                            color=C(68, 74, 86), shader=SH, collider='box')
        Entity(parent=self, model=Grid(22, 22), rotation_x=90, scale=4.4, y=.003,
               color=color.Color(1, 1, 1, .14))
        label(self, 'FRONT', (0, .006, 1.95), 14, C(255, 190, 80), rot=(90, 180, 0))
        box(self, (0, .004, 1.55), (.05, .006, .5), C(255, 190, 80))
        self.cube = Entity(parent=self, model='wireframe_cube', scale=1.5, y=.75, color=color.lime)
        self.cube_label = label(self, '18in sizing cube', (0, 1.58, 0), 2.2, color.lime, billboard=True)
        self.hover_box = Entity(parent=self, model='wireframe_cube', color=color.yellow, enabled=False)

        self.root = Entity(parent=self)
        self.items, self.ids = [], set()
        self.sel, self.mpid = None, None
        self.rot, self.mirror = Vec3(0, 0, 0), False
        self.ghost = self.mghost = None
        self.gb = self.mgb = None
        self.lift = 0.0
        self.history = []
        self.can_place = False
        self.hovered_part = None
        self.on_change = None
        self.info = analyze([], self.root)

    # ---------- spec / history ----------
    def to_spec(self):
        idx = {id(r): i for i, r in enumerate(self.items)}
        return [dict(id=r.pid, pos=[round(v, 4) for v in r.position], rot=[round(v, 2) for v in r.rotation],
                     parent=idx.get(id(r.spec_parent), -1) if r.spec_parent is not None else -1)
                for r in self.items]

    def _finish(self, r):
        b = r.getTightBounds(r)
        lo, hi = (Vec3(b[0]), Vec3(b[1])) if b else (Vec3(-.05, -.05, -.05), Vec3(.05, .05, .05))
        r.blo, r.bhi = lo, hi
        r.collider = BoxCollider(r, center=(lo + hi) / 2, size=hi - lo + Vec3(.005, .005, .005))
        self.items.append(r)
        self.ids.add(id(r))

    def load_spec(self, spec):
        self.clear(record=False)
        instantiate(spec, self.root, finish=self._finish)
        self.apply_lift()
        self.changed()

    def snapshot(self):
        self.history.append(self.to_spec())
        self.history = self.history[-60:]

    def undo(self):
        if self.history:
            self.load_spec(self.history.pop())
            toast('Undo')

    def clear(self, record=True):
        if record:
            self.snapshot()
        self.hover_box.parent = self
        self.hover_box.enabled = False
        for r in self.items:
            if r.spec_parent is None:          # attached parts go with their slide
                destroy_tree(r)
        self.items, self.ids = [], set()
        if record:
            self.changed()

    def changed(self):
        saved = self.lift
        self.lift = 0
        self.apply_lift()
        self.info = analyze(self.items, self.root)
        self.lift = saved
        self.apply_lift()
        i = self.info
        if self.items:
            c = (i['lo'] + i['hi']) / 2
            self.cube.position = (c.x, i['lo'].y + .75, c.z)
            self.cube_label.position = (c.x, i['lo'].y + 1.58, c.z)
        col = color.lime if i['fits'] else color.red
        self.cube.color = self.cube_label.color = col
        if self.on_change:
            self.on_change()

    # ---------- selection / ghost ----------
    def _make_ghost(self, pid, rot):
        g = make_part(pid, self)
        g.rotation = rot
        b = g.getTightBounds(self)
        lo, hi = (Vec3(b[0]), Vec3(b[1])) if b else (Vec3(0, 0, 0), Vec3(0, 0, 0))
        g.setTransparency(TransparencyAttrib.MAlpha)
        g.setColorScale(.6, 1, .65, .55)
        g.enabled = False
        return g, (lo, hi)

    def _clear_ghosts(self):
        for g in (self.ghost, self.mghost):
            if g:
                destroy_tree(g)
        self.ghost = self.mghost = None

    def rebuild_ghosts(self):
        self._clear_ghosts()
        if not self.sel:
            return
        self.ghost, self.gb = self._make_ghost(self.sel, self.rot)
        if self.mirror:
            self.mpid = MIRROR.get(self.sel, self.sel)
            self.mghost, self.mgb = self._make_ghost(self.mpid, Vec3(self.rot.x, -self.rot.y, -self.rot.z))

    def select(self, pid):
        self.sel = pid
        self.rot = Vec3(0, 0, 0)
        self.rebuild_ghosts()

    def rotate(self, axis):
        if not self.sel:
            return
        r = Vec3(self.rot)
        setattr(r, axis, (getattr(r, axis) + 90) % 360)
        self.rot = r
        self.rebuild_ghosts()

    def toggle_mirror(self):
        self.mirror = not self.mirror
        self.rebuild_ghosts()
        toast(f"Mirror {'ON' if self.mirror else 'OFF'}")

    # ---------- placement maths ----------
    def _snap(self, v):
        return round(v / self.GRID) * self.GRID

    def _place_pos(self, p, n, bounds, on_plate):
        lo, hi = bounds
        cx, cy, cz = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2
        S = self._snap
        if on_plate or n.y > .7:
            pos = Vec3(S(p.x) - cx, p.y - lo.y, S(p.z) - cz)
        elif n.y < -.7:
            pos = Vec3(S(p.x) - cx, p.y - hi.y, S(p.z) - cz)
        elif abs(n.x) >= abs(n.z):
            pos = Vec3(p.x - (lo.x if n.x > 0 else hi.x), S(p.y) - cy, S(p.z) - cz)
        else:
            pos = Vec3(S(p.x) - cx, S(p.y) - cy, p.z - (lo.z if n.z > 0 else hi.z))
        if pos.y + lo.y < 0:
            pos.y = -lo.y
        return pos

    def _attach_owner(self, h):
        if h is None or id(h) not in self.ids:
            return None
        if 'carriage' in h.handles:
            return h
        return h.spec_parent

    def apply_lift(self):
        for r in self.items:
            if 'carriage' in r.handles:
                r.handles['carriage'].y = r.handles['base_y'] + self.lift * r.handles['travel']

    # ---------- per-frame ----------
    def update_bay(self, dt):
        li = held_keys['up arrow'] - held_keys['down arrow']
        if li:
            self.lift = clamp(self.lift + li * .8 * dt, 0, 1)
            self.apply_lift()

        h = mouse.hovered_entity
        part = h if (h is not None and id(h) in self.ids) else None
        on_plate = h is not None and h == self.plate
        self.hovered_part = part

        if part:
            self.hover_box.parent = part
            self.hover_box.position = (part.blo + part.bhi) / 2
            self.hover_box.scale = part.bhi - part.blo + Vec3(.03, .03, .03)
            self.hover_box.enabled = True
        else:
            self.hover_box.parent = self
            self.hover_box.enabled = False

        self.can_place = False
        if not self.ghost:
            return
        wp = mouse.world_point
        if (on_plate or part) and wp is not None:
            n = mouse.world_normal if mouse.world_normal is not None else Vec3(0, 1, 0)
            p = wp - self.world_position
            pos = self._place_pos(p, n, self.gb, on_plate)
            self.ghost.position = pos
            self.ghost.enabled = True
            self.can_place = True
            if self.mghost:
                lo, hi = self.gb
                c = pos + (lo + hi) / 2
                if abs(c.x) > .03:
                    mlo, mhi = self.mgb
                    mc = (mlo + mhi) / 2
                    self.mghost.position = Vec3(-c.x - mc.x, pos.y + lo.y - mlo.y, c.z - mc.z)
                    self.mghost.enabled = True
                else:
                    self.mghost.enabled = False
        else:
            self.ghost.enabled = False
            if self.mghost:
                self.mghost.enabled = False

    # ---------- edit operations ----------
    def _add(self, pid, local_pos, rot, owner):
        r = make_part(pid, self.root)
        r.position, r.rotation = local_pos, rot
        if owner is not None:
            r.world_parent = owner.handles['carriage']
        r.spec_parent = owner
        self._finish(r)
        return r

    def place(self):
        if not (self.can_place and self.ghost and self.ghost.enabled):
            return False
        owner = self._attach_owner(mouse.hovered_entity)
        self.snapshot()
        self._add(self.sel, Vec3(self.ghost.position), Vec3(self.ghost.rotation), owner)
        if self.mghost and self.mghost.enabled:
            self._add(self.mpid, Vec3(self.mghost.position), Vec3(self.mghost.rotation), owner)
        self.apply_lift()
        self.changed()
        return True

    def _descends(self, r, anc):
        while r is not None:
            if r is anc:
                return True
            r = r.spec_parent
        return False

    def delete(self, part, record=True):
        if part is None:
            return
        if record:
            self.snapshot()
        self.hover_box.parent = self
        self.hover_box.enabled = False
        doomed = [r for r in self.items if self._descends(r, part)]
        for r in doomed:
            self.items.remove(r)
            self.ids.discard(id(r))
        destroy_tree(part)                     # attached parts live under it in the scene graph
        self.hovered_part = None
        self.changed()

    def pick_up(self, part):
        if part is None:
            return None
        pid = part.pid
        rot = Vec3(part.rotation) if part.spec_parent is None else Vec3(0, 0, 0)
        self.delete(part)
        self.sel, self.rot = pid, rot
        self.rebuild_ghosts()
        return pid


# ----------------------------------------------------------------------------
# Build UI: tabs, parts catalog dropdowns with pictures, stats, buttons
# ----------------------------------------------------------------------------
PANEL = C(16, 18, 24, 238)
CARD = C(38, 42, 52)
CARD_HI = C(62, 70, 90)
HEADER = C(44, 49, 62)


class BuildUI(Entity):
    def __init__(self, bay, images, **kw):
        super().__init__(parent=camera.ui, **kw)
        self.bay, self.images = bay, images
        A = window.aspect_ratio
        self.L, self.R = -A / 2, A / 2
        L, R = self.L, self.R

        # ----- left: catalog -----
        Entity(parent=self, model='quad', color=PANEL, position=(L + .178, -.025, 1),
               scale=(.35, .9), collider='box')
        Text(parent=self, text='PARTS CATALOG', position=(L + .02, .41, -.1), scale=1.05, color=ORANGE)
        Text(parent=self, text=f'{len(PARTS)} parts - click one, then click to place',
             position=(L + .02, .38, -.1), scale=.62, color=C(170, 175, 190))
        self.open_cat = CATEGORIES[0]
        self.headers, self.cards = {}, {}
        for cat in CATEGORIES:
            pids = [p for p in PARTS if PARTS[p]['cat'] == cat]
            b = Button(parent=self, scale=(.336, .037), color=HEADER, highlight_color=C(70, 78, 98),
                       pressed_color=ORANGE, z=-.1)
            b.on_click = Func(self.toggle_cat, cat)
            t = Text(parent=self, text='', scale=.82, origin=(-.5, 0), z=-.2)
            self.headers[cat] = (b, t, pids)
            for pid in pids:
                cont = Entity(parent=self, z=-.1)
                cb = Button(parent=cont, scale=(.1, .112), color=CARD, highlight_color=CARD_HI,
                            pressed_color=ORANGE)
                cb.on_click = Func(self.pick, pid)
                if pid in images:
                    Entity(parent=cont, model='quad', texture=images[pid], scale=.078, y=.012, z=-.01)
                else:
                    Entity(parent=cont, model='quad', color=C(80, 85, 100), scale=.078, y=.012, z=-.01)
                Text(parent=cont, text=PARTS[pid]['short'], scale=.56, origin=(0, 0), y=-.043, z=-.02)
                self.cards[pid] = (cont, cb)

        # ----- right: stats, info, actions -----
        Entity(parent=self, model='quad', color=PANEL, position=(R - .178, -.025, 1),
               scale=(.35, .9), collider='box')
        self.stats = Text(parent=self, text='', position=(R - .343, .41, -.1), scale=.74, line_height=1.12)
        Entity(parent=self, model='quad', color=C(60, 64, 76), position=(R - .178, -.045, -.05),
               scale=(.33, .002))
        self.info_img = Entity(parent=self, model='quad', position=(R - .29, -.11, -.1), scale=.1,
                               color=C(40, 44, 54))
        self.info_name = Text(parent=self, text='No part selected', position=(R - .23, -.065, -.1),
                              scale=.8, color=ORANGE, wordwrap=19)
        self.info_meta = Text(parent=self, text='Pick a part from the catalog', position=(R - .23, -.125, -.1),
                              scale=.64, color=C(170, 175, 190), wordwrap=24)
        self.info_desc = Text(parent=self, text=' ', position=(R - .343, -.17, -.1), scale=.64, wordwrap=25)

        def btn(text, x, y, fn, w=.162, col=C(50, 56, 72), hi=C(75, 84, 106)):
            b = Button(parent=self, text=text, position=(x, y, -.1), scale=(w, .036), color=col,
                       highlight_color=hi, pressed_color=ORANGE)
            b.text_entity.scale *= .78
            b.on_click = fn
            return b

        x1, x2 = R - .262, R - .094
        btn('Default Robot', x1, -.255, self.load_default)
        btn('Clear All', x2, -.255, self.clear_all, col=C(110, 40, 40), hi=C(150, 55, 55))
        btn('Undo', x1, -.297, self.bay.undo)
        self.mirror_btn = btn('Mirror: OFF', x2, -.297, self.toggle_mirror)
        btn('Save', x1, -.339, self.save)
        btn('Load', x2, -.339, self.load)
        btn('TEST DRIVE  >', R - .178, -.395, lambda: set_mode('sim'), w=.33,
            col=C(30, 140, 70), hi=C(45, 175, 90))

        Text(parent=self, origin=(0, 0), position=(0, -.47, -.1), scale=.68, color=C(220, 225, 235),
             text='LMB place  |  R/T/F rotate  |  M mirror  |  X delete  |  G pick up  |  '
                  'Up/Down slide  |  Ctrl+Z undo  |  Esc deselect  |  RMB orbit, wheel zoom')
        self.tooltip = Text(parent=self, text='', scale=.75, z=-1, color=color.yellow)

        bay.on_change = self.refresh_stats
        self.relayout()
        self.refresh_stats()

    # ----- catalog -----
    def toggle_cat(self, cat):
        self.open_cat = None if self.open_cat == cat else cat
        self.relayout()

    def relayout(self):
        L = self.L
        y = .345
        for cat in CATEGORIES:
            b, t, pids = self.headers[cat]
            is_open = cat == self.open_cat
            b.position = (L + .178, y)
            t.position = (L + .022, y)
            t.text = f"{'-' if is_open else '+'}  {cat.upper()}   ({len(pids)})"
            b.color = C(150, 70, 20) if is_open else HEADER
            y -= .042
            for i, pid in enumerate(pids):
                cont = self.cards[pid][0]
                cont.enabled = is_open
                if is_open:
                    cont.position = (L + .068 + (i % 3) * .108, y - .058 - (i // 3) * .118, -.1)
            if is_open:
                y -= ((len(pids) + 2) // 3) * .118 + .006

    def pick(self, pid):
        if self.bay.sel == pid:
            pid = None
        self.bay.select(pid)
        self.show_info(pid)

    def show_info(self, pid):
        for p, (cont, cb) in self.cards.items():
            cb.color = ORANGE if p == pid else CARD
        if not pid:
            self.info_name.text = 'No part selected'
            self.info_meta.text = 'Pick a part from the catalog'
            self.info_desc.text = ' '
            self.info_img.texture = None
            self.info_img.color = C(40, 44, 54)
            return
        d = PARTS[pid]
        self.info_name.text = d['name']
        self.info_meta.text = f"{d['cat']}  |  {d['kg'] * 1000:.0f} g"
        self.info_desc.text = d['desc']
        self.info_img.texture = self.images.get(pid)
        self.info_img.color = color.white

    # ----- stats -----
    def refresh_stats(self):
        i = self.bay.info
        ok = lambda b: '<lime>[OK]<default>' if b else '<red>[ X]<default>'
        opt = lambda b: '<lime>[OK]<default>' if b else '<gray>[--]<default>'
        sx, sy, sz = i['size_in'].x, i['size_in'].y, i['size_in'].z
        lines = [
            '<orange>BUILD STATS<default>',
            f"Parts: {i['parts']}     Weight: {i['kg']:.1f} kg",
            f"Size: {sx:.1f} x {sz:.1f} x {sy:.1f} in (WxLxH)",
            f"18in cube: {'<lime>PASS' if i['fits'] else '<red>TOO BIG'}<default>",
            f"Drive: {i['drive']}",
            f"Motors {i['motors']}/{i['motor_ports']} ports   Servos {i['servos']}/{i['servo_ports']}",
            '',
            '<orange>CAN IT DRIVE?<default>',
            f"{ok(i['hubs'] > 0)} Control Hub",
            f"{ok(i['battery'])} 12V battery",
            f"{ok(i['motors'] > 0)} Motors ({i['motors']})",
            f"{ok('needs wheels on both sides' not in i['problems'])} Wheels on both sides ({len(i['ground'])})",
            f"{opt(i['switch'])} Power switch",
            f"{opt(i['has']['slide'])} Lift    {opt(i['has']['claw'])} Claw",
            f"{opt(i['has']['color'] or i['has']['dist'] or i['has']['touch'])} Sensors",
        ]
        if i['problems']:
            lines.append(f"<red>Won't drive: {i['problems'][0]}<default>")
        elif i['warnings']:
            lines.append(f"<yellow>Note: {i['warnings'][0]}<default>")
        else:
            lines.append('<lime>Ready to drive!<default>')
        self.stats.text = '\n'.join(lines)

    # ----- actions -----
    def load_default(self):
        self.bay.snapshot()
        self.bay.load_spec(default_spec())
        toast('Loaded the default robot')

    def clear_all(self):
        self.bay.clear()
        toast('Cleared - Ctrl+Z to undo')

    def toggle_mirror(self):
        self.bay.toggle_mirror()
        self.mirror_btn.text = f"Mirror: {'ON' if self.bay.mirror else 'OFF'}"
        self.mirror_btn.text_entity.scale *= .78
        self.mirror_btn.color = C(150, 70, 20) if self.bay.mirror else C(50, 56, 72)

    def save(self):
        try:
            SAVE_FILE.write_text(json.dumps(self.bay.to_spec(), indent=1))
            toast(f'Saved to {SAVE_FILE.name}')
        except Exception as e:
            toast(f'Save failed: {e}', color.red)

    def load(self):
        try:
            spec = json.loads(SAVE_FILE.read_text())
            self.bay.snapshot()
            self.bay.load_spec(spec)
            toast(f'Loaded {SAVE_FILE.name}')
        except FileNotFoundError:
            toast('No saved robot yet - press Save first', color.red)
        except Exception as e:
            toast(f'Load failed: {e}', color.red)

    def update_tooltip(self):
        hp = self.bay.hovered_part
        if hp is not None and not self.bay.sel:
            self.tooltip.text = PARTS[hp.pid]['name'] + '   (X delete, G pick up)'
            self.tooltip.position = mouse.position + Vec3(.015, .03, 0)
        elif self.bay.sel and self.bay.ghost and self.bay.ghost.enabled:
            self.tooltip.text = PARTS[self.bay.sel]['name']
            self.tooltip.position = mouse.position + Vec3(.015, .03, 0)
        else:
            self.tooltip.text = ''


# ============================================================================
# BIOBUZZ  -  FIRST Tech Challenge 2026-27 (FIRST CANOPY season)
# Rules/scoring from the TechnoBlades team page. Exact field geometry and the
# Hive tip weight are NOT published there, so the numbers marked (est.) below
# are estimates - tweak them to match the real field.
# ============================================================================
RED, BLUE = 'red', 'blue'
OTHER = {RED: BLUE, BLUE: RED}
TEAM_COL = {RED: C(215, 45, 45), BLUE: C(40, 95, 225)}
POLLEN_COL = C(250, 212, 40)
POLLEN_R, NECTAR_R = 1.4 / 12, 1.8 / 12          # 2.8in and 3.6in balls
HIVE_PIVOT_Y = 44 / 12                             # pivot ~44in above the floor
HIVE_BASE_R = 1.25                                 # (est.)
TIP_WEIGHT = 9.0                                   # (est.) Pollen = 1, Nectar = 1.6
FLOWER_TOP = 21.5 / 12                             # Flower top is 21.5in
AUTO_T, TRANS_T, TELE_T = 30, 8, 120
MAX_PIECES = 4                                     # G407
LOADING_ZONE = {RED: (-6, -4, -6, -4), BLUE: (4, 6, 4, 6)}         # x0, x1, z0, z1 (est.)
GARDEN_ZONE = {RED: (-6, -4, 4, 6), BLUE: (4, 6, -6, -4)}         # (est.)
START_POS = {RED: [Vec3(-5.15, 0, -1.6), Vec3(-5.15, 0, 1.6)],
             BLUE: [Vec3(5.15, 0, 1.6), Vec3(5.15, 0, -1.6)]}
START_YAW = {RED: 90, BLUE: -90}
FLOWER_SPOTS = [(Vec3(-2, 0, -5.72), Vec3(0, 0, 1)), (Vec3(2, 0, -5.72), Vec3(0, 0, 1)),
                (Vec3(-2, 0, 5.72), Vec3(0, 0, -1)), (Vec3(2, 0, 5.72), Vec3(0, 0, -1))]


def in_zone(p, z, pad=0.0):
    return z[0] - pad <= p.x <= z[1] + pad and z[2] - pad <= p.z <= z[3] + pad


def flat(v):
    return Vec3(v.x, 0, v.z)


def yaw_to(dx, dz):
    return math.degrees(math.atan2(dx, dz))


def wrap180(a):
    return (a + 180) % 360 - 180


class Ball(Entity):
    def __init__(self, kind, team=None, **kw):
        r = NECTAR_R if kind == 'nectar' else POLLEN_R
        super().__init__(model='sphere', scale=2 * r, shader=SH,
                         color=TEAM_COL[team] if kind == 'nectar' else POLLEN_COL, **kw)
        self.kind, self.team, self.r = kind, team, r
        self.w = 1.6 if kind == 'nectar' else 1.0
        self.vel = Vec3(0, 0, 0)
        self.state = 'field'          # field | stored | flight | cell | flower | held
        self.flight = None
        self.color_name = f'{team.upper()} NECTAR' if kind == 'nectar' else 'YELLOW POLLEN'

    def to_field(self, vel=Vec3(0, 0, 0)):
        wp = self.world_position
        self.parent = scene
        self.position = wp
        self.rotation = (0, 0, 0)
        self.state, self.vel = 'field', Vec3(vel)


# ---------------------------------------------------------------- the Hive --
class HiveHalf(Entity):
    TILT = 22

    def __init__(self, team, x, game, tag0, **kw):
        super().__init__(position=(x, HIVE_PIVOT_Y, 0), **kw)
        self.team, self.game = team, game
        self.upi, self.anim = 0, None
        col = TEAM_COL[team]
        self.beam = Entity(parent=self)
        box(self.beam, (0, 0, 0), (.12, .12, 2.75), C(64, 64, 70))
        self.cells = []
        for i, z in enumerate((-1.3, 1.3)):
            c = Entity(parent=self.beam, position=(0, -.08, z))
            box(c, (0, -.22, 0), (.86, .04, .72), C(42, 42, 48))
            for sx in (-1, 1):
                box(c, (sx * .43, -.02, 0), (.03, .42, .72), col)
            for sz in (-1, 1):
                box(c, (0, -.02, sz * .36), (.86, .42, .03), col * .8 + color.Color(0, 0, 0, .2))
            box(c, (0, -.255, 0), (.3, .02, .3), color.white)                 # AprilTag
            box(c, (0, -.267, 0), (.22, .006, .22), BLACK)
            label(c, str(tag0 + i), (0, -.272, 0), 3, color.white, rot=(-90, 0, 0))
            c.balls = []
            self.cells.append(c)
        self.beam.rotation_x = self.target_angle()

    def target_angle(self):
        return self.TILT if self.upi == 0 else -self.TILT     # +x pitch lifts the audience (-Z) end

    def up_cell(self):
        return self.cells[self.upi]

    def weight(self):
        return sum(b.w for b in self.up_cell().balls)

    def aim_point(self):
        return self.up_cell().world_position + Vec3(0, .15, 0)

    def add_ball(self, b):
        c = self.up_cell()
        k = len(c.balls)
        b.parent, b.state, b.rotation = c, 'cell', (0, 0, 0)
        b.position = Vec3(-.27 + (k % 3) * .27, -.2 + b.r + (k // 6) * .28, -.16 + ((k // 3) % 2) * .32)
        c.balls.append(b)
        if self.weight() >= TIP_WEIGHT and self.anim is None:
            self.tip()

    def tip(self):
        old = self.up_cell()
        self.upi = 1 - self.upi
        self.anim = [0.0, self.beam.rotation_x, self.target_angle(), old, False]
        self.game.on_tip(self.team)

    def reset(self):
        for c in self.cells:
            for b in c.balls:
                destroy(b)
            c.balls = []
        self.upi, self.anim = 0, None
        self.beam.rotation_x = self.target_angle()

    def step(self, dt):
        if not self.anim:
            return
        a = self.anim
        a[0] += dt / .8
        u = min(1, a[0])
        self.beam.rotation_x = lerp(a[1], a[2], u * u * (3 - 2 * u))
        if u > .45 and not a[4]:
            a[4] = True
            hive_c = self.parent.world_position
            for b in a[3].balls:
                wp = b.world_position
                out = flat(wp - hive_c)
                out = out.normalized() if out.length() > .01 else Vec3(random.uniform(-1, 1), 0, 1).normalized()
                out = Vec3(out.x + random.uniform(-.5, .5), 0, out.z + random.uniform(-.5, .5)).normalized()
                b.to_field(out * random.uniform(2.5, 5.5) + Vec3(0, random.uniform(1, 4), 0))
                self.game.balls_field_add(b)
            a[3].balls = []
        if u >= 1:
            self.anim = None


class Hive(Entity):
    def __init__(self, game, **kw):
        super().__init__(**kw)
        cyl(self, (0, .05, 0), HIVE_BASE_R, .1, C(56, 58, 66), res=40)
        frame = C(84, 86, 94)
        for x in (-1.15, 0, 1.15):
            box(self, (x, HIVE_PIVOT_Y / 2, 0), (.12, HIVE_PIVOT_Y, .22), frame)
            box(self, (x, .25, 0), (.3, .3, .9), frame)
        box(self, (0, HIVE_PIVOT_Y + .06, 0), (2.42, .09, .2), frame)
        for k in range(6):                                         # honeycomb crest
            h = Entity(parent=self, position=(0, HIVE_PIVOT_Y + .45, 0), rotation_z=k * 60)
            box(h, (0, .22, 0), (.25, .05, .05), C(240, 190, 40))
        label(self, 'HIVE', (0, HIVE_PIVOT_Y + .45, 0), 6, color.black, billboard=True)
        self.halves = {RED: HiveHalf(RED, -.6, game, 30, parent=self),
                       BLUE: HiveHalf(BLUE, .6, game, 32, parent=self)}


# ----------------------------------------------------------------- Flowers --
class Flower(Entity):
    def __init__(self, pos, facing, idx, **kw):
        super().__init__(position=pos, **kw)
        self.facing, self.idx = facing, idx
        self.rotation_y = yaw_to(facing.x, facing.z)
        cyl(self, (0, FLOWER_TOP / 2, 0), .21, FLOWER_TOP, color.Color(.75, .9, 1, .22), res=20)
        for y in (.03, FLOWER_TOP - .02):
            cyl(self, (0, y, 0), .23, .05, C(60, 160, 70), res=20)
        box(self, (0, FLOWER_TOP / 2, -.24), (.08, FLOWER_TOP, .04), C(60, 160, 70))     # wall mount
        box(self, (0, .1, .2), (.26, .2, .03), C(20, 20, 24))                          # bottom opening
        self.petals = []
        for k in range(6):
            yaw = Entity(parent=self, position=(0, FLOWER_TOP, 0), rotation_y=k * 60)
            piv = Entity(parent=yaw, position=(0, 0, .2))
            box(piv, (0, 0, .14), (.16, .02, .28), C(235, 120, 170))
            piv.rotation_x = -75
            self.petals.append(piv)
        ball(self, (0, FLOWER_TOP + .02, 0), .1, C(250, 200, 40))
        label(self, f'FLOWER {idx}', (0, FLOWER_TOP + .45, 0), 4, color.white, billboard=True)
        self.owner_tag = label(self, '', (0, FLOWER_TOP + .3, 0), 4, color.white, billboard=True)
        self.pieces = []

    def used(self):
        return sum(2 * b.r for b in self.pieces)

    def can_add(self, b):
        return self.used() + 2 * b.r <= FLOWER_TOP - .05

    def _restack(self):
        y = 0.0
        for b in self.pieces:
            b.position = (0, y + b.r, 0)
            y += 2 * b.r

    def add(self, b):
        b.parent, b.state, b.rotation = self, 'flower', (0, 0, 0)
        self.pieces.append(b)
        self._restack()
        self.refresh_owner()

    def take_bottom_pollen(self):
        if self.pieces and self.pieces[0].kind == 'pollen':
            b = self.pieces.pop(0)
            self._restack()
            self.refresh_owner()
            return b
        return None

    def owner(self):
        for b in reversed(self.pieces):
            if b.kind == 'nectar':
                return b.team
        return None

    def bottom_team(self):
        for b in self.pieces:
            if b.kind == 'nectar':
                return b.team
        return None

    def refresh_owner(self):
        o = self.owner()
        self.owner_tag.text = f'{o.upper()} owns' if o else ''
        self.owner_tag.color = TEAM_COL[o] if o else color.white

    def set_bloom(self, amount):
        for p in self.petals:
            p.rotation_x = lerp(-75, 15, amount)

    def reset(self):
        for b in self.pieces:
            destroy(b)
        self.pieces = []
        self.refresh_owner()


class HumanPlayer(Entity):
    def __init__(self, team, **kw):
        super().__init__(**kw)
        self.team = team
        box(self, (0, 1.3, 0), (.5, 2.6, .35), C(40, 45, 60))
        box(self, (0, 3.4, 0), (.85, 1.6, .45), TEAM_COL[team])
        ball(self, (0, 4.6, 0), .55, C(225, 185, 150))
        box(self, (.65, 2.6, 0), (.4, .08, .8), C(90, 90, 96))       # nectar shelf
        self.supply = []
        self.label = label(self, '', (0, 5.3, 0), 5, color.white, billboard=True)

    def restock(self, n):
        for b in self.supply:
            destroy(b)
        self.supply = []
        for i in range(n):
            self.supply.append(Ball('nectar', self.team, parent=self, position=(.65, 2.8, -.3 + i * .15)))
        self._lbl()

    def _lbl(self):
        self.label.text = f'{self.team.upper()} HUMAN PLAYER  Nectar x{len(self.supply)}'

    def give(self):
        if not self.supply:
            return None
        b = self.supply.pop()
        self._lbl()
        return b


# ------------------------------------------------------------------ AI driver --
class AIDriver:
    """Simple autonomous bee: collect -> launch into the Hive -> fill Flowers -> park."""

    def __init__(self, robot, game, skill=.75):
        self.r, self.g, self.skill = robot, game, skill
        self.state, self.target, self.timer = 'collect', None, 0.0
        self.stuck_t, self.last_pos, self.backoff = 0.0, Vec3(robot.position), 0.0
        self.act_cd = 0.0
        self.flower = None
        self.blacklist, self.target_t = {}, 0.0
        self.park_offset = Vec3(random.uniform(-.4, .4), 0, random.uniform(-.4, .4))

    # --- helpers ---
    def drive_to(self, p, stop=.35, face=None):
        r = self.r
        d = flat(p - r.position)
        dist = d.length()
        c = flat(-r.position)                                  # avoid the Hive
        to_c = flat(Vec3(0, 0, 0) - r.position)
        if dist > .6 and to_c.length() > HIVE_BASE_R:
            dn = d.normalized()
            along = clamp(to_c.dot(dn), 0, dist)
            closest = flat(r.position + dn * along)
            if along > .1 and closest.length() < HIVE_BASE_R + 1.0:
                ar = math.atan2(r.x, r.z)
                at = math.atan2(p.x, p.z)
                step = math.radians(55) * (1 if wrap180(math.degrees(at - ar)) > 0 else -1)
                rad = HIVE_BASE_R + 1.4
                p = Vec3(math.sin(ar + step) * rad, 0, math.cos(ar + step) * rad)
                d = flat(p - r.position)
                dist = max(d.length(), 1.0)
        if dist < stop:
            if face is not None:
                err = wrap180(face - r.rotation_y)
                return 0, 0, clamp(err / 25, -1, 1), abs(err) < 6
            return 0, 0, 0, True
        want = yaw_to(d.x, d.z)
        err = wrap180(want - r.rotation_y)
        t = clamp(err / 30, -1, 1)
        f = clamp(dist / 1.2, .25, 1) * max(0, math.cos(math.radians(min(abs(err), 90)))) ** 2
        return f * (.55 + .45 * self.skill), 0, t, False

    def pick_target(self, kinds):
        g, r = self.g, self.r
        claimed = {id(a.target) for a in g.ai_drivers if a is not self and a.target is not None}
        best, bd = None, 1e9
        for b in g.field_balls:
            if b.y > .5 or id(b) in claimed:
                continue
            if b.kind == 'nectar' and (b.team != r.team or 'nectar' not in kinds):
                continue
            if b.kind == 'pollen' and 'pollen' not in kinds:
                continue
            if flat(b.position).length() < HIVE_BASE_R + r.reach + .25 or in_zone(b.position, GARDEN_ZONE[r.team]):
                continue
            if self.blacklist.get(id(b), -1) > g.clock:
                continue
            dd = flat(b.position - r.position).length()
            if b.kind == 'nectar':
                dd -= 3
            if dd < bd:
                best, bd = b, dd
        return best

    # --- main ---
    def step(self, dt, phase, time_left):
        r, g = self.r, self.g
        self.act_cd -= dt
        lift = 0
        moved = flat(r.position - self.last_pos).length()
        self.last_pos = Vec3(r.position)

        if self.backoff > 0:
            self.backoff -= dt
            return -.6, 0, .8, 0
        if getattr(self, 'last_f', 0) > .2 and moved < .002:     # trying to drive but not moving
            self.stuck_t += dt
            if self.stuck_t > 1.2:
                self.stuck_t, self.backoff, self.target = 0, .6, None
        else:
            self.stuck_t = 0

        out = self._step(dt, phase, time_left)
        self.last_f = out[0]
        return out

    def _step(self, dt, phase, time_left):
        r, g = self.r, self.g
        # ---- decide ----
        nectar_ok = g.nectar_flowers_open()
        if phase == 'teleop' and time_left < 9:
            self.state = 'park'
        elif phase == 'auto':
            if r.store and r.has_launcher:
                self.state = 'shoot_go' if self.state not in ('shoot',) else 'shoot'
            elif self.state not in ('park',):
                self.state = 'park'
        elif self.state == 'park' and phase == 'teleop' and time_left >= 9:
            self.state = 'collect'
        if phase == 'teleop' and nectar_ok and r.finisher and self.state in ('collect', 'shoot_go', 'shoot'):
            own_n = [b for b in r.store if b.kind == 'nectar']
            if own_n and any(g.flower_room(fl, r) for fl in g.flowers):
                self.state = 'flower_go'

        lift_down = -1 if r.lift_h > .05 and self.state not in ('flower_go', 'flower') else 0

        # ---- act ----
        if self.state == 'collect':
            r.intake_on = r.has_intake
            want_n = nectar_ok and r.finisher and not any(b.kind == 'nectar' for b in r.store) and \
                any(b.kind == 'nectar' and b.team == r.team for b in g.field_balls)
            if want_n and len(r.store) >= MAX_PIECES:
                g.robot_drop(r, next(b for b in r.store if b.kind == 'pollen'))   # make room for Nectar
            if not want_n and (len(r.store) >= (MAX_PIECES if phase == 'teleop' else 1) or (r.store and self.timer > 14)):
                self.timer = 0
                has_n = any(b.kind == 'nectar' and b.team == r.team for b in r.store)
                self.state = 'flower_go' if (nectar_ok and r.finisher and has_n) else ('shoot_go' if r.has_launcher else 'flower_go' if r.finisher else 'park')
                return 0, 0, 0, lift_down
            self.timer += dt
            kinds = ('nectar',) if want_n else ('pollen', 'nectar') if (nectar_ok and r.finisher) else ('pollen',)
            self.target_t += dt
            if self.target is not None and self.target_t > 7:          # give up on a target we can't reach
                self.blacklist[id(self.target)] = g.clock + 12
                self.target = None
            if self.target is None or self.target.state != 'field' or random.random() < .005:
                self.target = self.pick_target(kinds)
                self.target_t = 0.0
            if self.target is None:
                if r.store:
                    self.state = 'shoot_go' if r.has_launcher else 'park'
                return 0, 0, .3, lift_down
            b = self.target
            if r.has_claw and not r.has_intake:
                gp = r.grab.world_position
                if flat(gp - b.position).length() < .42 and self.act_cd <= 0:
                    g.robot_grab(r)
                    self.act_cd = .5 / (.5 + self.skill)
                    self.target = None
                    return 0, 0, 0, lift_down
                aim = b.position - r.forward * (r.reach - .05)
                f, s, t, done = self.drive_to(aim, stop=.12, face=yaw_to(b.x - r.x, b.z - r.z))
                return f, s, t, lift_down
            f, s, t, _ = self.drive_to(b.position, stop=.05)
            return max(f, .35), s, t, lift_down

        if self.state in ('shoot_go', 'shoot'):
            r.intake_on = False
            if not r.store:
                self.state = 'collect' if phase == 'teleop' else 'park'
                return 0, 0, 0, lift_down
            cur = flat(r.position)
            dist = cur.length()
            if self.state == 'shoot_go':
                spot = cur.normalized() * 4.3 if dist > .1 else Vec3(-4.3, 0, 0)
                spot.x = clamp(spot.x, -5, 5)
                spot.z = clamp(spot.z, -5, 5)
                f, s, t, done = self.drive_to(spot, stop=.5)
                if done or 3.2 < dist < 6.5:
                    self.state = 'shoot'
                return f, s, t, lift_down
            if not (2.3 < dist < 8.5):
                self.state = 'shoot_go'
                return 0, 0, 0, lift_down
            if self.act_cd <= 0 and g.half_ready(r.team):
                g.robot_launch(r)
                self.act_cd = .75 / (.4 + self.skill)
            return 0, 0, 0, lift_down

        if self.state in ('flower_go', 'flower'):
            r.intake_on = False
            has_n = any(b.kind == 'nectar' and b.team == r.team for b in r.store)
            if not r.store or (not has_n and (self.flower is None or self.flower.owner() == r.team)):
                self.state, self.flower = ('collect' if (not r.store or not r.has_launcher) else 'shoot_go'), None
                return 0, 0, 0, -1
            if self.flower is None:
                taken = {id(a.flower) for a in g.ai_drivers if a is not self and a.flower is not None}
                opts = [fl for fl in g.flowers if id(fl) not in taken and g.flower_room(fl, r)]
                if not opts:
                    self.state = 'shoot_go' if r.has_launcher else 'park'
                    return 0, 0, 0, -1
                opts.sort(key=lambda fl: (fl.owner() == r.team) * 6 + flat(fl.position - r.position).length())
                self.flower = opts[0]
            fl = self.flower
            spot = fl.position + fl.facing * (r.reach + .25)
            face = yaw_to(-fl.facing.x, -fl.facing.z)
            f, s, t, done = self.drive_to(spot, stop=.3, face=face)
            near = flat(spot - r.position).length() < 2.5
            lift = 1 if (near and r.has_slide and r.lift_h < .85) else 0
            close = flat(fl.position - r.position).length() < r.reach + .7
            if (done or close) and lift == 0 and self.act_cd <= 0:
                ok = g.robot_deposit(r, quiet=True, flower=fl, reserve=True)
                self.act_cd = .6
                if not ok:
                    self.flower = None
            if done:
                return 0, 0, 0, lift
            return f, s, t, lift

        if self.state == 'park':
            r.intake_on = False
            z = LOADING_ZONE[r.team]
            c = Vec3((z[0] + z[1]) / 2, 0, (z[2] + z[3]) / 2) + self.park_offset
            f, s, t, done = self.drive_to(c, stop=.35)
            return f, s, t, lift_down
        return 0, 0, 0, 0


# -------------------------------------------------------------------- the Game --
class Game:
    def __init__(self):
        self.field_balls, self.flights = [], []
        self.hive = Hive(self)
        self.flowers = [Flower(p, f, i + 1) for i, (p, f) in enumerate(FLOWER_SPOTS)]
        self.hp = {RED: HumanPlayer(RED, position=(-6.9, 0, -5.0), rotation_y=90),
                   BLUE: HumanPlayer(BLUE, position=(6.9, 0, 5.0), rotation_y=-90)}
        self._draw_zones()
        self.phase, self.t = 'practice', 0.0
        self.robots, self.ai_drivers = [], []
        self.player = None
        self.result = None
        self.on_end = None
        self.bloom, self.bloomed = 1.0, True
        self.tips = {RED: [0, 0], BLUE: [0, 0]}           # [auto, teleop]
        self.foul_pts = {RED: 0, BLUE: 0}
        self.leave, self.auto_park = {}, {}
        self.messages = []
        self.clock = 0.0

    # ----- field drawing -----
    def _draw_zones(self):
        for team in (RED, BLUE):
            col = TEAM_COL[team]
            for zone, name in ((LOADING_ZONE[team], 'LOADING ZONE'), (GARDEN_ZONE[team], 'GARDEN')):
                x0, x1, z0, z1 = zone
                cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
                tint = col if name == 'LOADING ZONE' else C(60, 170, 80)
                Entity(model='cube', position=(cx, .004, cz), scale=(x1 - x0, .006, z1 - z0),
                       color=color.Color(tint.r, tint.g, tint.b, .22))
                for (px, pz, sx, sz) in ((cx, z0, x1 - x0, .06), (cx, z1, x1 - x0, .06),
                                          (x0, cz, .06, z1 - z0), (x1, cz, .06, z1 - z0)):
                    box(scene, (px, .008, pz), (sx, .01, sz), col)
                label(scene, f'{team.upper()}\n{name}', (cx, .02, cz), 7, col, rot=(90, 0, 0))
        for team, x in ((RED, -6.6), (BLUE, 6.6)):          # alliance areas
            Entity(model='cube', position=(x, .01, 0), scale=(1.0, .02, 12), color=TEAM_COL[team] * .7)
            label(scene, f'{team.upper()} ALLIANCE AREA', (x, .03, 0), 9, color.white,
                  rot=(90, 90 if team == RED else -90, 0))

    # ----- set-up -----
    def balls_field_add(self, b):
        if b not in self.field_balls:
            self.field_balls.append(b)

    def clear_pieces(self):
        for b in self.field_balls + [f[0] for f in self.flights]:
            destroy(b)
        self.field_balls, self.flights = [], []
        self.hive.halves[RED].reset()
        self.hive.halves[BLUE].reset()
        for fl in self.flowers:
            fl.reset()
        for r in self.robots:
            for b in list(r.store):
                destroy(b)
            r.store = []

    def setup(self, robots, extra_pollen=0):
        """Starting setup: 4 Pollen per Flower, per Garden and per robot; 3 Nectar in each upward Cell."""
        self.clear_pieces()
        self.robots = robots
        for team in (RED, BLUE):
            for _ in range(3):
                self.hive.halves[team].add_ball(Ball('nectar', team))
            self.hp[team].restock(5)
            x0, x1, z0, z1 = GARDEN_ZONE[team]
            for i in range(4):
                self._spawn('pollen', None, Vec3(lerp(x0, x1, .3 + .4 * (i % 2)), POLLEN_R, lerp(z0, z1, .3 + .4 * (i // 2))))
        for fl in self.flowers:
            for _ in range(4):
                fl.add(Ball('pollen'))
            fl.set_bloom(self.bloom)
        for r in robots:
            for _ in range(4):
                r.stow(Ball('pollen'))
        for i in range(extra_pollen):
            a = i / max(1, extra_pollen) * math.tau
            self._spawn('pollen', None, Vec3(math.sin(a) * 3.2, POLLEN_R, math.cos(a) * 3.2))
        self.tips = {RED: [0, 0], BLUE: [0, 0]}
        self.foul_pts = {RED: 0, BLUE: 0}
        self.leave = {id(r): False for r in robots}
        self.auto_park = {id(r): False for r in robots}

    def _spawn(self, kind, team, pos, vel=Vec3(0, 0, 0)):
        b = Ball(kind, team, position=pos)
        b.vel = Vec3(vel)
        self.field_balls.append(b)
        return b

    # ----- modes -----
    def start_practice(self, player):
        self.phase, self.t = 'practice', 0.0
        self.bloom, self.bloomed = 1.0, True
        for a in self.ai_drivers:
            a.r.enabled = False
        self.ai_drivers = []
        self.player = player
        player.team = RED
        self.setup([player], extra_pollen=12)
        self.place_robot(player, RED, 0)

    def start_match(self, player, partner, opp1, opp2, skills):
        self.phase, self.t = 'pre', 0.0
        self.bloom, self.bloomed = 0.0, False
        self.player = player
        robots = [player, partner, opp1, opp2]
        teams = [RED, RED, BLUE, BLUE]
        for r, tm in zip(robots, teams):
            r.enabled = True
            r.team = tm
        self.setup(robots)
        self.place_robot(player, RED, 0)
        self.place_robot(partner, RED, 1)
        self.place_robot(opp1, BLUE, 0)
        self.place_robot(opp2, BLUE, 1)
        self.ai_drivers = [AIDriver(player, self, .85), AIDriver(partner, self, skills[0]),
                           AIDriver(opp1, self, skills[1]), AIDriver(opp2, self, skills[2])]
        self.result = None

    def place_robot(self, r, team, slot):
        r.reset_motion()
        r.position = START_POS[team][slot]
        r.rotation_y = START_YAW[team]
        r.start = Vec3(r.position)
        r.lift_h = 0

    def time_left(self):
        if self.phase == 'auto':
            return AUTO_T - self.t
        if self.phase == 'teleop':
            return TELE_T - self.t
        if self.phase == 'transition':
            return TRANS_T - self.t
        if self.phase == 'pre':
            return 3 - self.t
        return 0

    def nectar_flowers_open(self):
        return self.phase == 'practice' or (self.phase == 'teleop' and self.time_left() <= 60)

    def robots_enabled(self):
        return self.phase in ('practice', 'auto', 'teleop')

    def half_ready(self, team):
        return self.hive.halves[team].anim is None

    # ----- events -----
    def msg(self, text, col=color.yellow):
        toast(text, col)

    def foul(self, offender_team, major, rule, text):
        pts = 20 if major else 5
        if self.phase in ('auto', 'teleop'):
            self.foul_pts[OTHER[offender_team]] += pts
            self.msg(f"{rule} {'MAJOR' if major else 'MINOR'} FOUL on {offender_team.upper()}: "
                     f"+{pts} to {OTHER[offender_team].upper()} ({text})", color.orange)
        else:
            self.msg(f'{rule}: {text} (would be a foul in a match)', color.orange)

    def on_tip(self, team):
        if self.phase == 'auto':
            self.tips[team][0] += 1
        else:
            self.tips[team][1] += 1
        if self.phase in ('practice', 'teleop', 'auto'):
            self.msg(f'{team.upper()} HIVE TIPPED! +20', TEAM_COL[team])
        hp = self.hp[team]
        b = hp.give()
        if b:
            self._hp_drop(team, b)

    def _hp_drop(self, team, b):
        x0, x1, z0, z1 = LOADING_ZONE[team]
        b.parent = scene
        b.position = Vec3(lerp(x0, x1, random.uniform(.3, .7)), .4, lerp(z0, z1, random.uniform(.3, .7)))
        b.state, b.vel = 'field', Vec3(random.uniform(-.5, .5), 0, random.uniform(-.5, .5))
        self.field_balls.append(b)

    # ----- robot actions -----
    def robot_grab(self, r):
        """Claw grab (or manual intake pulse): take the nearest piece in front."""
        if len(r.store) >= MAX_PIECES:
            if r is self.player:
                self.msg('G407: robots may hold at most 4 pieces')
            return False
        r.claw_pulse()
        if r.lift_h > .25 and r.has_slide:
            if r is self.player:
                self.msg('Lower the lift to grab from the floor')
            return False
        gp = r.grab.world_position
        cands = [b for b in self.field_balls if b.y < .5 and flat(b.position - gp).length() < .45]
        if not cands:
            return False
        b = min(cands, key=lambda e: flat(e.position - gp).length())
        self._collect(r, b)
        return True

    def _collect(self, r, b):
        self.field_balls.remove(b)
        r.stow(b)
        if b.kind == 'nectar' and b.team != r.team:
            self.foul(r.team, False, 'G408', "controlled the opponent's Nectar")
            self.robot_drop(r, b, quiet=True)

    def robot_launch(self, r):
        if not r.has_launcher:
            if r is self.player:
                self.msg('No launcher on this robot - add one in ROBOT BUILD', color.red)
            return False
        if not r.store or r.launch_cd > 0:
            return False
        half = self.hive.halves[r.team]
        pos = flat(r.position)
        d = pos.length()
        if d < 2.2 or d > 9:
            if r is self.player:
                self.msg(f'Out of range ({d:.1f} ft) - launch from 2.2 to 9 ft from the Hive')
            return False
        b = next((x for x in r.store if x.kind == 'pollen'), r.store[0])
        r.unstow(b)
        start = r.launch_point()
        target = half.aim_point()
        speed = flat(r.vel_world).length()
        skill = getattr(r, 'skill', .85)
        p_hit = clamp(.98 - .055 * max(0, d - 3.5) - .12 * speed - .25 * (1 - skill), .3, .98)
        hit = random.random() < p_hit
        end = target if hit else target + Vec3(random.uniform(-.9, .9), random.uniform(-.2, .3), random.uniform(-.9, .9))
        T = .5 + d * .07
        b.state = 'flight'
        b.flight = dict(a=start, b=end, T=T, t=0.0, hit=hit, team=r.team, cell=half.upi, h=1.4 + d * .12)
        self.flights.append((b, b.flight))
        r.launch_cd = .35
        r.kick_flywheel()
        return True

    def nearest_flower(self, r, max_d=None):
        best, bd = None, 1e9
        for fl in self.flowers:
            dd = flat(fl.position - r.position).length()
            if dd < bd:
                best, bd = fl, dd
        if max_d is not None and bd > max_d:
            return None
        return best

    def flowers_have_room(self, r):
        return any(fl.used() + 2 * NECTAR_R <= FLOWER_TOP - .05 for fl in self.flowers)

    def flower_room(self, fl, r):
        nectar_left = any(b.kind == 'nectar' and b.team == r.team for b in r.store)
        need = 2 * NECTAR_R if (nectar_left or self.nectar_flowers_open()) else 2 * POLLEN_R
        return fl.used() + need <= FLOWER_TOP - .05

    def robot_deposit(self, r, quiet=False, flower=None, reserve=False):
        if not r.finisher:
            if not quiet:
                self.msg('Needs a Flower finisher: add a Linear Slide or an Arm in ROBOT BUILD', color.red)
            return False
        fl = flower if flower is not None and flat(flower.position - r.position).length() < r.reach + .75 \
            else self.nearest_flower(r, max_d=r.reach + .75)
        if fl is None:
            if not quiet:
                self.msg('Drive up to a Flower first')
            return False
        if r.has_slide and r.lift_h < .75:
            if not quiet:
                self.msg(f'Raise the lift above the 21.5in Flower top (Up arrow)')
            return False
        own_n = [b for b in r.store if b.kind == 'nectar' and b.team == r.team]
        pol = [b for b in r.store if b.kind == 'pollen']
        if own_n and self.nectar_flowers_open():
            b = own_n[0]
        elif pol:
            b = pol[0]
        elif own_n:
            if not quiet:
                self.msg('G410: Nectar may only go in Flowers with 1:00 or less left (Major Foul)', color.orange)
            return False
        else:
            return False
        if b.kind == 'pollen' and reserve and fl.used() + 2 * POLLEN_R + 2 * NECTAR_R > FLOWER_TOP - .05:
            return False                                     # AI keeps room for its Nectar on top
        if not fl.can_add(b):
            if not quiet:
                self.msg(f'Flower {fl.idx} is full')
            return False
        r.unstow(b)
        fl.add(b)
        return True

    def robot_drop(self, r, b=None, quiet=False):
        if not r.store:
            return False
        b = b or r.store[-1]
        r.unstow(b)
        p = r.world_position - r.forward * (r.info['hi'].z - r.info['lo'].z) * .5 - r.forward * .3
        b.to_field(-r.forward * 1.2)
        b.position = Vec3(p.x, .5, p.z)
        self.field_balls.append(b)
        return True

    # ----- per-frame -----
    def update(self, dt):
        self.clock = getattr(self, 'clock', 0.0) + dt
        # clock
        if self.phase not in ('practice', 'over'):
            self.t += dt
            if self.phase == 'pre' and self.t >= 3:
                self.phase, self.t = 'auto', 0.0
                self.msg('AUTO - robots run on their own for 30 seconds', color.cyan)
            elif self.phase == 'auto' and self.t >= AUTO_T:
                for r in self.robots:
                    self.auto_park[id(r)] = self.in_loading_zone(r)
                self.phase, self.t = 'transition', 0.0
                self.msg('Drivers, pick up your controllers!', color.cyan)
            elif self.phase == 'transition' and self.t >= TRANS_T:
                self.phase, self.t = 'teleop', 0.0
                self.msg('TELEOP - 2:00 of driver control', color.lime)
            elif self.phase == 'teleop':
                if not self.bloomed and self.time_left() <= 60:
                    self.bloomed = True
                    self.msg('1:00 LEFT - Flowers open! Human players add all Nectar', color.lime)
                    for team in (RED, BLUE):
                        while True:
                            b = self.hp[team].give()
                            if not b:
                                break
                            self._hp_drop(team, b)
                if self.t >= TELE_T:
                    self.end_match()
        if self.bloomed and self.bloom < 1:
            self.bloom = min(1, self.bloom + dt)
            for fl in self.flowers:
                fl.set_bloom(self.bloom)

        # auto LEAVE
        if self.phase == 'auto':
            for r in self.robots:
                if flat(r.position - r.start).length() > 1.0:
                    self.leave[id(r)] = True

        for h in self.hive.halves.values():
            h.step(dt)
        self._flights(dt)
        self._robot_physics(dt)
        self._ball_physics(dt)

    def _flights(self, dt):
        for b, f in list(self.flights):
            f['t'] += dt
            u = min(1, f['t'] / f['T'])
            p = lerp(f['a'], f['b'], u)
            p.y += 4 * f['h'] * u * (1 - u)
            b.position = p
            if u >= 1:
                self.flights.remove((b, f))
                half = self.hive.halves[f['team']]
                if f['hit'] and half.upi == f['cell'] and half.anim is None:
                    half.add_ball(b)
                else:
                    out = flat(b.position).normalized() if flat(b.position).length() > .01 else Vec3(1, 0, 0)
                    b.to_field(out * random.uniform(1.5, 3) + Vec3(0, -1, 0))
                    self.field_balls.append(b)

    def in_loading_zone(self, r):
        z = LOADING_ZONE[r.team]
        lo, hi = r.info['lo'], r.info['hi']
        for lx in (lo.x, hi.x):
            for lz in (lo.z, hi.z):
                p = scene.getRelativePoint(r, Vec3(lx, 0, lz))
                if in_zone(p, z):
                    return True
        return in_zone(r.position, z)

    def _robot_physics(self, dt):
        rs = [r for r in self.robots if r.enabled]
        for r in rs:
            r.launch_cd -= dt
            r.foul_cd -= dt
            r.vel_world = (r.position - getattr(r, '_lastp', r.position)) / max(dt, 1e-4)
            r._lastp = Vec3(r.position)
            rad = r.radius
            p = flat(r.position)
            d = p.length()
            if d < HIVE_BASE_R + rad:                                   # the Hive
                n = p.normalized() if d > .01 else Vec3(1, 0, 0)
                r.position = n * (HIVE_BASE_R + rad)
                if flat(r.vel_world).length() > 2.8 and r.foul_cd <= 0 and self.phase in ('auto', 'teleop', 'practice'):
                    r.foul_cd = 3
                    self.foul(r.team, False, 'G417', 'drove into the Hive')
            for fl in self.flowers:
                v = flat(r.position - fl.position)
                if v.length() < rad * .8 + .25:
                    r.position = flat(fl.position) + (v.normalized() if v.length() > .01 else -fl.facing) * (rad * .8 + .25)
        for i in range(len(rs)):                                      # robot vs robot
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                v = flat(b.position - a.position)
                dmin = (a.radius + b.radius) * .85
                if 0 < v.length() < dmin:
                    push = v.normalized() * (dmin - v.length()) / 2
                    a.position -= push
                    b.position += push
        for r in rs:
            lim = 6 - r.radius * .9
            r.x, r.z = clamp(r.x, -lim, lim), clamp(r.z, -lim, lim)

    def _ball_physics(self, dt):
        dt = min(dt, .05)
        balls = self.field_balls
        for b in balls:
            v = b.vel
            if b.y > b.r + .001 or v.y > 0:
                v.y -= 32 * dt
            p = b.position + v * dt
            if p.y < b.r:
                p.y = b.r
                if v.y < -2:
                    v.y *= -.35
                    v.x *= .8
                    v.z *= .8
                else:
                    v.y = 0
            if p.y <= b.r + .01:
                k = max(0, 1 - 2.2 * dt)
                v.x *= k
                v.z *= k
            lim = 6 - b.r
            if abs(p.x) > lim:
                p.x = math.copysign(lim, p.x)
                v.x *= -.5
            if abs(p.z) > lim:
                p.z = math.copysign(lim, p.z)
                v.z *= -.5
            hp = flat(p)
            if hp.length() < HIVE_BASE_R + b.r and p.y < .5:
                n = hp.normalized() if hp.length() > .01 else Vec3(1, 0, 0)
                p = Vec3(n.x * (HIVE_BASE_R + b.r), p.y, n.z * (HIVE_BASE_R + b.r))
                vn = v.x * n.x + v.z * n.z
                if vn < 0:
                    v.x -= 1.6 * vn * n.x
                    v.z -= 1.6 * vn * n.z
            for fl in self.flowers:
                fv = flat(p - fl.position)
                if fv.length() < .23 + b.r and p.y < FLOWER_TOP:
                    n = fv.normalized() if fv.length() > .01 else fl.facing
                    p = Vec3(fl.x + n.x * (.23 + b.r), p.y, fl.z + n.z * (.23 + b.r))
            b.position = p
            b.vel = v

        collected = []
        for r in self.robots:
            if not r.enabled:
                continue
            lo, hi = r.info['lo'], r.info['hi']
            rv = flat(r.vel_world) if hasattr(r, 'vel_world') else Vec3(0, 0, 0)
            for b in balls:
                if b.y > 1.2 or b in collected:
                    continue
                lp = r.getRelativePoint(scene, b.position)
                if r.intake_on and r.has_intake and len(r.store) < MAX_PIECES and \
                        abs(lp.x) < .32 and hi.z - .1 < lp.z < hi.z + .35 and \
                        not (b.kind == 'nectar' and b.team != r.team and r.ai is not None):
                    collected.append(b)
                    self._collect(r, b)
                    continue
                if lo.x - b.r < lp.x < hi.x + b.r and lo.z - b.r < lp.z < hi.z + b.r:
                    px = min(lp.x - (lo.x - b.r), (hi.x + b.r) - lp.x)
                    pz = min(lp.z - (lo.z - b.r), (hi.z + b.r) - lp.z)
                    if px < pz:
                        lp.x = lo.x - b.r if lp.x - lo.x < hi.x - lp.x else hi.x + b.r
                    else:
                        lp.z = lo.z - b.r if lp.z - lo.z < hi.z - lp.z else hi.z + b.r
                    np_ = scene.getRelativePoint(r, lp)
                    b.position = Vec3(np_.x, b.y, np_.z)
                    b.vel = Vec3(rv.x * 1.1, b.vel.y, rv.z * 1.1)
            # pull Pollen out of a Flower's bottom opening with an intake
            if r.intake_on and r.has_intake and len(r.store) < MAX_PIECES and r.launch_cd < -.4:
                fl = self.nearest_flower(r, max_d=r.reach + .45)
                if fl:
                    b = fl.take_bottom_pollen()
                    if b:
                        r.stow(b)
                        r.launch_cd = 0
        # ball vs ball (only balls resting on the floor)
        ground = [b for b in balls if b.y < b.r + .05]
        for i in range(len(ground)):
            a = ground[i]
            for j in range(i + 1, len(ground)):
                c = ground[j]
                dx, dz = c.x - a.x, c.z - a.z
                dmin = a.r + c.r
                d2 = dx * dx + dz * dz
                if 1e-8 < d2 < dmin * dmin:
                    d = math.sqrt(d2)
                    push = (dmin - d) / 2
                    nx, nz = dx / d, dz / d
                    a.x -= nx * push
                    a.z -= nz * push
                    c.x += nx * push
                    c.z += nz * push

    # ----- scoring -----
    def score(self, team):
        rs = [r for r in self.robots if r.team == team]
        in_play = self.phase in ('teleop', 'over', 'practice')
        s = dict(
            leave=3 * sum(1 for r in rs if self.leave.get(id(r))),
            auto_park=5 * sum(1 for r in rs if self.auto_park.get(id(r))),
            tips=20 * sum(self.tips[team]),
            cell=2 * len(self.hive.halves[team].up_cell().balls) if in_play else 0,
            flower=0, bonus=0,
            garden=sum(1 for b in self.field_balls if in_zone(b.position, GARDEN_ZONE[team]) and b.y < .5),
            park=5 * sum(1 for r in rs if self.in_loading_zone(r)) if in_play else 0,
            fouls=self.foul_pts[team])
        for fl in self.flowers:
            if fl.owner() == team:
                s['flower'] += 2 * len(fl.pieces)
            if fl.bottom_team() == team:
                s['bonus'] += 5
        s['total'] = sum(s.values())
        s['tip_count'] = sum(self.tips[team])
        return s

    def end_match(self):
        self.phase = 'over'
        red, blue = self.score(RED), self.score(BLUE)
        res = {RED: red, BLUE: blue}
        for team in (RED, BLUE):
            me, op = res[team], res[OTHER[team]]
            rp = 3 if me['total'] > op['total'] else 1 if me['total'] == op['total'] else 0
            swarm = me['leave'] + me['auto_park'] + me['park'] >= 16
            p1, p2 = me['tip_count'] >= 4, me['tip_count'] >= 7
            me['rp'] = rp + swarm + p1 + p2
            me['rp_parts'] = dict(win=rp, swarm=swarm, pollinator1=p1, pollinator2=p2)
        self.result = res
        for r in self.robots:
            r.intake_on = False
        if self.on_end:
            self.on_end(res)


# ------------------------------------------------------------------ Event --
TEAMS = [
    (12345, 'TechnoBlades', None), (7821, 'Hive Minds', .9), (16045, 'Buzzworthy', .8),
    (9302, 'Gear Bees', .7), (21477, 'Stinger Robotics', .85), (18810, 'Pollen Pushers', .55),
    (5519, 'Queen Bee Bots', .95), (23104, 'Nectar Ninjas', .6), (11278, 'Honeycomb Hackers', .75),
    (14092, 'Wax Works', .45), (8466, 'Swarm Theory', .65), (19983, 'Bumblebots', .5)]
OUR_TEAM = 12345
N_ROUNDS = 5


class Event:
    def __init__(self):
        self.names = {n: nm for n, nm, _ in TEAMS}
        self.skill = {n: (s if s is not None else .8) for n, nm, s in TEAMS}
        self.reset()

    def reset(self):
        self.stats = {n: dict(rp=0, w=0, l=0, t=0, pts=0, played=0) for n, _, _ in TEAMS}
        self.round = 0
        self.log = []
        others = [n for n, _, _ in TEAMS if n != OUR_TEAM]
        self.schedule = []
        for rnd in range(N_ROUNDS):
            random.shuffle(others)
            ours = ([OUR_TEAM, others[0]], [others[1], others[2]])
            rest = others[3:]
            extra = [([rest[0], rest[1]], [rest[2], rest[3]]), ([rest[4], rest[5]], [rest[6], rest[7]])]
            self.schedule.append(dict(ours=ours, others=extra, result=None))

    def done(self):
        return self.round >= N_ROUNDS

    def next_match(self):
        return None if self.done() else self.schedule[self.round]

    def _record(self, red, blue, rs, bs):
        for teams, me, op in ((red, rs, bs), (blue, bs, rs)):
            for n in teams:
                st = self.stats[n]
                st['rp'] += me['rp']
                st['pts'] += me['total']
                st['played'] += 1
                if me['total'] > op['total']:
                    st['w'] += 1
                elif me['total'] < op['total']:
                    st['l'] += 1
                else:
                    st['t'] += 1

    def sim_alliance(self, teams):
        s = sum(self.skill[n] for n in teams) / 2
        tips = max(0, round(random.gauss(1 + 6.5 * s, 1.3)))
        leave = 3 * sum(random.random() < .6 + .4 * self.skill[n] for n in teams)
        apark = 5 * sum(random.random() < .3 + .5 * self.skill[n] for n in teams)
        park = 5 * sum(random.random() < .5 + .45 * self.skill[n] for n in teams)
        flower = max(0, round(random.gauss(14 * s, 5))) * 2
        bonus = 5 * max(0, min(4, round(random.gauss(2.5 * s, 1))))
        garden = max(0, round(random.gauss(3, 2)))
        cell = 2 * random.randint(0, 5)
        return dict(leave=leave, auto_park=apark, tips=20 * tips, cell=cell, flower=flower, bonus=bonus,
                    garden=garden, park=park, fouls=0, tip_count=tips)

    def finish_sim(self, a, b):
        for me, op in ((a, b), (b, a)):
            me['fouls'] = 5 * random.choice([0, 0, 0, 1, 2]) + 20 * (random.random() < .1)
        for me, op in ((a, b), (b, a)):
            me['total'] = sum(v for k, v in me.items() if k not in ('tip_count', 'total', 'rp', 'rp_parts'))
        for me, op in ((a, b), (b, a)):
            win = 3 if me['total'] > op['total'] else 1 if me['total'] == op['total'] else 0
            me['rp'] = win + (me['leave'] + me['auto_park'] + me['park'] >= 16) + \
                (me['tip_count'] >= 4) + (me['tip_count'] >= 7)

    def complete_round(self, our_result):
        m = self.schedule[self.round]
        red, blue = m['ours']
        self._record(red, blue, our_result[RED], our_result[BLUE])
        m['result'] = (our_result[RED]['total'], our_result[BLUE]['total'],
                       our_result[RED]['rp'])
        for r2, b2 in m['others']:
            a, b = self.sim_alliance(r2), self.sim_alliance(b2)
            self.finish_sim(a, b)
            self._record(r2, b2, a, b)
        self.round += 1

    def rankings(self):
        rows = []
        for n, st in self.stats.items():
            g = max(1, st['played'])
            rows.append((n, st['rp'] / g, st['pts'] / g, st))
        rows.sort(key=lambda r: (-r[1], -r[2]))
        return rows


# ----------------------------------------------------------------------------
# Create game, robots, bay, UI
# ----------------------------------------------------------------------------
game = Game()
event = Event()
robot = BuiltRobot(default_spec(), alliance=RED, number=OUR_TEAM, position=(0, 0, -3))
ai_bots = [BuiltRobot(default_spec(), alliance=tm, position=(0, -30, 0)) for tm in (RED, BLUE, BLUE)]
for _b in ai_bots:
    _b.enabled = False

part_images = render_part_images()
bay = BuildBay(position=BAY_POS)
build_ui = BuildUI(bay, part_images)
bay.load_spec(default_spec())
bay.history.clear()
build_ui.enabled = False

# ----------------------------------------------------------------------------
# HUD: tabs, scoreboard, toast, help
# ----------------------------------------------------------------------------
toast_text = Text(parent=camera.ui, text='', position=(0, .3, -2), origin=(0, 0), scale=1.05)
toast_t = 0.0


def toast(msg, col=color.yellow):
    global toast_t
    toast_text.text, toast_text.color = msg, col
    toast_t = 2.6


sim_ui = Entity(parent=camera.ui)
help_text = Text(parent=sim_ui, position=(window.top_left.x + .02, -.39), scale=.72, background=True, text=(
    'WASD drive | Q/E turn | Up/Down lift | SPACE launch into Hive | V intake on/off or claw grab\n'
    'F fill Flower | G drop piece (Garden) | N human player Nectar | TAB opmode | R reset field\n'
    'C wifi | T touch | H spin hub | 1/2/3/4 camera | B build mode'))
status_hud = Text(parent=sim_ui, text='', position=(0, .345), origin=(0, 0), scale=1.1)

score_ui = Entity(parent=camera.ui)
Entity(parent=score_ui, model='quad', color=C(12, 14, 20, 225), position=(0, .403, 1), scale=(1.02, .072))
score_main = Text(parent=score_ui, text='', position=(0, .417), origin=(0, 0), scale=1.25)
score_sub = Text(parent=score_ui, text='', position=(0, .385), origin=(0, 0), scale=.72, color=C(210, 215, 225))

TAB_DEFS = (('sim', 'PRACTICE'), ('build', 'ROBOT BUILD'), ('event', 'BIOBUZZ EVENT'))
tabs = {}
for _i, (_m, _t) in enumerate(TAB_DEFS):
    _b = Button(parent=camera.ui, text=_t, position=(-.22 + _i * .22, .467, -2), scale=(.21, .044))
    _b.text_entity.scale *= .9
    _b.on_click = Func(lambda m: set_mode(m), _m)
    tabs[_m] = _b

# ----------------------------------------------------------------------------
# Event screen + match results
# ----------------------------------------------------------------------------
class EventUI(Entity):
    def __init__(self, **kw):
        super().__init__(parent=camera.ui, **kw)
        Entity(parent=self, model='quad', color=C(14, 16, 22, 240), scale=(1.42, .84), position=(0, -.03, 1),
               collider='box')
        Text(parent=self, text='BIOBUZZ QUALIFIER  -  FTC 2026-27 (simulated event)', position=(-.68, .36),
             scale=1.15, color=ORANGE)
        Text(parent=self, position=(-.68, .325), scale=.62, color=C(170, 175, 190),
             text='12 teams, 5 qualification matches each. You are Red with an AI partner; the other '
                  'matches are simulated. Ranked by average RP, then average score.')
        Text(parent=self, text='RANKINGS', position=(-.68, .27), scale=.9, color=C(255, 200, 80))
        self.rank_text = Text(parent=self, text='', position=(-.68, .235), scale=.68, font='VeraMono.ttf',
                              line_height=1.2)
        Text(parent=self, text='YOUR MATCHES', position=(.06, .27), scale=.9, color=C(255, 200, 80))
        self.sched_text = Text(parent=self, text='', position=(.06, .235), scale=.68, font='VeraMono.ttf',
                               line_height=1.25)
        Text(parent=self, position=(.06, -.07), scale=.62, color=C(200, 205, 215), line_height=1.15, text=(
            'SCORING   AUTO: Leave 3, Park 5, Hive tip 20\n'
            'TELEOP: Hive tip 20, Park 5, Upward Cell 2 each,\n'
            'Flower you own 2/piece, Bottom Nectar 5, Garden 1\n'
            'RP: Win 3 / Tie 1, SWARM (leave+park >= 16) 1,\n'
            'POLLINATOR 4+ tips 1, 7+ tips 1'))
        self.play_btn = Button(parent=self, text='PLAY NEXT MATCH', position=(.22, -.25), scale=(.3, .055),
                               color=C(30, 140, 70), highlight_color=C(45, 175, 90))
        self.play_btn.on_click = start_event_match
        rb = Button(parent=self, text='Reset event', position=(.5, -.25), scale=(.18, .045),
                    color=C(110, 40, 40), highlight_color=C(150, 55, 55))
        rb.text_entity.scale *= .8
        rb.on_click = self.reset_event
        self.refresh()

    def reset_event(self):
        event.reset()
        self.refresh()
        toast('Event reset - new schedule')

    def refresh(self):
        rows = ['Rk  Team   Name               RP/M   Avg   W-L-T']
        for k, (n, rpm, avg, st) in enumerate(event.rankings()):
            nm = event.names[n][:17]
            mark = '<orange>' if n == OUR_TEAM else ''
            end = '<default>' if mark else ''
            rows.append(f"{mark}{k + 1:>2}  {n:<6} {nm:<17} {rpm:5.2f} {avg:5.0f}   {st['w']}-{st['l']}-{st['t']}{end}")
        self.rank_text.text = '\n'.join(rows)
        lines = []
        for i, m in enumerate(event.schedule):
            red, blue = m['ours']
            vs = f"w/ {red[1]} vs {blue[0]}, {blue[1]}"
            if m['result']:
                rs, bs, rp = m['result']
                wl = 'W' if rs > bs else 'L' if rs < bs else 'T'
                c = '<lime>' if wl == 'W' else '<red>' if wl == 'L' else '<yellow>'
                lines.append(f"Q{i + 1}  {vs:<26} {c}{wl} {rs}-{bs}  +{rp} RP<default>")
            elif i == event.round:
                lines.append(f"<orange>Q{i + 1}  {vs:<26} NEXT<default>")
            else:
                lines.append(f"Q{i + 1}  {vs}")
        if event.done():
            rank = [r[0] for r in event.rankings()].index(OUR_TEAM) + 1
            lines.append('')
            lines.append(f'<lime>Qualifications complete - you ranked #{rank} of 12!<default>')
        self.sched_text.text = '\n'.join(lines)
        self.play_btn.enabled = not event.done()


class ResultsUI(Entity):
    def __init__(self, **kw):
        super().__init__(parent=camera.ui, **kw)
        Entity(parent=self, model='quad', color=C(12, 14, 20, 245), scale=(.95, .74), position=(0, -.02, 1),
               collider='box')
        self.title = Text(parent=self, text='', position=(0, .3), origin=(0, 0), scale=1.6)
        self.body = Text(parent=self, text='', position=(-.42, .24), scale=.75, font='VeraMono.ttf',
                         line_height=1.2)
        b = Button(parent=self, text='Continue', position=(0, -.32), scale=(.25, .05), color=C(30, 140, 70),
                   highlight_color=C(45, 175, 90))
        b.on_click = finish_match_results
        self.enabled = False

    def show(self, res):
        r, b = res[RED], res[BLUE]
        win = RED if r['total'] > b['total'] else BLUE if b['total'] > r['total'] else None
        self.title.text = f"{win.upper()} ALLIANCE WINS!" if win else 'TIE!'
        self.title.color = TEAM_COL[win] if win else color.yellow
        rows = [('Leave (auto)', 'leave'), ('Park (auto)', 'auto_park'), ('Hive tips', 'tips'),
                ('Upward Cell pieces', 'cell'), ('Flowers owned', 'flower'), ('Bottom Nectar bonus', 'bonus'),
                ('Garden', 'garden'), ('Park (end)', 'park'), ('Opponent penalties', 'fouls')]
        lines = [f"{'':<22}{'RED':>8}{'BLUE':>8}", '-' * 38]
        for name, k in rows:
            extra = f" ({r['tip_count']}/{b['tip_count']})" if k == 'tips' else ''
            lines.append(f"{name:<22}{r[k]:>8}{b[k]:>8}{extra}")
        lines.append('-' * 38)
        lines.append(f"{'TOTAL':<22}{r['total']:>8}{b['total']:>8}")
        lines.append('')
        for team, sc in ((RED, r), (BLUE, b)):
            pr = sc['rp_parts']
            parts = [f"win {pr['win']}"] + [n.upper() for n in ('swarm', 'pollinator1', 'pollinator2') if pr[n]]
            lines.append(f"{team.upper():<5} {sc['rp']} RP  ({', '.join(parts)})")
        self.body.text = '\n'.join(lines)
        self.enabled = True


# ----------------------------------------------------------------------------
# Camera
# ----------------------------------------------------------------------------
editor_cam = EditorCamera()
cam_mode = 'overview'


def set_cam(pos, rot, dist):
    editor_cam.position, editor_cam.rotation = pos, rot
    if hasattr(editor_cam, 'target_z'):
        editor_cam.target_z = -dist
    camera.position = (0, 0, -dist)
    camera.rotation = (0, 0, 0)


def cam_overview():
    set_cam((0, .5, -.4), (56, 0, 0), 22.5)


def cam_driver():
    set_cam((1.2, 1.4, DS_Z), (18, 0, 0), 4.5)


def cam_bench():
    set_cam((BENCH_X, 1.1, DS_Z), (52, 0, 0), 7.5)


def cam_build():
    set_cam(BAY_POS + Vec3(0, .55, 0), (28, 150, 0), 5.2)


cam_overview()

# ----------------------------------------------------------------------------
# Mode switching
# ----------------------------------------------------------------------------
mode = 'sim'
state = 'STOPPED'


def ensure_robot():
    """Rebuild the player's robot if the build changed."""
    global robot
    spec = bay.to_spec()
    if json.dumps(spec) != robot.spec_json:
        robot.release()
        destroy_tree(robot)
        robot = BuiltRobot(spec, alliance=RED, number=OUR_TEAM, position=(0, 0, -3))
        if not robot.can_drive:
            toast("Your robot can't drive yet: " + ', '.join(robot.problems), color.red)
        return True
    return False


def style_tabs():
    for m, b in tabs.items():
        active = mode == m or (m == 'event' and mode == 'match')
        b.color = ORANGE if active else C(40, 44, 54)
        b.highlight_color = C(255, 140, 50) if active else C(70, 78, 96)


def hide_ai():
    for b in ai_bots:
        for x in list(b.store):
            destroy(x)
        b.store = []
        b.enabled = False


def set_mode(m):
    global mode, state, cam_mode
    if m == mode:
        return
    if mode == 'match' and game.phase not in ('over',):
        toast('Match abandoned', color.orange)
    prev = mode
    mode = m
    state = 'STOPPED'
    results_ui.enabled = False
    build_ui.enabled = m == 'build'
    sim_ui.enabled = m == 'sim'
    event_ui.enabled = m == 'event'
    score_ui.enabled = m in ('sim', 'match')
    help_text.enabled = m == 'sim'
    if m == 'build':
        cam_mode = 'build'
        cam_build()
    else:
        bay.select(None)
        build_ui.show_info(None)
        build_ui.tooltip.text = ''
    if m == 'sim':
        hide_ai()
        changed = ensure_robot()
        robot.enabled = True
        robot.set_alliance(RED, OUR_TEAM)
        game.start_practice(robot)
        if changed and robot.can_drive:
            toast('Your robot is on the field! Press TAB twice to start', color.lime)
        cam_mode = 'overview'
        cam_overview()
    if m == 'event':
        hide_ai()
        ensure_robot()
        game.phase = 'idle'
        event_ui.refresh()
        cam_mode = 'overview'
        cam_overview()
    style_tabs()


def start_event_match():
    global mode, cam_mode
    m = event.next_match()
    if m is None:
        return
    ensure_robot()
    red, blue = m['ours']
    nums = [red[1], blue[0], blue[1]]
    for bot, n, tm in zip(ai_bots, nums, (RED, BLUE, BLUE)):
        bot.enabled = True
        bot.set_alliance(tm, n)
        bot.skill = event.skill[n]
    robot.set_alliance(RED, OUR_TEAM)
    robot.enabled = True
    game.start_match(robot, ai_bots[0], ai_bots[1], ai_bots[2], [event.skill[n] for n in nums])
    for a in game.ai_drivers:
        a.r.ai = a
    robot.ai = None
    mode = 'match'
    event_ui.enabled, score_ui.enabled, sim_ui.enabled = False, True, True
    help_text.enabled = False
    cam_mode = 'overview'
    cam_overview()
    style_tabs()
    toast(f'Q{event.round + 1}: {OUR_TEAM} + {red[1]}  vs  {blue[0]} + {blue[1]}', color.cyan)


def on_match_end(res):
    results_ui.show(res)


def finish_match_results():
    results_ui.enabled = False
    if mode == 'match' and game.result:
        event.complete_round(game.result)
    set_mode('event')


game.on_end = on_match_end
event_ui = EventUI()
event_ui.enabled = False
results_ui = ResultsUI()
game.start_practice(robot)
help_text.enabled = True
style_tabs()

# ----------------------------------------------------------------------------
# Sensors + main loop
# ----------------------------------------------------------------------------
run_time = 0.0
battery = 13.6
clock = 0.0
tel_timer = 0.0


def axis(pos_key, neg_key, pad_key=None):
    v = held_keys[pos_key] - held_keys[neg_key]
    if pad_key:
        v += held_keys[pad_key]
    return clamp(v, -1, 1)


def wall_distance(origin, direction):
    best = 1e9
    for dv, pv in ((direction.x, origin.x), (direction.z, origin.z)):
        if abs(dv) > 1e-6:
            best = min(best, ((6 if dv > 0 else -6) - pv) / dv)
    return best


def read_sensors():
    has = robot.info['has']
    lo, hi = robot.info['lo'], robot.info['hi']
    dist_cm = clamp((wall_distance(robot.position, robot.forward) - hi.z) * 30.48, 0, 999) if has['dist'] else 999
    back = wall_distance(robot.position, -robot.forward) + lo.z
    touch = bool(has['touch']) and (bool(held_keys['t']) or back < .05)
    cs = robot.color_sensor.world_position
    near = [b for b in game.field_balls if flat(b.position - cs).length() < .3 and abs(b.y - cs.y) < .35]
    if not has['color']:
        col_name, col_rgb = 'no sensor', C(40, 40, 40)
    elif near:
        col_name, col_rgb = near[0].color_name, near[0].color
    else:
        col_name, col_rgb = 'GRAY (field)', C(150, 150, 150)
    mag = bool(has['mag']) and robot.lift_h < .03
    return dist_cm, touch, col_name, col_rgb, mag


def fmt_t(sec):
    sec = max(0, int(math.ceil(sec)))
    return f'{sec // 60}:{sec % 60:02d}'


def update_scoreboard():
    rs, bs = game.score(RED), game.score(BLUE)
    ph = game.phase
    if mode == 'sim':
        score_main.text = f"<red>PRACTICE  RED {rs['total']}<default>"
        sub = f"Tips {rs['tip_count']}  |  Hive weight {game.hive.halves[RED].weight():.1f}/{TIP_WEIGHT:.0f}"
    else:
        label_ = {'pre': 'GET READY', 'auto': 'AUTO', 'transition': 'PICK UP CONTROLLERS',
                  'teleop': 'TELEOP', 'over': 'FINAL'}.get(ph, '')
        score_main.text = f"<red>RED {rs['total']:>3}<default>     {label_} {fmt_t(game.time_left())}     <azure>{bs['total']:<3} BLUE"
        flowers = 'OPEN' if game.bloomed else f'open in {fmt_t(game.time_left() - 60)}' if ph == 'teleop' else 'closed'
        sub = f"Tips R{rs['tip_count']} B{bs['tip_count']}  |  Flowers {flowers}"
    kinds = ''.join('N' if b.kind == 'nectar' else 'P' for b in robot.store)
    score_sub.text = f"{sub}  |  Carrying {len(robot.store)}/4 {kinds}"


def update():
    global run_time, battery, clock, tel_timer, toast_t, state
    dt = time.dt
    clock += dt

    if toast_t > 0:
        toast_t -= dt
        if toast_t <= 0:
            toast_text.text = ''

    f = s = t = lift_in = 0
    if mode == 'build':
        bay.update_bay(dt)
        build_ui.update_tooltip()
    elif mode in ('sim', 'match'):
        keyboard = mode == 'sim' or game.phase == 'teleop'
        if keyboard:
            f = axis('w', 's', 'gamepad left stick y')
            s = axis('d', 'a', 'gamepad left stick x')
            t = axis('e', 'q', 'gamepad right stick x')
            lift_in = clamp(held_keys['up arrow'] - held_keys['down arrow']
                            + held_keys['gamepad right trigger'] - held_keys['gamepad left trigger'], -1, 1)
        if mode == 'match':
            state = 'RUNNING' if game.phase in ('auto', 'teleop') else 'INIT' if game.phase in ('pre', 'transition') else 'STOPPED'
            if game.phase == 'auto' and game.ai_drivers:
                f, s, t, lift_in = game.ai_drivers[0].step(dt, 'auto', game.time_left())

    link.ok = conn = link.connected and robot.has_hub
    enabled = conn and state == 'RUNNING' and mode in ('sim', 'match')
    robot.drive(f, s, t, dt, enabled)
    robot.update_mechanisms(lift_in, dt, enabled)
    if mode in ('sim', 'match'):
        robot.spin_extras(dt)
        robot.aim_at(game.hive.halves[robot.team].aim_point(), dt)
        if mode == 'match' and game.phase in ('auto', 'teleop'):
            for a in game.ai_drivers[1:]:
                af, as_, at, al = a.step(dt, game.phase, game.time_left())
                a.r.drive(af, as_, at, dt, True)
                a.r.update_mechanisms(al, dt, True)
                a.r.spin_extras(dt)
                a.r.aim_at(game.hive.halves[a.r.team].aim_point(), dt)
        elif mode == 'match':
            for a in game.ai_drivers[1:]:
                a.r.drive(0, 0, 0, dt, False)
        game.update(dt)
        update_scoreboard()
    pad.show(f, s, t)

    if state == 'RUNNING':
        run_time += dt
    load = sum(abs(p) for p in robot.powers) / 4 + (abs(lift_in) * .5 if enabled else 0)
    battery = max(11.0, battery - (0.0004 + load * .002) * dt)
    volts = battery - load * .6

    a = driver_hub.antenna.world_position
    b = robot.hub.world_position + Vec3(0, .15, 0)
    link.update(a, b, dt, enabled)
    robot.hub.set_status(conn, state, clock)
    showcase.set_status(conn, state, clock)
    driver_hub.set_state_button(state, conn)
    if spin_showcase:
        showcase.rotation_y += 20 * dt

    dist_cm, touch, col_name, col_rgb, mag = read_sensors()
    bench.update_bench(dt, dict(
        connected=conn, state=state, clock=clock,
        drive=robot.powers[0] if enabled else 0,
        lift_in=lift_in if (enabled and robot.slides) else 0, claw_amt=robot.claw_amt,
        lift_frac=robot.lift_h / Robot.LIFT_MAX, touch=touch, mag=mag,
        color_name=col_name, color_rgb=col_rgb, dist_cm=min(dist_cm, 200)))

    if cam_mode == 'follow':
        k = min(1, 5 * dt)
        editor_cam.position = lerp(editor_cam.position, robot.world_position + Vec3(0, .6, 0), k)
        editor_cam.rotation_y = lerp_ang(editor_cam.rotation_y, robot.rotation_y, k)
        editor_cam.rotation_x = lerp(editor_cam.rotation_x, 25, k)

    tel_timer += dt
    if tel_timer > .1:
        tel_timer = 0
        p = robot.powers
        rs, bs = game.score(RED), game.score(BLUE)
        kinds = ' '.join('N' if x.kind == 'nectar' else 'P' for x in robot.store) or '-'
        driver_hub.tel.text = '\n'.join([
            f"Robot : {'CONNECTED' if conn else 'NO CONNECTION'}",
            f"Net   : FTC-{OUR_TEAM}-RC  ping {link.ping:4.1f}ms",
            f"OpMode: {'Match ' + game.phase.upper() if mode == 'match' else 'TeleOp'} [{state}]",
            f"Drive : {robot.info['drive']}",
            f"Batt  : {volts:5.2f} V   Time {run_time:5.1f}s",
            f"FL {p[0]:+.2f}   FR {p[1]:+.2f}",
            f"BL {p[2]:+.2f}   BR {p[3]:+.2f}",
            f"Head  : {robot.rotation_y % 360:6.1f} deg",
            f"Pos   : {robot.x:+5.2f}, {robot.z:+5.2f} ft",
            f"Lift  : {robot.lift_h / Robot.LIFT_MAX * 100:5.1f} %",
            f"Carry : {len(robot.store)}/4  {kinds}",
            f"Score : RED {rs['total']}  BLUE {bs['total']}",
            f"Dist  : {'>200' if dist_cm >= 200 else f'{dist_cm:4.0f}'} cm  Touch {'ON' if touch else 'off'}",
            f"Color : {col_name}  Limit {'ON' if mag else 'off'}",
        ])
        if mode == 'sim':
            msg = {'STOPPED': 'OpMode STOPPED  -  press TAB to INIT',
                   'INIT': 'OpMode INIT  -  press TAB to START',
                   'RUNNING': 'Practice - launch Pollen into your Hive until it tips!'}[state]
            col = color.lime if state == 'RUNNING' else color.yellow
            if not robot.has_hub:
                msg, col = 'Robot has no Control Hub - no Wi-Fi link (add one in ROBOT BUILD)', color.red
            elif not link.connected:
                msg, col = 'Wi-Fi LOST - robot disabled  (press C to reconnect)', color.red
            elif state == 'RUNNING' and not robot.can_drive:
                msg, col = "Robot can't drive: " + ', '.join(robot.problems), color.red
            status_hud.text, status_hud.color = msg, col
        elif mode == 'match':
            msg = {'pre': 'Match starting...', 'auto': 'AUTO: your robot runs its autonomous routine',
                   'transition': 'Get ready to drive!', 'teleop': 'TELEOP: you are driving! (SPACE launch, V intake/claw, F flower)',
                   'over': 'Match over'}.get(game.phase, '')
            status_hud.text, status_hud.color = msg, color.cyan


def input(key):
    global state, run_time, cam_mode, spin_showcase
    if key == 'b' and mode in ('sim', 'build'):
        set_mode('build' if mode == 'sim' else 'sim')
        return

    if mode == 'build':
        if key == 'left mouse down':
            bay.place()
        elif key in ('r', 't', 'f'):
            bay.rotate({'r': 'y', 't': 'x', 'f': 'z'}[key])
        elif key == 'm':
            build_ui.toggle_mirror()
        elif key in ('x', 'delete'):
            bay.delete(bay.hovered_part)
        elif key == 'g':
            pid = bay.pick_up(bay.hovered_part)
            if pid:
                build_ui.show_info(pid)
        elif key == 'escape':
            bay.select(None)
            build_ui.show_info(None)
        elif key == 'u' or (key == 'z' and held_keys['control']):
            bay.undo()
        return
    if mode not in ('sim', 'match'):
        return

    driving = state == 'RUNNING' and (mode == 'sim' or game.phase == 'teleop') and link.ok
    if key in ('space', 'gamepad a') and driving:
        game.robot_launch(robot)
    elif key in ('v', 'gamepad x') and driving:
        if robot.has_intake:
            robot.intake_on = not robot.intake_on
            toast(f"Intake {'ON' if robot.intake_on else 'OFF'}")
        elif robot.has_claw:
            game.robot_grab(robot)
        else:
            toast('No intake or claw - add one in ROBOT BUILD', color.red)
    elif key in ('f', 'gamepad y') and driving:
        game.robot_deposit(robot)
    elif key in ('g', 'gamepad b') and driving:
        game.robot_drop(robot)
    elif key == 'n' and mode == 'sim':
        b_ = game.hp[RED].give()
        if b_ is None:
            game.hp[RED].restock(5)
            b_ = game.hp[RED].give()
        game._hp_drop(RED, b_)
        toast('Human player added a Nectar to the Loading Zone')
    elif key in ('tab', 'gamepad start') and mode == 'sim':
        if not link.ok:
            return
        if state == 'STOPPED':
            state = 'INIT'
        elif state == 'INIT':
            state = 'RUNNING'
        else:
            state = 'STOPPED'
            run_time = 0
    elif key == 'c':
        link.connected = not link.connected
        if not link.connected and mode == 'sim':
            state = 'STOPPED'
    elif key == 'r' and mode == 'sim':
        game.start_practice(robot)
        toast('Field reset')
    elif key == 'h':
        spin_showcase = not spin_showcase
    elif key == '1':
        cam_mode = 'overview'
        cam_overview()
    elif key == '2':
        cam_mode = 'follow'
        set_cam(robot.world_position, (25, robot.rotation_y, 0), 6)
    elif key == '3':
        cam_mode = 'driver'
        cam_driver()
    elif key == '4':
        cam_mode = 'bench'
        cam_bench()


app.run()