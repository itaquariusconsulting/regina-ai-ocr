from dataclasses import dataclass, asdict, field
from typing import Optional


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
    documentDate: str
    issuerRuc: str
    issuerAddress: str
    amount: float
    imageBase64: str
    rawText: str

    def to_dict(self):
        return asdict(self)

    def is_valid(self) -> bool:
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
