/** 맨 위 값(say·retreatBelowHp)을 다 받았거나, 단계 하나를 다 받았다. value는 JSON으로 읽은 값 (읽지 못하면 undefined) */
export type StreamPiece = { kind: 'field'; key: string; value: unknown } | { kind: 'step'; value: unknown }

const STEPS_KEY = 'steps'
/** 맨 위 객체 안 = 1, steps 배열 안 = 2, 단계 객체 안 = 3 */
const ROOT_DEPTH = 1
const STEP_DEPTH = 3

/**
 * 언어 모델이 흘려 보내는 계획 JSON에서 다 받은 값을 먼저 꺼낸다. 계획 전체(약 3초)를 기다리지 않고 첫 단계(약 1.5초)부터 시작하려고.
 * 글자를 한 번씩만 보며 문자열 안의 괄호·쉼표는 건너뛴다. 꺼낸 값은 아직 확인하지 않은 값이다 (planCheck가 본다).
 */
export class PlanStreamReader {
  private text = ''
  private depth = 0
  private inString = false
  private escaped = false
  private expectingKey = false
  private keyStart = -1
  private key: string | null = null
  private valueStart = -1
  private stepStart = -1

  push(chunk: string): StreamPiece[] {
    const pieces: StreamPiece[] = []
    const from = this.text.length
    this.text += chunk
    for (let index = from; index < this.text.length; index++) {
      this.scan(index, pieces)
    }
    return pieces
  }

  private scan(index: number, pieces: StreamPiece[]): void {
    const char = this.text[index]
    if (this.inString) {
      this.scanString(char, index)
      return
    }
    switch (char) {
      case '"':
        this.inString = true
        if (this.depth === ROOT_DEPTH && this.expectingKey) {
          this.keyStart = index
        }
        return
      case '{':
      case '[':
        this.depth++
        if (this.depth === ROOT_DEPTH) {
          this.expectingKey = true
        } else if (char === '{' && this.depth === STEP_DEPTH && this.key === STEPS_KEY) {
          this.stepStart = index
        }
        return
      case '}':
      case ']':
        if (char === '}' && this.depth === STEP_DEPTH && this.stepStart >= 0) {
          pieces.push({ kind: 'step', value: parseJson(this.text.slice(this.stepStart, index + 1)) })
          this.stepStart = -1
        } else if (this.depth === ROOT_DEPTH) {
          this.endField(index, pieces)
        }
        this.depth--
        return
      case ':':
        if (this.depth === ROOT_DEPTH) {
          this.valueStart = index + 1
        }
        return
      case ',':
        if (this.depth === ROOT_DEPTH) {
          this.endField(index, pieces)
          this.expectingKey = true
        }
        return
    }
  }

  private scanString(char: string | undefined, index: number): void {
    if (this.escaped) {
      this.escaped = false
    } else if (char === '\\') {
      this.escaped = true
    } else if (char === '"') {
      this.inString = false
      if (this.keyStart >= 0) {
        const key = parseJson(this.text.slice(this.keyStart, index + 1))
        this.key = typeof key === 'string' ? key : null
        this.keyStart = -1
        this.expectingKey = false
      }
    }
  }

  private endField(end: number, pieces: StreamPiece[]): void {
    if (this.key !== null && this.key !== STEPS_KEY && this.valueStart >= 0) {
      pieces.push({ kind: 'field', key: this.key, value: parseJson(this.text.slice(this.valueStart, end)) })
    }
    this.key = null
    this.valueStart = -1
  }
}

export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}
