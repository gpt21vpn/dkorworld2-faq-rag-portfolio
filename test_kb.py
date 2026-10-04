from backend.rag_index import local_answer

CASES = [
    ("Что ты можешь?", "Главное направление DKORWORLD2"),
    ("бот", "Бот может отвечать по материалам компании"),
    ("видео", "Работа с AI-видео"),
    ("сайт", "Сайт или лендинг может включать"),
    ("кейс", "три реальные работы"),
    ("Какие боты вы делаете?", "Бот может отвечать по материалам компании"),
    ("Сколько стоит сделать чат-бот?", "от 15 000 ₽"),
    ("Сколько стоит лендинг?", "от 12 000 ₽"),
    ("Сколько стоит AI-видео?", "от 10 000 ₽"),
    ("Сколько стоит?", "AI-проморолик — от 10 000 ₽"),
    ("За сколько дней сделаете?", "3–5 дней"),
    ("Сколько дней чат-бот?", "5–7 дней"),
    ("Какие сроки?", "3–5 дней"),
    ("Что умеет AutoNeuro?", "AutoNeuro"),
    ("Как работает квиз?", "Квиз состоит из пяти шагов"),
    ("Куда приходит заявка?", "SQLite"),
    ("Где посмотреть портфолио?", "YouTube @Dkorworld2"),
    ("Расскажите про ваши кейсы", "три реальные работы"),
    ("Как с вами связаться?", "@dimaseo2"),
]

for question, expected in CASES:
    result = local_answer(question)
    answer = result["answer"]
    assert expected.lower() in answer.lower(), (question, answer, expected)
    print("OK", question, "=>", answer[:120])

for bad in ["Погода в Москве", "asdf qwerty", "Курс доллара сегодня", "сколько"]:
    result = local_answer(bad)
    assert result["confidence"] == 0.0, (bad, result)
    assert "нет точного ответа" in result["answer"].lower(), (bad, result["answer"])
    print("OK OOS", bad, "=>", result["answer"][:100])

# Browser sends the current turn inside history too — backend must skip that duplicate.
history = [
    {"role": "user", "content": "Сколько стоит?"},
    {"role": "assistant", "content": "По текущему публичному прайсу..."},
    {"role": "user", "content": "лендинг"},
]
result = local_answer("лендинг", history=history)
assert "от 12 000 ₽" in result["answer"], result
assert "Сколько стоит? лендинг" in result.get("resolved_query", ""), result
print("OK FOLLOWUP price -> landing =>", result["answer"])

history = [
    {"role": "user", "content": "Какие сроки?"},
    {"role": "assistant", "content": "Зависит от направления."},
    {"role": "user", "content": "бот"},
]
result = local_answer("бот", history=history)
assert "5–7 дней" in result["answer"], result
print("OK FOLLOWUP timing -> bot =>", result["answer"])


# V9 regressions: hyphen normalization + long personal-data phrase.
v9_regressions = [
    ("152-ФЗ", "обработ"),
    ("152–ФЗ", "обработ"),
    ("Работаете с персональными данными?", "данн"),
    ("Как вы работаете с персональными данными?", "данн"),
]
for query, needle in v9_regressions:
    result = local_answer(query)
    answer = result["answer"].lower()
    assert needle in answer, (query, answer)
print("V9 privacy regressions: OK")


print("\n--- V12 NATURAL LANGUAGE REGRESSIONS ---")

def v12_check(query, needles, history=None):
    result = local_answer(query, history=history)
    answer = result["answer"].lower()
    for needle in needles:
        assert needle.lower() in answer, (query, needle, answer)
    print("OK V12", query, "=>", result["answer"][:220])
    return result

v12_check("Можешь сделать лендинг для автомойки и сколько это будет стоить?", ["12 000", "лендинг"])
v12_check("Сколько стоит сделать бота для СТО и какие у него будут возможности?", ["15 000", "autoneuro"])

h1 = [
    {"role": "user", "content": "Мне нужен бот, который принимает фото, голосовые сообщения, отвечает по прайсу и записывает клиентов. Что предложишь?"},
    {"role": "assistant", "content": "Бот может принимать заявки, фото и голос."},
]
v12_check("Мне нужен бот, который принимает фото, голосовые сообщения, отвечает по прайсу и записывает клиентов. Что предложишь?", ["голос", "фото", "autoneuro"])
v12_check("А сколько это будет стоить?", ["15 000"], history=h1)

h2 = h1 + [
    {"role": "user", "content": "А сколько это будет стоить?"},
    {"role": "assistant", "content": "Ориентир — от 15 000 ₽."},
]
v12_check("А сроки?", ["5–7"], history=h2)

v12_check("Можно ли у вас записаться на консультацию завтра?", ["раздел «запись»", "09:00", "21:00"])
v12_check(
    "Сделай мне лендинг для автосервиса, AI-бота и рекламный ролик. Сколько примерно будет стоить всё вместе?",
    ["12 000", "15 000", "10 000", "37 000"]
)
v12_check("Где можно посмотреть твои реальные работы?", ["youtube", "@carsautohelperaibot", "@astronum108bot"])
# ИСПРАВЛЕНО: 0.44 -> 0.73 и 0.5145 -> 0.6749 — два РАЗНЫХ замера модуля 5.
# Карточка проектов говорит про нарезку (ДЗ3), там 0.6749. К какому именно
# эксперименту относится 0.44 -> 0.73, уточняется по оригинальному отчёту ДЗ2.
v12_check("Какие у Дмитрия есть ещё проекты кроме трёх кейсов?", ["eda", "taskzero", "competitor monitor", "0.6749"])
v12_check("Можешь ли ты мне сделать сайт на тивиде или на коде? И сколько это будет стоить?", ["12 000", "сайт"])

oos = local_answer("А поубирать-то можешь или нет? У меня дома.")
assert oos["confidence"] == 0.0, oos
print("OK V12 OOS уборка => refusal")
print("V12 natural-language regressions: OK")
