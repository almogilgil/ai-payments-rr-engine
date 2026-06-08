from dataclasses import dataclass, field
from typing import Optional
from pydantic import BaseModel


class MerchantInput(BaseModel):
    guesty_id: str
    guesty_name: str
    guestypay: str = "N/A"
    region: str = ""
    bank: str = ""
    segment: str = ""
    avg_mrr: str = ""
    active_listings: str = ""
    requested_change: str = ""


class StatementFile(BaseModel):
    filename: str
    mime: str
    bytes_b64: str


class AssessRequest(BaseModel):
    ticket_id: str = ""
    test_mode: bool = False
    merchant: MerchantInput
    statements: list[StatementFile]
    flat_amount: Optional[float] = None


class MonthResult(BaseModel):
    label: str
    sales: float
    refunds: float
    chargebacks: float
    refund_pct: float
    chb_rate: float


class ExposureResult(BaseModel):
    field_10pct: int = 0
    field_5pct: int = 0
    flat: int = 0
    waiver_incl: int = 0
    waiver_no_chb: int = 0

    def as_dict(self):
        return {
            "10%": self.field_10pct,
            "5%": self.field_5pct,
            "Flat": self.flat,
            "Waiver_incl": self.waiver_incl,
            "Waiver_noCHB": self.waiver_no_chb,
        }


class ConfidenceEntry(BaseModel):
    field: str
    month: str
    score: float


class ExtractionMeta(BaseModel):
    source_type: str
    needs_review: bool
    confidence: list[ConfidenceEntry] = field(default_factory=list)


class AssessResponse(BaseModel):
    months: list[MonthResult]
    volume_90d: float
    highest_chb_rate: float
    highest_refund_rate: float
    flat_amount: float
    exposure: dict
    ticket_markdown: str
    qa_table_markdown: str
    filled_workbook_b64: str
    extraction: dict
