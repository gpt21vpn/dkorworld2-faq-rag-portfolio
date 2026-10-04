"""Knowledge-base retrieval + optional RAG generation for DKORWORLD2.

V9 principles:
- deterministic intent routing for prices, deadlines, portfolio, cases and contacts;
- lexical relevance threshold so unrelated questions never fall into a random card;
- FAQ priority is only a tie-breaker, never artificial relevance;
- short follow-ups (for example: "Сколько стоит?" -> "лендинг") use recent history;
- optional OpenAI generation is strictly constrained by retrieved local knowledge.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FAQS_PATH = DATA_DIR / "faqs.json"

_client: Any | None = None

STOPWORDS = {
    "а", "без", "бы", "в", "вам", "ваш", "ваша", "ваши", "во", "вот", "вы",
    "где", "да", "для", "до", "его", "ее", "еще", "же", "за", "и", "из", "или",
    "как", "какая", "какие", "какой", "когда", "кто", "ли", "мне", "можно", "мы",
    "на", "над", "не", "но", "о", "об", "он", "она", "они", "от", "по", "под",
    "при", "про", "с", "со", "сколько", "так", "такое", "то", "у", "что", "это", "я", "ты",
    # Общие глаголы и обращения: они есть почти в любом вопросе и не указывают на тему.
    "сделать", "сделай", "делать", "делаете", "сделаете", "можешь", "можете",
    "сможешь", "сможете", "нужно", "надо", "хочу", "хотим", "твои", "твой", "мои",
    "посмотреть", "подскажи", "пожалуйста", "есть",
}

PRICE_WORDS = {"цена", "цену", "цены", "стоимость", "стоит", "бюджет", "прайс", "руб", "рублей"}
BOT_WORDS = {"бот", "бота", "боты", "чатбот", "чат-бот", "telegram", "телеграм", "ассистент", "ассистента"}
SITE_WORDS = {"сайт", "сайта", "лендинг", "лендинга", "страница", "веб", "web"}
VIDEO_WORDS = {"видео", "ролик", "ролика", "проморолик", "промо", "монтаж"}
DEADLINE_WORDS = {"срок", "сроки", "дней", "день", "готово", "сделаете", "сделать"}

MIN_RELEVANCE_SCORE = 3.0


def _normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    # Любой вид дефиса/тире считаем разделителем слов:
    # "152-ФЗ" -> "152 фз", "чат-бот" -> "чат бот".
    text = re.sub(r"[-‐‑‒–—−]+", " ", text)
    text = re.sub(r"[^a-zа-я0-9@+ ]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if len(t) > 2 and t not in STOPWORDS}


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    norm = _normalize(text)
    return any(_normalize(p) in norm for p in phrases)


def load_faqs() -> List[Dict[str, Any]]:
    """Load verified local KB cards."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FAQS_PATH.exists():
        return []
    with FAQS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("data/faqs.json must contain a JSON list")
    return [item for item in data if isinstance(item, dict) and item.get("answer")]


def _find_by_id(faqs: Sequence[Dict[str, Any]], target_id: str | None) -> Dict[str, Any] | None:
    if not target_id:
        return None
    for item in faqs:
        if item.get("id") == target_id:
            return item
    return None


def _intent_name(message: str) -> str | None:
    """Return broad conversational intent, used for short follow-ups."""
    text = _normalize(message)
    tokens = _tokens(text)

    # Deadline intent must be checked BEFORE price. "За сколько дней?" is about time.
    if _contains_phrase(text, {"сколько дней", "за сколько дней", "какие сроки", "какой срок", "когда будет готово", "когда готово"}):
        return "timing"
    if tokens & {"срок", "сроки"}:
        return "timing"

    # "сколько" alone is not a price signal. It becomes price only with "стоит/стоимость/цена".
    if _contains_phrase(text, {"сколько стоит", "какая цена", "какова цена", "стоимость", "цены", "прайс", "по цене", "бюджет"}):
        return "price"
    if tokens & PRICE_WORDS:
        return "price"

    return None


def _contextualize(message: str, history: Sequence[Dict[str, str]] | None = None) -> str:
    """Resolve terse follow-ups against the latest user intent.

    Example: user asks "Сколько стоит?", then "лендинг". Retrieval sees
    "Сколько стоит? лендинг" and routes to price_site.
    """
    current = _normalize(message)
    if not current or not history:
        return message

    current_tokens = _tokens(current)
    target_words = BOT_WORDS | SITE_WORDS | VIDEO_WORDS
    is_short_target = len(current_tokens) <= 4 and bool(current_tokens & target_words)
    if not is_short_target:
        return message

    for item in reversed(list(history)[-8:]):
        if str(item.get("role") or "") != "user":
            continue
        previous = str(item.get("content") or "").strip()
        # Frontend may include the current user message in history; skip that duplicate.
        if _normalize(previous) == current:
            continue
        previous_intent = _intent_name(previous)
        if previous_intent in {"price", "timing"}:
            return f"{previous} {message}".strip()
        # Stop at the most recent meaningful user turn; do not drag old intents indefinitely.
        if previous:
            break
    return message


def _special_intent(message: str, faqs: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Resolve high-value intents deterministically before generic retrieval."""
    text = _normalize(message)
    token_set = _tokens(text)

    def has_any(words: Iterable[str]) -> bool:
        normalized = {_normalize(w) for w in words}
        return bool(token_set & normalized) or any(w and w in text for w in normalized)

    target_id: str | None = None

    # 1) Time before money: "за сколько дней" must never become pricing.
    if _intent_name(text) == "timing":
        if has_any(BOT_WORDS):
            target_id = "timing_chatbot"
        elif has_any(SITE_WORDS):
            target_id = "timing_site"
        elif has_any(VIDEO_WORDS):
            target_id = "timing_video"
        else:
            target_id = "timing"

    # 2) Specific real cases before generic "cases".
    elif "autoneuro" in text or "автонейро" in text or (
        "сто" in token_set and has_any({"кейс", "пример", "бот", "сервис"})
    ):
        target_id = "case_autoneuro"
    elif "astronum" in text or "астролог" in text:
        target_id = "case_astro"

    # 3) Privacy / personal-data intent must beat generic "what can a bot do".
    elif _contains_phrase(text, {
        "персональные данные",
        "работаете с персональными данными",
        "обработка персональных данных",
        "обработка данных",
        "152 фз",
        "политика конфиденциальности",
    }) or has_any({"конфиденциальность", "privacy"}):
        target_id = "privacy"

    # 4) Price intent with product disambiguation.
    elif _intent_name(text) == "price":
        if has_any(BOT_WORDS):
            target_id = "price_chatbot"
        elif has_any(SITE_WORDS):
            target_id = "price_site"
        elif has_any(VIDEO_WORDS):
            target_id = "price_video"
        elif len(token_set) <= 5:
            # «Сколько стоит?» без предмета — это про наш прайс.
            target_id = "price_overview"
        else:
            # Длинная фраза с «цена/стоит», но без нашего предмета: скорее речь о
            # чужой услуге. Отдаём вопрос обычному отбору, где порог даст отказ.
            target_id = None

    # 5) High-level navigation / capabilities.
    elif _contains_phrase(text, {"что ты можешь", "что вы можете", "что умеете", "чем занимаетесь", "что делаете", "какие услуги", "ваши услуги", "направления работы"}):
        target_id = "overview"
    elif has_any({"портфолио", "youtube", "ютуб", "видеоработы", "работы посмотреть"}):
        target_id = "portfolio_overview"
    elif has_any({"кейс", "кейсы", "проекты", "пример", "примеры работ", "ваши кейсы"}):
        target_id = "cases_overview"
    elif has_any({"контакт", "контакты", "связаться", "написать", "почта", "email"}):
        target_id = "contacts"
    elif has_any({"квиз", "бриф", "опрос"}):
        target_id = "quiz"
    elif has_any({"голос", "голосом", "микрофон", "groq", "whisper"}):
        target_id = "voice_demo"
    elif has_any(BOT_WORDS):
        target_id = "bots_capabilities"
    elif has_any(VIDEO_WORDS):
        target_id = "video_service"
    elif has_any(SITE_WORDS):
        target_id = "site_service"

    return _find_by_id(faqs, target_id)



# ============================================================================
# Слой понимания запроса (multi-intent).
#
# Прежняя схема выбирала ОДНУ карточку на весь вопрос. Живой человек спрашивает
# сразу о нескольких вещах: «можете сделать бот для СТО, сколько стоит и что он
# умеет». Поэтому предмет (subject) и запрос (ask) определяются отдельно, и обоих
# может быть несколько; ответ собирается из 1-3 проверенных карточек.
# ============================================================================

BASE_PRICES = {
    "video": (10000, "AI-проморолик"),
    "site": (12000, "сайт или лендинг"),
    "bot": (15000, "AI-чат-бот"),
}


SUBJECT_WORDS = {
    "bot": BOT_WORDS | {"ассистент", "ассистента", "консультант", "телеграм"},
    "site": SITE_WORDS | {"страница", "страницу", "визитка"},
    "video": VIDEO_WORDS | {"рекламу", "рекламный"},
}

ASK_PHRASES = {
    "price": {"сколько стоит", "сколько будет стоить", "сколько это будет стоить", "какая цена",
              "какова цена", "стоимость", "по цене", "во сколько обойдется", "цена", "цены", "бюджет"},
    "timing": {"сколько дней", "за сколько дней", "какие сроки", "какой срок", "сроки", "срок",
               "когда будет готово", "когда готово", "как быстро", "за какое время"},
    "capabilities": {"что умеет", "что может", "какие возможности", "что он умеет", "возможности",
                     "что предложишь", "что посоветуешь", "как это работает"},
    "examples": {"примеры работ", "реальные работы", "покажи работы", "ваши работы", "твои работы",
                 "что посмотреть", "портфолио", "видеоработы", "кейсы", "кейс"},
    "booking": {"записаться", "запись", "забронировать", "свободное время", "созвон", "созвониться",
                "поговорить", "консультацию", "на консультацию"},
    "contacts": {"контакты", "как связаться", "связаться", "написать вам", "ваша почта", "телефон"},
}

# «Бот отвечает по прайсу клиента» — это возможность бота, а не вопрос о нашей цене.
PRICE_FALSE_FRIENDS = (
    "по прайсу", "по вашему прайсу", "по прайс", "прайсу компании", "прайс клиента",
    "отвечать по прайсу", "отвечает по прайсу", "ответы по прайсу", "из прайса",
)

CAN_YOU_PHRASES = ("можешь", "можете", "сможешь", "сможете", "можно ли", "делаете ли", "умеешь", "умеете")


def _word_hit(text: str, word: str) -> bool:
    """Совпадение по границам слова.

    Обычная подстрока даёт ложные срабатывания: «бот» находится внутри «работы»,
    поэтому вопрос «покажи реальные работы» определялся как вопрос про бота.
    """
    word = _normalize(word)
    if not word:
        return False
    if " " in word:
        return word in text
    return re.search(r"(?<![а-яa-z0-9])" + re.escape(word) + r"(?![а-яa-z0-9])", text) is not None


def _detect_subjects(text: str) -> list[str]:
    found = []
    for subject, words in SUBJECT_WORDS.items():
        if any(_word_hit(text, w) for w in words):
            found.append(subject)
    return found


def _detect_asks(text: str) -> list[str]:
    asks = []
    price_free = text
    for bad in PRICE_FALSE_FRIENDS:
        price_free = price_free.replace(bad, " ")

    for ask, phrases in ASK_PHRASES.items():
        probe = price_free if ask == "price" else text
        if any(p in probe for p in phrases) or (_tokens(probe) & {_normalize(p) for p in phrases if " " not in p}):
            asks.append(ask)

    if "price" not in asks and (_tokens(price_free) & PRICE_WORDS):
        asks.append("price")

    # «Можете сделать X?» — это вопрос о возможности, даже без слова «умеете».
    if "capabilities" not in asks and any(p in text for p in CAN_YOU_PHRASES):
        asks.append("capabilities")
    # Сроки важнее цены: «за сколько дней» не должно становиться ценой.
    if "timing" in asks and "price" in asks and "стоит" not in text and "цен" not in text:
        asks.remove("price")
    return asks


def _carry_subject(history: Sequence[Dict[str, str]] | None) -> list[str]:
    """Предмет разговора наследуется: «А сколько это будет стоить?» после бота — про бота."""
    if not history:
        return []
    for item in reversed(list(history)[-8:]):
        content = _normalize(str(item.get("content") or ""))
        if not content:
            continue
        subjects = _detect_subjects(content)
        if subjects:
            return subjects[:1]
    return []


def analyze_query(message: str, history: Sequence[Dict[str, str]] | None = None) -> Dict[str, Any]:
    text = _normalize(message)
    subjects = _detect_subjects(text)
    asks = _detect_asks(text)

    industry = None
    if "сто" in _tokens(text) or "автосервис" in text or "автомойк" in text or "автозапчаст" in text:
        industry = "auto"

    # Одинокое «сколько» ценой не считается: «сколько всё вместе» становится
    # вопросом о цене только когда в реплике есть предмет (лендинг, бот, ролик).
    if subjects and "price" not in asks and "timing" not in asks and "сколько" in text:
        asks.append("price")

    carried = False
    # Предмет наследуется только для КОРОТКОГО уточнения вроде «а сколько?».
    # Длинная фраза со своим смыслом («сколько будет стоить уборка у меня дома»)
    # не должна подхватывать бота из прошлой реплики — иначе вопрос вне нашей
    # темы получит цену бота вместо честного отказа.
    is_short_followup = len(_tokens(text)) <= 5
    if not subjects and is_short_followup and asks and set(asks) & {"price", "timing", "capabilities"}:
        subjects = _carry_subject(history)
        carried = bool(subjects)

    return {
        "subjects": subjects,
        "asks": asks,
        "carried": carried,
        "short": is_short_followup,
        "industry": industry,
        "projects": any(p in text for p in ("другие проекты", "ещё проекты", "еще проекты",
                                            "кроме кейсов", "кроме трех кейсов", "кроме трёх кейсов",
                                            "собственные проекты", "свои проекты", "личные проекты")),
    }


def compose_answer(message: str, faqs: Sequence[Dict[str, Any]],
                   history: Sequence[Dict[str, str]] | None = None) -> Dict[str, Any] | None:
    """Собирает ответ из нескольких карточек, когда вопрос многосоставной.

    Возвращает None, если вопрос простой — тогда работает прежний однокарточный путь.
    """
    analysis = analyze_query(message, history)
    subjects, asks = analysis["subjects"], analysis["asks"]
    text_norm = _normalize(message)

    if analysis["projects"]:
        card = _find_by_id(faqs, "projects_overview")
        if card:
            return {"cards": [card], "answer": str(card.get("answer") or ""), "analysis": analysis}

    if "booking" in asks and "examples" not in asks:
        card = _find_by_id(faqs, "booking_intent")
        if card:
            return {"cards": [card], "answer": str(card.get("answer") or ""), "analysis": analysis}

    if "examples" in asks and not subjects:
        wants_cases = "кейс" in text_norm or "проект" in text_norm
        card = _find_by_id(faqs, "cases_overview" if wants_cases else "portfolio_overview")
        if card:
            return {"cards": [card], "answer": str(card.get("answer") or ""), "analysis": analysis}

    meaningful = [a for a in asks if a in {"price", "timing", "capabilities", "examples"}]

    # Вопрос о цене или сроке без названного предмета: даём общий прайс,
    # а не случайный кейс. «А сколько это будет стоить?» без контекста — это
    # запрос ориентиров по всем трём направлениям.
    # Общий прайс отдаём только на короткий вопрос вроде «Сколько стоит?».
    # Длинная фраза без нашего предмета («сколько стоит уборка у меня дома»)
    # уходит в обычный отбор, где порог релевантности даёт честный отказ.
    if not subjects and meaningful and analysis.get("short"):
        if "price" in meaningful:
            card = _find_by_id(faqs, "price_overview")
        elif "timing" in meaningful:
            card = _find_by_id(faqs, "timing")
        else:
            card = None
        if card:
            return {"cards": [card], "answer": str(card.get("answer") or ""), "analysis": analysis}

    if not subjects or not meaningful:
        return None
    # Сборка нужна, когда предметов больше одного, вопросов больше одного,
    # либо предмет унаследован из разговора (тогда одного вопроса достаточно).
    if (len(subjects) < 2 and len(meaningful) < 2
            and not analysis.get("carried")
            and "capabilities" not in meaningful):
        return None

    parts: list[str] = []
    cards: list[Dict[str, Any]] = []

    def add(card_id: str) -> str | None:
        card = _find_by_id(faqs, card_id)
        if not card or card in cards:
            return None
        cards.append(card)
        return str(card.get("answer") or "").strip()

    # 1. Возможности — по первому предмету.
    if "capabilities" in meaningful:
        primary = subjects[0]
        text = add({"bot": "bots_capabilities", "site": "site_service", "video": "video_service"}[primary])
        if text:
            prefix = "Да, это можно сделать. " if any(p in _normalize(message) for p in CAN_YOU_PHRASES) else ""
            parts.append(prefix + text)

    # 2. Похожий кейс — примером, а не вместо ответа.
    wants_example = bool({"capabilities", "examples"} & set(meaningful))
    if wants_example and "bot" in subjects and (analysis["industry"] == "auto" or "capabilities" in meaningful):
        text = add("case_autoneuro")
        if text:
            parts.append("Похожий реализованный кейс — " + text)
    elif "examples" in meaningful:
        text = add("cases_overview" if "case" in _normalize(message) or "кейс" in _normalize(message) else "portfolio_overview")
        if text:
            parts.append(text)

    # 3. Цена — по каждому названному предмету.
    if "price" in meaningful:
        price_ids = {"bot": "price_chatbot", "site": "price_site", "video": "price_video"}
        wanted = [s for s in ("site", "bot", "video") if s in subjects and s in price_ids]
        if len(wanted) > 1:
            # Комплекс: короткая строка с ориентирами и явной суммой вместо трёх абзацев.
            for s_key in wanted:
                add(price_ids[s_key])
            listing = "; ".join(
                f"{BASE_PRICES[s_key][1]} — от {BASE_PRICES[s_key][0]:,} ₽".replace(",", " ")
                for s_key in wanted
            )
            total = sum(BASE_PRICES[s_key][0] for s_key in wanted)
            parts.append(
                f"По текущему публичному прайсу DKORWORLD2: {listing}. "
                f"Арифметический минимум этих позиций — от {total:,} ₽".replace(",", " ")
                + ". Но комплекс считается отдельно после короткого брифа: часть работ "
                  "переиспользуется, часть требует интеграций."
            )
        elif wanted:
            text = add(price_ids[wanted[0]])
            if text:
                parts.append(text)

    # 4. Сроки.
    if "timing" in meaningful:
        timing_ids = {"bot": "timing_chatbot", "site": "timing_site", "video": "timing_video"}
        timings = [add(timing_ids[s]) for s in subjects if s in timing_ids]
        timings = [t for t in timings if t]
        if timings:
            parts.append(" ".join(timings))

    if not parts:
        return None
    return {"cards": cards[:3], "answer": " ".join(parts).strip(), "analysis": analysis}


def _score_item(message: str, item: Dict[str, Any]) -> float:
    """Pure relevance score. Priority is deliberately NOT included here."""
    text = _normalize(message)
    q_tokens = _tokens(text)
    if not q_tokens:
        return 0.0

    question = _normalize(str(item.get("question", "")))
    answer = _normalize(str(item.get("answer", "")))
    keywords = [str(x) for x in (item.get("keywords") or [])]
    tags = [str(x) for x in (item.get("tags") or [])]

    hay_tokens = _tokens(" ".join([question, answer, *keywords, *tags]))
    overlap = q_tokens & hay_tokens
    score = float(len(overlap) * 2.0)

    for kw in keywords:
        norm_kw = _normalize(kw)
        if norm_kw and norm_kw in text:
            score += 7.0 if " " in norm_kw else 4.0

    question_tokens = _tokens(question)
    score += len(q_tokens & question_tokens) * 1.8
    return score


def retrieve_similar(
    message: str,
    top_k: int = 4,
    history: Sequence[Dict[str, str]] | None = None,
) -> List[Dict[str, Any]]:
    """Hybrid lexical retrieval with a real relevance gate."""
    faqs = load_faqs()
    if not faqs:
        return []

    query = _contextualize(message, history)
    special = _special_intent(query, faqs)
    special_id = special.get("id") if special else None

    # Порог растёт с длиной вопроса. В длинной фразе случайных совпадений больше:
    # «сколько будет стоить уборка у меня дома» набирало 4.0 на карточке кейса
    # при пороге 3.0 и выдавало AutoNeuro вместо отказа. Настоящие попадания
    # набирают 6-15, так что планка ниже них.
    query_tokens = len(_tokens(query))
    min_score = MIN_RELEVANCE_SCORE + 0.6 * max(0, query_tokens - 3)
    min_score = min(min_score, 8.0)

    ranked: List[tuple[int, float, int, Dict[str, Any]]] = []
    for item in faqs:
        relevance = _score_item(query, item)
        is_special = int(item.get("id") == special_id)

        # A deterministic intent is sufficient evidence for that exact card.
        if not is_special and relevance < min_score:
            continue

        priority = int(item.get("priority") or 0)
        ranked.append((is_special, relevance, priority, item))

    # Priority is only the LAST tie-breaker after intent + actual relevance.
    ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)

    results: List[Dict[str, Any]] = []
    limit = max(1, min(int(top_k or 4), 6))
    for is_special, relevance, _priority, item in ranked[:limit]:
        row = dict(item)
        row["score"] = round(relevance, 3)
        row["matched_by_intent"] = bool(is_special)
        results.append(row)
    return results


def _public_source(item: Dict[str, Any]) -> Dict[str, str]:
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or item.get("question") or "База знаний"),
        "source": str(item.get("source") or "База знаний DKORWORLD2"),
    }


def local_answer(message: str, history: Sequence[Dict[str, str]] | None = None) -> Dict[str, Any]:
    """Reliable deterministic answer directly from local KB."""
    text = _normalize(message)
    if not text:
        return {
            "answer": "Напишите вопрос об AI-ботах, видео, сайтах, стоимости, сроках или реальных кейсах.",
            "context": [], "sources": [], "confidence": 0.0,
        }

    faqs = load_faqs()
    composed = compose_answer(message, faqs, history)
    if composed:
        cards = composed["cards"]
        return {
            "answer": composed["answer"],
            "context": [dict(c, score=20.0, matched_by_intent=True) for c in cards],
            "sources": [_public_source(c) for c in cards],
            "confidence": 0.94,
            "resolved_query": _contextualize(message, history),
            "analysis": composed["analysis"],
        }

    related = retrieve_similar(message, top_k=4, history=history)
    if not related:
        return {
            "answer": (
                "В базе знаний DKORWORLD2 нет точного ответа на этот вопрос. "
                "Можно спросить про AI-ботов, AI-видео, сайты, цены, сроки или кейсы. "
                "Для своей задачи пройдите квиз или напишите Дмитрию в Telegram @dimaseo2."
            ),
            "context": [], "sources": [], "confidence": 0.0,
        }

    best = related[0]
    score = float(best.get("score") or 0)
    answer = str(best.get("answer") or "").strip()
    if not answer:
        answer = "Точного ответа в базе знаний пока нет. Можно оставить вопрос через квиз или Telegram @dimaseo2."

    # Intent-matched cards are reliable even when the literal words are short.
    confidence = 0.92 if best.get("matched_by_intent") else min(1.0, score / 18.0)
    return {
        "answer": answer,
        "context": related,
        "sources": [_public_source(best)],
        "confidence": confidence,
        "resolved_query": _contextualize(message, history),
    }


def get_client() -> Any:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        try:
            import httpx
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Python packages 'openai' and 'httpx' are required") from exc

        # Cloud4box may block direct access to OpenAI. Reuse the same outbound
        # proxy convention as the DZ9 RAG service when PROXY_URL is configured.
        proxy_url = (os.environ.get("PROXY_URL") or "").strip()
        if proxy_url:
            http_client = httpx.Client(proxy=proxy_url, timeout=60.0)
            _client = OpenAI(api_key=api_key, http_client=http_client)
        else:
            _client = OpenAI(api_key=api_key)
    return _client


def generate_answer(
    message: str,
    top_k: int = 4,
    history: Sequence[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """RAG: local retrieval -> LLM answer strictly constrained to verified cards."""
    resolved_query = _contextualize(message, history)
    related = retrieve_similar(message, top_k=top_k, history=history)
    if not related:
        return local_answer(message, history=history)

    context_blocks = []
    for item in related:
        context_blocks.append(
            "\n".join([
                f"ID: {item.get('id','')}",
                f"Тема: {item.get('title') or item.get('question','')}",
                f"Факт/ответ: {item.get('answer','')}",
                f"Источник: {item.get('source','База знаний DKORWORLD2')}",
            ])
        )
    context_text = "\n\n---\n\n".join(context_blocks)

    system_prompt = (
        "Ты AI-консультант сайта DKORWORLD2. Отвечай на русском, кратко и по делу. "
        "Используй ТОЛЬКО факты из КОНТЕКСТА. Не придумывай цены, сроки, проценты, функции, клиентов или гарантии. "
        "Если спрашивают цену — называй сумму только если она прямо есть в контексте. "
        "Если контекста недостаточно, прямо скажи об этом и предложи квиз или Telegram @dimaseo2. "
        "Учитывай последние реплики диалога: короткое 'лендинг' после 'сколько стоит?' означает цену лендинга. "
        "Не объясняй внутреннее устройство RAG, если пользователь сам об этом не спрашивает."
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in list(history or [])[-6:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        # Frontend may already include the current user turn in history.
        if role == "user" and _normalize(content) == _normalize(message):
            continue
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:1200]})

    messages.append({
        "role": "user",
        "content": f"КОНТЕКСТ:\n{context_text}\n\nУТОЧНЁННЫЙ ЗАПРОС:\n{resolved_query}\n\nТЕКУЩАЯ РЕПЛИКА:\n{message}",
    })

    client = get_client()
    completion = client.chat.completions.create(
        model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        messages=messages,
        temperature=0.1,
        max_tokens=450,
    )
    answer = (completion.choices[0].message.content or "").strip()
    if not answer:
        return local_answer(message, history=history)

    best = related[0]
    score = float(best.get("score") or 0)
    confidence = 0.92 if best.get("matched_by_intent") else min(1.0, score / 18.0)
    return {
        "answer": answer,
        "context": related,
        "sources": [_public_source(item) for item in related[:2]],
        "confidence": confidence,
        "resolved_query": resolved_query,
    }
