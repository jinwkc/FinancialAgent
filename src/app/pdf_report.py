"""재무제표 대화 요약을 읽기 쉬운 한국어 PDF 보고서로 저장한다."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pymupdf as fitz


REPORT_DIR = Path(
    os.getenv("FINANCIAL_REPORT_DIR")
    or Path(__file__).resolve().parent.parent / "data" / "reports"
)
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
LEFT_MARGIN = 48
RIGHT_MARGIN = 48
TOP_MARGIN = 48
BOTTOM_MARGIN = 56
FONT_NAME = "nanumgothic"
FONT_FILE = Path(__file__).resolve().parent / "assets" / "fonts" / "NanumGothic-Regular.ttf"
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
CONTENT_BOTTOM = PAGE_HEIGHT - BOTTOM_MARGIN - 18

NAVY = (0.08, 0.16, 0.28)
BLUE = (0.16, 0.39, 0.66)
TEXT = (0.15, 0.19, 0.25)
MUTED = (0.39, 0.44, 0.51)
PALE_BLUE = (0.93, 0.96, 0.99)
PALE_GRAY = (0.96, 0.97, 0.98)
PALE_AMBER = (1.00, 0.97, 0.91)
AMBER = (0.69, 0.40, 0.10)
WHITE = (1.0, 1.0, 1.0)
BORDER = (0.86, 0.89, 0.92)


@lru_cache(maxsize=1)
def _report_font() -> fitz.Font:
    """Use the same bundled font for layout measurements and PDF drawing."""
    return fitz.Font(fontfile=str(FONT_FILE))


def _fit_single_line(
    text: str, max_width: float, font_size: float, min_size: float
) -> tuple[str, float, bool]:
    """Fit a header label into its fixed area and report any omitted text."""
    value = " ".join(text.split())
    font = _report_font()
    while font_size > min_size and font.text_length(value, fontsize=font_size) > max_width:
        font_size = max(min_size, font_size - 0.5)
    if font.text_length(value, fontsize=font_size) <= max_width:
        return value, font_size, False

    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if font.text_length(value[:middle].rstrip() + "…", fontsize=font_size) <= max_width:
            low = middle
        else:
            high = middle - 1
    return value[:low].rstrip() + "…", font_size, True


def _wrap_paragraph(
    text: str,
    max_width: float = CONTENT_WIDTH,
    font_size: float = 10.5,
) -> list[str]:
    """문자 수가 아니라 실제 한글 글꼴 폭을 기준으로 문단을 줄바꿈한다."""
    font = _report_font()
    lines: list[str] = []
    for source_line in text.splitlines() or [text]:
        remaining = source_line.strip()
        if not remaining:
            lines.append("")
            continue

        while remaining:
            if font.text_length(remaining, fontsize=font_size) <= max_width:
                lines.append(remaining)
                break

            low, high = 1, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if font.text_length(remaining[:middle], fontsize=font_size) <= max_width:
                    low = middle
                else:
                    high = middle - 1

            split_at = low
            whitespace = remaining.rfind(" ", 0, split_at + 1)
            if whitespace > split_at // 2:
                split_at = whitespace
            lines.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
    return lines or [""]


def _parse_metric_rows(text: str) -> list[tuple[str, str, str]]:
    """`지표 | 현재값 | 비교값` 또는 `지표: 현재값` 줄을 표 데이터로 읽는다."""
    rows: list[tuple[str, str, str]] = []
    for source_line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]\s*)?", "", source_line).strip()
        if not line or line.startswith("```"):
            continue

        if "|" in line:
            parts = [part.strip() for part in line.strip("| ").split("|")]
        else:
            match = re.match(r"^([^:：]{1,40})[:：]\s*(.+)$", line)
            if not match:
                continue
            parts = [match.group(1).strip(), match.group(2).strip()]

        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        label, value = parts[0], parts[1]
        comparison = " · ".join(part for part in parts[2:] if part)
        rows.append((label, value, comparison))
    return rows


def _safe_company_slug(company_name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", company_name).strip("_")
    return slug[:48] or "company"


def generate_financial_report_pdf(
    *,
    company_name: str,
    report_period: str,
    executive_summary: str,
    financial_analysis: str,
    key_metrics: str,
    caveats: str,
    sources: str,
) -> dict[str, str]:
    """요약, 지표 카드, 분석, 주의사항과 출처를 페이지가 나뉘는 PDF로 저장한다."""
    if not company_name.strip():
        raise ValueError("company_name이 필요합니다.")

    _report_font()  # Fail clearly if the bundled font is missing or unreadable.
    title_text, title_size, title_shortened = _fit_single_line(
        company_name, CONTENT_WIDTH, 23, 11
    )
    period_value = report_period or "보고서 기준 정보 없음"
    period_text, period_size, period_shortened = _fit_single_line(
        period_value, CONTENT_WIDTH, 9, 7
    )

    report_id = uuid.uuid4().hex
    filename = f"{_safe_company_slug(company_name)}_financial_report_{report_id[:8]}.pdf"
    output_path = REPORT_DIR / f"{report_id}.pdf"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    document = fitz.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_font(fontname=FONT_NAME, fontfile=str(FONT_FILE))
    y = TOP_MARGIN

    def draw_page_header(*, first_page: bool = False) -> None:
        nonlocal y
        if first_page:
            page.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, 158), color=NAVY, fill=NAVY)
            page.draw_circle((PAGE_WIDTH - 46, 34), 17, color=BLUE, fill=BLUE)
            page.insert_text(
                (LEFT_MARGIN, 39), "OPENDART  /  FINANCIAL BRIEF",
                fontsize=8.5, fontname=FONT_NAME, color=(0.79, 0.86, 0.94),
            )
            page.insert_text(
                (LEFT_MARGIN, 78), title_text,
                fontsize=title_size, fontname=FONT_NAME, color=WHITE,
            )
            page.insert_text(
                (LEFT_MARGIN, 105), "재무제표 요약 보고서",
                fontsize=13, fontname=FONT_NAME, color=(0.89, 0.93, 0.97),
            )
            page.insert_text(
                (LEFT_MARGIN, 135), period_text,
                fontsize=period_size, fontname=FONT_NAME, color=(0.79, 0.86, 0.94),
            )
            y = 181
        else:
            page.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, 49), color=PALE_GRAY, fill=PALE_GRAY)
            short_name, short_size, _ = _fit_single_line(
                company_name, CONTENT_WIDTH - 165, 10, 8
            )
            page.insert_text(
                (LEFT_MARGIN, 30), short_name,
                fontsize=short_size, fontname=FONT_NAME, color=NAVY,
            )
            page.insert_text(
                (PAGE_WIDTH - RIGHT_MARGIN - 150, 30), "재무제표 요약 보고서",
                fontsize=8.5, fontname=FONT_NAME, color=MUTED,
            )
            y = 69

    def add_page() -> None:
        nonlocal page
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_font(fontname=FONT_NAME, fontfile=str(FONT_FILE))
        draw_page_header()

    def ensure_room(height: float) -> None:
        if y + height > CONTENT_BOTTOM:
            add_page()

    def draw_section_heading(title: str, color: tuple[float, float, float] = BLUE) -> None:
        nonlocal y
        ensure_room(85)  # Keep the heading with the first line of its content.
        page.draw_rect(
            fitz.Rect(LEFT_MARGIN, y, LEFT_MARGIN + 4, y + 21),
            color=color,
            fill=color,
        )
        page.insert_text(
            (LEFT_MARGIN + 13, y + 16), title,
            fontsize=12.5, fontname=FONT_NAME, color=NAVY,
        )
        y += 30

    def draw_paragraph(
        text: str,
        *,
        font_size: float = 10.5,
        color: tuple[float, float, float] = TEXT,
        background: tuple[float, float, float] | None = None,
        accent: tuple[float, float, float] | None = None,
        line_height: float | None = None,
    ) -> None:
        nonlocal y
        content = text.strip() or "대화에서 확인된 내용이 없습니다."
        leading = line_height or font_size * 1.65
        text_width = CONTENT_WIDTH - 34 if background else CONTENT_WIDTH
        lines = _wrap_paragraph(content, text_width, font_size)
        line_index = 0

        while line_index < len(lines):
            padding = 12 if background else 0
            available = int((CONTENT_BOTTOM - y - padding * 2) // leading)
            if available < 1:
                add_page()
                available = int((CONTENT_BOTTOM - y - padding * 2) // leading)
            batch = lines[line_index:line_index + available]
            box_height = len(batch) * leading + padding * 2
            if background:
                page.draw_rect(
                    fitz.Rect(LEFT_MARGIN, y, PAGE_WIDTH - RIGHT_MARGIN, y + box_height),
                    color=background,
                    fill=background,
                    radius=0.02,
                )
                if accent:
                    page.draw_rect(
                        fitz.Rect(LEFT_MARGIN, y + 7, LEFT_MARGIN + 3, y + box_height - 7),
                        color=accent,
                        fill=accent,
                    )
            text_x = LEFT_MARGIN + (22 if background else 0)
            text_y = y + padding + font_size
            for line in batch:
                if line:
                    page.insert_text(
                        (text_x, text_y), line,
                        fontsize=font_size, fontname=FONT_NAME, color=color,
                    )
                text_y += leading
            y += box_height + (9 if background else 5)
            line_index += len(batch)
            if line_index < len(lines):
                add_page()

    def draw_metric_cards(rows: Iterable[tuple[str, str, str]]) -> None:
        nonlocal y
        metrics = list(rows)
        card_gap = 12
        card_width = (CONTENT_WIDTH - card_gap) / 2
        for index in range(0, len(metrics), 2):
            card_data = []
            for metric in metrics[index:index + 2]:
                label, value, comparison = metric
                label_lines = _wrap_paragraph(label, card_width - 24, 9)
                value_lines = _wrap_paragraph(value, card_width - 24, 11.5)
                comparison_lines = _wrap_paragraph(comparison, card_width - 24, 7.5) if comparison else []
                content_height = (
                    12 + len(label_lines) * 12 + 6 + len(value_lines) * 15
                    + (4 + len(comparison_lines) * 10 if comparison_lines else 0) + 12
                )
                card_data.append((label_lines, value_lines, comparison_lines, max(78, content_height)))
            card_height = max(item[3] for item in card_data)
            if card_height + 10 > CONTENT_BOTTOM - 69:
                for label, value, comparison in metrics[index:index + 2]:
                    detail = f"{label}: {value}"
                    if comparison:
                        detail += f"\n{comparison}"
                    draw_paragraph(detail, background=PALE_GRAY)
                continue
            ensure_room(card_height + 10)

            for column, (label_lines, value_lines, comparison_lines, _) in enumerate(card_data):
                x = LEFT_MARGIN + column * (card_width + card_gap)
                rect = fitz.Rect(x, y, x + card_width, y + card_height)
                page.draw_rect(rect, color=BORDER, fill=PALE_GRAY, radius=0.08, width=0.7)
                text_y = y + 21
                for line in label_lines:
                    page.insert_text(
                        (x + 12, text_y), line,
                        fontsize=9, fontname=FONT_NAME, color=MUTED,
                    )
                    text_y += 12
                text_y += 6
                for line in value_lines:
                    page.insert_text(
                        (x + 12, text_y), line,
                        fontsize=11.5, fontname=FONT_NAME, color=NAVY,
                    )
                    text_y += 15
                if comparison_lines:
                    text_y += 4
                    for line in comparison_lines:
                        page.insert_text(
                            (x + 12, text_y), line,
                            fontsize=7.5, fontname=FONT_NAME, color=MUTED,
                        )
                        text_y += 10
            y += card_height + 10

    draw_page_header(first_page=True)
    if title_shortened:
        draw_paragraph(f"대상 기업: {company_name}")
    if period_shortened:
        draw_paragraph(f"보고서 기준: {period_value}")

    draw_section_heading("핵심 요약")
    draw_paragraph(
        executive_summary,
        font_size=10.5,
        background=PALE_BLUE,
        accent=BLUE,
    )

    draw_section_heading("한눈에 보는 주요 지표")
    metric_rows = _parse_metric_rows(key_metrics)
    if metric_rows:
        draw_metric_cards(metric_rows)
    else:
        draw_paragraph(key_metrics)

    draw_section_heading("재무제표 분석")
    draw_paragraph(financial_analysis)

    draw_section_heading("해석 시 유의사항", color=AMBER)
    draw_paragraph(
        caveats,
        font_size=9.5,
        color=(0.35, 0.28, 0.18),
        background=PALE_AMBER,
        accent=AMBER,
        line_height=15,
    )

    draw_section_heading("자료 출처", color=MUTED)
    draw_paragraph(sources, font_size=9, color=MUTED, line_height=14)

    for page_number, report_page in enumerate(document, start=1):
        report_page.draw_line(
            (LEFT_MARGIN, PAGE_HEIGHT - 39),
            (PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 39),
            color=BORDER,
            width=0.7,
        )
        report_page.insert_text(
            (LEFT_MARGIN, PAGE_HEIGHT - 23),
            f"작성일 {datetime.now().astimezone().strftime('%Y-%m-%d')}  ·  OpenDART 자료 기반",
            fontsize=7.5,
            fontname=FONT_NAME,
            color=MUTED,
        )
        report_page.insert_text(
            (PAGE_WIDTH - RIGHT_MARGIN - 48, PAGE_HEIGHT - 23),
            f"{page_number} / {len(document)}",
            fontsize=8,
            fontname=FONT_NAME,
            color=MUTED,
        )

    document.set_metadata(
        {
            "title": f"{company_name} 재무제표 요약 보고서",
            "author": "OpenDART 재무 요약 챗봇",
            "subject": report_period,
        }
    )
    document.save(output_path, garbage=4, deflate=True)
    document.close()

    return {
        "report_id": report_id,
        "filename": filename,
        "download_token": f"PDF_READY:{report_id}:{filename}",
    }
