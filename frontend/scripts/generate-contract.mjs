// Generate the schema subset used by this client directly from the checked-in
// contract. Pydantic's nested discriminator.mapping contains objects, which
// Redocly rejects; the underlying oneOf and literal target types remain exact.
// No backend schema is patched or replaced. Unsupported type forms fail closed.
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const source = fs.readFileSync(path.join(root, '../backend/contracts/openapi.json'), 'utf8')
const contract = JSON.parse(source), schemas = contract.components.schemas
const literal = value => JSON.stringify(value)
function type(schema) {
  if (schema === true) return 'unknown'
  if (schema === false) return 'never'
  if (schema.$ref) {
    const name = schema.$ref.replace('#/components/schemas/', '')
    if (!schema.$ref.startsWith('#/components/schemas/') || !schemas[name]) throw Error(`Unresolved schema ${schema.$ref}`)
    return `components['schemas'][${literal(name)}]`
  }
  if ('const' in schema) return literal(schema.const)
  if (schema.enum) return schema.enum.map(literal).join(' | ')
  if (schema.oneOf || schema.anyOf) return '(' + (schema.oneOf || schema.anyOf).map(type).join(' | ') + ')'
  if (schema.allOf) return '(' + schema.allOf.map(type).join(' & ') + ')'
  if (Array.isArray(schema.type)) return '(' + schema.type.map(t => type({ ...schema, type: t })).join(' | ') + ')'
  switch (schema.type) {
    case 'string': return 'string'
    case 'number': case 'integer': return 'number'
    case 'boolean': return 'boolean'
    case 'null': return 'null'
    case 'array': if (!schema.items) throw Error('Untyped array'); return `Array<${type(schema.items)}>`
    case 'object': case undefined: {
      if (!schema.properties && schema.additionalProperties === undefined) return 'unknown'
      const required = new Set(schema.required || [])
      const fields = Object.entries(schema.properties || {}).map(([name, value]) => `${literal(name)}${required.has(name) ? '' : '?'}: ${type(value)}`)
      if (schema.additionalProperties && schema.additionalProperties !== true) fields.push(`[key: string]: ${type(schema.additionalProperties)}`)
      else if (schema.additionalProperties === true) fields.push('[key: string]: unknown')
      return fields.length ? `{ ${fields.join('; ')} }` : 'Record<string, never>'
    }
    default: throw Error(`Unsupported JSON Schema type: ${schema.type}`)
  }
}
const hash = crypto.createHash('sha256').update(source).digest('hex')
const output = `// Generated from backend/contracts/openapi.json. Do not edit.\n// SHA-256 ${hash}\nexport interface components {\n  schemas: {\n${Object.entries(schemas).map(([name, schema]) => `    ${literal(name)}: ${type(schema)};`).join('\n')}\n  }\n}\n`
const destination = path.join(root, 'src/api/schema.d.ts')
if (process.argv.includes('--check')) {
  if (!fs.existsSync(destination) || fs.readFileSync(destination, 'utf8') !== output) {
    console.error('Frontend contract differs. Run npm run contracts and review the backend change.'); process.exit(1)
  }
  console.log(`Frontend contract matches ${hash}`)
} else {
  fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.writeFileSync(destination, output)
  console.log(`Generated ${Object.keys(schemas).length} schemas; source SHA-256 ${hash}`)
}
