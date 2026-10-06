"""Image parsing, streaming validation, format detection, and full decoding."""
import hashlib
import io
import re
import tempfile
from dataclasses import dataclass
from typing import Optional, Set
from fastapi import HTTPException, Request, status
import multipart
from python_multipart.multipart import parse_options_header
from PIL import Image

MAX_FILE_BYTES: int = 10_485_760        # Exact 10 MiB
MAX_TRANSPORT_BYTES: int = 11_534_336   # 11 MiB transport limit
MAX_DECODED_PIXELS: int = 24_000_000    # 24 Megapixels

ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}

HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")


@dataclass
class ValidatedImage:
    data: bytes
    size_bytes: int
    sha256: str
    content_type: str
    extension: str
    width: int
    height: int


def _is_heic_or_heif(header: bytes) -> bool:
    if len(header) >= 12 and header[4:8] == b"ftyp":
        prefix = header[:32].lower()
        return any(brand in prefix for brand in HEIC_BRANDS)
    return False


def _detect_preliminary_magic(header: bytes) -> Optional[str]:
    """Check magic bytes to detect format before Pillow, preventing unsupported types."""
    if _is_heic_or_heif(header):
        return "HEIC"
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return "WEBP"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "GIF"
    if header.startswith(b"BM"):
        return "BMP"
    if header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        return "TIFF"
    return "UNKNOWN"


def validate_image_bytes(data: bytes) -> ValidatedImage:
    """Validate image bytes in memory against size, magic bytes, Pillow verify and load."""
    size_bytes = len(data)
    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_IMAGE", "message": "El archivo de imagen está vacío."},
        )
    if size_bytes > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,

            detail={"code": "IMAGE_TOO_LARGE", "message": "La imagen supera los 10 MiB permitidos."},
        )

    magic = _detect_preliminary_magic(data[:32])
    if magic in ("HEIC", "GIF", "BMP", "TIFF", "UNKNOWN"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "UNSUPPORTED_MEDIA_TYPE", "message": "Formato de imagen no admitido."},
        )

    # Configure Pillow decompression bomb limit
    import warnings
    warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
    Image.MAX_IMAGE_PIXELS = MAX_DECODED_PIXELS

    # First pass: Pillow verify
    stream1 = io.BytesIO(data)
    try:
        with Image.open(stream1) as img1:
            img1.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "IMAGE_TOO_LARGE", "message": "La imagen supera los límites de descompresión permitidos."},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_IMAGE", "message": "Imagen corrupta o no decodificable."},
        )

    # Second pass: Pillow load and dimension check
    stream2 = io.BytesIO(data)
    try:
        with Image.open(stream2) as img2:
            fmt = (img2.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail={"code": "UNSUPPORTED_MEDIA_TYPE", "message": f"Formato {fmt} no admitido."},
                )

            # Multiframe / animation check
            is_animated = bool(getattr(img2, "is_animated", False))
            n_frames = int(getattr(img2, "n_frames", 1))
            if is_animated or n_frames > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_IMAGE", "message": "Imágenes animadas o multifotograma no están permitidas."},
                )

            width, height = img2.size
            if width * height > MAX_DECODED_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail={"code": "IMAGE_TOO_LARGE", "message": "La imagen supera los 24 megapíxeles permitidos."},
                )

            # Complete pixel decode
            img2.load()

            content_type, ext = ALLOWED_FORMATS[fmt]
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "IMAGE_TOO_LARGE", "message": "La imagen supera los límites de descompresión permitidos."},
        )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_IMAGE", "message": "Error al decodificar píxeles de la imagen."},
        )

    sha256 = hashlib.sha256(data).hexdigest()
    return ValidatedImage(
        data=data,
        size_bytes=size_bytes,
        sha256=sha256,
        content_type=content_type,
        extension=ext,
        width=width,
        height=height,
    )


class _MultipartReceiver:
    def __init__(self):
        self.parts_count = 0
        self.finished = False
        self.is_file = False
        self.has_image_part = False
        self.current_field_name: Optional[str] = None
        self.spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        self.file_bytes = 0
        self.header_field = b""
        self.header_value = b""

    def on_part_begin(self):
        self.parts_count += 1
        if self.parts_count > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Solo se permite una parte multipart (image)."},
            )
        self.current_field_name = None
        self.header_field = b""
        self.header_value = b""

    def on_header_field(self, data: bytes, start: int, end: int):
        self.header_field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int):
        self.header_value += data[start:end]

    def on_header_end(self):
        field_str = self.header_field.decode("latin1", errors="ignore").lower()
        val_str = self.header_value.decode("latin1", errors="ignore")
        if field_str == "content-disposition":
            disposition, options = parse_options_header(val_str)
            self.current_field_name = options.get(b"name", b"").decode("latin1")
            self.is_file = disposition == b"form-data" and b"filename" in options
        self.header_field = b""
        self.header_value = b""

    def on_headers_finished(self):
        if self.current_field_name != "image" or not self.is_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Campo multipart no permitido o diferente de 'image'."},
            )
        self.has_image_part = True

    def on_part_data(self, data: bytes, start: int, end: int):
        chunk = data[start:end]
        self.file_bytes += len(chunk)
        if self.file_bytes > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"code": "IMAGE_TOO_LARGE", "message": "La imagen supera los 10 MiB permitidos."},
            )

        self.spool.write(chunk)

    def on_part_end(self):
        pass

    def on_end(self):
        self.finished = True
        if not self.has_image_part or self.parts_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Campo 'image' obligatorio en multipart."},
            )

    def close(self):
        self.spool.close()


async def parse_multipart_image(request: Request) -> ValidatedImage:
    """Stream-parse request body, enforce single 'image' field, 10 MiB limit, and validate."""
    content_type_header = request.headers.get("content-type", "")
    if not content_type_header.startswith("multipart/form-data"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Content-Type debe ser multipart/form-data."},
        )

    # Check for boundary
    match = re.search(r'boundary=([^;]+)', content_type_header)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Falta el parámetro boundary en multipart/form-data."},
        )
    boundary = match.group(1).strip('"\'').encode("ascii")

    # Content-Length transport check if present
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            cl_val = int(content_length)
            if cl_val > MAX_TRANSPORT_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail={"code": "IMAGE_TOO_LARGE", "message": "El cuerpo de la solicitud supera el límite de transporte de 11 MiB."},
                )
        except ValueError:
            pass

    receiver = _MultipartReceiver()
    callbacks = {
        "on_part_begin": receiver.on_part_begin,
        "on_header_field": receiver.on_header_field,
        "on_header_value": receiver.on_header_value,
        "on_header_end": receiver.on_header_end,
        "on_headers_finished": receiver.on_headers_finished,
        "on_part_data": receiver.on_part_data,
        "on_part_end": receiver.on_part_end,
        "on_end": receiver.on_end,
    }

    try:
        parser = multipart.MultipartParser(boundary, callbacks)
        total_transport_bytes = 0

        async for chunk in request.stream():
            total_transport_bytes += len(chunk)
            if total_transport_bytes > MAX_TRANSPORT_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail={"code": "IMAGE_TOO_LARGE", "message": "El cuerpo de la solicitud supera el límite de transporte de 11 MiB."},
                )
            parser.write(chunk)

        parser.finalize()
        if not receiver.finished or not receiver.has_image_part:
            raise HTTPException(400, detail={"code": "INVALID_REQUEST", "message": "Multipart incompleto."})

        receiver.spool.seek(0)
        data = receiver.spool.read()
    except HTTPException:
        raise
    except multipart.MultipartError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": f"Error al procesar multipart: {exc}"},
        )
    finally:
        receiver.close()

    return validate_image_bytes(data)
