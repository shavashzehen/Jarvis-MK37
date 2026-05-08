#!/usr/bin/env python3
"""
ULTIMATE F.R.I.D.A.Y. bootstrap dashboard.
- Auto-installs dependencies
- Dark themed GUI
- Real-time laptop health + Android ADB status syncing
"""

from __future__ import annotations

import importlib
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


def ensure_dependencies() -> None:
    required = {
        "psutil": "psutil",
        "customtkinter": "customtkinter",
    }
    missing = []
    for module_name, pip_name in required.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"[F.R.I.D.A.Y.] Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *missing])


ensure_dependencies()

import customtkinter as ctk
import psutil
import tkinter as tk
from tkinter import messagebox


@dataclass
class LaptopHealth:
    cpu: float
    ram: float
    disk: float
    temp_c: Optional[float]


@dataclass
class PhoneStatus:
    connected: bool
    device_id: str
    battery: Optional[int]
    screen_on: Optional[bool]


class FridayCore:
    def __init__(self) -> None:
        self.ui_queue: queue.Queue = queue.Queue()
        self.running = True

    @staticmethod
    def _run(cmd: list[str], timeout: int = 8) -> str:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.stdout.strip()

    def get_laptop_health(self) -> LaptopHealth:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent

        temp = None
        try:
            temps = psutil.sensors_temperatures()
            for entries in temps.values():
                if entries:
                    temp = float(entries[0].current)
                    break
        except Exception:
            temp = None

        return LaptopHealth(cpu=cpu, ram=ram, disk=disk, temp_c=temp)

    def get_phone_status(self) -> PhoneStatus:
        try:
            lines = self._run(["adb", "devices"]).splitlines()
            devices = [ln.split()[0] for ln in lines[1:] if "\tdevice" in ln]
            if not devices:
                return PhoneStatus(False, "Disconnected", None, None)

            device = devices[0]
            battery = None
            screen_on = None

            battery_info = self._run(["adb", "-s", device, "shell", "dumpsys", "battery"])
            for line in battery_info.splitlines():
                if "level:" in line:
                    battery = int(line.split(":")[-1].strip())
                    break

            power_info = self._run(["adb", "-s", device, "shell", "dumpsys", "power"])
            for line in power_info.splitlines():
                if "Display Power" in line and "state=" in line:
                    state = line.split("state=")[-1].split()[0].strip()
                    screen_on = state.upper().startswith("ON")
                    break

            return PhoneStatus(True, device, battery, screen_on)
        except Exception:
            return PhoneStatus(False, "ADB unavailable", None, None)

    def sentinel_scan(self, health: LaptopHealth, phone: PhoneStatus) -> list[str]:
        alerts = []
        if health.cpu > 92:
            alerts.append("CPU spike detected (>92%).")
        if health.ram > 90:
            alerts.append("RAM critically high (>90%).")
        if health.temp_c is not None and health.temp_c > 88:
            alerts.append("Thermal alert (>88°C).")
        if phone.connected and phone.battery is not None and phone.battery < 12:
            alerts.append("Phone battery critically low (<12%).")
        if not phone.connected:
            alerts.append("Android device disconnected or ADB not available.")
        return alerts

    def self_heal(self, alerts: list[str]) -> str:
        actions = []
        for item in alerts:
            if "CPU spike" in item or "RAM critically" in item:
                actions.append("Suggested fix: close heavy background processes.")
            if "Thermal alert" in item:
                actions.append("Suggested fix: reduce workload and verify cooling.")
            if "battery" in item:
                actions.append("Suggested fix: plug phone into power source.")
            if "disconnected" in item:
                actions.append("Suggested fix: run `adb kill-server && adb start-server` and reconnect USB/Wi-Fi ADB.")
        return " | ".join(sorted(set(actions))) if actions else "All systems nominal."


class FridayDashboard(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("F.R.I.D.A.Y. — Master Control")
        self.geometry("1100x760")
        self.minsize(980, 700)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.core = FridayCore()

        self._build_ui()
        self._start_background_sync()
        self.after(300, self._process_queue)
        self.protocol("WM_DELETE_WINDOW", self._shutdown)

    def _build_ui(self) -> None:
        header = ctk.CTkLabel(self, text="F.R.I.D.A.Y. Autonomous Sentinel", font=("Segoe UI", 28, "bold"))
        header.pack(pady=(20, 10))

        body = ctk.CTkFrame(self, corner_radius=16)
        body.pack(fill="both", expand=True, padx=20, pady=12)

        self.laptop_label = ctk.CTkLabel(body, text="Laptop Health: initializing...", anchor="w", font=("Consolas", 16))
        self.laptop_label.pack(fill="x", padx=16, pady=(16, 8))

        self.phone_label = ctk.CTkLabel(body, text="Phone Status: initializing...", anchor="w", font=("Consolas", 16))
        self.phone_label.pack(fill="x", padx=16, pady=8)

        self.alert_label = ctk.CTkLabel(body, text="Sentinel Alerts: none", anchor="w", font=("Consolas", 15), text_color="#8be9fd")
        self.alert_label.pack(fill="x", padx=16, pady=8)

        self.heal_label = ctk.CTkLabel(body, text="Self-Heal Plan: pending", anchor="w", font=("Consolas", 14), text_color="#f1fa8c")
        self.heal_label.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(body, text="Command Console", font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=16, pady=(18, 8))

        self.command_input = ctk.CTkEntry(body, placeholder_text="Enter ADB/PowerShell-safe command request...", height=36)
        self.command_input.pack(fill="x", padx=16, pady=8)

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=(4, 10))

        ctk.CTkButton(buttons, text="Execute", command=self._execute_command, width=120).pack(side="left", padx=(0, 8))
        ctk.CTkButton(buttons, text="Run ADB Reset", command=self._adb_reset, width=150).pack(side="left", padx=8)

        self.log = ctk.CTkTextbox(body, height=260)
        self.log.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self._write_log("F.R.I.D.A.Y. online. Monitoring initiated.")

    def _write_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")

    def _start_background_sync(self) -> None:
        def worker() -> None:
            while self.core.running:
                health = self.core.get_laptop_health()
                phone = self.core.get_phone_status()
                alerts = self.core.sentinel_scan(health, phone)
                heal = self.core.self_heal(alerts)
                self.core.ui_queue.put((health, phone, alerts, heal))
                time.sleep(3)

        threading.Thread(target=worker, daemon=True).start()

    def _process_queue(self) -> None:
        try:
            while True:
                health, phone, alerts, heal = self.core.ui_queue.get_nowait()
                temp = f"{health.temp_c:.1f}°C" if health.temp_c is not None else "N/A"
                self.laptop_label.configure(text=f"Laptop Health | CPU: {health.cpu:.1f}% | RAM: {health.ram:.1f}% | Disk: {health.disk:.1f}% | Temp: {temp}")

                self.phone_label.configure(
                    text=(
                        f"Phone Status | Connected: {phone.connected} | Device: {phone.device_id} "
                        f"| Battery: {phone.battery if phone.battery is not None else 'N/A'}% "
                        f"| Screen On: {phone.screen_on if phone.screen_on is not None else 'N/A'}"
                    )
                )

                if alerts:
                    self.alert_label.configure(text=f"Sentinel Alerts: {' ; '.join(alerts)}", text_color="#ff5555")
                    self._write_log("ALERT: " + " | ".join(alerts))
                else:
                    self.alert_label.configure(text="Sentinel Alerts: none", text_color="#50fa7b")

                self.heal_label.configure(text=f"Self-Heal Plan: {heal}")
        except queue.Empty:
            pass
        self.after(500, self._process_queue)

    def _execute_command(self) -> None:
        cmd = self.command_input.get().strip()
        if not cmd:
            return

        destructive_keywords = {"rm ", "del ", "format", "wipe", "shutdown", "reboot", "factory reset"}
        if any(key in cmd.lower() for key in destructive_keywords):
            confirmed = messagebox.askyesno(
                "Confirmation Shield",
                "Master Shawez, this action is irreversible. Should I proceed?",
            )
            if not confirmed:
                self._write_log("Destructive command cancelled by Confirmation Shield.")
                return

        try:
            output = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            msg = output.stdout.strip() or output.stderr.strip() or "Command completed with no output."
            self._write_log(f"Command: {cmd}\n{msg}")
        except Exception as exc:
            self._write_log(f"Command failed: {exc}")

    def _adb_reset(self) -> None:
        try:
            subprocess.run(["adb", "kill-server"], capture_output=True, text=True)
            subprocess.run(["adb", "start-server"], capture_output=True, text=True)
            self._write_log("ADB server reset completed.")
        except Exception as exc:
            self._write_log(f"ADB reset failed: {exc}")

    def _shutdown(self) -> None:
        self.core.running = False
        self.destroy()


if __name__ == "__main__":
    app = FridayDashboard()
    app.mainloop()
