from dataclasses import dataclass, asdict
from typing import Dict, List


@dataclass
class ScannedDocument:
    """
    Documento reconocido. Los campos son los que consume la vista y los que
    espera el backend; los datos que agrega el extractor nuevo (tasa de IGV,
    subtotal, trazabilidad de la lectura) viajan aparte en la respuesta HTTP
    para no alterar este contrato.
    """

    documentType: str
    documentNumber: str
    documentCurrency: str
    documentDate: str

    # Lista de RUC detectados en el documento, con el del EMISOR primero.
    # El orden importa: la vista hace `this.ruc = issuerRuc[0]`.
    issuerRuc: List[str]

    issuerName: str
    issuerAddress: str
    amount: float

    # items solo contiene el detalle (lineas de descripcion)
    items: List[Dict]

    imageBase64: str
    rawText: str
    igv: float

    def to_dict(self):
        return asdict(self)

    def is_valid(self) -> bool:
        """
        Indica si vale la pena guardar el documento y enviarlo al backend.

        Mismo criterio de siempre —importe, RUC y detalle—, pero a prueba de
        campos vacios: antes cualquier None hacia reventar la comparacion en
        vez de devolver False.

        Ojo: NO condiciona lo que ve el usuario. La vista trabaja con
        `detectedData`, que se devuelve siempre, asi que un documento sin
        items igual llena el formulario.
        """
        try:
            monto_ok = self.amount is not None and float(self.amount) > 0
        except (TypeError, ValueError):
            monto_ok = False

        rucs = self.issuerRuc if isinstance(self.issuerRuc, list) else []
        rucs_ok = len(rucs) > 0 and all(
            isinstance(r, str) and len(r) == 11 and r.isdigit() for r in rucs
        )

        items_ok = isinstance(self.items, list) and len(self.items) > 0

        return monto_ok and rucs_ok and items_ok
