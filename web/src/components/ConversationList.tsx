import type { ConversationSummary } from "../api/types";

type Props = { conversations: ConversationSummary[]; selectedId: string | null; loading: boolean; error: string | null; onNew: () => void; onSelect: (id: string) => void };

export function ConversationList({ conversations, selectedId, loading, error, onNew, onSelect }: Props) {
  return <aside className="conversation-list" aria-labelledby="conversations-title">
    <div className="conversation-list__heading"><div><p className="eyebrow">Saved in this workspace</p><h2 id="conversations-title">Conversations</h2></div><button type="button" onClick={onNew} disabled={loading}>New conversation</button></div>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {loading && conversations.length === 0 ? <p className="conversation-list__empty" role="status">Loading conversations…</p> : conversations.length > 0 ? <nav aria-label="Conversations"><ol>{conversations.map((conversation) => <li key={conversation.id}><button type="button" aria-current={conversation.id === selectedId ? "page" : undefined} onClick={() => onSelect(conversation.id)}><strong>{conversation.title}</strong><time dateTime={conversation.updated_at}>{new Date(conversation.updated_at).toLocaleString()}</time></button></li>)}</ol></nav> : <p className="conversation-list__empty">Start a conversation to save it here.</p>}
  </aside>;
}
