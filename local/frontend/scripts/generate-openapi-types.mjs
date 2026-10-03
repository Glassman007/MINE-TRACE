import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const inputPath = path.join(root, 'contracts', 'openapi.json')
const outputPath = path.join(root, 'src', 'api', 'generated', 'openapi.ts')
const check = process.argv.includes('--check')

const document = JSON.parse(fs.readFileSync(inputPath, 'utf8'))
const schemas = document.components?.schemas ?? {}

function refName(ref) {
  const prefix = '#/components/schemas/'
  if (!ref.startsWith(prefix)) throw new Error(`Unsupported ref: ${ref}`)
  return decodeURIComponent(ref.slice(prefix.length).replaceAll('~1', '/').replaceAll('~0', '~'))
}

function literal(value) {
  if (typeof value === 'string') return JSON.stringify(value)
  if (value === null) return 'null'
  return String(value)
}

function renderSchema(schema, level = 0) {
  if (!schema || typeof schema !== 'object') return 'unknown'
  if (schema.$ref) return `components["schemas"][${JSON.stringify(refName(schema.$ref))}]`
  if (Object.hasOwn(schema, 'const')) return literal(schema.const)
  if (Array.isArray(schema.enum)) return schema.enum.map(literal).join(' | ') || 'never'
  if (Array.isArray(schema.anyOf)) return schema.anyOf.map((item) => renderSchema(item, level)).join(' | ')
  if (Array.isArray(schema.oneOf)) return schema.oneOf.map((item) => renderSchema(item, level)).join(' | ')
  if (Array.isArray(schema.allOf)) return schema.allOf.map((item) => renderSchema(item, level)).join(' & ')

  const type = schema.type
  if (type === 'string') return 'string'
  if (type === 'integer' || type === 'number') return 'number'
  if (type === 'boolean') return 'boolean'
  if (type === 'null') return 'null'
  if (type === 'array') return `Array<${renderSchema(schema.items ?? {}, level)}>`

  if (type === 'object' || schema.properties || schema.additionalProperties !== undefined) {
    const required = new Set(schema.required ?? [])
    const props = schema.properties ?? {}
    const indent = '  '.repeat(level + 1)
    const closing = '  '.repeat(level)
    const lines = []
    for (const [name, value] of Object.entries(props)) {
      const optional = required.has(name) ? '' : '?'
      lines.push(`${indent}${JSON.stringify(name)}${optional}: ${renderSchema(value, level + 1)};`)
    }
    if (schema.additionalProperties === true) {
      lines.push(`${indent}[key: string]: unknown;`)
    } else if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
      lines.push(`${indent}[key: string]: ${renderSchema(schema.additionalProperties, level + 1)};`)
    }
    if (lines.length === 0) return 'Record<string, never>'
    return `{\n${lines.join('\n')}\n${closing}}`
  }

  return 'unknown'
}

const schemaLines = Object.entries(schemas).map(([name, schema]) => {
  return `    ${JSON.stringify(name)}: ${renderSchema(schema, 2)};`
})

const content = `/* eslint-disable */\n/**\n * AUTO-GENERATED from contracts/openapi.json.\n * Do not edit by hand. Run: npm run api:types\n */\n\nexport interface components {\n  schemas: {\n${schemaLines.join('\n')}\n  };\n}\n`

if (check) {
  const existing = fs.existsSync(outputPath) ? fs.readFileSync(outputPath, 'utf8') : ''
  if (existing !== content) {
    console.error('Generated OpenAPI TypeScript snapshot is out of date. Run npm run api:types.')
    process.exit(1)
  }
  console.log('Generated OpenAPI TypeScript snapshot is current.')
} else {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true })
  fs.writeFileSync(outputPath, content)
  console.log(`Wrote ${path.relative(root, outputPath)} from ${path.relative(root, inputPath)}.`)
}
