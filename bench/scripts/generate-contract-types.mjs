// contracts/sim/*.schema.json에서 TypeScript 타입을 만든다 (규약은 JSON Schema 한 곳에서 정한다).
// 규약을 고치면 npm run contracts 로 다시 만들고 결과도 커밋한다.
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const contracts = join(root, 'contracts', 'sim')
const target = join(root, 'bench', 'src', 'sim', 'generated')
const schemas = ['command', 'message', 'scene']

await mkdir(target, { recursive: true })
for (const name of schemas) {
  const schema = JSON.parse(await readFile(join(contracts, `${name}.schema.json`), 'utf8'))
  const types = await compile(schema, schema.title, {
    bannerComment: `// contracts/sim/${name}.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.`,
    additionalProperties: false,
    unreachableDefinitions: true,
    style: { semi: false, singleQuote: true },
  })
  await writeFile(join(target, `${name}.ts`), types)
}
console.log(`${schemas.length}개 규약에서 타입을 만들었습니다 (${target}).`)
