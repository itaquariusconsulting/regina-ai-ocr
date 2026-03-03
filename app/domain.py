from dataclasses import dataclass, asdict

@dataclass
class ScannedDocument:
    documentType: str
    documentNumber: str
    documentDate: str
    issuerRuc: str
    issuerAddress: str
    amount: float
    imageBase64: str
    rawText: str

    def to_dict(self):
        return asdict(self)

    def is_valid(self) -> bool:
        """Basic validation logic to ensure the document is worth sending."""
        # Example: Don't send documents with 0 amount or empty RUC
        return self.amount > 0 and len(self.issuerRuc) == 11