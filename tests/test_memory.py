from app.memory.store import InMemorySessionStore
def test_memory_append_delete():
    store=InMemorySessionStore(); store.append("s","user","hello","u","demo-app"); assert store.get_history("s","u")[0]["content"]=="hello"; assert store.delete("s","u") is True
