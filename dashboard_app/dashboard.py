import asyncio
import logging
from nicegui import context, ui, app, events
from eg4_bms import EG4BMS, scan_for_batteries
from litime_bms import LiTimeBMS
from models import BatteryData
from typing import Dict, List, Optional
from datetime import datetime
import json
import os

# 1. CORE CONFIG & LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dashboard")

def get_config_path():
    return os.environ.get('LITHIUM_CONFIG_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'batteries_config.json'))

# 2. STATE MODELS
class BatteryState:
    def __init__(self, name: str, address: str, bms_type: str):
        self.name = name
        self.address = address
        self.bms_type = bms_type
        self.bms = None
        self.data = BatteryData()
        self.connected = False
        self.last_update = "Never"
        self.initial_sync = False 
        self.local_status = "INITIALIZING..."
        self.busy = False

class ClientState:
    def __init__(self):
        self.selected_mac = None

class AppState:
    def __init__(self):
        self.batteries: Dict[str, BatteryState] = {}
        self._devices = []
        self.device_options = {}
        self.scanning = False
        self.adding = False
        self.status_msg = "READY"
        self.clients: Dict[str, ClientState] = {} 

    @property
    def devices(self): return self._devices
    @devices.setter
    def devices(self, val):
        self._devices = val
        self.device_options = {d.address: f"{(d.name if d.name else 'Unknown')} ({d.address})" for d in val}

state = AppState()

# 3. UTILITIES
def get_cell_logic(voltages: List[float], idx: int):
    v = voltages[idx] if idx < len(voltages) else 0
    active = [cv for cv in voltages if cv > 0.5]
    avg = sum(active)/len(active) if active else 0
    return v, v <= 0.5, (v > 0.5 and abs(v - avg) > 0.1)

def get_status_info(current: float):
    if current > 0.2: return "CHARGING", "text-emerald-400", "bolt"
    if current < -0.2: return "DISCHARGING", "text-rose-400", "vertical_align_bottom"
    return "IDLE", "text-slate-500", "pause"

def get_soc_color(soc):
    if soc < 20: return "#f43f5e"
    if soc < 50: return "#f59e0b"
    return "#10b981"

def power_rail(bat, height='12px'):
    c = get_soc_color(bat.data.soc)
    with ui.element('div').classes('w-full rounded-full bg-slate-900 border border-slate-800 relative overflow-hidden').style(f'height: {height}'):
        fill = ui.element('div').classes('h-full transition-all duration-1000 relative')
        if bat.initial_sync: fill.style(f"width: {bat.data.soc}%; background: {c}; box-shadow: 0 0 20px {c}80;")
        ui.element('div').classes('absolute inset-0 w-full h-full').style('background-image: linear-gradient(90deg, transparent 80%, #020617 80%); background-size: 5% 100%;')

# 4. PERSISTENCE
config_lock = asyncio.Lock()
async def _atomic_save():
    async with config_lock:
        path = get_config_path()
        data = [{'mac': mac, 'bms_type': b.bms_type, 'name': b.name} for mac, b in state.batteries.items()]
        temp_file = path + '.tmp'
        try:
            with open(temp_file, 'w') as f: json.dump(data, f)
            if os.path.exists(path): os.remove(path)
            os.rename(temp_file, path)
        except Exception as e: logger.error(f"Save failed: {e}")

def save_config(): asyncio.create_task(_atomic_save())
def load_config():
    path = get_config_path()
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: return json.load(f)
        except Exception as e: logger.error(f"Load failed: {e}")
    return []

# 5. REFRESH & ACTION HANDLERS
def select_battery(mac):
    try:
        client_id = context.get_client().id
        if client_id not in state.clients: state.clients[client_id] = ClientState()
        state.clients[client_id].selected_mac = mac
        layout.refresh() # Targeted refresh for specific client
    except RuntimeError: pass

def broadcast_refresh():
    # Only refreshable functions can be broadcasted like this
    layout.refresh()

def remove_battery(mac):
    if mac in state.batteries:
        bat = state.batteries[mac]
        if bat.bms: asyncio.create_task(bat.bms.disconnect())
        del state.batteries[mac]; save_config(); broadcast_refresh()

# 6. BMS DRIVER INTEGRATION
def bms_callback(mac, data):
    bat = state.batteries.get(mac)
    if not bat: return
    was_synced = bat.initial_sync
    bat.initial_sync = True; bat.connected = True; bat.local_status = "LIVE"
    bat.data.voltage = data.voltage; bat.data.current = data.current
    bat.data.power_w = data.voltage * data.current
    bat.data.cell_voltages[:] = data.cell_voltages; bat.data.temp_env = data.temp_env; bat.data.temp_mos = data.temp_mos
    bat.data.soc = data.soc; bat.data.soh = data.soh; bat.data.cycles = data.cycles
    bat.data.status = data.status; bat.data.raw_hex = data.raw_hex
    bat.last_update = datetime.now().strftime('%H:%M:%S')
    if not was_synced: broadcast_refresh()

async def polling_loop():
    while True:
        try:
            # Poll or reconnect EVERY battery in the system
            tasks = [poll_battery(bat) for bat in state.batteries.values() if not bat.busy]
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e: logger.error(f"Polling loop error: {e}")
        await asyncio.sleep(4)

async def poll_battery(bat):
    bat.busy = True
    try:
        # 1. Initialize BMS if type is already known (Auto-Detect waits until after probing)
        if not bat.bms and bat.bms_type != 'Auto-Detect':
            from eg4_bms import EG4BMS
            from litime_bms import LiTimeBMS
            bms_class = EG4BMS if 'EG4' in bat.bms_type else LiTimeBMS
            bat.bms = bms_class(bat.address)
            bat.bms.on_data_callback = lambda d, m=bat.address: bms_callback(m, d)

        # 2. Handle connection/reconnection
        if not bat.connected:
            try:
                if bat.bms_type == 'Auto-Detect':
                    bat.local_status = "PROBING..."
                    from bleak import BleakClient
                    async with BleakClient(bat.address, timeout=5.0) as client:
                        svcs = [s.uuid.lower() for s in client.services]
                        bat.bms_type = 'LiTime/Redodo' if any("ffe0" in s for s in svcs) else 'EG4'
                    # Re-init bms with correct class if type was determined
                    bms_class = EG4BMS if 'EG4' in bat.bms_type else LiTimeBMS
                    bat.bms = bms_class(bat.address)
                    bat.bms.on_data_callback = lambda d, m=bat.address: bms_callback(m, d)

                bat.local_status = "CONNECTING..."
                await asyncio.wait_for(bat.bms.connect(), timeout=10.0)
                bat.connected = True
                bat.local_status = "SYNCING..."
                if 'LiTime' in bat.bms_type:
                    try:
                        meta = await bat.bms.fetch_metadata()
                        if meta.get("model"): bat.name = f"{meta['model']} ({bat.address[-5:]})"
                    except Exception: pass
                save_config()
            except Exception as e:
                bat.local_status = "CONN ERROR"
                bat.connected = False
                return

        # 3. Normal Polling
        try:
            await asyncio.wait_for(bat.bms.poll(), timeout=5.0)
        except Exception as e:
            bat.connected = False
            bat.local_status = "LINK TIMEOUT"
    finally:
        bat.busy = False

async def do_scan(device_sel_component=None):
    state.scanning = True; state.status_msg = "SCANNING..."
    try:
        state.devices = await scan_for_batteries()
        if device_sel_component:
            device_sel_component.options = state.device_options
            device_sel_component.update()
        state.status_msg = f"FOUND {len(state.devices)} SOURCES"
    except Exception: state.status_msg = "SCAN FAILED"
    finally: 
        state.scanning = False
        broadcast_refresh()

async def provision_node_task(mac, btype, name):
    if mac in state.batteries: return
    state.adding = True
    try:
        bat = BatteryState(name, mac, btype); state.batteries[mac] = bat
        save_config(); broadcast_refresh()
        await poll_battery(bat)
    finally:
        state.adding = any(not b.initial_sync for b in state.batteries.values())
        broadcast_refresh()

async def add_battery_logic(mac, btype):
    if not mac or mac in state.batteries: return
    name = "New Battery"
    for d in state.devices:
        if d.address == mac: name = d.name if d.name else "Unknown"; break
    asyncio.create_task(provision_node_task(mac, btype, name))

# 7. UI SUB-COMPONENTS
@ui.refreshable
def connected_list_ui():
    try: client_id = context.get_client().id
    except RuntimeError: return 
    cs = state.clients.get(client_id); sel = cs.selected_mac if cs else None
    with ui.column().classes('w-full gap-4'):
        ui.label('POWER SOURCES').classes('text-[10px] font-black text-slate-600 tracking-[0.4em] mb-2')
        for mac, bat in state.batteries.items():
            bg = 'bg-slate-800 ring-1 ring-cyan-500/50 shadow-2xl' if sel == mac else 'bg-slate-900/40'
            with ui.card().classes(f'w-full min-h-[100px] p-6 cursor-pointer rounded-3xl transition-all border-0 hover:scale-[1.02] {bg}').on('click', lambda m=mac: select_battery(m)):
                with ui.row().classes('w-full items-center no-wrap gap-2'):
                    ui.label(bat.name.split('(')[0]).classes('font-black text-lg text-slate-100 truncate flex-1')
                    with ui.row().classes('items-center shrink-0'):
                        ui.button(icon='refresh').on('click.stop', lambda e, b=bat: asyncio.create_task(poll_battery(b))).props('flat dense size=sm color=cyan-800')
                        ui.button(icon='close').on('click.stop', lambda e, m=mac: remove_battery(m)).props('flat dense size=sm color=slate-600')
                with ui.row().classes('w-full justify-between items-center mt-1'):
                    ui.label(bat.bms_type.split('/')[0].upper()).classes('text-[9px] font-black text-cyan-500/60 tracking-widest')
                    if bat.initial_sync: 
                        with ui.column().classes('items-end gap-0'):
                            _, color, icon = get_status_info(bat.data.current)
                            with ui.row().classes('items-center gap-1'):
                                ui.label().bind_text_from(bat.data, 'temp_env', backward=lambda t: f"{t}°C").classes('text-[9px] font-bold text-amber-500/80 mr-1')
                                ui.label().bind_text_from(bat.data, 'power_w', backward=lambda p: f"{abs(p):.0f}W").classes(f'text-[10px] font-bold {color}')
                                ui.icon(icon, size='10px').classes(color)
                            ui.label().bind_text_from(bat.data, 'soc', backward=lambda s: f"{s}%").classes('text-2xl font-black text-white tracking-tighter')
                    else: ui.label().bind_text_from(bat, 'local_status').classes('text-[9px] font-black text-slate-500 animate-pulse')

def node_card(mac, bat):
    data = bat.data
    with ui.card().classes('p-6 md:p-8 transition-all cursor-pointer border-0 rounded-[2rem] bg-slate-900/50 backdrop-blur-xl shadow-2xl hover:scale-[1.02]').on('click', lambda m=mac: select_battery(m)):
        if not bat.initial_sync:
            with ui.column().classes('w-full items-center justify-center py-6 md:py-10 gap-4'):
                ui.spinner(size='3rem', color='cyan-500', thickness=2); ui.label().bind_text_from(bat, 'local_status').classes('text-[10px] font-black text-cyan-500 animate-pulse')
            return
        txt, color, icon = get_status_info(data.current)
        with ui.row().classes('w-full justify-between items-start'):
            with ui.column().classes('gap-0'):
                ui.label(bat.name.split('(')[0]).classes('font-black text-xl md:text-2xl text-slate-100 truncate flex-1')
                ui.label(bat.bms_type.upper()).classes('text-[8px] md:text-[10px] font-black text-cyan-500 tracking-widest')    
            with ui.row().classes(f'items-center gap-1 {color} mt-1'):
                ui.icon(icon, size='12px'); ui.label(txt).classes('text-[8px] font-black tracking-widest')
        with ui.row().classes('w-full items-center gap-4 my-4 md:my-8 no-wrap'):
            ui.label().bind_text_from(data, 'soc', backward=lambda s: f"{s}%").classes('text-5xl md:text-7xl font-black text-white tracking-tighter')
            with ui.column().classes('flex-1 gap-2 min-w-0'):
                power_rail(bat, '8px')
                with ui.row().classes('w-full justify-between px-1'):
                    ui.label().bind_text_from(data, 'voltage', backward=lambda v: f"{v:.2f}V").classes('font-mono text-slate-400 font-bold text-[10px]')
                    ui.label().bind_text_from(data, 'power_w', backward=lambda p: f"({abs(p):.0f}W)").classes('text-[8px] font-black text-slate-600')

# 8. LAYOUT TEMPLATES
def sidebar_content():
    ui.label('DISCOVERY').classes('text-[10px] font-black text-slate-500 tracking-[0.3em] mb-4')
    dev_sel = ui.select(options=state.device_options, label='SELECT SOURCE').classes('w-full mb-4').props('dark outlined dense')
    def sync_options():
        if dev_sel.options != state.device_options: dev_sel.options = state.device_options; dev_sel.update()
    ui.timer(1.0, sync_options)
    bms_sel = ui.select(options=['Auto-Detect', 'EG4', 'LiTime/Redodo'], value='Auto-Detect').classes('w-full mb-4').props('dark outlined dense')
    with ui.row().classes('w-full gap-3 mb-8'):
        with ui.button(on_click=lambda: asyncio.create_task(do_scan(dev_sel))).props('unelevated color=cyan-10').classes('flex-1 font-black rounded-2xl h-14'):
            ui.label('SCAN').bind_visibility_from(state, 'scanning', backward=lambda s: not s); ui.spinner(color='white', size='sm').bind_visibility_from(state, 'scanning')
        ui.button('ADD', on_click=lambda: asyncio.create_task(add_battery_logic(dev_sel.value, bms_sel.value))).props('unelevated color=indigo-10').classes('flex-1 font-black rounded-2xl h-14')
    connected_list_ui()

def detail_view_content(bat):
    data = bat.data; txt, color, icon = get_status_info(data.current)
    with ui.column().classes('w-full p-4 md:p-10 gap-6'):
        with ui.row().classes('items-center gap-4 w-full no-wrap'):
            ui.button(icon='chevron_left', on_click=lambda: select_battery(None)).props('round unelevated color=slate-900 shadow-none').classes('shrink-0')
            ui.label(bat.name.split('(')[0]).classes('text-2xl md:text-5xl font-black text-white tracking-tighter flex-1 truncate')
            with ui.row().classes(f'items-center gap-1 bg-slate-900/40 px-3 py-1 rounded-xl border border-slate-800 shrink-0'):
                ui.icon(icon, size='14px').classes(color); ui.label(txt).classes(f'text-[8px] font-black tracking-[0.1em] {color}')
        ui.label().bind_text_from(bat, 'last_update', backward=lambda t: f"SYNC: {t}").classes('font-mono text-slate-600 text-[9px] tracking-widest px-2')
        with ui.row().classes('w-full gap-4 md:gap-10 items-stretch md:flex-row flex-col'):
            with ui.card().classes('w-full md:w-[450px] items-center justify-center p-6 bg-slate-900/40 rounded-[2rem] border border-slate-900 shadow-none shrink-0'):
                with ui.column().classes('items-center'):
                    ui.label().bind_text_from(data, 'soc', backward=lambda s: f"{s}%").classes('text-8xl md:text-[10rem] font-black text-white leading-none')
                    ui.label().bind_text_from(data, 'soh', backward=lambda s: f"SOH {s}% HEALTH").classes('text-[10px] font-black text-emerald-500 tracking-[0.3em] mt-2')
                with ui.column().classes('w-full mt-6 gap-2'): power_rail(bat, '12px'); ui.label('CHARGE LEVEL').classes('text-[7px] font-black text-slate-700 text-center')
            with ui.grid(columns=2).classes('w-full md:flex-1 gap-3 shrink-0'):
                for l, attr, c_cls in [('VOLTAGE', 'voltage', 'text-slate-100'), ('CURRENT', 'current', 'text-cyan-400'), ('TEMP', 'temp_env', 'text-amber-400'), ('CYCLES', 'cycles', 'text-indigo-400')]:
                    with ui.card().classes('p-4 bg-slate-900/40 rounded-[1.5rem] border border-slate-900 items-center justify-center'):
                        ui.label(l).classes('text-slate-600 font-black text-[8px] tracking-[0.2em] mb-1')
                        if attr == 'voltage': ui.label().bind_text_from(data, attr, backward=lambda v: f"{v:.3f}V").classes('text-2xl md:text-4xl font-black ' + c_cls)
                        elif attr == 'current':
                            with ui.column().classes('items-center'):
                                ui.label().bind_text_from(data, attr, backward=lambda i: f"{i:+.2f}A").classes('text-2xl md:text-4xl font-black ' + c_cls)
                                ui.label().bind_text_from(data, 'current', backward=lambda i: f"{abs(i*data.voltage):.0f}W").classes('text-[8px] font-bold text-slate-500')
                        elif attr == 'temp_env':
                            with ui.row().classes('items-baseline gap-1'):
                                ui.label().bind_text_from(data, 'temp_env', backward=lambda t: f"{t}°C").classes('text-2xl md:text-4xl font-black ' + c_cls)
                                ui.label().bind_text_from(data, 'temp_mos', backward=lambda t: f"/ {t}°" if t > 0 else "").classes('text-sm font-bold text-amber-600')
                        else: ui.label().bind_text_from(data, attr).classes('text-2xl md:text-4xl font-black ' + c_cls)
        
        with ui.card().classes('w-full p-6 md:p-8 bg-slate-900/40 rounded-[2rem] border border-slate-900 shadow-none min-w-0'):
            ui.label('CELL VOLTAGES').classes('text-slate-600 font-black text-[10px] tracking-[0.4em] mb-6 text-center w-full')
            
            active_indices = [i for i, v in enumerate(data.cell_voltages) if v > 0.5]
            count = max(active_indices) + 1 if active_indices else 16
            
            # Responsive grid: 4 columns for 4S, 8 columns for 8S/16S
            grid_cols = "grid-cols-2 sm:grid-cols-4"
            if count > 4: grid_cols += " md:grid-cols-8"
            else: grid_cols += " md:grid-cols-4"

            with ui.grid().classes(f'w-full gap-3 {grid_cols}'):
                for i in range(count):
                    v, ghost, bad = get_cell_logic(data.cell_voltages, i); c_style = 'bg-slate-900/60 border-slate-800 text-slate-200'
                    if ghost: c_style = 'bg-slate-900/20 opacity-10'
                    elif bad: c_style = 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                    with ui.card().classes(f'p-3 items-center rounded-2xl border {c_style} shadow-none'):
                        ui.label(f'L{i+1:02}').classes('text-[8px] font-black text-slate-600'); ui.label(f"{v:.3f}V").classes('text-sm font-mono font-black')

def main_grid_content():
    with ui.column().classes('w-full p-6 md:p-10 gap-10'):
        ui.label('SYSTEM NODES').classes('text-4xl md:text-5xl font-black text-white tracking-tighter')
        if not state.batteries:
            with ui.card().classes('w-full p-20 md:p-32 items-center justify-center bg-slate-900/20 border-2 border-dashed border-slate-800 rounded-[2rem] md:rounded-[3rem]'):
                ui.icon('power', size='6rem').classes('text-slate-800 animate-pulse')
                ui.label('WAITING FOR POWER INPUT...').classes('text-slate-600 mt-8 font-black tracking-widest text-sm text-center')
        else:
            with ui.grid().classes('w-full gap-6 md:gap-10 grid-cols-1 md:grid-cols-2 lg:grid-cols-3'):
                for m, b in state.batteries.items(): node_card(m, b)

# 9. DUAL ENGINE LAYOUT
@ui.refreshable
def layout():
    try: client_id = context.get_client().id
    except RuntimeError: return
    if client_id not in state.clients: state.clients[client_id] = ClientState()
    sel_mac = state.clients[client_id].selected_mac
    bat = state.batteries.get(sel_mac)

    # A. DESKTOP ENGINE (Hidden on Mobile)
    with ui.element('div').classes('max-md:hidden flex w-full no-wrap h-[calc(100vh-84px)] m-0 p-0 overflow-hidden'):
        # ALWAYS Sidebar
        with ui.column().classes('w-[420px] h-full bg-slate-950 p-10 border-r border-slate-900 shrink-0 overflow-y-auto'):
            sidebar_content()
            ui.space(); ui.button('SYSTEM GRID', icon='apps', on_click=lambda: select_battery(None)).props('unelevated color=slate-900').classes('w-full font-black h-14 rounded-2xl text-slate-400 mt-10')
        # ALWAYS Content (Switcher)
        with ui.scroll_area().classes('flex-1 h-full bg-slate-950'):
            if not bat: main_grid_content()
            else: detail_view_content(bat)

    # B. MOBILE ENGINE (Hidden on Desktop)
    with ui.element('div').classes('md:hidden flex w-full min-h-[calc(100vh-84px)] bg-slate-950 p-6 overflow-y-auto flex-col'):
        if not sel_mac:
            # List View
            sidebar_content()
            ui.space(); ui.button('SYSTEM GRID', icon='apps', on_click=lambda: select_battery(None)).props('unelevated color=slate-900').classes('w-full font-black h-14 rounded-2xl text-slate-400 mt-10')
        else:
            # Detail View (App-style)
            if bat: detail_view_content(bat)
            else: select_battery(None)

@ui.page('/')
def index():
    ui.query('body').style('background-color: #020617; font-family: \"Inter\", sans-serif; padding-top: 84px;')
    with ui.header().classes('items-center bg-slate-950/80 border-b border-slate-900 px-6 md:px-12 py-4 md:py-6 z-50'):
        ui.icon('hive', size='2rem', color='cyan-500'); ui.label('LITHIUM CORE').classes('text-xl md:text-3xl font-black text-white tracking-tighter'); ui.space()
        with ui.column().classes('items-end gap-1'):
            ui.label().bind_text_from(state, 'status_msg').classes('text-[8px] md:text-[10px] font-black text-cyan-500 tracking-[0.4em]')
            ui.linear_progress(value=None).classes('w-24 md:w-48 h-0.5 rounded-full').props('color=cyan-500 track-color=slate-900 shadow-none').bind_visibility_from(state, 'scanning', backward=lambda s: s or state.adding)
    layout()
    ui.timer(5.0, lambda: connected_list_ui.refresh())

@app.on_startup
def start_tasks(): 
    asyncio.create_task(polling_loop()); asyncio.create_task(do_scan())
    configs = load_config(); [asyncio.create_task(provision_node_task(c['mac'], c['bms_type'], c['name'])) for c in configs]

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title='Lithium Core', port=8080, reload=False, dark=True, storage_secret='lithium-dashboard-v1')
