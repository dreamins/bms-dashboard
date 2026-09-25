// parsers.js — Pure BMS frame parsing functions, no browser APIs.
// Safe to import in Node.js (tests) or in a browser <script type="module">.
//
// EG4:    Modbus RTU, 83-byte frames, big-endian
// LiTime: Proprietary c_13/c_16 protocol, 105-byte frames, little-endian
// JBD:    Proprietary "DD A5 <cmd> ... 77" request/response protocol, big-endian

// ---------------------------------------------------------------------------
// EG4 — CRC16 Modbus
// ---------------------------------------------------------------------------

export function crc16Modbus(bytes) {
    let crc = 0xFFFF;
    for (const b of bytes) {
        crc ^= b;
        for (let i = 0; i < 8; i++) {
            crc = (crc & 1) ? ((crc >>> 1) ^ 0xA001) & 0xFFFF : (crc >>> 1) & 0xFFFF;
        }
    }
    return crc;
}

// Parse an 83-byte EG4 Modbus RTU response frame.
// Throws on short frame or CRC mismatch.
export function parseEG4Frame(buf) {
    if (buf.length < 83) throw new Error(`Frame too short: ${buf.length} bytes`);

    const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);

    const receivedCrc = view.getUint16(81, true);                  // LE at [81:83]
    const calcCrc     = crc16Modbus(buf.slice(0, 81));
    if (receivedCrc !== calcCrc) {
        throw new Error(
            `CRC mismatch: expected 0x${calcCrc.toString(16).padStart(4,'0')}, ` +
            `got 0x${receivedCrc.toString(16).padStart(4,'0')}`
        );
    }

    const voltage = view.getUint16(3, false) / 100;   // BE ÷100 → V
    const current = view.getInt16(5, false) / 10;     // BE signed ÷10 → A

    const cellVoltages = [];
    for (let i = 0; i < 16; i++) {
        cellVoltages.push(view.getUint16(7 + i * 2, false) / 1000);  // BE ÷1000 → V
    }

    return {
        voltage,
        current,
        cellVoltages,
        tempEnv: buf[44],                          // byte [44]
        soh:     buf[50],                          // byte [50]
        soc:     buf[52],                          // byte [52]
        status:  buf[54],                          // byte [54]
        cycles:  view.getUint16(73, false),        // BE at [73:75]
        rawHex:  Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join(''),
    };
}

// EG4 poll command (Modbus Read Holding Registers, 39 regs from addr 0)
export const EG4_POLL_CMD = new Uint8Array([0x01, 0x03, 0x00, 0x00, 0x00, 0x27, 0x05, 0xD0]);

// ---------------------------------------------------------------------------
// LiTime / Redodo — proprietary protocol
// ---------------------------------------------------------------------------

// c_13 response anchor: type(01) + tag-with-response-bit(93) + magic(55 AA)
// Lives at frame bytes [3:7].
export const C13_RESPONSE_ANCHOR = new Uint8Array([0x01, 0x93, 0x55, 0xAA]);

// Additive checksum over frame[2..103] per spec §2.3.
export function litimeChecksum(frame) {
    let s = 0;
    for (let i = 2; i < 104; i++) s = (s + frame[i]) & 0xFF;
    return s;
}

// Build an 8-byte LiTime command frame for the given tag (0x13 = poll, 0x16 = metadata).
export function buildLiTimeFrame(tag) {
    const cs = (0x04 + tag) & 0xFF;
    return new Uint8Array([0x00, 0x00, 0x04, 0x01, tag, 0x55, 0xAA, cs]);
}

// Parse a 105-byte LiTime c_13 response payload.
// Throws on short payload or checksum mismatch.
export function parseLiTimePayload(buf) {
    if (buf.length < 105) throw new Error(`Payload too short: ${buf.length} bytes`);

    const cs = litimeChecksum(buf);
    if (cs !== buf[104]) {
        throw new Error(
            `LiTime checksum mismatch: calc 0x${cs.toString(16).padStart(2,'0')} ` +
            `!= recv 0x${buf[104].toString(16).padStart(2,'0')}`
        );
    }

    const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);

    const voltage = view.getUint16(12, true) / 1000;   // LE ÷1000 → V

    // Raw int32 LE / 1000: spec Positive=Discharge; invert for UI convention Positive=Charging.
    const current = -(view.getInt32(48, true) / 1000);

    const cellVoltages = [];
    for (let i = 0; i < 16; i++) {
        const raw = view.getUint16(16 + i * 2, true);
        cellVoltages.push(raw > 0 ? raw / 1000 : 0.0);
    }

    return {
        voltage,
        current,
        cellVoltages,
        tempEnv: view.getInt8(52),           // signed, cells temp
        tempMos: view.getInt8(54),           // signed, MOSFET temp
        soc:     view.getUint16(90, true),   // LE at [90:92]
        soh:     view.getUint16(92, true),   // LE at [92:94]
        cycles:  view.getUint16(96, true),   // LE at [96:98]
        status:  0,
        rawHex:  Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join(''),
    };
}

// ---------------------------------------------------------------------------
// JBD (Jiabaida) — "DD A5 <cmd> <len> <data> <chk> 77" proprietary protocol
// ---------------------------------------------------------------------------

export const JBD_CMD_BASIC = 0x03;
export const JBD_CMD_CELLS = 0x04;

// 16-bit additive checksum: (0x10000 - sum(bytes)) & 0xFFFF, stored big-endian.
// Caller passes the exact byte range the checksum covers:
//   request:  [cmd, len, ...data]
//   response: [status, len, ...data]
export function jbdChecksum(bytes) {
    let sum = 0;
    for (const b of bytes) sum += b;
    return (0x10000 - sum) & 0xFFFF;
}

// Build a read request: DD A5 <cmd> 00 <chk_hi> <chk_lo> 77.
// Only read commands exist here — this protocol's write (0x5A) commands are
// never used by this app.
export function buildJbdRequest(cmd) {
    const len = 0x00;
    const cs  = jbdChecksum([cmd, len]);
    return new Uint8Array([0xDD, 0xA5, cmd, len, (cs >> 8) & 0xFF, cs & 0xFF, 0x77]);
}

export const JBD_REQUEST_BASIC = buildJbdRequest(JBD_CMD_BASIC);
export const JBD_REQUEST_CELLS = buildJbdRequest(JBD_CMD_CELLS);

// Reassembles JBD BLE notifications (delivered in ≤20-byte fragments) into
// complete, checksum-validated frames. Pure/stateful but browser-API-free —
// feed it raw byte chunks, get back zero or more validated frames.
const JBD_MAX_BUFFER = 300;

export class JbdReassembler {
    constructor() {
        this.buf = [];
    }

    // Accepts a Uint8Array/array-like chunk. Returns an array of complete,
    // validated frames: { cmd, status, data (Uint8Array) }.
    // Malformed frames (bad footer/checksum) are dropped byte-by-byte and
    // the buffer resyncs on the next 0xDD.
    push(chunk) {
        for (const b of chunk) this.buf.push(b);

        const frames = [];
        while (true) {
            const idx = this.buf.indexOf(0xDD);
            if (idx === -1) { this.buf.length = 0; break; }
            if (idx > 0) this.buf.splice(0, idx);

            if (this.buf.length < 4) break;   // need cmd/status/len header

            const len   = this.buf[3];
            const total = len + 7;
            if (this.buf.length < total) {
                if (this.buf.length > JBD_MAX_BUFFER) this.buf.splice(0, this.buf.length - 10);
                break;   // frame not fully reassembled yet; wait for more fragments
            }

            const frame  = this.buf.slice(0, total);
            const cmd    = frame[1];
            const status = frame[2];
            const data   = frame.slice(4, 4 + len);
            const recv   = (frame[4 + len] << 8) | frame[4 + len + 1];
            const calc   = jbdChecksum([status, len, ...data]);

            if (frame[total - 1] !== 0x77 || calc !== recv) {
                this.buf.splice(0, 1);   // drop the stray/bad 0xDD, resync
                continue;
            }

            this.buf.splice(0, total);
            frames.push({ cmd, status, data: new Uint8Array(data) });
        }
        return frames;
    }
}

// Parse a JBD basic-info (cmd 0x03) data payload (frame[4:4+len] — i.e. the
// bytes already stripped of header/checksum/footer by JbdReassembler).
export function parseJbdBasic(bytes) {
    const buf = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (buf.length < 23) throw new Error(`JBD basic payload too short: ${buf.length} bytes`);

    const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);

    const voltage         = view.getUint16(0, false) / 100;   // BE ×0.01 → V
    const current         = view.getInt16(2, false) / 100;    // BE signed ×0.01 → A (charging positive; matches UI, do NOT invert)
    const nominalCapacity = view.getUint16(6, false) / 100;   // BE ×0.01 → Ah
    const cycles          = view.getUint16(8, false);         // BE
    const status          = view.getUint16(16, false);        // BE protection bitmask
    const soc             = buf[19];                          // RSOC %
    const ntcCount        = buf[22];

    let offset = 23;
    const temps = [];
    for (let i = 0; i < ntcCount; i++) {
        const raw = view.getUint16(offset, false);
        temps.push((raw - 2731) / 10);   // 0.1K → °C
        offset += 2;
    }
    const tempEnv = temps.length >= 1 ? Math.round(temps[0]) : 0;   // NTC1
    const tempMos = temps.length >= 2 ? Math.round(temps[1]) : 0;   // NTC2

    // Optional tail: humidity(1) + alarm(2) + full-charge cap(2) + remaining(2) + balance current(2) = 9 bytes.
    let soh = 0;
    if (buf.length >= offset + 9) {
        const fullChargeAh = view.getUint16(offset + 3, false) / 100;
        if (fullChargeAh > 0 && nominalCapacity > 0) {
            soh = Math.min(100, Math.round((fullChargeAh / nominalCapacity) * 100));
        }
    }

    return {
        voltage, current, soc, soh, cycles, status,
        tempEnv, tempMos,
        rawHex: Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join(''),
    };
}

// Parse a JBD cell-voltages (cmd 0x04) data payload. u16 BE mV per cell.
// Pads to at least 16 entries with 0; keeps all entries if more than 16.
export function parseJbdCells(bytes) {
    const buf   = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const view  = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const count = Math.floor(buf.length / 2);

    const cells = [];
    for (let i = 0; i < count; i++) {
        cells.push(view.getUint16(i * 2, false) / 1000);   // BE ÷1000 → V
    }
    while (cells.length < 16) cells.push(0);
    return cells;
}

// ---------------------------------------------------------------------------
// UI display logic (pure, no DOM)
// ---------------------------------------------------------------------------

// Returns { ghost, imbalance } flags for cell at idx, given all cell voltages.
// ghost     → voltage ≤ 0.5 V (unpopulated/inactive cell)
// imbalance → >100 mV deviation from the average of active cells
export function getCellLogic(voltages, idx) {
    const v      = idx < voltages.length ? voltages[idx] : 0;
    const active = voltages.filter(cv => cv > 0.5);
    const avg    = active.length > 0 ? active.reduce((a, b) => a + b, 0) / active.length : 0;
    return {
        voltage:   v,
        ghost:     v <= 0.5,
        imbalance: v > 0.5 && Math.abs(v - avg) > 0.1,
    };
}

export function getSocColor(soc) {
    if (soc < 20) return '#ef4444';
    if (soc < 50) return '#f59e0b';
    return '#10b981';
}

export function getStatusInfo(current) {
    if (current > 0.2)  return { text: 'CHARGING',    color: 'text-emerald-400' };
    if (current < -0.2) return { text: 'DISCHARGING', color: 'text-rose-400'    };
    return                     { text: 'IDLE',         color: 'text-slate-500'   };
}

export function generateCellSvg(voltage, ghost, imbalance, label = '') {
    if (ghost) {
        return `<svg viewBox="0 0 60 32" xmlns="http://www.w3.org/2000/svg" class="w-full" style="opacity:0.15">` +
            `<rect x="1" y="1" width="58" height="30" rx="4" fill="#0f172a" stroke="#1e293b" stroke-width="1"/>` +
            `</svg>`;
    }
    const bg     = imbalance ? 'rgba(239,68,68,0.12)'  : 'rgba(16,185,129,0.08)';
    const border = imbalance ? 'rgba(239,68,68,0.5)'   : 'rgba(16,185,129,0.2)';
    const fill   = imbalance ? '#ef4444'                : '#f8fafc';
    const lbl    = label
        ? `<text x="30" y="13" font-family="Inter,monospace" font-size="6" font-weight="700" fill="#475569" text-anchor="middle">${label}</text>`
        : '';
    return `<svg viewBox="0 0 60 32" xmlns="http://www.w3.org/2000/svg" class="w-full">` +
        `<rect x="1" y="1" width="58" height="30" rx="4" fill="${bg}" stroke="${border}" stroke-width="1"/>` +
        lbl +
        `<text x="30" y="25" font-family="Inter,monospace" font-size="9" font-weight="900" fill="${fill}" text-anchor="middle">${voltage.toFixed(3)}V</text>` +
        `</svg>`;
}
