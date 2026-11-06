import { describe, expect, it } from 'vitest'
import { OllamaModel } from './model'

const BASE_URL = 'http://ollama.test'

/** 정한 조각을 차례로 흘리는 HTTP 답 */
function streamed(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
  return new Response(body, { status })
}

function fakeFetch(respond: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const calls: { url: string; body: unknown }[] = []
  const fetcher = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined })
    return respond(url, init)
  }) as typeof fetch
  return { fetcher, calls }
}

async function chat(model: OllamaModel): Promise<string[]> {
  const texts: string[] = []
  await model.chat({ messages: [{ role: 'user', content: '공격' }], format: { type: 'object' }, signal: new AbortController().signal }, (text) => texts.push(text))
  return texts
}

describe('OllamaModel', () => {
  it('한 줄에 하나씩 오는 답을 조각이 줄 중간에서 끊겨 와도 글 조각으로 흘려 준다', async () => {
    const { fetcher, calls } = fakeFetch(() =>
      streamed(['{"message":{"content":"{\\"sa"}}\n{"mess', 'age":{"content":"y\\":"}}\n', '\n{"done":true,"eval_count":2}\n']),
    )
    const model = new OllamaModel('qwen2.5:7b', BASE_URL, fetcher)

    expect(await chat(model)).toEqual(['{"sa', 'y":'])
    expect(calls[0]).toMatchObject({
      url: `${BASE_URL}/api/chat`,
      body: { model: 'qwen2.5:7b', stream: true, format: { type: 'object' }, keep_alive: '30m', options: { temperature: 0.2 } },
    })
  })

  it('마지막 줄에 줄바꿈이 없어도 읽는다', async () => {
    const { fetcher } = fakeFetch(() => streamed(['{"message":{"content":"끝"}}']))

    expect(await chat(new OllamaModel('qwen2.5:7b', BASE_URL, fetcher))).toEqual(['끝'])
  })

  it.each([
    ['서버 오류 상태', () => streamed([], 500), '언어 모델 서버가 500로 답함'],
    ['오류 줄', () => streamed(['{"error":"model not found"}\n']), '언어 모델 오류: model not found'],
    ['JSON이 아닌 줄', () => streamed(['<html>\n']), 'JSON이 아닌 줄'],
    ['객체가 아닌 줄', () => streamed(['42\n']), '알 수 없는 모양'],
  ])('실패: %s이면 까닭을 붙여 던진다', async (_, respond, reason) => {
    const { fetcher } = fakeFetch(respond)

    await expect(chat(new OllamaModel('qwen2.5:7b', BASE_URL, fetcher))).rejects.toThrow(reason)
  })

  it.each([
    ['이름이 같음', 'qwen2.5:7b', [{ name: 'qwen2.5:7b' }], true],
    ['태그 없이 고르면 latest', 'llama3', [{ name: 'llama3:latest' }], true],
    ['다른 모델만 있음', 'qwen2.5:7b', [{ name: 'qwen2.5:14b' }], false],
    ['모델이 없음', 'qwen2.5:7b', [], false],
  ])('쓸 수 있는지: %s', async (_, name, models, available) => {
    const { fetcher } = fakeFetch(() => Response.json({ models }))

    expect(await new OllamaModel(name, BASE_URL, fetcher).isAvailable()).toBe(available)
  })

  it.each([
    ['서버가 꺼짐', () => Promise.reject(new TypeError('fetch failed'))],
    ['모양이 다른 답', () => Response.json({ tags: [] })],
    ['오류 상태', () => new Response('', { status: 503 })],
  ])('실패: %s이면 쓸 수 없다고 본다', async (_, respond) => {
    const { fetcher } = fakeFetch(respond)

    expect(await new OllamaModel('qwen2.5:7b', BASE_URL, fetcher).isAvailable()).toBe(false)
  })

  it('미리 올리기는 프롬프트 없이 모델과 keep_alive만 보낸다', async () => {
    const { fetcher, calls } = fakeFetch(() => Response.json({ done: true }))

    await new OllamaModel('qwen2.5:7b', BASE_URL, fetcher).warmUp()

    expect(calls).toEqual([{ url: `${BASE_URL}/api/generate`, body: { model: 'qwen2.5:7b', keep_alive: '30m' } }])
  })
})
