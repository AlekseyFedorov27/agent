# Agent Frontend (Vue 3)

SPA-фронтенд для LangGraph-агент-бэкенда: авторизация, чат с LLM, рендер ответов в Markdown, экспорт сообщения ассистента в PDF, Human-in-the-Loop подтверждение инструментов.

## Требования

- Node.js 20+
- Запущенный backend на `http://localhost:8000`

## Быстрый старт

```bash
npm install
cp .env.example .env       # по желанию
npm run dev
```

Откройте http://localhost:5173

## Как это работает

- `VITE_API_BASE=/api` → Vite проксирует запросы на `http://localhost:8000`.
- Токены (access + refresh) хранятся в `localStorage`.
- На 401 axios-интерсептор делает автоматический `/auth/refresh` и повторяет запрос.
- При `status="interrupted"` в ответе появляется `pending_approval_id` — рисуем карточку Approval.
- Markdown рендерится через `markdown-it` (raw HTML отключён) + `highlight.js`.
- PDF-экспорт — `html2canvas` + `jsPDF`, многостраничный A4.

## Сборка

```bash
npm run build     # → dist/
npm run preview
```

## Продакшн-варианты

- Собрать `dist/` и отдать через nginx рядом с backend — тогда `VITE_API_BASE` можно указать прямо
  на URL бэкенда (например `https://api.example.com`), а CORS настроить на бэкенде.
- Или оставить `/api` и проксировать тем же nginx.

## Структура

```
src/
├── api/           # http-клиент + endpoints
├── stores/        # Pinia: auth, chat
├── views/         # LoginView, RegisterView, ChatView
├── components/    # MessageItem, ApprovalCard
├── utils/         # markdown, pdf
└── router/        # guard по auth
```