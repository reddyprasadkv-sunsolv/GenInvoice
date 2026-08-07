import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.core.exceptions import ValidationError


MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024
MIN_LOGO_WIDTH = 300
MIN_LOGO_HEIGHT = 150
MIN_SIGNATURE_WIDTH = 300
MIN_SIGNATURE_HEIGHT = 100
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
GSTIN_PATTERN = re.compile(r"^[0-9A-Z]{15}$")
GSTIN_VALIDATION_ERROR_MESSAGE = (
    "Enter a valid 15-character GSTIN using only letters and numbers.\n"
    "Example: 36AADC07549J1ZZ"
)
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
IFSC_VALIDATION_ERROR_MESSAGE = "Enter a valid IFSC code. Example: SBIN0001234"
SVG_EVENT_PATTERN = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
SVG_FORBIDDEN_PATTERNS = (
    "<script",
    "javascript:",
    "<foreignobject",
    "<iframe",
    "<object",
    "<embed",
)


def validate_gstin_value(value):
    value = normalize_gstin_value(value)
    if not value:
        return
    if not GSTIN_PATTERN.match(value):
        raise ValidationError(GSTIN_VALIDATION_ERROR_MESSAGE)


def normalize_gstin_value(value):
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value)).upper()


def validate_ifsc_value(value):
    value = normalize_ifsc_value(value)
    if not value:
        return
    if not IFSC_PATTERN.match(value):
        raise ValidationError(IFSC_VALIDATION_ERROR_MESSAGE)


def normalize_ifsc_value(value):
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value)).upper()


def validate_logo_file(file_obj):
    _validate_local_image_file(
        file_obj,
        max_size_bytes=MAX_LOGO_SIZE_BYTES,
        min_width=MIN_LOGO_WIDTH,
        min_height=MIN_LOGO_HEIGHT,
        min_size_message="Logo must be at least 300px wide and 150px high.",
        invalid_extension_message="Logo must be a PNG, JPG, JPEG, or SVG file.",
    )


def validate_signature_file(file_obj):
    _validate_local_image_file(
        file_obj,
        max_size_bytes=MAX_LOGO_SIZE_BYTES,
        min_width=MIN_SIGNATURE_WIDTH,
        min_height=MIN_SIGNATURE_HEIGHT,
        min_size_message="Signature must be at least 300px wide and 100px high.",
        invalid_extension_message="Signature must be a PNG, JPG, JPEG, or SVG file.",
    )


def _validate_local_image_file(file_obj, max_size_bytes, min_width, min_height, min_size_message, invalid_extension_message):
    if not file_obj:
        return

    if file_obj.size > max_size_bytes:
        raise ValidationError("File size must not exceed 2 MB.")

    extension = Path(file_obj.name).suffix.lower()
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        raise ValidationError(invalid_extension_message)

    data = _read_uploaded_file(file_obj)
    if extension == ".png":
        dimensions = _png_dimensions(data)
    elif extension in {".jpg", ".jpeg"}:
        dimensions = _jpeg_dimensions(data)
    else:
        dimensions = _svg_dimensions(data)

    width, height = dimensions
    if width < min_width or height < min_height:
        raise ValidationError(min_size_message)


def _read_uploaded_file(file_obj):
    current_position = file_obj.tell() if hasattr(file_obj, "tell") else None
    data = file_obj.read()
    if hasattr(file_obj, "seek"):
        file_obj.seek(current_position or 0)
    return data


def _png_dimensions(data):
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ValidationError("Upload a valid PNG logo file.")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _jpeg_dimensions(data):
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise ValidationError("Upload a valid JPG or JPEG logo file.")

    index = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }

    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break

        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break

        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break

        if marker in sof_markers:
            segment_start = index + 2
            if segment_start + 5 > len(data):
                break
            height = int.from_bytes(data[segment_start + 1 : segment_start + 3], "big")
            width = int.from_bytes(data[segment_start + 3 : segment_start + 5], "big")
            return width, height

        index += segment_length

    raise ValidationError("Upload a valid JPG or JPEG logo file.")


def _svg_dimensions(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Upload a valid SVG logo file.") from exc

    lowered = text.lower()
    if not lowered.lstrip().startswith("<svg") and "<svg" not in lowered[:300]:
        raise ValidationError("Upload a valid SVG logo file.")
    if SVG_EVENT_PATTERN.search(text) or any(pattern in lowered for pattern in SVG_FORBIDDEN_PATTERNS):
        raise ValidationError("SVG logo contains unsupported active content.")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValidationError("Upload a valid SVG logo file.") from exc

    if not root.tag.lower().endswith("svg"):
        raise ValidationError("Upload a valid SVG logo file.")

    width = _parse_svg_length(root.attrib.get("width"))
    height = _parse_svg_length(root.attrib.get("height"))
    if width and height:
        return width, height

    view_box = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if view_box:
        parts = re.split(r"[\s,]+", view_box.strip())
        if len(parts) == 4:
            try:
                return float(parts[2]), float(parts[3])
            except ValueError as exc:
                raise ValidationError("SVG logo must include valid dimensions.") from exc

    raise ValidationError("SVG logo must include width and height or a viewBox.")


def _parse_svg_length(value):
    if not value:
        return None
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        return None
    return float(match.group(1))
