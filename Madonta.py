import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys


class FTCSimulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FTC Virtual Robot Configurator & Driver Hub")
        self.root.geometry("850x650")

        # Hardware Catalog Options
        self.MOTOR_OPTIONS = ["None", "GoBilda 5203 (19.2:1)", "REV HD Hex Motor", "Matrix NeveRest 40"]
        self.SERVO_OPTIONS = ["None", "GoBilda Torque Servo (270°)", "REV Smart Robot Servo",
                              "Continuous Rotation (CR) Servo"]

        # Track configured states
        self.active_config_name = tk.StringVar(value="None")
        self.is_connected = False
        self.motor_process = None

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_widgets(self):
        # -------------------------------------------------------------
        # TOP PANEL: Connection and Hub Controls
        # -------------------------------------------------------------
        top_frame = ttk.LabelFrame(self.root, text=" ⚡ Connection Status ", padding=10)
        top_frame.pack(fill="x", padx=15, pady=10)

        self.status_label = ttk.Label(top_frame, text="Status: DISCONNECTED FROM CONTROL HUB",
                                      font=("Arial", 11, "bold"), foreground="red")
        self.status_label.pack(side="left", padx=5)

        self.connect_btn = ttk.Button(top_frame, text="Connect to Control Hub", command=self.toggle_connection)
        self.connect_btn.pack(side="right", padx=5)

        # -------------------------------------------------------------
        # MIDDLE PANEL: Split View (Control Hub vs Driver Hub)
        # -------------------------------------------------------------
        main_split = ttk.Frame(self.root)
        main_split.pack(fill="both", expand=True, padx=15, pady=5)

        # LEFT COLUMN: Virtual Control Hub Configuration
        self.config_frame = ttk.LabelFrame(main_split, text=" 🎛️ Virtual Control Hub (Port Configuration) ", padding=10)
        self.config_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ttk.Label(self.config_frame, text="Configuration Name:").grid(row=0, column=0, sticky="w", pady=5)
        self.config_name_entry = ttk.Entry(self.config_frame, width=25)
        self.config_name_entry.insert(0, "MyRobotConfig")
        self.config_name_entry.grid(row=0, column=1, sticky="w", pady=5)

        # Motor Ports (0 to 3)
        ttk.Label(self.config_frame, text="DC Motors", font=("Arial", 10, "bold")).grid(row=1, column=0, pady=(15, 2),
                                                                                        sticky="w")
        self.motor_ports = {}
        self.motor_names = {}
        for i in range(4):
            ttk.Label(self.config_frame, text=f"Port {i}:").grid(row=2 + i, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(self.config_frame, values=self.MOTOR_OPTIONS, state="readonly", width=22)
            cb.set("None" if i > 0 else "GoBilda 5203 (19.2:1)")
            cb.grid(row=2 + i, column=1, pady=2, padx=5)
            cb.bind("<<ComboboxSelected>>", self.on_hardware_changed)
            self.motor_ports[i] = cb

            ent = ttk.Entry(self.config_frame, width=15)
            ent.insert(0, f"motor_{i}" if i > 0 else "left_drive")
            ent.grid(row=2 + i, column=2, pady=2, padx=5)
            self.motor_names[i] = ent

        # Servo Ports (0 to 3)
        ttk.Label(self.config_frame, text="Servos", font=("Arial", 10, "bold")).grid(row=6, column=0, pady=(15, 2),
                                                                                     sticky="w")
        self.servo_ports = {}
        self.servo_names = {}
        for i in range(4):
            ttk.Label(self.config_frame, text=f"Port {i}:").grid(row=7 + i, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(self.config_frame, values=self.SERVO_OPTIONS, state="readonly", width=22)
            cb.set("None")
            cb.grid(row=7 + i, column=1, pady=2, padx=5)
            cb.bind("<<ComboboxSelected>>", self.on_hardware_changed)
            self.servo_ports[i] = cb

            ent = ttk.Entry(self.config_frame, width=15)
            ent.insert(0, f"servo_{i}" if i > 0 else "claw_servo")
            ent.grid(row=7 + i, column=2, pady=2, padx=5)
            self.servo_names[i] = ent

        self.save_btn = ttk.Button(self.config_frame, text="Save & Activate Configuration", command=self.save_config)
        self.save_btn.grid(row=11, column=0, columnspan=3, pady=20, sticky="ew")

        # RIGHT COLUMN: Virtual Driver Hub
        self.driver_frame = ttk.LabelFrame(main_split, text=" 📱 Virtual Driver Hub ", padding=10)
        self.driver_frame.pack(side="right", fill="both", expand=True)

        ttk.Label(self.driver_frame, text="Active Config:", font=("Arial", 10)).grid(row=0, column=0, sticky="w")
        self.active_config_lbl = ttk.Label(self.driver_frame, textvariable=self.active_config_name,
                                           font=("Arial", 10, "bold"), foreground="blue")
        self.active_config_lbl.grid(row=0, column=1, sticky="w")

        ttk.Label(self.driver_frame, text="Driver Station Telemetry:", font=("Arial", 10, "bold")).grid(row=1, column=0,
                                                                                                        columnspan=2,
                                                                                                        pady=(15, 2),
                                                                                                        sticky="w")
        self.telemetry_box = tk.Text(self.driver_frame, width=40, height=18, bg="#1e1e1e", fg="#39ff14",
                                     font=("Courier", 10))
        self.telemetry_box.grid(row=2, column=0, columnspan=2, pady=5, sticky="nsew")
        self.telemetry_box.insert("1.0", "--- Robot Stopped ---\nNo Active hardware configs initialized.")
        self.telemetry_box.config(state="disabled")

        btn_frame = ttk.Frame(self.driver_frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10, sticky="ew")

        self.init_btn = ttk.Button(btn_frame, text="INIT", state="disabled", command=self.init_robot)
        self.init_btn.pack(side="left", fill="x", expand=True, padx=2)

        self.start_btn = ttk.Button(btn_frame, text="START / STOP", state="disabled", command=self.toggle_robot_runtime)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=2)

    def toggle_connection(self):
        if not self.is_connected:
            self.is_connected = True
            self.status_label.config(text="Status: CONNECTED via Wi-Fi Direct", foreground="green")
            self.connect_btn.config(text="Disconnect Hub")
        else:
            self.is_connected = False
            self.status_label.config(text="Status: DISCONNECTED FROM CONTROL HUB", foreground="red")
            self.connect_btn.config(text="Connect to Control Hub")
            self.init_btn.config(state="disabled")
            self.start_btn.config(state="disabled")
            self.stop_motor_process()
            self.update_telemetry("--- Disconnected ---\nConnect to a Hub to begin.")

    def save_config(self):
        if not self.is_connected:
            messagebox.showwarning("Connection Error",
                                   "You must connect to the Virtual Control Hub before saving a configuration!")
            return
        name = self.config_name_entry.get().strip()
        if not name:
            messagebox.showerror("Error", "Configuration must have a valid name!")
            return
        self.active_config_name.set(name)
        self.init_btn.config(state="normal")
        self.update_telemetry(f"Configuration '{name}' saved successfully.\nReady to press INIT on Driver Hub.")
        self.on_hardware_changed()

    def init_robot(self):
        self.update_telemetry(
            "Robot Initializing...\nLaunching separate Ursina 3D Engine sub-process...\nReady. Click START.")
        self.start_btn.config(state="normal")

        if not self.motor_process:
            try:
                self.motor_process = subprocess.Popen(
                    [sys.executable, "motor_3d.py"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                # Wait briefly and synchronize the dropdown states automatically
                self.root.after(400, self.on_hardware_changed)
            except Exception as e:
                messagebox.showerror("Engine Error", f"Failed to open 3D Subprocess:\n{str(e)}")

    def send_command(self, command_str):
        if self.motor_process and self.motor_process.poll() is None:
            try:
                self.motor_process.stdin.write(f"{command_str}\n".encode())
                self.motor_process.stdin.flush()
            except (OSError, ValueError):
                pass

    def on_hardware_changed(self, event=None):
        """Notifies the running sandbox to switch models based on port selection configurations."""
        if not self.motor_process or self.motor_process.poll() is not None:
            return

        motor_selection = self.motor_ports[0].get()
        servo_selection = self.servo_ports[0].get()

        if motor_selection != "None":
            self.send_command("CONFIG_MOTOR")
        elif servo_selection != "None":
            self.send_command("CONFIG_SERVO")
        else:
            self.send_command("CONFIG_NONE")

    def toggle_robot_runtime(self):
        if not self.motor_process or self.motor_process.poll() is not None:
            self.update_telemetry("Error: 3D Engine process is not running.")
            return

        current_text = self.telemetry_box.get("1.0", "end")
        if "Status: RUNNING" in current_text:
            self.send_command("STOP")
            self.update_telemetry("Status: STOPPED\nMotor hardware standing by.")
        else:
            self.send_command("START")
            self.update_telemetry("Status: RUNNING\nTelemetry streaming alive...\nMotor rotation active.")

    def stop_motor_process(self):
        if self.motor_process:
            try:
                self.motor_process.terminate()
                self.motor_process.wait(timeout=1)
            except Exception:
                pass
            self.motor_process = None

    def update_telemetry(self, msg):
        self.telemetry_box.config(state="normal")
        self.telemetry_box.delete("1.0", "end")
        self.telemetry_box.insert("1.0", msg)
        self.telemetry_box.config(state="disabled")

    def on_close(self):
        self.stop_motor_process()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = FTCSimulatorApp(root)
    root.mainloop()
