import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'

// ---------------------------------------------------------------------------
// Настройки страницы (в pt; A4 ≈ 595 × 842 pt)
// ---------------------------------------------------------------------------
const PAGE_MARGIN_TOP = 40
const PAGE_MARGIN_BOTTOM = 40
const PAGE_MARGIN_SIDE = 32
const BLOCK_GAP = 10 // отступ между блоками на странице

// Номер страницы (ASCII, чтобы работал встроенный helvetica без TTF)
const PAGE_NUMBER_FONT_SIZE = 9
const PAGE_NUMBER_COLOR: [number, number, number] = [130, 130, 130]
const PAGE_NUMBER_OFFSET_FROM_BOTTOM = 18 // от низа листа до baseline номера

// ---------------------------------------------------------------------------
// Клон для печати: белый фон + чёрный текст, независимо от темы приложения
// ---------------------------------------------------------------------------
function cloneForPrint(source: HTMLElement): {
  clone: HTMLElement
  cleanup: () => void
} {
  const clone = source.cloneNode(true) as HTMLElement

  const wrapper = document.createElement('div')
  wrapper.style.position = 'fixed'
  wrapper.style.left = '-10000px'
  wrapper.style.top = '0'
  wrapper.style.width = `${source.offsetWidth}px`
  wrapper.style.background = '#ffffff'
  wrapper.style.color = '#000000'
  wrapper.style.padding = '16px'
  wrapper.style.zIndex = '-1'

  wrapper.className = 'pdf-print-root'

  clone.style.background = '#ffffff'
  clone.style.color = '#000000'

  wrapper.appendChild(clone)
  document.body.appendChild(wrapper)

  const all = wrapper.querySelectorAll<HTMLElement>('*')
  all.forEach((el) => {
    el.style.setProperty('color', '#000000', 'important')
    el.style.setProperty('background-color', 'transparent', 'important')
    el.style.setProperty('border-color', '#d0d0d0', 'important')
  })

  wrapper.querySelectorAll<HTMLElement>('pre, code').forEach((el) => {
    el.style.setProperty('background-color', '#f3f4f6', 'important')
    el.style.setProperty('color', '#000000', 'important')
    el.style.setProperty('border', 'none', 'important')
  })

  wrapper.querySelectorAll<HTMLElement>('a').forEach((el) => {
    el.style.setProperty('color', '#1a3ec8', 'important')
    el.style.setProperty('text-decoration', 'underline', 'important')
  })

  wrapper.querySelectorAll<HTMLElement>('blockquote').forEach((el) => {
    el.style.setProperty('border-left', '3px solid #888888', 'important')
    el.style.setProperty('color', '#000000', 'important')
  })

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

// ---------------------------------------------------------------------------
// Рендер одного блока в canvas
// ---------------------------------------------------------------------------
async function renderBlock(el: HTMLElement): Promise<HTMLCanvasElement> {
  return html2canvas(el, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#ffffff',
    logging: false,
  })
}


function drawPageNumbers(pdf: jsPDF): void {
  const pageCount = pdf.getNumberOfPages()
  const pageWidth = pdf.internal.pageSize.getWidth()
  const pageHeight = pdf.internal.pageSize.getHeight()

  pdf.setFont('helvetica', 'normal')
  pdf.setFontSize(PAGE_NUMBER_FONT_SIZE)
  pdf.setTextColor(
    PAGE_NUMBER_COLOR[0],
    PAGE_NUMBER_COLOR[1],
    PAGE_NUMBER_COLOR[2],
  )

  for (let i = 1; i <= pageCount; i++) {
    pdf.setPage(i)
    const label = `${i} / ${pageCount}`
    pdf.text(label, pageWidth / 2, pageHeight - PAGE_NUMBER_OFFSET_FROM_BOTTOM, {
      align: 'center',
    })
  }

  pdf.setTextColor(0, 0, 0)
}

// ---------------------------------------------------------------------------
// Публичный API: экспорт произвольного DOM-узла в PDF (A4, многостраничный)
// ---------------------------------------------------------------------------
export async function exportElementToPdf(
  el: HTMLElement,
  filename: string,
): Promise<void> {
  const { clone, cleanup } = cloneForPrint(el)

  try {
    const pdf = new jsPDF({
      unit: 'pt',
      format: 'a4',
      orientation: 'portrait',
    })

    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const contentWidth = pageWidth - PAGE_MARGIN_SIDE * 2
    const usableHeight = pageHeight - PAGE_MARGIN_TOP - PAGE_MARGIN_BOTTOM

    const contentRoot: HTMLElement =
      (clone.querySelector('.md') as HTMLElement | null) ?? clone

    const blocks = Array.from(contentRoot.children).filter(
      (n): n is HTMLElement => n instanceof HTMLElement,
    )

    // --- Fallback: нет верхнеуровневых блоков — рендерим одним куском ---
    if (blocks.length === 0) {
      const canvas = await renderBlock(clone)
      const imgData = canvas.toDataURL('image/png')
      const ratio = contentWidth / canvas.width
      const imgHeight = canvas.height * ratio
      pdf.addImage(
        imgData,
        'PNG',
        PAGE_MARGIN_SIDE,
        PAGE_MARGIN_TOP,
        contentWidth,
        imgHeight,
      )
      drawPageNumbers(pdf)
      pdf.save(filename)
      return
    }

    let y = PAGE_MARGIN_TOP
    let firstPageUsed = false

    for (const block of blocks) {
      const rect = block.getBoundingClientRect()
      if (rect.height < 1) continue

      const canvas = await renderBlock(block)
      const imgData = canvas.toDataURL('image/png')
      const ratio = contentWidth / canvas.width
      const imgHeight = canvas.height * ratio

      // --- Случай 1: блок выше целой страницы ---
      if (imgHeight > usableHeight) {
        if (firstPageUsed && y > PAGE_MARGIN_TOP) {
          pdf.addPage()
          y = PAGE_MARGIN_TOP
          firstPageUsed = false
        }

        let remaining = imgHeight
        let offset = 0

        while (remaining > 0) {
          pdf.addImage(
            imgData,
            'PNG',
            PAGE_MARGIN_SIDE,
            PAGE_MARGIN_TOP - offset,
            contentWidth,
            imgHeight,
          )
          remaining -= usableHeight
          offset += usableHeight

          if (remaining > 0) {
            pdf.addPage()
          }
        }

        pdf.addPage()
        y = PAGE_MARGIN_TOP
        firstPageUsed = false
        continue
      }

      // --- Случай 2: блок не влезает в оставшееся место ---
      if (firstPageUsed && y + imgHeight > pageHeight - PAGE_MARGIN_BOTTOM) {
        pdf.addPage()
        y = PAGE_MARGIN_TOP
        firstPageUsed = false
      }

      // --- Случай 3: кладём блок целиком ---
      pdf.addImage(imgData, 'PNG', PAGE_MARGIN_SIDE, y, contentWidth, imgHeight)
      y += imgHeight + BLOCK_GAP
      firstPageUsed = true
    }

    drawPageNumbers(pdf)
    pdf.save(filename)
  } finally {
    cleanup()
  }
}

// ---------------------------------------------------------------------------
// Имя файла с таймстампом
// ---------------------------------------------------------------------------
export function buildPdfFilename(prefix = 'message'): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const ts =
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  return `${prefix}_${ts}.pdf`
}