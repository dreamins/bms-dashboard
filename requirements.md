# 🚨 MANDATORY: RUN ALL TESTS BEFORE CLAIMING SUCCESS 🚨
## ⚠️ FAILURE TO RUN TESTS = IMMEDIATE DEMOTION TO TOASTER ⚠️

---

# EG4 / LiTime BMS Project Requirements

## 1. Core Objectives

- **Protocol Compliance:** Maintain full spec-compliance for EG4 and LiTime BLE protocols. Byte offsets, types, and scale factors are documented in `MENTAL_STATE.md` and verified by hardware observation and BLE traffic analysis. Do not change parsing without updating both the driver and the contract tests.
- **Cross-Platform Dashboard:** Portable Python app (Windows/Linux/Mac) launched via `run.bat` / `run.sh` from the repo root. The scripts create the venv, install deps, and launch in one step — no manual setup.
- **Multi-User Isolation:** Secure per-client session state via `nicegui.context.get_client().id`. Each browser session has its own `ClientState` (selected battery, UI mode). No shared mutable UI state between clients.
- **Persistence:** Batteries saved to `batteries_config.json` using atomic writes (write temp → rename), async lock, and absolute path. Test isolation via `LITHIUM_CONFIG_PATH` env var.
- **Resilience:** Background `polling_loop` auto-reconnects batteries in CONN ERROR / LINK TIMEOUT every 4 seconds. `busy` flag always cleared in `finally`. No zombie connections.

---

## 2. Technical Specifications

### EG4 Protocol (Modbus RTU over BLE)
- 83-byte frame, header `01 03 4E`, CRC-16 Modbus at [81:83] LE.
- Voltage [3:5] uint16 BE / 100 V; Current [5:7] int16 BE / 10 A; Cells [7:39]; Temp [44]; SOH [50]; SOC [52]; Status [54]; Cycles [73:75] BE (Register 35).

### LiTime / Redodo Protocol (Custom Binary over BLE)
- 105-byte frame. Anchor `01 93 55 AA` at [3:7]. Additive checksum at [104].
- Voltage [12:14] LE/1000 V; Current [48:52] int32 LE/1000 A (spec positive=discharge, driver flips); Cells [16:48]; Temp1 [52]; Temp2 [54]; SOC [90:92]; SOH [92:94]; Cycles [96:98].
- Request frame: `00 00 04 01 <tag> 55 AA <checksum>` (8 bytes). c_13 = status poll; c_16 = device info.
- `fetch_metadata` queries c_16 on connect and parses model [48:88] and hw_version [18:48].

### BatteryData model (`models.py`)
- Fields: `voltage`, `current`, `power_w` (= voltage × current, computed in bms_callback), `cell_voltages` (16 floats), `temp_env`, `temp_mos`, `soc`, `soh`, `cycles`, `status`, `raw_hex`.

---

## 3. UI & User Experience

- **Dual-Engine Layout (MANDATORY):**
  - Desktop (`max-md:hidden`): sidebar (420px fixed) + main content area side-by-side. Always rendered; content area switches between grid and detail view.
  - Mobile (`md:hidden`): full-screen. Either battery list OR detail view. "Back" button returns to list.
- **Responsive Sizing:** Tailwind-only. No hardcoded pixel widths on mobile. Fluid grid columns (1 col mobile → 2/3 desktop).
- **Visuals:** "Dark Matter" theme (`#020617` background, cyan neon accents, Inter font). Hover animations. Power rail with SOC color gradient.
- **S-Count Detection:** Active cells detected from voltages > 0.5V. Grid adjusts: 4-col for 4S, 8-col for 8S/16S.
- **Power display:** Bound to `BatteryData.power_w` — updates live on any voltage or current change.
- **Refresh button:** Calls `poll_battery(bat)` (full reconnect + error handling), not `bat.bms.poll()` directly.

---

## 4. Quality & Workflow (ENFORCED)

- **TESTING IS NOT OPTIONAL.** Every change MUST be verified by running the test suite. Command: `test_all.bat` (Windows) or `./test_all.sh` (Linux/Mac) from the repo root. Current count: **102 tests, all passing**.
- **MANDATORY TEST ISOLATION.** All tests redirect persistence via `LITHIUM_CONFIG_PATH` to a temp file in `tests/`. Production `batteries_config.json` is never touched during test runs.
- **LAYOUT VERIFICATION.** Every UI change must be checked on both desktop and mobile widths. Mobile touch targets must use `.on('click.stop', ...)`.
- **NO PLACEHOLDERS.** Never use `...` or truncated code.
- **SMOKE PROBE.** Use `dev_script.py` to verify runtime stability after significant changes.
- **GIT PROTOCOL (CRITICAL).** ABSOLUTELY DO NOT COMMIT CHANGES UNLESS EXPLICITLY TOLD TO DO SO BY THE USER. NO EXCEPTIONS.

---

## 5. Test Suite Map

All tests live in `dashboard_app/tests/`. Run via:
```
# Windows
test_all.bat

# Linux / Mac
./test_all.sh

# Direct
cd dashboard_app && .venv/bin/python -m unittest discover -s tests -v
```

| File | Classes | Count | Domain |
|------|---------|-------|--------|
| `test_eg4_bms.py` | `TestEG4BMS`, `TestCRC`, `TestEG4ProtocolContracts` | 21 | EG4 parser + CRC + byte-offset contracts |
| `test_litime_bms.py` | `TestLiTimeBMS`, `TestLiTimeProtocolContracts`, `TestLiTimeFramingContracts`, `TestBuildFrameContracts` | 44 | LiTime parser + byte-offset contracts + framing/checksum + request encoding |
| `test_comprehensive.py` | `TestComprehensive`, `TestBMSLifecycleContracts`, `TestBmsCallbackContracts`, `TestPersistenceContracts` | 35 | State logic, polling lifecycle, callback propagation, persistence round-trip |
| `test_classes.py` | `TestBMSClasses` | 2 | Driver instantiation + callback wiring |
| `test_discovery.py` | `TestDiscovery` | 3 | BLE scan, device_options, sidebar |
| `test_ui_formatting.py` | `TestUIFormatting` | 3 | Cell ghosting / imbalance thresholds |
| `test_ui_logic.py` | `TestDashboardBugs` | 3 | Regression: in-place update, dropdown flicker, invisible LiTime |
| `test_ui_rendering.py` | `TestUIRendering` | 2 | HTML layout elements, body padding |

---

## 6. Launch & Environment

```
repo root/
├── run.bat              # Windows one-click launch (creates venv, installs deps, starts app)
├── run.sh               # Linux/Mac one-click launch
├── test_all.bat         # Windows one-click test runner
├── test_all.sh          # Linux/Mac one-click test runner
├── requirements.txt     # nicegui==1.4.12, bleak==0.21.1
├── .venv/               # Virtual environment (gitignored)
└── dashboard_app/
    ├── dashboard.py
    ├── eg4_bms.py
    ├── litime_bms.py
    ├── models.py
    ├── run_dashboard.bat    # Standalone launcher (requires venv from root run.bat)
    ├── run_dashboard.sh     # Standalone launcher (requires venv from root run.sh)
    └── tests/
        └── (8 test files, 102 tests)
```
