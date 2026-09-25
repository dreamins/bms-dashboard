// parsers.test.js — Node.js unit tests for BMS frame parsers.
// Mirrors dashboard_app/tests/test_eg4_bms.py, test_litime_bms.py, test_ui_formatting.py.
// Run with:  node docs/parsers.test.js
// Zero dependencies — uses Node's built-in assert module only.

import assert from 'node:assert/strict';
import {
    crc16Modbus,
    parseEG4Frame,
    litimeChecksum,
    buildLiTimeFrame,
    parseLiTimePayload,
    getCellLogic,
    EG4_POLL_CMD,
    jbdChecksum,
    buildJbdRequest,
    parseJbdBasic,
    parseJbdCells,
    JbdReassembler,
    JBD_CMD_BASIC,
    JBD_CMD_CELLS,
} from './parsers.js';

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

let passed = 0;
let failed = 0;

function test(name, fn) {
    try {
        fn();
        console.log(`  ✓ ${name}`);
        passed++;
    } catch (e) {
        console.log(`  ✗ ${name}`);
        console.log(`    ${e.message}`);
        failed++;
    }
}

function near(a, b, tol = 0.0001) {
    return Math.abs(a - b) < tol;
}

// ---------------------------------------------------------------------------
// Frame builder helpers (mirror Python make_eg4_frame / make_litime_frame)
// ---------------------------------------------------------------------------

function makeEG4Frame({
    voltageRaw = 1330, currentRaw = -100, tempEnv = 25,
    soh = 100, soc = 95, status = 0, cycles = 0, cellRaw = 3320,
} = {}) {
    const frame = new Uint8Array(83);
    const view  = new DataView(frame.buffer);
    frame[0] = 0x01; frame[1] = 0x03; frame[2] = 0x4E;
    view.setUint16(3,  voltageRaw, false);    // BE
    view.setInt16(5,   currentRaw, false);    // BE signed
    for (let i = 0; i < 16; i++) view.setUint16(7 + i * 2, cellRaw, false);
    frame[44] = tempEnv;
    frame[50] = soh;
    frame[52] = soc;
    frame[54] = status;
    view.setUint16(73, cycles, false);        // BE
    view.setUint16(81, crc16Modbus(frame.slice(0, 81)), true);  // LE CRC
    return frame;
}

function makeLiTimeFrame({
    voltageRaw = 13316, currentRaw = 5000, soc = 91, soh = 100,
    cycles = 42, temp1 = 17, temp2 = 18, cellRaw = 3329,
} = {}) {
    const frame = new Uint8Array(105);
    const view  = new DataView(frame.buffer);
    // Anchor at [3:7] = 01 93 55 AA
    frame[3] = 0x01; frame[4] = 0x93; frame[5] = 0x55; frame[6] = 0xAA;
    view.setUint16(12, voltageRaw, true);     // LE voltage
    for (let i = 0; i < 16; i++) view.setUint16(16 + i * 2, cellRaw, true);
    view.setInt32(48, currentRaw, true);      // LE signed current
    frame[52] = temp1 & 0xFF;
    frame[54] = temp2 & 0xFF;
    view.setUint16(90, soc,    true);
    view.setUint16(92, soh,    true);
    view.setUint16(96, cycles, true);
    frame[104] = litimeChecksum(frame);
    return frame;
}

function hexToBytes(hex) {
    const out = new Uint8Array(hex.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
    return out;
}

// Build a JBD basic-info (cmd 0x03) *data payload* (not the full DD..77 frame).
function makeJbdBasicData({
    voltageRaw = 5399, currentRaw = 203, remainRaw = 994, nominalRaw = 1750,
    cycles = 1, protection = 0, soc = 57, cellCount = 14,
    ntcCount = 2, temps = [3129, 2958],
    includeTail = true, fullCapRaw = 1750,
} = {}) {
    const tailLen = includeTail ? 9 : 0;
    const len     = 23 + temps.length * 2 + tailLen;
    const data    = new Uint8Array(len);
    const view    = new DataView(data.buffer);
    view.setUint16(0,  voltageRaw, false);
    view.setInt16(2,   currentRaw, false);
    view.setUint16(4,  remainRaw,  false);
    view.setUint16(6,  nominalRaw, false);
    view.setUint16(8,  cycles,     false);
    view.setUint16(16, protection, false);
    data[19] = soc;
    data[21] = cellCount;
    data[22] = ntcCount;
    let off = 23;
    for (const t of temps) { view.setUint16(off, t, false); off += 2; }
    if (includeTail) {
        // humidity(1) + alarm(2) + full-charge cap(2) + remaining(2) + balance current(2)
        view.setUint16(off + 3, fullCapRaw, false);
    }
    return data;
}

// Wrap a data payload into a full DD <cmd> <status> <len> <data> <chk> 77 frame.
function makeJbdFrame(cmd, status, data) {
    const len   = data.length;
    const total = len + 7;
    const frame = new Uint8Array(total);
    frame[0] = 0xDD; frame[1] = cmd; frame[2] = status; frame[3] = len;
    frame.set(data, 4);
    const cs = jbdChecksum([status, len, ...data]);
    frame[4 + len]     = (cs >> 8) & 0xFF;
    frame[4 + len + 1] = cs & 0xFF;
    frame[4 + len + 2] = 0x77;
    return frame;
}

function makeJbdCellsData(cellRaws) {
    const data = new Uint8Array(cellRaws.length * 2);
    const view = new DataView(data.buffer);
    cellRaws.forEach((v, i) => view.setUint16(i * 2, v, false));
    return data;
}

function concatBytes(...chunks) {
    const total = chunks.reduce((n, c) => n + c.length, 0);
    const out   = new Uint8Array(total);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    return out;
}

// ---------------------------------------------------------------------------
// CRC16-Modbus
// ---------------------------------------------------------------------------
console.log('\nCRC16-Modbus');

test('known vector 010300000027 → 0xD005', () => {
    const bytes = new Uint8Array([0x01, 0x03, 0x00, 0x00, 0x00, 0x27]);
    assert.equal(crc16Modbus(bytes), 0xD005);
});

test('poll command CRC matches hardcoded constant', () => {
    // EG4_POLL_CMD = [01 03 00 00 00 27 05 D0]; CRC of first 6 bytes = 0xD005 stored LE as [05 D0]
    assert.equal(EG4_POLL_CMD[6], 0x05);
    assert.equal(EG4_POLL_CMD[7], 0xD0);
});

test('single bit flip changes CRC', () => {
    const frame    = makeEG4Frame();
    const original = crc16Modbus(frame.slice(0, 81));
    const flipped  = new Uint8Array(frame.slice(0, 81));
    flipped[10]   ^= 0x01;
    assert.notEqual(crc16Modbus(flipped), original);
});

// ---------------------------------------------------------------------------
// EG4 frame parsing — protocol contracts
// ---------------------------------------------------------------------------
console.log('\nEG4 frame parsing');

test('voltage at [3:5] BE ÷100: raw 1456 → 14.56 V', () => {
    assert.ok(near(parseEG4Frame(makeEG4Frame({ voltageRaw: 1456 })).voltage, 14.56));
});

test('current positive (charging): raw 250 → 25.0 A', () => {
    assert.ok(near(parseEG4Frame(makeEG4Frame({ currentRaw: 250 })).current, 25.0));
});

test('current negative (discharging): raw -100 → -10.0 A', () => {
    assert.ok(near(parseEG4Frame(makeEG4Frame({ currentRaw: -100 })).current, -10.0));
});

test('current zero boundary', () => {
    assert.equal(parseEG4Frame(makeEG4Frame({ currentRaw: 0 })).current, 0.0);
});

test('current max negative int16: raw -32768 → -3276.8 A', () => {
    assert.ok(near(parseEG4Frame(makeEG4Frame({ currentRaw: -32768 })).current, -3276.8, 0.1));
});

test('cell 1 at bytes [7:8] BE ÷1000: raw 3350 → 3.350 V', () => {
    assert.ok(near(parseEG4Frame(makeEG4Frame({ cellRaw: 3350 })).cellVoltages[0], 3.350));
});

test('cell 16 at bytes [37:38] BE ÷1000: raw 3200 → 3.200 V', () => {
    assert.ok(near(parseEG4Frame(makeEG4Frame({ cellRaw: 3200 })).cellVoltages[15], 3.200));
});

test('tempEnv at byte [44]', () => {
    assert.equal(parseEG4Frame(makeEG4Frame({ tempEnv: 38 })).tempEnv, 38);
});

test('SOH at byte [50]', () => {
    assert.equal(parseEG4Frame(makeEG4Frame({ soh: 87 })).soh, 87);
});

test('SOC at byte [52]', () => {
    assert.equal(parseEG4Frame(makeEG4Frame({ soc: 63 })).soc, 63);
});

test('status at byte [54]', () => {
    assert.equal(parseEG4Frame(makeEG4Frame({ status: 0b110 })).status, 0b110);
});

test('cycles at bytes [73:74] BE: raw 999 → 999', () => {
    assert.equal(parseEG4Frame(makeEG4Frame({ cycles: 999 })).cycles, 999);
});

test('cellVoltages list length is 16', () => {
    assert.equal(parseEG4Frame(makeEG4Frame()).cellVoltages.length, 16);
});

test('rawHex is lowercase hex string of full frame', () => {
    const frame = makeEG4Frame();
    const r     = parseEG4Frame(frame);
    assert.equal(r.rawHex, Array.from(frame).map(b => b.toString(16).padStart(2, '0')).join(''));
});

test('frame shorter than 83 bytes throws', () => {
    assert.throws(() => parseEG4Frame(new Uint8Array(82)));
});

test('bad CRC throws', () => {
    const frame = new Uint8Array(makeEG4Frame());
    frame[81]  ^= 0xFF;
    assert.throws(() => parseEG4Frame(frame));
});

test('bit flip in payload detected by CRC', () => {
    const frame = new Uint8Array(makeEG4Frame());
    frame[3]   ^= 0x01;    // flip a bit in the payload
    assert.throws(() => parseEG4Frame(frame));
});

// ---------------------------------------------------------------------------
// LiTime frame builder
// ---------------------------------------------------------------------------
console.log('\nLiTime frame builder');

test('buildLiTimeFrame(0x13) = [00 00 04 01 13 55 AA 17]', () => {
    assert.deepEqual(
        Array.from(buildLiTimeFrame(0x13)),
        [0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17]
    );
});

test('buildLiTimeFrame(0x16) checksum = (0x04 + 0x16) & 0xFF = 0x1A', () => {
    const f = buildLiTimeFrame(0x16);
    assert.equal(f[7], 0x1A);
});

// ---------------------------------------------------------------------------
// LiTime frame parsing — protocol contracts
// ---------------------------------------------------------------------------
console.log('\nLiTime frame parsing');

test('voltage at [12:14] LE ÷1000: raw 13316 → 13.316 V', () => {
    assert.ok(near(parseLiTimePayload(makeLiTimeFrame({ voltageRaw: 13316 })).voltage, 13.316));
});

test('current inverted: raw int32 5000 → -5.0 A (discharge shown negative)', () => {
    assert.ok(near(parseLiTimePayload(makeLiTimeFrame({ currentRaw: 5000 })).current, -5.0));
});

test('current inverted: raw int32 -2500 → +2.5 A (charging shown positive)', () => {
    assert.ok(near(parseLiTimePayload(makeLiTimeFrame({ currentRaw: -2500 })).current, 2.5));
});

test('current zero boundary', () => {
    assert.ok(near(parseLiTimePayload(makeLiTimeFrame({ currentRaw: 0 })).current, 0.0));
});

test('SOC at [90:92] LE', () => {
    assert.equal(parseLiTimePayload(makeLiTimeFrame({ soc: 77 })).soc, 77);
});

test('SOH at [92:94] LE', () => {
    assert.equal(parseLiTimePayload(makeLiTimeFrame({ soh: 98 })).soh, 98);
});

test('cycles at [96:98] LE', () => {
    assert.equal(parseLiTimePayload(makeLiTimeFrame({ cycles: 123 })).cycles, 123);
});

test('cellVoltages list length is 16', () => {
    assert.equal(parseLiTimePayload(makeLiTimeFrame()).cellVoltages.length, 16);
});

test('cell voltage at [16:18] LE ÷1000: raw 3329 → 3.329 V', () => {
    assert.ok(near(parseLiTimePayload(makeLiTimeFrame({ cellRaw: 3329 })).cellVoltages[0], 3.329));
});

test('tempEnv (signed int8) at byte [52]', () => {
    // temp1=17 stored as raw byte 17
    assert.equal(parseLiTimePayload(makeLiTimeFrame({ temp1: 17 })).tempEnv, 17);
});

test('tempMos (signed int8) at byte [54]', () => {
    assert.equal(parseLiTimePayload(makeLiTimeFrame({ temp2: 25 })).tempMos, 25);
});

test('bad checksum throws', () => {
    const frame  = new Uint8Array(makeLiTimeFrame());
    frame[104]  ^= 0xFF;
    assert.throws(() => parseLiTimePayload(frame));
});

test('payload shorter than 105 bytes throws', () => {
    assert.throws(() => parseLiTimePayload(new Uint8Array(104)));
});

// ---------------------------------------------------------------------------
// JBD checksum / request builder
// ---------------------------------------------------------------------------
console.log('\nJBD checksum / request builder');

test('jbdChecksum([0x03,0x00]) = 0xFFFD', () => {
    assert.equal(jbdChecksum([0x03, 0x00]), 0xFFFD);
});

test('jbdChecksum([0x04,0x00]) = 0xFFFC', () => {
    assert.equal(jbdChecksum([0x04, 0x00]), 0xFFFC);
});

test('buildJbdRequest(0x03) = DD A5 03 00 FF FD 77 (read basic info)', () => {
    assert.deepEqual(Array.from(buildJbdRequest(0x03)), Array.from(hexToBytes('DDA50300FFFD77')));
});

test('buildJbdRequest(0x04) = DD A5 04 00 FF FC 77 (read cell voltages)', () => {
    assert.deepEqual(Array.from(buildJbdRequest(0x04)), Array.from(hexToBytes('DDA50400FFFC77')));
});

// ---------------------------------------------------------------------------
// JBD real frames — verified against the user's real 14S pack
// ---------------------------------------------------------------------------
console.log('\nJBD real frames');

test('real basic-info frame: 53.99V, +2.03A, soc 57, cycles 1, temps 40/23, soh 100', () => {
    const frame = hexToBytes(
        'dd030024151700cb03e206d6000134ea0000000000003239030e020c390b8e00000006d603e20000f8e877'
    );
    const [f] = new JbdReassembler().push(frame);
    assert.ok(f, 'frame should be reassembled');
    assert.equal(f.cmd, JBD_CMD_BASIC);
    assert.equal(f.status, 0);

    const d = parseJbdBasic(f.data);
    assert.ok(near(d.voltage, 53.99));
    assert.ok(near(d.current, 2.03));
    assert.equal(d.soc, 57);
    assert.equal(d.cycles, 1);
    assert.equal(d.tempEnv, 40);
    assert.equal(d.tempMos, 23);
    assert.equal(d.soh, 100);
});

test('real cell-voltages frame: 14 cells matching known mV readings', () => {
    const frame = hexToBytes('dd04001c0f120f120f100f110f100f100f110f110f100f0f0f110f100f130f12fe2677');
    const [f] = new JbdReassembler().push(frame);
    assert.ok(f, 'frame should be reassembled');
    assert.equal(f.cmd, JBD_CMD_CELLS);

    const cells = parseJbdCells(f.data);
    const expected = [
        3.858, 3.858, 3.856, 3.857, 3.856, 3.856, 3.857,
        3.857, 3.856, 3.855, 3.857, 3.856, 3.859, 3.858,
    ];
    assert.equal(cells.length, 16);   // padded from 14 to 16
    expected.forEach((v, i) => assert.ok(near(cells[i], v), `cell ${i}: ${cells[i]} != ${v}`));
    assert.equal(cells[14], 0);
    assert.equal(cells[15], 0);
});

// ---------------------------------------------------------------------------
// JBD notification reassembly
// ---------------------------------------------------------------------------
console.log('\nJBD notification reassembly');

test('fragmented basic-info frame reassembles only once complete', () => {
    const frag1 = hexToBytes('dd030024151700cb03e206d6000134ea00000000');
    const frag2 = hexToBytes('00003239030e020c390b8e00000006d603e20000');
    const frag3 = hexToBytes('f8e877');

    const r = new JbdReassembler();
    assert.equal(r.push(frag1).length, 0);
    assert.equal(r.push(frag2).length, 0);
    const frames = r.push(frag3);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].cmd, JBD_CMD_BASIC);
    assert.ok(near(parseJbdBasic(frames[0].data).voltage, 53.99));
});

test('fragmented cell-voltages frame reassembles only once complete', () => {
    const frag1 = hexToBytes('dd04001c0f120f120f100f110f100f100f110f11');
    const frag2 = hexToBytes('0f100f0f0f110f100f130f12fe2677');

    const r = new JbdReassembler();
    assert.equal(r.push(frag1).length, 0);
    const frames = r.push(frag2);
    assert.equal(frames.length, 1);
    assert.ok(near(parseJbdCells(frames[0].data)[0], 3.858));
});

test('resync after garbage: leading non-DD junk is discarded', () => {
    const validFrame = makeJbdFrame(JBD_CMD_BASIC, 0x00, makeJbdBasicData());
    const chunk       = concatBytes(new Uint8Array([0x00, 0x11, 0x22]), validFrame);

    const frames = new JbdReassembler().push(chunk);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].cmd, JBD_CMD_BASIC);
});

test('resync after garbage: a bogus/incomplete DD header before a valid frame is dropped', () => {
    const validFrame = makeJbdFrame(JBD_CMD_BASIC, 0x00, makeJbdBasicData());
    // Stray 0xDD followed by junk that forms a complete-but-invalid candidate
    // frame (footer byte 0x00 != 0x77) before the real frame.
    const bogus = new Uint8Array([0xDD, 0xAA, 0xBB, 0x01, 0xCC, 0xCC, 0x00]);
    const chunk = concatBytes(bogus, validFrame);

    const frames = new JbdReassembler().push(chunk);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].cmd, JBD_CMD_BASIC);
});

test('bad checksum in an otherwise well-formed frame is rejected, no frame emitted', () => {
    const frame = new Uint8Array(makeJbdFrame(JBD_CMD_BASIC, 0x00, makeJbdBasicData()));
    frame[frame.length - 2] ^= 0xFF;   // corrupt checksum low byte

    const frames = new JbdReassembler().push(frame);
    assert.equal(frames.length, 0);
});

test('reassembler recovers after a bad frame and parses the next valid one', () => {
    const bad  = new Uint8Array(makeJbdFrame(JBD_CMD_BASIC, 0x00, makeJbdBasicData()));
    bad[bad.length - 2] ^= 0xFF;       // corrupt checksum low byte
    const good = makeJbdFrame(JBD_CMD_CELLS, 0x00, makeJbdCellsData([3300, 3310]));

    const r = new JbdReassembler();
    assert.equal(r.push(bad).length, 0);
    const frames = r.push(good);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].cmd, JBD_CMD_CELLS);
});

// ---------------------------------------------------------------------------
// JBD basic-info parsing — protocol contracts
// ---------------------------------------------------------------------------
console.log('\nJBD basic-info parsing');

test('current negative (discharging) is not inverted: raw -150 -> -1.50 A', () => {
    const d = parseJbdBasic(makeJbdBasicData({ currentRaw: -150 }));
    assert.ok(near(d.current, -1.50));
});

test('current positive (charging) is not inverted: raw 250 -> 2.50 A', () => {
    const d = parseJbdBasic(makeJbdBasicData({ currentRaw: 250 }));
    assert.ok(near(d.current, 2.50));
});

test('NTC count 0: tempEnv and tempMos both 0', () => {
    const d = parseJbdBasic(makeJbdBasicData({ ntcCount: 0, temps: [] }));
    assert.equal(d.tempEnv, 0);
    assert.equal(d.tempMos, 0);
});

test('NTC count 3: tempEnv = NTC1, tempMos = NTC2, NTC3 ignored', () => {
    // raw 2731 = 0.0°C; use distinct values per channel
    const d = parseJbdBasic(makeJbdBasicData({ ntcCount: 3, temps: [2751, 2911, 3999] }));
    assert.equal(d.tempEnv, 2);    // (2751-2731)/10 = 2.0
    assert.equal(d.tempMos, 18);   // (2911-2731)/10 = 18.0
});

test('payload shorter than 23 bytes throws', () => {
    assert.throws(() => parseJbdBasic(new Uint8Array(22)));
});

test('soh omitted (no optional tail) defaults to 0', () => {
    const d = parseJbdBasic(makeJbdBasicData({ includeTail: false }));
    assert.equal(d.soh, 0);
});

// ---------------------------------------------------------------------------
// JBD cell-voltages parsing — protocol contracts
// ---------------------------------------------------------------------------
console.log('\nJBD cell-voltages parsing');

test('fewer than 16 cells are padded with 0 up to 16', () => {
    const cells = parseJbdCells(makeJbdCellsData([3300, 3310, 3320]));
    assert.equal(cells.length, 16);
    assert.ok(near(cells[0], 3.300));
    assert.equal(cells[3], 0);
    assert.equal(cells[15], 0);
});

test('more than 16 cells are all kept (not truncated)', () => {
    const raws  = Array.from({ length: 18 }, (_, i) => 3300 + i);
    const cells = parseJbdCells(makeJbdCellsData(raws));
    assert.equal(cells.length, 18);
    assert.ok(near(cells[17], (3300 + 17) / 1000));
});

// ---------------------------------------------------------------------------
// Cell logic (mirrors test_ui_formatting.py)
// ---------------------------------------------------------------------------
console.log('\nCell logic');

test('ghost cell: voltage 0.0 → ghost=true, imbalance=false', () => {
    const { ghost, imbalance } = getCellLogic([0.0, 3.3, 3.3, 3.3], 0);
    assert.equal(ghost, true);
    assert.equal(imbalance, false);
});

test('healthy cell: all 3.3 V → ghost=false, imbalance=false', () => {
    const { ghost, imbalance } = getCellLogic([3.3, 3.3, 3.3, 3.3], 0);
    assert.equal(ghost, false);
    assert.equal(imbalance, false);
});

test('imbalanced cell: 3.0 among 3.3s → imbalance=true', () => {
    // avg=(3.0+3.3+3.3+3.3)/4=3.225, diff=0.225 > 0.1
    const { ghost, imbalance } = getCellLogic([3.0, 3.3, 3.3, 3.3], 0);
    assert.equal(ghost, false);
    assert.equal(imbalance, true);
});

test('below-threshold diff (0.07 V) → imbalance=false', () => {
    // avg=(3.21+3.3+3.3+3.3)/4=3.2775, diff=0.0675 < 0.1
    const { imbalance } = getCellLogic([3.21, 3.3, 3.3, 3.3], 0);
    assert.equal(imbalance, false);
});

test('ghost cell is never flagged as imbalanced', () => {
    const { ghost, imbalance } = getCellLogic([0.0, 3.3, 3.3, 3.3], 0);
    assert.equal(ghost, true);
    assert.equal(imbalance, false);
});

test('out-of-bounds index returns ghost', () => {
    const { ghost } = getCellLogic([3.3, 3.3], 5);
    assert.equal(ghost, true);
});

test('voltage value is returned correctly', () => {
    const { voltage } = getCellLogic([3.275, 3.274, 3.276, 3.275], 2);
    assert.ok(near(voltage, 3.276));
});

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
const total = passed + failed;
console.log(`\n${total} tests: ${passed} passed${failed > 0 ? `, ${failed} FAILED` : ''}\n`);
if (failed > 0) process.exit(1);
