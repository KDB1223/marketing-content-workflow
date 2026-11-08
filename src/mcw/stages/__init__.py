"""Pipeline stages. Each stage has its own module and a JSON artifact."""

from mcw.stages.confirm import confirm
from mcw.stages.extract import extract
from mcw.stages.generate import generate_drafts
from mcw.stages.risk_check import risk_check

__all__ = ["confirm", "extract", "generate_drafts", "risk_check"]
