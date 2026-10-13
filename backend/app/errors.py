class BusinessError(Exception):
    """Safe errors shared by HTTP and tools; never include raw database exceptions."""

    def __init__(self, code: str, status: int, *, data: dict | None = None, retryable=False):
        super().__init__(code)
        self.code = code
        self.status = status
        self.data = data or {}
        self.retryable = retryable
