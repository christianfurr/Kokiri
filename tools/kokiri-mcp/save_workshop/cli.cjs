// Typed wrapper around the MIT-licensed OoT Editor pure save model.
'use strict';
const d = require('./domain.cjs');
const catalog = require('./catalog.json');
const editCatalog = d.editOptions(catalog);
const namedFlags = new Map(catalog.fields.map(([hash, , name]) => [name, hash]));
const items = new Map(catalog.inventory.map(row => [row[1], row]));

function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error(`${label} must be an object.`);
}
function keys(value, allowed, label) {
  object(value, label);
  for (const name of Object.keys(value)) if (!allowed.includes(name)) throw Error(`Unsupported ${label} field: ${name}`);
}
function bytes(value) {
  if (typeof value !== 'string' || value.length > 3_000_000 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) throw Error('Invalid bounded save data.');
  const result = Uint8Array.from(Buffer.from(value, 'base64'));
  if (!result.length || result.length > 2 << 20) throw Error('Save data exceeds its limit.');
  return result;
}
function state(slot) {
  const inventory = {}, progression = {}, songs = {};
  for (const [name, [hash]] of items) if (slot.p.fields.has(hash)) inventory[name] = slot.p.int(hash);
  for (const [name, hash] of namedFlags) if (slot.p.fields.has(hash) && [0, 1].includes(slot.p.int(hash))) progression[name] = Boolean(slot.p.int(hash));
  for (const [name, groups] of Object.entries(d.worldSongs)) {
    const hashes = groups.flat();
    if (hashes.every(hash => slot.p.fields.has(hash))) songs[name] = hashes.every(hash => slot.p.int(hash) === 1);
  }
  let checkpoint = null;
  if (slot.p.fields.has(0x1D6189DA) && slot.p.fields.has(0xC884818D)) {
    const offset = slot.p.block(0xC884818D, 12);
    const xyz = [0, 4, 8].map(delta => slot.p.view.getFloat32(offset + delta, true));
    if (!xyz.every(Number.isFinite)) throw Error('The checkpoint coordinates are not finite.');
    checkpoint = {map: slot.p.string(0x1D6189DA, 64), x: xyz[0], y: xyz[1], z: xyz[2]};
  }
  return {wallet: slot.w.id, rupees: slot.rupees, hearts: slot.vitals.hearts, max_hearts: slot.vitals.maxHearts,
    magic: slot.vitals.magic, max_magic: slot.vitals.maxMagic, ammo: {...slot.counts}, capacity: {...slot.capacities},
    bottles: slot.bottles.filter(b => b.stock === 1).length, inventory, progression, songs, checkpoint};
}
function stringArray(value, label) {
  if (!Array.isArray(value) || value.length > 128 || value.some(x => typeof x !== 'string') || new Set(value).size !== value.length) throw Error(`${label} must be a bounded list of unique names.`);
  return value;
}
function changesFor(slot, request) {
  keys(request, ['wallet', 'rupees', 'hearts', 'max_hearts', 'magic', 'max_magic', 'ammo', 'capacity', 'bottles', 'bottle_fill', 'inventory', 'equipment', 'progression', 'destination', 'learn_songs'], 'change');
  if (!Object.keys(request).length) throw Error('At least one typed change is required.');
  for (const [name, value] of Object.entries(request)) if (value === null) throw Error(`${name} cannot be null.`);
  for (const name of ['rupees', 'hearts', 'max_hearts', 'magic', 'max_magic', 'bottles']) {
    if (Object.hasOwn(request, name) && (typeof request[name] !== 'number' || !Number.isFinite(request[name]))) throw Error(`${name} must be a finite number.`);
  }
  const changes = {wallet: request.wallet ?? slot.w.id, rupees: request.rupees ?? slot.rupees,
    vitals: {hearts: request.hearts ?? slot.vitals.hearts, maxHearts: request.max_hearts ?? slot.vitals.maxHearts,
      magic: request.magic ?? slot.vitals.magic, maxMagic: request.max_magic ?? slot.vitals.maxMagic},
    amounts: {...slot.counts}, upgrades: {}, bottles: request.bottles ?? slot.bottles.filter(b => b.stock === 1).length,
    additions: [], removals: [], clearAcquisitions: [], flags: []};
  if (request.ammo !== undefined) {
    keys(request.ammo, d.quantityFields.map(x => x.id), 'ammo');
    Object.assign(changes.amounts, request.ammo);
  }
  if (request.capacity !== undefined) {
    keys(request.capacity, d.capacityGroups.map(x => x.id), 'capacity');
    for (const [name, amount] of Object.entries(request.capacity)) {
      if (!Number.isInteger(amount)) throw Error('Capacity must be an integer.');
      changes.upgrades[name] = amount;
    }
  }
  if (request.bottle_fill !== undefined) {
    const entry = [...d.bottleContents].find(([, name]) => name === request.bottle_fill);
    if (!entry || !d.refillContents.has(entry[0])) throw Error('Unsupported bottle refill.');
    changes.bottleFill = entry[0];
  }
  for (const group of ['inventory', 'equipment']) {
    if (request[group] === undefined) continue;
    keys(request[group], ['add', 'remove', 'clear_acquisitions'], group);
    for (const [operation, field] of [['add', 'additions'], ['remove', 'removals'], ['clear_acquisitions', 'clearAcquisitions']]) {
      if (request[group][operation] === undefined) continue;
      for (const name of stringArray(request[group][operation], `${group}.${operation}`)) {
        const row = items.get(name);
        if (!row || (group === 'equipment' && row[2] !== 'Equipment')) throw Error(`Unsupported ${group} item: ${name}`);
        changes[field].push(row[0]);
      }
    }
  }
  for (const field of ['additions', 'removals', 'clearAcquisitions']) if (new Set(changes[field]).size !== changes[field].length) throw Error('An item was requested more than once.');
  if (request.progression !== undefined) {
    object(request.progression, 'progression');
    if (Object.keys(request.progression).length > 128) throw Error('Too many progression changes.');
    for (const [name, value] of Object.entries(request.progression)) {
      if (!namedFlags.has(name) || typeof value !== 'boolean') throw Error(`Unsupported progression flag: ${name}`);
      changes.flags.push([namedFlags.get(name), value]);
    }
  }
  return changes;
}
function diff(before, after, path = '') {
  const result = [];
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const a = before[key], b = after[key], name = path ? `${path}.${key}` : key;
    if (a && b && typeof a === 'object' && typeof b === 'object') result.push(...diff(a, b, name));
    else if (a !== b) result.push({field: name, before: a ?? null, after: b ?? null});
  }
  return result;
}
function run(request) {
  keys(request, ['operation', 'progress', 'caption', 'changes'], 'request');
  if (!['inspect', 'plan'].includes(request.operation)) throw Error('Unsupported operation.');
  const slot = d.readSlot(bytes(request.progress), bytes(request.caption));
  const before = state(slot);
  if (request.operation === 'inspect') return {state: before, supported: {wallets: d.wallets.map(x => x.id),
    equipment_slots: false, live_inventory: false, destinations: Object.keys(d.travelDestinations), songs: Object.keys(d.worldSongs)}};
  const changes = changesFor(slot, request.changes);
  const [progress, caption] = d.updateSlot(slot, changes, editCatalog);
  const p = d.readSave(progress, 0x175D8), c = d.readSave(caption, 0x2A0);
  if (request.changes.destination !== undefined) {
    if (!Object.hasOwn(d.travelDestinations, request.changes.destination)) throw Error('Unsupported checkpoint destination.');
    d.moveCheckpoint(p, c, request.changes.destination);
  }
  if (request.changes.learn_songs !== undefined) {
    const groups = stringArray(request.changes.learn_songs, 'learn_songs');
    if (!groups.length) throw Error('Choose at least one song group.');
    if (groups.some(x => !Object.hasOwn(d.worldSongs, x))) throw Error('Unsupported song group.');
    d.learnWorldSongs(p, groups, new Map(changes.flags));
    const fairy = items.get('Item_Ocarina_Fairy')[0], time = items.get('Item_Ocarina_Time')[0];
    if (p.int(fairy) === 0 && p.int(time) === 0) p.view.setInt32(p.at(fairy), 1, true);
    if ((changes.removals.includes(fairy) || changes.removals.includes(time)) && p.int(fairy) === 1) throw Error('Learning songs conflicts with removing the ocarina.');
    d.registerInventory(p, editCatalog.registrations, changes.flags);
  }
  const after = state(d.readSlot(progress, caption));
  const semantic = diff(before, after);
  return {before, after, diff: semantic, replacements: {'progress.sav': Buffer.from(progress).toString('base64'), 'caption.sav': Buffer.from(caption).toString('base64')}};
}
let chunks = [], size = 0;
process.stdin.on('data', chunk => {
  size += chunk.length;
  if (size > 6 << 20) { process.stderr.write('Input exceeds its limit.\n'); process.exit(1); }
  chunks.push(chunk);
});
process.stdin.on('end', () => {
  try { process.stdout.write(JSON.stringify({ok: true, ...run(JSON.parse(Buffer.concat(chunks).toString('utf8')))})); }
  catch (error) { process.stdout.write(JSON.stringify({ok: false, error: error.message})); process.exitCode = 1; }
});
