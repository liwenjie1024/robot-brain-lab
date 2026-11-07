import type { CommandResult, OutgoingCommand, SimClientEvents } from './simClient'

/**
 * 몸과의 연결이 갖출 것. 몸의 WebSocket에 바로 붙거나(SimClient) ROS 2로 붙거나(RosBodyClient) 두뇌는 같은 모양으로 쓴다.
 * 실제 로봇을 붙여도 이 모양만 맞추면 빠른 뇌·느린 뇌·시험은 그대로다.
 */
export interface BodyLink {
  on<K extends keyof SimClientEvents>(event: K, listener: SimClientEvents[K]): () => void
  connect(): void | Promise<void>
  retry(): void
  close(): void
  send(command: OutgoingCommand): Promise<CommandResult>
}
