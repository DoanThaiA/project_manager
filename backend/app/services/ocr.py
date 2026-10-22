"""Đọc danh thiếp bằng OCR.space (https://ocr.space/ocrapi) rồi tách họ tên, chức vụ, email, điện thoại."""

import re

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
_URL = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|vn|net|org|io)\b", re.IGNORECASE)
# Nhãn đầu dòng: "Tel:", "Mobile -", "ĐT:", "Họ tên:" ...
_LABEL = re.compile(
    r"^\s*(tel|tell|phone|mobile|mob|hotline|cell|đt|đtdđ|dđ|điện thoại|di động|sđt|e-?mail|name|họ tên|họ và tên)"
    r"\s*[:.\-]?\s*",
    re.IGNORECASE,
)
_VN_MOBILE = re.compile(r"^(0|84)(3|5|7|8|9)\d{8}$")

_POSITION_WORDS = (
    "giám đốc", "phó", "trưởng", "chủ tịch", "tổng", "quản lý", "kế toán", "nhân viên", "chuyên viên", "thư ký",
    "trợ lý", "kỹ sư", "tư vấn", "điều phối", "sáng lập", "đại diện",
    "ceo", "cto", "cfo", "coo", "cmo", "founder", "director", "manager", "president", "chairman", "head", "lead",
    "officer", "executive", "engineer", "developer", "consultant", "specialist", "assistant", "accountant",
    "sales", "marketing", "representative", "partner", "supervisor", "coordinator", "secretary",
)  # fmt: skip
_COMPANY_WORDS = (
    "công ty", "cty", "tnhh", "cổ phần", "tập đoàn", "chi nhánh", "văn phòng",
    "co.", "ltd", "jsc", "corp", "inc", "llc", "group", "company", "holdings", "joint stock",
)  # fmt: skip
_ADDRESS_WORDS = (
    "đường", "phường", "quận", "huyện", "tỉnh", "thành phố", "tp.", "tầng", "số nhà", "tòa", "ngõ", "ngách",
    "street", "district", "ward", "city", "floor", "road", "address", "địa chỉ", "việt nam", "vietnam",
)  # fmt: skip


async def read_text(data: bytes, file_name: str, content_type: str) -> str:
    """Gửi ảnh lên OCR.space, trả về toàn bộ chữ đọc được (mỗi dòng một dòng)."""
    if not settings.ocr_space_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Chưa cấu hình OCR (OCR_SPACE_API_KEY)"
        )
    form = {
        "language": "auto",
        "OCREngine": str(settings.ocr_space_engine),
        "scale": "true",
        "detectOrientation": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                settings.ocr_space_url,
                headers={"apikey": settings.ocr_space_api_key},
                data=form,
                files={"file": (file_name, data, content_type)},
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="OCR.space phản hồi quá lâu") from exc
    try:
        body = resp.json()
    except ValueError:
        body = None
    if resp.is_error or not isinstance(body, dict) or body.get("IsErroredOnProcessing"):
        errors = body.get("ErrorMessage") if isinstance(body, dict) else None
        detail = "; ".join(errors) if isinstance(errors, list) else str(errors or resp.text[:200])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OCR.space lỗi: {detail}")
    return "\n".join(r.get("ParsedText", "") for r in body.get("ParsedResults") or []).strip()


def _has(line: str, words: tuple[str, ...]) -> bool:
    low = line.lower()
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low) for w in words)


def _looks_like_name(line: str) -> bool:
    words = line.split()
    return (
        2 <= len(words) <= 6
        and len(line) <= 60
        and all(w.replace(".", "").replace("-", "").isalpha() for w in words)
        and not _has(line, _POSITION_WORDS + _COMPANY_WORDS + _ADDRESS_WORDS)
    )


def _pick_phone(lines: list[str]) -> str | None:
    found: list[str] = []
    for line in lines:
        if "fax" in line.lower():
            continue
        for m in _PHONE.finditer(_LABEL.sub("", line)):
            digits = re.sub(r"\D", "", m.group())
            if 9 <= len(digits) <= 13:
                found.append(m.group().strip(" .-"))
    mobile = next((p for p in found if _VN_MOBILE.match(re.sub(r"\D", "", p))), None)
    phone = mobile or (found[0] if found else None)
    return phone[:30] if phone else None


def parse_card(text: str) -> dict[str, str | None]:
    """Đoán các trường người liên hệ từ chữ OCR của danh thiếp. Chỉ là gợi ý, người dùng sửa lại trước khi lưu."""
    lines = [re.sub(r"\s+", " ", ln).strip(" |•·,;") for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    email = next((m.group().lower() for ln in lines if (m := _EMAIL.search(ln))), None)
    phone = _pick_phone(lines)
    company = next((ln for ln in lines if _has(ln, _COMPANY_WORDS)), None)

    # Dòng chữ thuần (không email, số, web) mới có thể là họ tên / chức vụ
    plain = [
        i
        for i, ln in enumerate(lines)
        if not _EMAIL.search(ln) and not _URL.search(ln) and not re.search(r"\d{3}", ln) and ln != company
    ]
    position_idx = next((i for i in plain if _has(lines[i], _POSITION_WORDS) and len(lines[i]) <= 100), None)
    names = [i for i in plain if _looks_like_name(_LABEL.sub("", lines[i]))]
    # Họ tên thường nằm ngay trên/dưới chức vụ
    name_idx = None
    if position_idx is not None:
        name_idx = next((i for i in names if abs(i - position_idx) == 1), None)
    if name_idx is None and names:
        name_idx = names[0]

    full_name = _LABEL.sub("", lines[name_idx]) if name_idx is not None else None
    if full_name and full_name.isupper():
        full_name = full_name.title()
    return {
        "full_name": full_name[:150] if full_name else None,
        "position": lines[position_idx][:100] if position_idx is not None else None,
        "email": email,
        "phone": phone,
        "company": company,
    }
