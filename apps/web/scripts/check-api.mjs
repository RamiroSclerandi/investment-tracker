import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { generateApiClient } from './generate-api.mjs'

const committed = {
  'src/api/openapi.json': 'openapi.json',
  'src/api/generated/schema.ts': 'schema.ts',
}

const normalize = (path) => readFileSync(path, 'utf8').replaceAll('\r\n', '\n')

const scratch = mkdtempSync(join(tmpdir(), 'api-check-'))
try {
  const schemaPath = join(scratch, 'openapi.json')
  const typesPath = join(scratch, 'schema.ts')
  generateApiClient(schemaPath, typesPath)

  const fresh = { 'openapi.json': schemaPath, 'schema.ts': typesPath }
  const stale = Object.entries(committed).filter(
    ([path, name]) => normalize(path) !== normalize(fresh[name]),
  )
  if (stale.length > 0) {
    console.error(`Generated API client is stale: ${stale.map(([path]) => path).join(', ')}`)
    console.error('Run "pnpm api:generate" and commit the result.')
    process.exitCode = 1
  } else {
    console.log('Generated API client is up to date.')
  }
} finally {
  rmSync(scratch, { recursive: true, force: true })
}
