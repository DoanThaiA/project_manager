"""Đọc danh thiếp bằng OCR.space (https://ocr.space/ocrapi) rồi tách thông tin người liên hệ / khách hàng."""

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
_WEBSITE = re.compile(r"(https?://|www\.)[^\s,;]+", re.IGNORECASE)
_TAX_CODE = re.compile(
    r"(?:mst|mã số thuế|mã số dn|mã số doanh nghiệp|msdn|tax code|tax id|vat)\s*[:.\-]?\s*"
    r"(\d[\d\s]{8,}\d(?:\s*-\s*\d{3})?)",
    re.IGNORECASE,
)
_ADDRESS_LABEL = re.compile(
    r"^\s*(địa chỉ|đ/c|đc|address|addr|add|trụ sở( chính)?|văn phòng|vp|office|head office)\s*[:.\-]\s*",
    re.IGNORECASE,
)

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
    # "tp." phải khớp cả "TP.HCM" nên chỉ chặn chữ dính sau khi từ khoá kết thúc bằng chữ cái
    return any(re.search(rf"(?<!\w){re.escape(w)}{'(?!\\w)' if w[-1].isalnum() else ''}", low) for w in words)


def _looks_like_name(line: str) -> bool:
    words = line.split()
    return (
        2 <= len(words) <= 6
        and len(line) <= 60
        and all(w.replace(".", "").replace("-", "").isalpha() for w in words)
        and not _has(line, _POSITION_WORDS + _COMPANY_WORDS + _ADDRESS_WORDS)
    )


def _lines(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", ln).strip(" |•·,;") for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def _pick_email(lines: list[str]) -> str | None:
    return next((m.group().lower() for ln in lines if (m := _EMAIL.search(ln))), None)


def _pick_phone(lines: list[str], prefer_mobile: bool = True) -> str | None:
    found: list[str] = []
    for line in lines:
        if "fax" in line.lower() or _TAX_CODE.search(line):
            continue
        for m in _PHONE.finditer(_LABEL.sub("", line)):
            digits = re.sub(r"\D", "", m.group())
            if 9 <= len(digits) <= 13 or re.fullmatch(r"1[89]00\d{4}", digits):  # tổng đài 1900 / 1800
                found.append(m.group().strip(" .-"))
    mobile = next((p for p in found if _VN_MOBILE.match(re.sub(r"\D", "", p))), None)
    phone = (mobile if prefer_mobile else None) or (found[0] if found else None)
    return phone[:30] if phone else None


def parse_card(text: str) -> dict[str, str | None]:
    """Đoán các trường người liên hệ từ chữ OCR của danh thiếp. Chỉ là gợi ý, người dùng sửa lại trước khi lưu."""
    lines = _lines(text)
    email = _pick_email(lines)
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


def _pick_website(lines: list[str]) -> str | None:
    for ln in lines:
        if m := _WEBSITE.search(ln):
            return m.group().rstrip(".")[:255]
    # Tên miền trần ("abc.com.vn"), bỏ qua dòng email
    return next((m.group() for ln in lines if "@" not in ln and (m := _URL.search(ln))), None)


def _pick_address(lines: list[str], skip: set[str]) -> str | None:
    labelled = [_ADDRESS_LABEL.sub("", ln) for ln in lines if _ADDRESS_LABEL.match(ln)]
    guessed = [
        ln
        for ln in lines
        if ln not in skip and len(ln) > 10 and _has(ln, _ADDRESS_WORDS) and not _EMAIL.search(ln)
        and not _WEBSITE.search(ln) and not _PHONE.search(_LABEL.sub("", ln))
    ]  # fmt: skip
    address = next((a for a in labelled if a), None) or (guessed[0] if guessed else None)
    return address.strip(" ,") if address else None


def parse_company(text: str) -> dict[str, str | None]:
    """Đoán thông tin khách hàng (doanh nghiệp) từ chữ OCR của danh thiếp / giấy tờ công ty. Chỉ là gợi ý."""
    lines = _lines(text)
    tax = next((m for ln in lines if (m := _TAX_CODE.search(ln))), None)
    tax_code = re.sub(r"\s", "", tax.group(1))[:30] if tax else None
    companies = [ln for ln in lines if _has(ln, _COMPANY_WORDS) and not _TAX_CODE.search(ln)]
    # Tên công ty thường không kèm số (dòng có số hay là địa chỉ chi nhánh / văn phòng)
    name = next((ln for ln in companies if not re.search(r"\d", ln)), companies[0] if companies else None)
    return {
        "name": name[:255] if name else None,
        "tax_code": tax_code,
        "email": _pick_email(lines),
        "phone": _pick_phone(lines, prefer_mobile=False),
        "address": _pick_address(lines, skip={name} if name else set()),
        "website": _pick_website(lines),
    }
