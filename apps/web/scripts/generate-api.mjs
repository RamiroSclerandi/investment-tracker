import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export function generateApiClient(schemaPath, typesPath) {
  execFileSync(
    'uv',
    ['run', '--project', '../api', 'python', '-m', 'investment_tracker.cli', 'export-openapi', '--output', schemaPath],
    { stdio: 'inherit' },
  )
  execFileSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', schemaPath, '-o', typesPath],
    { stdio: 'inherit' },
  )
}

if (resolve(process.argv[1] ?? '') === fileURLToPath(import.meta.url)) {
  generateApiClient('src/api/openapi.json', 'src/api/generated/schema.ts')
}
