uv run uvicorn app.main:app --reload --port 8000  




# 1. Изменить модели
# 2. Сгенерировать миграцию
uv run alembic revision --autogenerate -m "add runs table"

# 3. Проверить глазами файл в alembic/versions/
# 4. Накатить
uv run alembic upgrade head


uv run alembic current         # текущая версия
uv run alembic history         # список миграций
uv run alembic downgrade -1    # откатить на одну назад
uv run alembic upgrade +1      # накатить одну вперёд
uv run alembic check           # проверить, что модели соответствуют миграциям

http://127.0.0.1:8000/docs

{
  "thread_id": "f9dc3552-728a-4140-91de-1c4c4f8cd82f",
  "status": "completed",
  "messages": [
    {
      "type": "human",
      "content": "Посчитай (123 + 456) * 7",
      "tool_calls": null
    },
    {
      "type": "ai",
      "content": "",
      "tool_calls": [
        {
          "name": "calculator",
          "args": {
            "expression": "(123 + 456) * 7"
          },
          "id": "18a02ef3-14fd-407d-bd71-a4bd64bab6dc",
          "type": "tool_call"
        }
      ]
    },
    {
      "type": "tool",
      "content": "4053",
      "tool_calls": null
    },
    {
      "type": "ai",
      "content": "4053",
      "tool_calls": null
    }
  ],
  "pending_approval_id": null
}


## Тесты

```bash
# Все тесты
python -m pytest

# Только unit (быстро, без БД-стриминга)
python -m pytest tests/unit

# Только integration
python -m pytest tests/integration

# Один файл
python -m pytest tests/unit/test_security.py -v

# С остановкой на первой ошибке
python -m pytest -x

# С stdout (для print/debug)
python -m pytest -s