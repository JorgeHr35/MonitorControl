import sys
import os
import json
import socket
import subprocess
import shutil
from pathlib import Path

import requests
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QComboBox, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QLabel, QDialog, QDialogButtonBox,
    QHeaderView, QAbstractItemView, QTextEdit, QGroupBox, QSpinBox
)

APP_NAME = "MonitorControl"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
TOKEN_DIR = APP_DIR / "tokens"
APP_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "devices.db"

BRANDS = ["Samsung", "LG", "Roku", "Android TV", "Fire TV"]


def db_connect():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT NOT NULL,
            ip TEXT NOT NULL,
            token_json TEXT DEFAULT '{}',
            UNIQUE(brand, ip)
        )
    """)
    conn.commit()
    return conn


def load_devices():
    with db_connect() as conn:
        return conn.execute("SELECT * FROM devices ORDER BY name COLLATE NOCASE").fetchall()


def save_device(device_id, name, brand, ip):
    with db_connect() as conn:
        if device_id is None:
            conn.execute(
                "INSERT INTO devices(name, brand, ip, token_json) VALUES(?,?,?,'{}')",
                (name, brand, ip)
            )
        else:
            conn.execute(
                "UPDATE devices SET name=?, brand=?, ip=? WHERE id=?",
                (name, brand, ip, device_id)
            )
        conn.commit()


def delete_device(device_id):
    with db_connect() as conn:
        conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
        conn.commit()
    token_path = TOKEN_DIR / f"samsung_{device_id}.txt"
    try:
        token_path.unlink()
    except FileNotFoundError:
        pass


def save_lg_token(device_id, token):
    with db_connect() as conn:
        conn.execute("UPDATE devices SET token_json=? WHERE id=?",
                     (json.dumps(token), device_id))
        conn.commit()


def get_samsung_token_path(device_id):
    return TOKEN_DIR / f"samsung_{device_id}.txt"


def validate_ip(ip):
    try:
        socket.inet_pton(socket.AF_INET, ip)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        return True
    except OSError:
        return False


class DeviceError(Exception):
    pass


def samsung_action(device, action):
    try:
        from samsungtvws import SamsungTVWS
    except ImportError as exc:
        raise DeviceError("Falta samsungtvws.") from exc

    token_file = str(get_samsung_token_path(device["id"]))
    remote = SamsungTVWS(host=device["ip"], port=8002, token_file=token_file, timeout=8, name="MonitorControl")
    try:
        remote.open()
        if action in ["key", "right"]: remote.send_key("KEY_RIGHT")
        elif action == "up": remote.send_key("KEY_CHUP")
        elif action == "down": remote.send_key("KEY_CHDOWN")
        return "Conexión Samsung abierta correctamente." if action == "test" else f"Orden {action.upper()} enviada a Samsung."
    except Exception as exc:
        raise DeviceError(f"Samsung rechazó la conexión: {exc}") from exc
    finally:
        try: remote.close()
        except Exception: pass


def lg_action(device, action):
    try:
        from aiowebostv import WebOsClient
        import asyncio
    except ImportError as exc:
        raise DeviceError("Falta aiowebostv. Instala con: pip install aiowebostv") from exc

    try: 
        store = json.loads(device["token_json"] or "{}")
        client_key = store.get("client_key")
    except (ValueError, TypeError): 
        client_key = None

    async def run_lg():
        client = WebOsClient(device["ip"], client_key=client_key)
        try:
            await client.connect()
            
            # Si generó un token nuevo (primera vez o se borró), lo guardamos en la base de datos
            if client.client_key and client.client_key != client_key:
                save_lg_token(device["id"], {"client_key": client.client_key})
                
            if action == "test": 
                return "Conexión LG establecida. Emparejamiento listo."
            
            if action == "up":
                await client.channel_up()
            elif action == "down":
                await client.channel_down()
            elif action in ["key", "right"]:
                # La tecla de prueba manual enviará un cambio de canal arriba como test visual seguro
                await client.channel_up()
                
            return f"Orden {action.upper()} enviada a LG."
        except Exception as exc:
            raise DeviceError(f"LG rechazó la conexión: {exc}")
        finally:
            await client.disconnect()

    # Ejecuta el bloque asíncrono dentro del hilo actual
    return asyncio.run(run_lg())


def roku_action(device, action):
    base = f"http://{device['ip']}:8060"
    try:
        if action == "test":
            response = requests.get(base + "/query/device-info", timeout=5)
            response.raise_for_status()
            return "Roku ECP respondió correctamente."
        
        key_cmd = "Right"
        if action == "up": key_cmd = "Up"
        if action == "down": key_cmd = "Down"
        
        response = requests.post(base + f"/keypress/{key_cmd}", timeout=5)
        response.raise_for_status()
        return f"Orden {key_cmd} enviada por Roku ECP."
    except Exception as exc:
        raise DeviceError(f"Roku no respondió por ECP: {exc}") from exc


def android_action(device, action):
    # Primero busca en el sistema (PATH)
    adb = shutil.which("adb")
    
    # Si no lo encuentra, busca explícitamente en la misma carpeta que main.py
    if not adb:
        local_adb = Path(__file__).parent / "adb.exe"
        if local_adb.exists():
            adb = str(local_adb)
        else:
            raise DeviceError("No se encontró adb.exe en el sistema ni en la carpeta del programa.")
        
    target = f"{device['ip']}:5555"
    try:
        result = subprocess.run([adb, "connect", target], capture_output=True, text=True, timeout=8)
        output = (result.stdout + result.stderr).strip()
        if "unable" in output.lower() or "failed" in output.lower():
            raise DeviceError(f"ADB no pudo conectar: {output}")
            
        if action == "test": return "Comando ADB ejecutado: conexión solicitada."
        
        key_cmd = "KEYCODE_DPAD_RIGHT"
        if action == "up": key_cmd = "KEYCODE_CHANNEL_UP"
        if action == "down": key_cmd = "KEYCODE_CHANNEL_DOWN"

        key_result = subprocess.run([adb, "-s", target, "shell", "input", "keyevent", key_cmd], capture_output=True, text=True, timeout=8)
        if key_result.returncode != 0: raise DeviceError("ADB no aceptó la tecla.")
        return f"Orden {key_cmd} enviada por ADB."
    except subprocess.TimeoutExpired as exc:
        raise DeviceError("ADB agotó el tiempo de espera.") from exc


def run_device_action(device, action):
    brand = device["brand"]
    if brand == "Samsung": return samsung_action(device, action)
    if brand == "LG": return lg_action(device, action)
    if brand == "Roku": return roku_action(device, action)
    if brand in ["Android TV", "Fire TV"]: return android_action(device, action)
    raise DeviceError(f"Marca no soportada: {brand}")


class ActionWorker(QThread):
    finished_result = Signal(int, str, bool, str)

    def __init__(self, device, action):
        super().__init__()
        self.device = dict(device)
        self.action = action

    def run(self):
        try:
            message = run_device_action(self.device, self.action)
            self.finished_result.emit(self.device["id"], self.device["name"], True, message)
        except Exception as exc:
            self.finished_result.emit(self.device["id"], self.device["name"], False, str(exc))


class DeviceDialog(QDialog):
    def __init__(self, parent=None, device=None):
        super().__init__(parent)
        self.setWindowTitle("Editar dispositivo" if device else "Añadir dispositivo")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(device["name"] if device else "")
        self.brand_combo = QComboBox()
        self.brand_combo.addItems(BRANDS)
        self.ip_edit = QLineEdit(device["ip"] if device else "")
        self.ip_edit.setPlaceholderText("Ej. 192.168.1.50")
        if device: self.brand_combo.setCurrentText(device["brand"])
        form.addRow("Nombre:", self.name_edit)
        form.addRow("Marca:", self.brand_combo)
        form.addRow("Dirección IP:", self.ip_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self): return self.name_edit.text().strip(), self.brand_combo.currentText(), self.ip_edit.text().strip()

    def accept(self):
        name, brand, ip = self.values()
        if not name or not validate_ip(ip):
            QMessageBox.warning(self, "Error", "Verifica el nombre y la IP.")
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitor Control")
        self.resize(950, 600)
        
        self.workers = []
        self.active_tasks = 0

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QLabel("Monitor Control")
        header.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Nombre", "Marca", "IP", "Direction", "Status", "Resultado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Añadir")
        self.edit_btn = QPushButton("Editar")
        self.delete_btn = QPushButton("Eliminar")
        self.test_btn = QPushButton("Probar conexión manual")
        for button in (self.add_btn, self.edit_btn, self.delete_btn, self.test_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        auto_group = QGroupBox("Control Automático (Lee la tabla de arriba)")
        auto_layout = QHBoxLayout(auto_group)
        
        auto_layout.addWidget(QLabel("Intervalo (segundos):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(15)
        auto_layout.addWidget(self.interval_spin)

        self.auto_btn = QPushButton("Iniciar Cambio Automático")
        self.auto_btn.setCheckable(True)
        auto_layout.addWidget(self.auto_btn)
        layout.addWidget(auto_group)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(105)
        self.log.setPlaceholderText("Registro de actividad…")
        layout.addWidget(self.log)

        self.add_btn.clicked.connect(self.add_device)
        self.edit_btn.clicked.connect(self.edit_device)
        self.delete_btn.clicked.connect(self.remove_device)
        self.test_btn.clicked.connect(self.manual_test_action)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.trigger_auto_action)
        self.auto_btn.toggled.connect(self.toggle_auto)

        self.refresh_table()

    def refresh_table(self):
        devices = load_devices()
        self.table.setRowCount(0)
        for device in devices:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            item_name = QTableWidgetItem(device["name"])
            item_name.setData(Qt.ItemDataRole.UserRole, device["id"])
            self.table.setItem(row, 0, item_name)
            
            self.table.setItem(row, 1, QTableWidgetItem(device["brand"]))
            self.table.setItem(row, 2, QTableWidgetItem(device["ip"]))
            
            dir_combo = QComboBox()
            dir_combo.addItems(["Up", "Down"])
            self.table.setCellWidget(row, 3, dir_combo)
            
            status_combo = QComboBox()
            status_combo.addItems(["Active", "Inactive"])
            self.table.setCellWidget(row, 4, status_combo)
            
            self.table.setItem(row, 5, QTableWidgetItem("Sin probar"))

    def selected_devices(self):
        selected_items = self.table.selectedItems()
        if not selected_items: return []
        rows = set(item.row() for item in selected_items)
        devices = []
        loaded = load_devices()
        for row in rows:
            device_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for d in loaded:
                if d["id"] == device_id:
                    devices.append(d)
                    break
        return devices

    def add_device(self):
        dialog = DeviceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, brand, ip = dialog.values()
            try: save_device(None, name, brand, ip)
            except Exception: return
            self.refresh_table()

    def edit_device(self):
        devs = self.selected_devices()
        if len(devs) != 1: return QMessageBox.warning(self, "Aviso", "Selecciona solo 1 dispositivo.")
        dialog = DeviceDialog(self, devs[0])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, brand, ip = dialog.values()
            try: save_device(devs[0]["id"], name, brand, ip)
            except Exception: return
            self.refresh_table()

    def remove_device(self):
        devs = self.selected_devices()
        if len(devs) != 1: return QMessageBox.warning(self, "Aviso", "Selecciona solo 1 dispositivo.")
        if QMessageBox.question(self, "Confirmar", f"¿Eliminar {devs[0]['name']}?") == QMessageBox.StandardButton.Yes:
            delete_device(devs[0]["id"])
            self.refresh_table()

    def manual_test_action(self):
        if self.active_tasks > 0: return
        devices = self.selected_devices()
        if not devices: return QMessageBox.warning(self, "Aviso", "Selecciona dispositivos para probar.")
        
        self.set_busy(True)
        self.workers = [w for w in self.workers if w.isRunning()]
        for device in devices:
            self.log.append(f"Probando: {device['name']}...")
            worker = ActionWorker(device, "test")
            worker.finished_result.connect(self.on_action_finished)
            self.workers.append(worker)
            self.active_tasks += 1
            worker.start()

    def toggle_auto(self, checked):
        if checked:
            interval_ms = self.interval_spin.value() * 1000
            self.timer.start(interval_ms)
            self.auto_btn.setText("Detener Cambio Automático")
            self.auto_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
            self.log.append(f"--- Modo Automático Activado ({self.interval_spin.value()}s) ---")
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            self.trigger_auto_action()
        else:
            self.timer.stop()
            self.auto_btn.setText("Iniciar Cambio Automático")
            self.auto_btn.setStyleSheet("")
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.log.append("--- Modo Automático Detenido ---")

    def trigger_auto_action(self):
        if self.active_tasks > 0:
            return
            
        devices_to_process = []
        loaded = load_devices()
        
        for row in range(self.table.rowCount()):
            status_widget = self.table.cellWidget(row, 4)
            if status_widget and status_widget.currentText() == "Active":
                dir_widget = self.table.cellWidget(row, 3)
                action = "up" if dir_widget.currentText() == "Up" else "down"
                
                device_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                device = next((d for d in loaded if d["id"] == device_id), None)
                if device:
                    devices_to_process.append((device, action))
                    
        if not devices_to_process:
            self.log.append("No hay dispositivos con el estado 'Active'.")
            return
            
        self.set_busy(True)
        self.workers = [w for w in self.workers if w.isRunning()]
        
        for device, action in devices_to_process:
            worker = ActionWorker(device, action)
            worker.finished_result.connect(self.on_action_finished)
            self.workers.append(worker)
            self.active_tasks += 1
            worker.start()

    def set_busy(self, busy):
        for button in (self.add_btn, self.edit_btn, self.delete_btn, self.test_btn):
            button.setEnabled(not busy)

    def on_action_finished(self, device_id, name, success, message):
        self.active_tasks -= 1
        if self.active_tasks <= 0:
            self.active_tasks = 0
            self.set_busy(False)
            
        status = "OK" if success else "ERROR"
        if not self.auto_btn.isChecked() or not success:
            self.log.append(f"[{status}] {name}: {message}")
            
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == device_id:
                self.table.item(row, 5).setText("OK" if success else "Error")
                break


def main():
    db_connect().close()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()