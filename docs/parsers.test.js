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
