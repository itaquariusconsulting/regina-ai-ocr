<<<<<<< HEAD
from dataclasses import dataclass, asdict, field
from typing import Optional
=======
from dataclasses import dataclass, asdict
from typing import List, Dict
>>>>>>> origin/dev


@dataclass
class ScannedDocument:
    """
    Documento reconocido. Los campos son los historicos: lo que consume la
    vista y lo que espera el backend. Los datos adicionales que ahora produce
    el extractor (razon social, IGV, moneda, confianza) viajan aparte en la
    respuesta HTTP, para no alterar este contrato.
    """
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
    rawText: str
<<<<<<< HEAD
=======
    igv: float
>>>>>>> origin/dev

    def to_dict(self):
        return asdict(self)

    def is_valid(self) -> bool:
<<<<<<< HEAD
        """
        Vale la pena enviarlo si tiene importe y un RUC de emisor de 11
        digitos. Antes reventaba con None (len(None)): ahora un documento del
        que no se pudo leer el RUC devuelve False, que es lo correcto — la
        vista pide el dato en vez de arrastrar un vacio hasta SUNAT.
        """
        try:
            monto_ok = float(self.amount or 0) > 0
        except (TypeError, ValueError):
            monto_ok = False

        ruc = (self.issuerRuc or "").strip()
        return monto_ok and len(ruc) == 11 and ruc.isdigit()
=======
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
>>>>>>> origin/dev
