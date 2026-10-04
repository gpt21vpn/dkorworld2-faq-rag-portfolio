from faq_service.rag_index import build_retrieval_query, load_cards

cards = load_cards()
assert len(cards) == 31, len(cards)

history = [
    {"role": "user", "content": "Расскажи про чат-бота для бизнеса"},
    {"role": "assistant", "content": "Бот работает по базе знаний."},
]
query = build_retrieval_query("А сколько это будет стоить?", history)
assert "чат-бота" in query.lower(), query
assert "сколько" in query.lower(), query

query2 = build_retrieval_query("Нужен лендинг для автомойки с формой и квизом", history)
assert query2 == "Нужен лендинг для автомойки с формой и квизом", query2

print("FAQ memory/data tests: OK")
