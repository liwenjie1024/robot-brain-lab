// contracts/*/*.schema.json에서 TypeScript 타입을 만든다 (규약은 JSON Schema 한 곳에서 정한다).
// 규약을 고치면 npm run contracts 로 다시 만들고 결과도 커밋한다.
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
// 규약 묶음(contracts 아래 폴더) → 만든 타입을 둘 곳(shared/src 아래)
const groups = {
  sim: ['command', 'message', 'scene'],
  brain: ['control', 'status', 'plan'],
}

let count = 0
for (const [group, schemas] of Object.entries(groups)) {
  const target = join(root, 'shared', 'src', group, 'generated')
  await mkdir(target, { recursive: true })
  for (const name of schemas) {
    const schema = JSON.parse(await readFile(join(root, 'contracts', group, `${name}.schema.json`), 'utf8'))
    const types = await compile(schema, schema.title, {
      bannerComment: `// contracts/${group}/${name}.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.`,
      // 다른 규약 파일을 가리키는 $ref(예: status → control.schema.json#/$defs/TrialSetup)를 같은 폴더에서 찾는다
      cwd: join(root, 'contracts', group),
      additionalProperties: false,
      unreachableDefinitions: true,
      style: { semi: false, singleQuote: true },
    })
    await writeFile(join(target, `${name}.ts`), types)
    count++
  }
}
console.log(`규약 ${count}개에서 타입을 만들었습니다 (shared/src/*/generated).`)
