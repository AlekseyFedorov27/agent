import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'

/**
 * Инжектит «печатные» стили внутрь клона: белый фон + чёрный текст.
 * Возвращает сам клон, вставленный в off-screen контейнер.
 */
function cloneForPrint(source: HTMLElement): { clone: HTMLElement; cleanup: () => void } {
  const clone = source.cloneNode(true) as HTMLElement

  // Внешний контейнер: держим фиксированную ширину, чтобы перенос строк
  // совпадал с оригиналом, но держим off-screen.
  const wrapper = document.createElement('div')
  wrapper.style.position = 'fixed'
  wrapper.style.left = '-10000px'
  wrapper.style.top = '0'
  wrapper.style.width = `${source.offsetWidth}px`
  wrapper.style.background = '#ffffff'
  wrapper.style.color = '#000000'
  wrapper.style.padding = '16px'
  wrapper.style.zIndex = '-1'

  // ВАЖНО: сбрасываем унаследованные CSS-переменные темы
  wrapper.className = 'pdf-print-root'

  clone.style.background = '#ffffff'
  clone.style.color = '#000000'

  wrapper.appendChild(clone)
  document.body.appendChild(wrapper)

  // Форсируем тёмный текст во всех дочерних узлах.
  // html2canvas читает computed styles, поэтому !important через CSSOM
  // работает надёжнее всего.
  const all = wrapper.querySelectorAll<HTMLElement>('*')
  all.forEach((el) => {
    el.style.setProperty('color', '#000000', 'important')
    el.style.setProperty('background-color', 'transparent', 'important')
    el.style.setProperty('border-color', '#d0d0d0', 'important')
  })

  // Точечно: код-блоки и inline-код — на светлом фоне
  wrapper.querySelectorAll<HTMLElement>('pre, code').forEach((el) => {
    el.style.setProperty('background-color', '#f3f4f6', 'important')
    el.style.setProperty('color', '#000000', 'important')
    el.style.setProperty('border', 'none', 'important')                // ← нет рамки
  })

  // Ссылки — тёмно-синие, чтобы отличались от обычного текста
  wrapper.querySelectorAll<HTMLElement>('a').forEach((el) => {
    el.style.setProperty('color', '#1a3ec8', 'important')
    el.style.setProperty('text-decoration', 'underline', 'important')
  })

  // Цитаты — серый маркер, но текст чёрный
  wrapper.querySelectorAll<HTMLElement>('blockquote').forEach((el) => {
    el.style.setProperty('border-left', '3px solid #888888', 'important')
    el.style.setProperty('color', '#000000', 'important')
  })

  // Убираем подсветку highlight.js (тёмная тема) — перекрасим токены
  // в контрастные цвета поверх белого фона.
  const tokenColors: Record<string, string> = {
    'hljs-keyword': '#7c3aed',
    'hljs-string': '#0a7d32',
    'hljs-number': '#b45309',
    'hljs-comment': '#6b7280',
    'hljs-function': '#1d4ed8',
    'hljs-title': '#1d4ed8',
    'hljs-built_in': '#0f766e',
    'hljs-attr': '#0f766e',
    'hljs-literal': '#b45309',
    'hljs-variable': '#b45309',
    'hljs-type': '#0f766e',
    'hljs-tag': '#7c3aed',
  }
  Object.entries(tokenColors).forEach(([cls, color]) => {
    wrapper.querySelectorAll<HTMLElement>(`.${cls}`).forEach((el) => {
      el.style.setProperty('color', color, 'important')
    })
  })

  return {
    clone: wrapper,
    cleanup: () => {
      if (wrapper.parentNode) wrapper.parentNode.removeChild(wrapper)
    },
  }
}

/**
 * Рендерит произвольный DOM-узел в PDF (A4, многостраничный).
 * Текст печатается чёрным на белом, независимо от темы приложения.
 */
export async function exportElementToPdf(
  el: HTMLElement,
  filename: string,
): Promise<void> {
  const { clone, cleanup } = cloneForPrint(el)

  try {
    const canvas = await html2canvas(clone, {
      scale: 2,
      useCORS: true,
      backgroundColor: '#ffffff',
      logging: false,
      // Явно просим html2canvas не тащить тёмные CSS-переменные —
      // backgroundColor уже перекрывает, но подстрахуемся.
      windowWidth: clone.scrollWidth,
      windowHeight: clone.scrollHeight,
    })

    const imgData = canvas.toDataURL('image/png')

    const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' })
    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const margin = 28

    const imgWidth = pageWidth - margin * 2
    const imgHeight = (canvas.height * imgWidth) / canvas.width
    const pageContentHeight = pageHeight - margin * 2

    let heightLeft = imgHeight
    let yOffset = 0

    pdf.addImage(imgData, 'PNG', margin, margin - yOffset, imgWidth, imgHeight)
    heightLeft -= pageContentHeight

    while (heightLeft > 0) {
      yOffset += pageContentHeight
      pdf.addPage()
      pdf.addImage(imgData, 'PNG', margin, margin - yOffset, imgWidth, imgHeight)
      heightLeft -= pageContentHeight
    }

    pdf.save(filename)
  } finally {
    cleanup()
  }
}

export function buildPdfFilename(prefix = 'message'): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const ts = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  return `${prefix}_${ts}.pdf`
}