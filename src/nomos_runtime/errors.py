"""Admission, control and settlement failures shared by current runtime components."""


class AdmissionError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ControlRejection(AdmissionError):
    """A false root completion or invalid destination, before any publication."""


class SettlementDefect(Exception):
    pass


class EffectBudgetExceeded(SettlementDefect):
    code = "EffectBudget"

    def __init__(self, path):
        self.path = path
        super().__init__(f"EffectBudget: {path}: finite effect expansion exceeds its node budget")


class FormationBudgetExceeded(SettlementDefect):
    code = "FormationBudget"

    def __init__(self):
        self.path = "form"
        super().__init__("FormationBudget: form: products exceed their finite expansion budget")
