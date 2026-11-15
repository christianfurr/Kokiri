// Pure save-domain code extracted from OoT Editor's MIT-licensed OOT-SW2SE adaptation.
// Copyright (c) 2026 Traiver; macOS additions by Christian Furr / contributors.
// See LICENSE and PROVENANCE.md. No DOM, WebView host or startup code is included.
'use strict';
const HEX = (n, width = 8) => '0x' + n.toString(16).toUpperCase().padStart(width, '0');
const utf8 = new TextEncoder();
const decode = new TextDecoder();
const wallets = [
  { id: 'Item_Wallet_Small', stock: 0x1D74617E, limit: 200, label: "Kokiri Wallet" },
  { id: 'Item_Wallet_Medium', stock: 0x2D2C874B, limit: 500, label: "Adult's Wallet" },
  { id: 'Item_Wallet_Large', stock: 0xAFA4BB52, limit: 1000, label: "Giant's Wallet" },
];
const capacityGroups = [
  { id: 'seeds', label: "Deku Seed Bag", hash: 0xAE8CC742, nameHash: 0xD732DD7F, actor: 'Item_BulletBag',
    tiers: [[30, 0xDC52ACAF], [40, 0x9A30A9E5], [50, 0x7B9673F5]] },
  { id: 'nuts', label: "Deku Nut Bag", hash: 0x735B00F7, nameHash: 0x0DA3A7A7, actor: 'Item_NutBag',
    tiers: [[20, 0x19B80DBC], [30, 0xEAA1785E], [40, 0xD60E4B23]] },
  { id: 'sticks', label: "Deku Stick Bag", hash: 0x457616B0, nameHash: 0x2808EE1C, actor: 'Item_StickBag',
    tiers: [[10, 0x2FE6AB1A], [20, 0x41DB7AB5], [30, 0x48E53698]] },
  { id: 'bombs', label: "Bomb Bag", hash: 0xE753508B,
    tiers: [[20, 0xB0A1BF51], [30, 0xE5FF45AA], [40, 0xBD3CA2C6]] },
  { id: 'arrows', label: "Quiver", hash: 0x418DB791,
    tiers: [[30, 0xA8C3E1FB], [40, 0x3BB370E1], [50, 0xD331C7DA]] },
];
const supplies = [
  { id: 'seeds', label: "Deku Seeds", stock: 0x5FADF7FC, group: 'seeds' },
  { id: 'nuts', label: "Deku Nuts", stock: 0xF30D9F54, group: 'nuts' },
  { id: 'sticks', label: "Deku Sticks", stock: 0xB9494411, group: 'sticks' },
  { id: 'arrows', label: "Arrows", stock: 0x518EC74B, group: 'arrows' },
  { id: 'bombs', label: "Bombs", stock: 0xDB1BCD4F, group: 'bombs' },
  { id: 'bombchu', label: "Bombchus", stock: 0xDF7C517A, group: 'bombs' },
  { id: 'beans', label: "Magic Beans", stock: 0xB003124D, max: 10 },
  { id: 'scrub', label: "Business Scrub Seeds", stock: 0x600E29EB, max: 30 },
  { id: 'skulltulas', label: "Gold Skulltula Tokens", stock: 0x04735978, max: 100 },
  { id: 'heartPieces', label: "Pieces of Heart", stock: 0x51EC97B3, max: 3 },
];
const smallKeys = [
  { id: 'well', label: "Bottom of the Well", stock: 0x7DD79D10, max: 2 },
  { id: 'forest', label: "Forest Temple", stock: 0x90237092, max: 5 },
  { id: 'fire', label: "Fire Temple", stock: 0x1DF11487, max: 7 },
  { id: 'water', label: "Water Temple", stock: 0x877BDCEE, max: 4 },
  { id: 'shadow', label: "Shadow Temple", stock: 0x5EDDA9E3, max: 5 },
  { id: 'spirit', label: "Spirit Temple", stock: 0x79EEEC8E, max: 5 },
  { id: 'fortress', label: "Gerudo Fortress", stock: 0x3A28B6A4, max: 4 },
  { id: 'training', label: "Gerudo Proving Grounds", stock: 0xEA9786F5, max: 8 },
  { id: 'castle', label: "Ganondorf's Castle", stock: 0xFBFD2910, max: 1 },
];
const bottleSlots = [
  [0xD53CE3A7, 0xF39CE410, 0x7D48DF76], [0xFCA29A04, 0x000FF6EA, 0x1EDD164A],
  [0x893216A1, 0xF63B1194, 0xB80C70A8], [0x5324F9D3, 0xB7F052CE, 0xE4C1B1FC],
  [0xC92B16BE, 0xE27B136D, 0x365E1953],
];
const emptyBottle = 0xBE69DE49;
const bottleContents = new Map([
  [emptyBottle, "empty"], [0xEABA6067, "red potion"], [0x049D37C1, "green potion"],
  [0xF383D6E5, "blue potion"], [0x1C293517, "blue fire"], [0x1E834EF8, "fish"],
  [0x0F24E808, "letter"], [0xCDC21471, "Big Poe"], [0x02084F9E, "Poe"],
  [0x74D62ECB, "bug"], [0x6F49E357, "fairy"], [0x73356827, "milk"], [0xEEF6E4B0, "half milk"],
]);
const refillContents = new Set([0xEABA6067, 0x049D37C1, 0xF383D6E5, 0x6F49E357, 0x73356827]);
const travelDestinations = {
  hyrule: ['Hyrule Field', 'HyruleField', [
    [[104.514, 154.897, 271.022], 1.2672, [106.44, 155.567, 271.55], [106.261, 155.508, 271.505], -104.4832],
    [[155.323, 154.149, 35.418], -1.3256, [153.946, 153.97, 35.722], [154.076, 153.984, 35.702], 97.9094],
  ]],
  kokiri: ['Kokiri Forest', 'KokiriForest', [
    [[-46.549, 118.432, 15.352], 1.649, [-46.549, 118.432, 15.352], [-46.549, 118.432, 15.352], -85.5178],
    [[-46.087, 118.439, 15.394], 1.8949, [-46.087, 118.439, 15.394], [-46.087, 118.439, 15.394], -71.433],
  ]],
  kakariko: ['Kakariko Village', 'KakarikoVillage', [
    [[-118.964, 96.68, 58.696], 1.5684, [-118.96, 96.68, 58.696], [-118.96, 96.68, 58.696], -90.1399],
    [[-2.528, 101.535, 68.747], -1.64, [-2.899, 101.519, 68.721], [-2.844, 101.521, 68.725], 85.6471],
  ]],
};

function writeWorldString(save, hash, length, value) {
  const offset = save.block(hash, length);
  save.bytes.fill(0, offset, offset + length);
  save.bytes.set(utf8.encode(value), offset);
}

function writeWorldVector(save, hash, values) {
  const offset = save.block(hash, 12);
  values.forEach((value, index) => save.view.setFloat32(offset + index * 4, value, true));
}

function moveCheckpoint(progress, caption, destination) {
  const [, region, variants] = travelDestinations[destination];
  const child = progress.int(0xCEA220D3); // Sequence_IsChildhood
  if (child !== 0 && child !== 1) throw Error('This save does not identify Link’s era.');
  const banc = region + (child ? '_Child' : '_Adult');
  const [position, facing, previous, grounded, cameraFacing] = variants[child];
  writeWorldString(progress, 0x1D6189DA, 64, banc);
  writeWorldString(progress, 0x4A6BDB7D, 32, destination === 'kokiri' ? banc : '');
  writeWorldVector(progress, 0xC884818D, position);
  writeWorldVector(progress, 0x960AD56A, previous);
  writeWorldVector(progress, 0x8773F02D, grounded);
  progress.view.setFloat32(progress.at(0x1EA93BD8), facing, true);
  progress.view.setFloat32(progress.at(0xA4AEE8CD), cameraFacing, true);
  writeWorldString(caption, 0xF74E0E8E, 64, region);
  writeWorldString(caption, 0x0CCCC6CD, 64, region + '/' + banc);
}

const worldSongs = {
  epona: [[0xB492AC33, 0xF4E14AC4]],
  sun: [[0x165DD1AD, 0x56383EA6]],
  warps: [
    [0xDC0A0B54, 0x035F129A], [0x49041AB9, 0x570522B0],
    [0x3FA63986, 0xAF0CEB1A], [0xC2FB95F4, 0xE631AD85],
    [0x802A36A8, 0xB53851E0], [0xD6320BA4, 0xEF7B5505],
  ],
};
function learnWorldSongs(save, groups, edits = new Map()) {
  for (const group of groups) {
    for (const hash of worldSongs[group].flat()) {
      if (edits.get(hash) === false) throw Error('A world song conflicts with a progress flag edit.');
      if (![0, 1].includes(save.int(hash))) throw Error('The save has an unsupported song flag.');
      save.view.setInt32(save.at(hash), 1, true);
    }
  }
}

const quantityFields = [...supplies, ...smallKeys];
const key = { rupees: 0xA77921D7, limit: 0xE0010A50, wallet: 0x3E42AFFA, previewRupees: 0xA9557547 };
const vitalsFields = [
  { id: 'hearts', progress: 0x31AB5580, caption: 0x1E55ECC5, scale: 4 },
  { id: 'maxHearts', progress: 0xFBE01DA1, caption: 0x74BD05D0, scale: 4 },
  { id: 'magic', progress: 0x76B18200, caption: 0x19F26B6A, scale: 10 },
  { id: 'maxMagic', progress: 0x12D63A97, caption: 0x943F8EC3, scale: 10 },
];
const magicStages = [
  { max: 0, label: "No Magic Meter" },
  { max: 24, label: "Standard Magic Meter · 24 MP", blessing: 0x5E671D92 },
  { max: 48, label: "Double Magic Meter · 48 MP", blessing: 0x5F043856 },
];
const voiceHash = 0xA2DCDC9D;
const voiceLanguages = new Map([
  [0x69B014CE, "Japanese"], [0x82591FA9, "English"], [0x2498C397, "French (France)"],
  [0x7D30FC45, "French (Canada)"], [0x515B9EEB, "German"], [0x33C26987, "Spanish (Spain)"],
  [0xA683B1FD, "Spanish (Latin America)"], [0x8D62C251, "Italian"], [0x1C3498EB, "Portuguese (Brazil)"],
]);

function readSave(bytes, headerEnd) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u32 = o => view.getUint32(o, true);
  if (bytes.length < headerEnd || u32(0) !== 0x01020304 ||
      u32(4) !== 0x002D80EB || u32(8) !== headerEnd) {
    throw Error("This file does not match the supported Switch 2 save format.");
  }
  const fields = new Map();
  for (let o = 40; o < headerEnd; o += 8) {
    const hash = u32(o);
    if (!hash) continue;
    if (fields.has(hash)) throw Error("Duplicate field hash: " + HEX(hash));
    fields.set(hash, o + 4);
  }
  function at(hash) {
    if (!fields.has(hash)) throw Error("Required field missing: " + HEX(hash));
    return fields.get(hash);
  }
  function block(hash, len) {
    const o = u32(at(hash));
    if (o < headerEnd || o > bytes.length - len) throw Error("Invalid data offset: " + HEX(hash));
    return o;
  }
  const int = h => view.getInt32(at(h), true);
  const textAt = (o, len) => {
    const raw = bytes.subarray(o, o + len);
    const nul = raw.indexOf(0);
    return decode.decode(nul < 0 ? raw : raw.subarray(0, nul));
  };
  const string = (h, len) => textAt(block(h, len), len);
  return { bytes, view, fields, u32, at, int, block, string, textAt };
}

function readSlot(progress, caption) {
  const p = readSave(progress, 0x175D8);
  const c = readSave(caption, 0x2A0);
  const w = wallets.find(w => w.id === p.string(key.wallet, 64));
  if (!w || p.int(key.limit) !== w.limit || p.int(w.stock) !== 1) {
    throw Error("The wallet, ownership flag, and rupee limit are inconsistent.");
  }
  const rupees = p.int(key.rupees);
  if (rupees < 0) throw Error("Unexpected rupee count in progress.sav.");
  c.at(key.previewRupees);
  const capacities = Object.fromEntries(capacityGroups.map(group => [group.id, p.int(group.hash)]));
  const counts = Object.fromEntries(quantityFields.map(item => [item.id, p.int(item.stock)]));
  if (Object.values(counts).some(n => n < 0) || Object.values(capacities).some(n => n < 0 || n > 9999)) {
    throw Error("Unexpected inventory quantity in the save.");
  }
  const bottles = bottleSlots.map(([stock, valid, content]) => ({
    stock: p.int(stock), valid: p.int(valid), content: p.u32(p.at(content)),
  }));
  const storedMagicMax = p.int(0x12D63A97);
  const legacyMagic = magicStages.some(stage => stage.blessing && stage.max === storedMagicMax);
  const vitals = Object.fromEntries(vitalsFields.map(({ id, progress, caption, scale }) => {
    c.at(caption);
    const fromLegacyEditor = legacyMagic && (id === 'magic' || id === 'maxMagic');
    return [id, p.int(progress) / (fromLegacyEditor ? 1 : scale)];
  }));
  return { p, c, w, rupees, capacities, counts, bottles, vitals, legacyMagic };
}

function readOptions(bytes) {
  const save = readSave(bytes, 0x2A0);
  const language = save.u32(save.at(voiceHash));
  if (!voiceLanguages.has(language)) throw Error("Unknown voice language value.");
  return { save, language };
}

function updateOptions(options, language) {
  if (!voiceLanguages.has(language)) throw Error("Unknown voice language.");
  const copy = readSave(options.save.bytes.slice(), 0x2A0);
  copy.view.setUint32(copy.at(voiceHash), language, true);
  return copy.bytes;
}

function checkedInt(value, max, label) {
  if (!Number.isInteger(value) || value < 0 || value > max) throw Error(label + " must be between 0 and " + max + ".");
  return value;
}

function amountLimit(slot, item, upgrades = {}) {
  const group = capacityGroups.find(group => group.id === item.group);
  if (group && upgrades[group.id] !== undefined) return upgrades[group.id];
  const cap = group ? Math.max(slot.capacities[group.id], group.tiers.at(-1)[0]) : item.max;
  return Math.max(cap, slot.counts[item.id]);
}

function tierSelectable(slot, group, [limit, stock]) {
  const current = slot.capacities[group.id];
  return limit > current || (group.id === 'seeds' && limit < current && slot.p.int(stock) === 1);
}

function plannedUpgrades(slot, amounts, upgrades = {}) {
  return capacityGroups.flatMap(group => {
    const capacity = slot.capacities[group.id];
    const selected = upgrades[group.id];
    if (selected !== undefined) {
      const tier = group.tiers.findIndex(([limit]) => limit === selected);
      if (tier < 0 || !tierSelectable(slot, group, group.tiers[tier])) throw Error("Invalid capacity tier for " + group.label + '.');
      return [{ group, tier, limit: selected }];
    }
    const increased = supplies.filter(item => item.group === group.id && amounts[item.id] > slot.counts[item.id]);
    const requested = Math.max(...increased.map(item => amounts[item.id]));
    if (requested <= capacity) return [];
    const tier = group.tiers.findIndex(([limit]) => limit >= requested);
    return tier < 0 ? [] : [{ group, tier, limit: group.tiers[tier][0] }];
  });
}

function setBottleCount(slot, p, requested) {
  const owned = slot.bottles.flatMap((bottle, i) => bottle.stock === 1 ? [i] : []);
  if (requested === owned.length) return;
  if (slot.bottles.some(b => (b.stock !== 0 && b.stock !== 1) || b.stock !== b.valid)) {
    throw Error("The bottle ownership fields are inconsistent.");
  }
  const delta = requested - owned.length;
  const affected = delta > 0
    ? slot.bottles.flatMap((bottle, i) => bottle.stock === 0 ? [i] : []).slice(0, delta)
    : owned.slice(requested);
  for (const i of affected) {
    const [stock, valid, content] = bottleSlots[i];
    const value = Number(delta > 0);
    p.view.setInt32(p.at(stock), value, true);
    p.view.setInt32(p.at(valid), value, true);
    p.view.setUint32(p.at(content), emptyBottle, true);
  }
}

function missingRegistrations(save, registrations) {
  return registrations.filter(([stocks, acquired]) =>
    save.fields.has(acquired) && save.int(acquired) === 0 &&
    stocks.some(hash => save.fields.has(hash) && save.int(hash) > 0));
}

function registerInventory(save, registrations, manualFlags) {
  const manual = new Map(manualFlags);
  for (const [, acquired, related, name] of missingRegistrations(save, registrations)) {
    for (const hash of [acquired, related]) {
      if (!hash || !save.fields.has(hash)) continue;
      if (manual.get(hash) === false) throw Error("The item and its acquisition flag conflict: " + name);
      save.view.setInt32(save.at(hash), 1, true);
    }
  }
}

const equippedItemFields = [0xA95A3521, 0xEE463235, 0xA1F7EE2B, 0x2342B619];

function removalIssue(save, hash, editCatalog) {
  if (!editCatalog.removable.has(hash) || !save.fields.has(hash) || save.int(hash) !== 1) {
    return 'Only supported, owned single items can be removed here.';
  }
  const name = editCatalog.items.get(hash);
  // Do not guess the game's empty equipment value or silently change equipment.
  for (const field of equippedItemFields) {
    if (!save.fields.has(field)) return 'The equipment fields could not be checked.';
    if (save.string(field, 64) === name) return 'Unequip this item in both eras before removing it.';
  }
  return '';
}

function acquisitionFlags(save, hash, registrations) {
  const entries = registrations.filter(([stocks]) => stocks.includes(hash));
  const hashes = [...new Set(entries.flatMap(([, acquired, related]) => [acquired, related].filter(Boolean)))];
  if (!hashes.length || hashes.some(h => !save.fields.has(h) || ![0, 1].includes(save.int(h)))) {
    throw Error('The acquisition flags cannot be safely edited for ' + HEX(hash));
  }
  return hashes;
}

function removeInventory(slot, save, changes, editCatalog) {
  const removals = new Set(changes.removals ?? []);
  const clears = new Set(changes.clearAcquisitions ?? []);
  const additions = new Set(changes.additions);
  const manual = new Map(changes.flags);
  for (const hash of removals) {
    const issue = removalIssue(slot.p, hash, editCatalog);
    if (issue) throw Error(issue + ' ' + editCatalog.items.get(hash));
    if (additions.has(hash)) throw Error('An item cannot be added and removed in the same patch.');
    save.view.setInt32(save.at(hash), 0, true);
  }
  const resetFlags = new Set();
  for (const hash of clears) {
    if (!removals.has(hash)) throw Error('Clearing acquisition flags requires removing the item.');
    for (const flag of acquisitionFlags(save, hash, editCatalog.registrations)) resetFlags.add(flag);
  }
  for (const flag of resetFlags) {
    if (manual.get(flag) === true) throw Error('A Progress flag conflicts with clearing acquisition flags: ' + HEX(flag));
    const stillOwned = editCatalog.registrations.some(([stocks, acquired, related]) =>
      (acquired === flag || related === flag) && stocks.some(h => save.fields.has(h) && save.int(h) > 0));
    if (stillOwned) throw Error('An acquisition flag is shared with an item still in inventory: ' + HEX(flag));
    save.view.setInt32(save.at(flag), 0, true);
  }
}

function writeVitals(slot, p, c, vitals) {
  const { maxHearts, hearts, maxMagic, magic } = vitals;
  if (!Number.isInteger(maxHearts) || maxHearts < 3 || maxHearts > 20) {
    throw Error("Max hearts must be between 3 and 20.");
  }
  if (!Number.isInteger(hearts * 4) || hearts < 0 || hearts > maxHearts) {
    throw Error("Current hearts must be between 0 and the maximum, in quarter-heart steps.");
  }
  const allowedStage = magicStages.some(stage => stage.max === maxMagic);
  const currentStage = magicStages.some(stage => stage.max === slot.vitals.maxMagic);
  if (!allowedStage || (currentStage && maxMagic < slot.vitals.maxMagic)) {
    throw Error("Select the current magic meter or an upgrade.");
  }
  const rawMagic = Math.round(magic * 10);
  if (rawMagic / 10 !== magic || magic < 0 || magic > maxMagic) {
    throw Error("Magic points must be between 0 and " + maxMagic + ", in tenths.");
  }
  for (const { id, progress, caption, scale } of vitalsFields) {
    const value = id === 'magic' ? rawMagic : vitals[id] * scale;
    p.view.setInt32(p.at(progress), value, true);
    c.view.setInt32(c.at(caption), value, true);
  }
  if (maxMagic > slot.vitals.maxMagic || slot.legacyMagic) {
    for (const { max, blessing } of magicStages) {
      if (blessing && max <= maxMagic) p.view.setInt32(p.at(blessing), 1, true);
    }
  }
}

function updateSlot(slot, changes, editCatalog) {
  const wallet = wallets.find(w => w.id === changes.wallet);
  if (!wallet) throw Error("Unknown wallet.");
  const rupees = checkedInt(changes.rupees, wallet.limit, "Rupees");
  const p = readSave(slot.p.bytes.slice(), 0x175D8);
  const c = readSave(slot.c.bytes.slice(), 0x2A0);
  const set = (save, hash, value) => save.view.setInt32(save.at(hash), value, true);
  if (wallet !== slot.w) {
    const o = p.block(key.wallet, 64);
    p.bytes.fill(0, o, o + 64);
    p.bytes.set(utf8.encode(wallet.id), o);
    set(p, key.limit, wallet.limit);
    for (const w of wallets) set(p, w.stock, Number(w === wallet));
  }
  set(p, key.rupees, rupees);
  set(c, key.previewRupees, rupees);
  writeVitals(slot, p, c, changes.vitals ?? slot.vitals);
  const upgrades = changes.upgrades ?? {};
  const pendingUpgrades = plannedUpgrades(slot, changes.amounts, upgrades);
  for (const item of quantityFields) {
    const value = checkedInt(changes.amounts[item.id], amountLimit(slot, item, upgrades), item.label);
    set(p, item.stock, value);
  }
  for (const { group, tier, limit } of pendingUpgrades) {
    set(p, group.hash, limit);
    if (limit > slot.capacities[group.id]) {
      for (const [, stock] of group.tiers.slice(0, tier + 1)) set(p, stock, 1);
    }
    if (group.nameHash) {
      const id = group.actor + '_' + ['Small', 'Medium', 'Large'][tier];
      const offset = p.block(group.nameHash, 64);
      p.bytes.fill(0, offset, offset + 64);
      p.bytes.set(utf8.encode(id), offset);
    }
  }
  setBottleCount(slot, p, checkedInt(changes.bottles, bottleSlots.length, "Bottles"));
  if (changes.bottleFill) {
    if (!refillContents.has(changes.bottleFill)) throw Error("Unsupported bottle contents.");
    for (const [stock, valid, content] of bottleSlots) {
      if (p.int(stock) === 1 && p.int(valid) === 1 && p.u32(p.at(content)) === emptyBottle) {
        p.view.setUint32(p.at(content), changes.bottleFill, true);
      }
    }
  }
  for (const hash of changes.additions) {
    if (!editCatalog.addable.has(hash) || slot.p.int(hash) !== 0) {
      throw Error("This item cannot be added here: " + HEX(hash));
    }
    set(p, hash, 1);
  }
  removeInventory(slot, p, changes, editCatalog);
  registerInventory(p, editCatalog.registrations, changes.flags);
  for (const [hash, checked] of changes.flags) {
    const before = slot.p.u32(slot.p.at(hash));
    if (!editCatalog.flags.has(hash) || (before !== 0 && before !== 1) || typeof checked !== 'boolean') {
      throw Error("This flag cannot be edited here: " + HEX(hash));
    }
    set(p, hash, Number(checked));
  }
  readSlot(p.bytes, c.bytes);
  return [p.bytes, c.bytes];
}

function editOptions(catalog) {
  return {
    addable: new Set(catalog.inventory.filter(item => item[3]).map(item => item[0])),
    removable: new Set(catalog.inventory.filter(item => item[3] &&
      !['Armor_Adult_Normal', 'Obj_Armor_Child_Normal'].includes(item[1])).map(item => item[0])),
    items: new Map(catalog.inventory.map(([hash, name]) => [hash, name])),
    flags: new Set(catalog.fields.filter(([, type, name]) => name && catalog.types[type] === 'Bool').map(item => item[0])),
    registrations: catalog.registrations,
  };
}


module.exports = { readSave, readSlot, updateSlot, editOptions, moveCheckpoint, learnWorldSongs, registerInventory,
 wallets, capacityGroups, quantityFields, supplies, smallKeys, bottleSlots, emptyBottle,
 bottleContents, refillContents, vitalsFields, key, equippedItemFields, travelDestinations, worldSongs };
