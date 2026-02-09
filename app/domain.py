from dataclasses import dataclass, asdict
from typing import List, Dict


@dataclass
class ScannedDocument:
    documentType: str
    documentNumber: str
    documentCurrency: str
    documentDate: str

    # Lista de RUC detectados en el documento
    issuerRuc: List[str]

    issuerName: str
    issuerAddress: str
    amount: float

    # items solo contiene el detalle (líneas de descripción)
    items: List[Dict]

    imageBase64: str

    def to_dict(self):
        return asdict(self)

    def is_valid(self) -> bool:
        return (
            self.amount is not None
            and self.amount > 0
            and isinstance(self.issuerRuc, list)
            and len(self.issuerRuc) > 0
            and all(
                isinstance(r, str) and len(r) == 11 and r.isdigit()
                for r in self.issuerRuc
            )
            and isinstance(self.items, list)
            and len(self.items) > 0
        )
