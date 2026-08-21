const fs = require('fs');
const path = require('path');

const BASE = 'C:/Users/Administrator/AppData/Local/npm-cache/_npx/a8a7eec953f1f314/node_modules';
const DEFS = path.join(BASE, 'n8n-nodes-base/dist/node-definitions/nodes/n8n-nodes-base');

let z;
for (const p of [path.join(BASE, 'zod'), path.join(BASE, 'n8n-nodes-base/node_modules/zod')]) {
  try { z = require(p).z || require(p); break; } catch (e) {}
}
if (!z) { console.error('zod not found'); process.exit(2); }

const any = z.any();
const helpers = {
  z,
  expressionSchema: any,
  stringOrExpression: any,
  numberOrExpression: any,
  booleanOrExpression: any,
  resourceLocatorValueSchema: any,
  resourceMapperValueSchema: any,
  filterValueSchema: any,
  assignmentCollectionValueSchema: any,
  iDataObjectSchema: any,
};

function isDisplayed(parameters, displayOptions, defaults) {
  if (!displayOptions) return true;
  const eff = Object.assign({}, defaults || {}, parameters || {});
  for (const [k, vals] of Object.entries(displayOptions.show || {})) {
    if (Array.isArray(vals) && !vals.includes(eff[k])) return false;
  }
  for (const [k, vals] of Object.entries(displayOptions.hide || {})) {
    if (Array.isArray(vals) && vals.includes(eff[k])) return false;
  }
  return true;
}

helpers.resolveSchema = ({ parameters, schema, required, displayOptions, defaults }) => {
  if (!isDisplayed(parameters, displayOptions, defaults)) return z.any().optional();
  return required ? schema : schema.optional();
};

helpers.resolveOneOfSchemas = ({ parameters, variants }) => {
  const active = (variants || []).filter(v => isDisplayed(parameters, v.displayOptions, v.defaults));
  if (!active.length) return z.any().optional();
  const chosen = active.find(v => v.required) || active[0];
  return chosen.required ? chosen.schema : chosen.schema.optional();
};

function verKey(v) {
  const s = String(v);
  return 'v' + s.replace('.', '');
}

const files = process.argv.slice(2);
let fail = 0, checked = 0;

for (const f of files) {
  const wf = JSON.parse(fs.readFileSync(f, 'utf8'));
  console.log(`\n=== ${path.basename(f)} (${wf.nodes.length} nodes) ===`);
  for (const node of wf.nodes) {
    const short = node.type.replace('n8n-nodes-base.', '');
    const dir = path.join(DEFS, short);
    if (!fs.existsSync(dir)) { console.log(`  ✗ ${node.name}: node type dir missing (${short})`); fail++; continue; }
    const schemaFile = path.join(dir, `${verKey(node.typeVersion)}.schema.js`);
    if (!fs.existsSync(schemaFile)) {
      const avail = fs.readdirSync(dir).filter(n => n.endsWith('.schema.js')).join(',');
      console.log(`  ~ ${node.name}: no schema for typeVersion ${node.typeVersion} (have: ${avail || 'none'}) - skipped`);
      continue;
    }
    try {
      const schema = require(schemaFile)({ parameters: node.parameters, ...helpers });
      schema.parse({ parameters: node.parameters });
      console.log(`  ✓ ${node.name} [${short}@${node.typeVersion}]`);
      checked++;
    } catch (e) {
      const msg = e.issues ? JSON.stringify(e.issues).slice(0, 400) : String(e).slice(0, 300);
      console.log(`  ✗ ${node.name} [${short}@${node.typeVersion}]: ${msg}`);
      fail++;
    }
  }
}
console.log(`\nvalidated=${checked} failed=${fail}`);
process.exit(fail ? 1 : 0);
