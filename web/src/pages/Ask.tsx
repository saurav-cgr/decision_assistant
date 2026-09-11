import { type FormEvent, useEffect, useState } from "react";

import { appendConversationMessage, createConversation, getConversation, listConversations } from "../api/client";
import type { ConversationDetail, ConversationSummary } from "../api/types";
import { ConversationList } from "../components/ConversationList";
import { ConversationThread } from "../components/ConversationThread";
import "./AskCore.css";
import "./Ask.css";

function message(error: unknown) {
  return error instanceof Error ? error.message : "Conversation could not be loaded.";
}

export function Ask() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const select = async (id: string) => {
    setLoading(true); setError(null);
    try { setConversation(await getConversation(id)); } catch (caught) { setError(message(caught)); } finally { setLoading(false); }
  };

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const items = await listConversations();
        setConversations(items);
        if (items[0]) await select(items[0].id); else setLoading(false);
      } catch (caught) { setError(message(caught)); setLoading(false); }
    })();
  }, []);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = question.trim();
    if (!prompt || loading) return;
    void (async () => {
      setLoading(true); setError(null);
      try {
        if (conversation) {
          const appended = await appendConversationMessage(conversation.id, prompt);
          setConversation({ ...conversation, messages: [...conversation.messages, appended] });
        } else setConversation(await createConversation(prompt));
        setConversations(await listConversations());
        setQuestion("");
      } catch (caught) { setError(message(caught)); } finally { setLoading(false); }
    })();
  };

  return <section className="ask-page ask-workspace"><ConversationList conversations={conversations} selectedId={conversation?.id ?? null} loading={loading} error={error} onNew={() => { setConversation(null); setQuestion(""); setError(null); }} onSelect={(id) => void select(id)} /><ConversationThread conversation={conversation} question={question} loading={loading} error={error} onQuestionChange={setQuestion} onSubmit={submit} /></section>;
}
