// 照 contracts/sim/*.schema.json 生成 TypeScript 的类型（规约只写在 JSON Schema 那一处）。
// 改了规约以后运行 npm run contracts 重新生成，生成的文件也要提交。
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = join(root, 'contracts', 'sim')
const target = join(root, 'view', 'src', 'generated')
const names = ['scene', 'message', 'command']

await mkdir(target, { recursive: true })
for (const name of names) {
  const schema = JSON.parse(await readFile(join(source, `${name}.schema.json`), 'utf8'))
  const types = await compile(schema, schema.title, {
    bannerComment: `// 这个文件是照 contracts/sim/${name}.schema.json 生成的。不要手改：改规约，再运行 npm run contracts。`,
    cwd: source,
    additionalProperties: false,
    unreachableDefinitions: true,
    style: { semi: false, singleQuote: true },
  })
  await writeFile(join(target, `${name}.ts`), types)
}
console.log(`照 ${names.length} 份规约生成了类型（view/src/generated）。`)
