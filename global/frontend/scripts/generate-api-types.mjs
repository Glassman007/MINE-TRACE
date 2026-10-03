import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const input = path.join(root, 'src/api/generated/openapi.json')
const output = path.join(root, 'src/api/generated/types.ts')
const spec = JSON.parse(fs.readFileSync(input, 'utf8'))
const schemas = spec.components?.schemas ?? {}

function refName(ref) { return ref.split('/').at(-1) }
function uniq(items) { return [...new Set(items)] }
function ts(schema) {
  if (!schema) return 'unknown'
  if (schema.$ref) return refName(schema.$ref)
  if (schema.const !== undefined) return JSON.stringify(schema.const)
  if (Array.isArray(schema.enum)) return schema.enum.map((v) => JSON.stringify(v)).join(' | ') || 'never'
  if (Array.isArray(schema.anyOf)) return uniq(schema.anyOf.map(ts)).join(' | ')
  if (Array.isArray(schema.oneOf)) return uniq(schema.oneOf.map(ts)).join(' | ')
  if (Array.isArray(schema.allOf)) return uniq(schema.allOf.map(ts)).join(' & ')
  if (Array.isArray(schema.type)) return uniq(schema.type.map((t) => ts({ ...schema, type: t }))).join(' | ')
  switch (schema.type) {
    case 'string': return 'string'
    case 'integer':
    case 'number': return 'number'
    case 'boolean': return 'boolean'
    case 'null': return 'null'
    case 'array': return `Array<${ts(schema.items)}>`
    case 'object': {
      const props = schema.properties ?? {}
      const required = new Set(schema.required ?? [])
      const fields = Object.entries(props).map(([name, value]) => `  ${JSON.stringify(name)}${required.has(name) ? '' : '?'}: ${ts(value)};`)
      if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        if (fields.length === 0) return `Record<string, ${ts(schema.additionalProperties)}>`
        fields.push(`  [key: string]: ${ts(schema.additionalProperties)} | unknown;`)
      }
      return `{\n${fields.join('\n')}\n}`
    }
    default:
      if (schema.properties) return ts({ ...schema, type: 'object' })
      if (schema.additionalProperties && typeof schema.additionalProperties === 'object') return `Record<string, ${ts(schema.additionalProperties)}>`
      return 'unknown'
  }
}

const lines = [
  '// AUTO-GENERATED from src/api/generated/openapi.json. DO NOT EDIT BY HAND.',
  '// Regenerate with: npm run generate:api',
  '',
]
for (const name of Object.keys(schemas).sort()) {
  lines.push(`export type ${name} = ${ts(schemas[name])}`)
  lines.push('')
}
fs.writeFileSync(output, lines.join('\n'))
console.log(`generated ${path.relative(root, output)} from frozen backend OpenAPI`)
