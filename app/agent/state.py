from typing import Annotated, TypedDict, Any, Literal
from typing_extensions import NotRequired  

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class Request(TypedDict):
    currency: str                                # Валюта бюджета: "EUR", "USD", "RUB".
    destination: NotRequired[str | None]         # Куда едем: город/страна/регион. 
    duration_days: NotRequired[int | None]       # Сколько дней длится поездка.
    month: NotRequired[str | None]               # Когда едем ("июль"). Влияет на погоду, цены, часы работы.
    budget: NotRequired[float | None]            # Лимит денег в currency. Используется в BudgetReport.limit.
    interests: NotRequired[list[str]]            # Интересы: "музеи", "еда", "хайкинг" — влияют на подбор мест.
    travel_type: NotRequired[str | None]         # Тип поездки: "solo", "family", "couple", "business".
    constraints: NotRequired[list[str]]          # Жёсткие ограничения: "вегетарианец", "без перелётов" и т.п.


class Research(TypedDict):
    attractions: list[dict[str, Any]]            # Достопримечательности: name, description, price, часы.
    restaurants: list[dict[str, Any]]            # Рестораны/кафе: кухня, средний чек, рейтинг, локация.
    rules: list[dict[str, Any]]                  # Местные правила: виза, чаевые, транспорт, запреты.

class DayPlan(TypedDict):
    day: int                                     # Номер дня: 1, 2, 3…
    activities: list[dict[str, Any]]             # Активности дня: time, title, location, cost.
    notes: NotRequired[str | None]               # Заметки: "музей закрыт в понедельник", "взять зонт".


class Plan(TypedDict):
    markdown: str                    # готовый markdown-текст
    costs: dict[str, float] 
    days: list[DayPlan]                          # Полный маршрут по дням.
    hotels: list[dict[str, Any]]                 # Варианты проживания: название, район, цена/ночь.
    transport: list[dict[str, Any]]              # Как перемещаться: перелёт, поезд, метро — с ценами.
    total_cost: float                            # Итоговая сумма. Сравнивается с Request.budget.


class BudgetReport(TypedDict):
    total: float                                 # Посчитанная стоимость плана.
    limit: float                                 # Лимит пользователя (из Request.budget).
    fits: bool                                   # True если total <= limit. Иначе — граф идёт в реплан.
    breakdown: dict[str, Any]                    # Разбивка по категориям: {"hotels": 400, "food": 200, ...}.


# =============================================================================
# QualityReport — проверка качества плана
# -----------------------------------------------------------------------------
# Отдельный "критик" проверяет логику маршрута, а не деньги.
# =============================================================================
class QualityReport(TypedDict):
    passed: bool                                 # True если план прошёл проверку. Иначе — реплан.
    issues: list[str]                            # Проблемы: "день 2 перегружен", "нет времени на переезд".



class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]

    user_name: str                               # Имя пользователя — для персонализации ответов.
    system_prompt: str                           # Системный промпт, подставляемый в LLM-узлы.

    approval_decision: Literal["approved", "rejected"] | None
    # Решение человека в HITL-паузе (human-in-the-loop).
    # Управляет условным переходом после показа плана пользователю.

    # --- Уточнение запроса --------------------------------------------------
    request: Request                             # Нормализованный запрос. Заполняется узлом-парсером из messages.

    missing_fields: list[str]                    # Каких ключей Request не хватает: ["destination", "month"].
    question_to_user: str | None                 # Готовый вопрос пользователю, если чего-то не хватает. Пауза графа.

    # --- Результаты работы узлов --------------------------------------------
    research: Research                           # Выход RAG-узла.
    plan: Plan                                   # Текущий черновик маршрута (перезаписывается при реплане).
    budget_report: BudgetReport                  # Выход бюджетного критика.
    quality_report: QualityReport                # Выход критика качества.
    final_itinerary: str | None                  # Финальный текст маршрута для пользователя. Заполняется в конце.

    # --- Управление циклом перепланирования ---------------------------------
    replan_count: int                            # Сколько раз уже перепланировали. Инкрементируется в узле реплана.
    max_replans: int                             # Верхний предел итераций. Защита от бесконечного цикла.
