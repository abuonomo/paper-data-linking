def read_pdf_bytes(file_field):
    """Read PDF bytes from a FileField, works for both local and S3 storage."""
    file_field.open('rb')
    try:
        return file_field.read()
    finally:
        file_field.close()
