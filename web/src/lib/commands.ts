export interface PendingCommand {
  path: string
  body: Record<string, unknown> & { client_command_id: string }
}

const prefix = 'hyperknow.command.'

export function prepareCommand(pending: PendingCommand | null, path: string | undefined, body: Record<string, unknown> | undefined, commandId: string): PendingCommand | null {
  if (pending) return pending
  return path && body ? { path, body: { ...body, client_command_id: commandId } } : null
}

export function readPending(scope: string): PendingCommand | null {
  try {
    const saved = sessionStorage.getItem(prefix + scope)
    if (!saved) return null
    const value = JSON.parse(saved) as PendingCommand
    return typeof value.path === 'string' && typeof value.body?.client_command_id === 'string' ? value : null
  } catch {
    return null
  }
}

export function savePending(scope: string, command: PendingCommand | null) {
  try {
    if (command) sessionStorage.setItem(prefix + scope, JSON.stringify(command))
    else sessionStorage.removeItem(prefix + scope)
  } catch {
    // In-memory identity still protects retries if browser storage is unavailable.
  }
}
