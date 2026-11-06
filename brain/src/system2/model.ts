/** 느린 뇌가 쓰는 언어 모델. 시험에서는 가짜 모델로 바꾼다. */

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  messages: ChatMessage[]
  /** 이 JSON Schema 모양으로만 답하게 한다 */
  format: object
  signal: AbortSignal
}

export interface LanguageModel {
  readonly name: string
  /** 답을 글 조각으로 흘려 준다 (onText). 다 받으면 끝난다. 묻지 못하거나 끊기면 오류를 던진다. */
  chat(request: ChatRequest, onText: (text: string) => void): Promise<void>
  isAvailable(): Promise<boolean>
  /** 모델을 GPU에 미리 올린다 (처음 묻는 명령이 몇 초 더 기다리지 않게) */
  warmUp(): Promise<void>
}

/** 마지막으로 쓴 뒤 이만큼 GPU에 둔다 (명령 사이가 길어도 다시 올리지 않게) */
const KEEP_ALIVE = '30m'
/** 같은 명령에 같은 계획이 나오게 낮게 (0이면 틀린 답을 다시 물어도 똑같이 틀린다) */
const TEMPERATURE = 0.2
const CHECK_TIMEOUT_MS = 2000
const LATEST_TAG = ':latest'

/** 이 PC에서 도는 Ollama (http://localhost:11434). 답은 한 줄에 JSON 하나씩 흘러온다. */
export class OllamaModel implements LanguageModel {
  constructor(
    readonly name: string,
    private readonly baseUrl: string,
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async isAvailable(): Promise<boolean> {
    try {
      const response = await this.fetcher(`${this.baseUrl}/api/tags`, { signal: AbortSignal.timeout(CHECK_TIMEOUT_MS) })
      return response.ok && listsModel(await response.json(), this.name)
    } catch {
      return false
    }
  }

  async warmUp(): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/generate`, {
      method: 'POST',
      body: JSON.stringify({ model: this.name, keep_alive: KEEP_ALIVE }),
    })
    await response.body?.cancel()
  }

  async chat({ messages, format, signal }: ChatRequest, onText: (text: string) => void): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      signal,
      body: JSON.stringify({ model: this.name, messages, format, stream: true, keep_alive: KEEP_ALIVE, options: { temperature: TEMPERATURE } }),
    })
    if (!response.ok || !response.body) {
      throw new Error(`언어 모델 서버가 ${response.status}로 답함`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      const lines = buffer.split('\n')
      buffer = done ? '' : (lines.pop() ?? '')
      for (const line of lines) {
        const text = chunkText(line)
        if (text) {
          onText(text)
        }
      }
      if (done) {
        return
      }
    }
  }
}

/** 한 줄을 경계에서 확인한다: 오류면 던지고, 글이 있으면 돌려준다 */
function chunkText(line: string): string {
  if (!line.trim()) {
    return ''
  }
  let chunk: unknown
  try {
    chunk = JSON.parse(line)
  } catch {
    throw new Error('언어 모델 서버가 JSON이 아닌 줄을 보냄')
  }
  if (!isRecord(chunk)) {
    throw new Error('언어 모델 서버가 알 수 없는 모양으로 답함')
  }
  if (typeof chunk.error === 'string') {
    throw new Error(`언어 모델 오류: ${chunk.error}`)
  }
  const message = chunk.message
  return isRecord(message) && typeof message.content === 'string' ? message.content : ''
}

function listsModel(body: unknown, name: string): boolean {
  if (!isRecord(body) || !Array.isArray(body.models)) {
    return false
  }
  const wanted = new Set([name, name.includes(':') ? name : `${name}${LATEST_TAG}`])
  return body.models.some((model: unknown) => isRecord(model) && typeof model.name === 'string' && wanted.has(model.name))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
