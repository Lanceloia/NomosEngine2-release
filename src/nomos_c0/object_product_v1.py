"""One required causal Object product under the existing native owner contract."""

from dataclasses import dataclass

from nomos_kernel._dynamic_owner_abi import _K0FormOwnerRequest

from .author_contract_v1 import C0LawError


@dataclass(frozen=True)
class C0ObjectProductIR:
    family: str
    state_type: type
    initial_output: str

    def check(self, outputs):
        if (
            type(self.family) is not str
            or not self.family
            or not isinstance(self.state_type, type)
            or type(self.initial_output) is not str
            or not self.initial_output
            or outputs.get(self.initial_output) is not self.state_type
        ):
            raise C0LawError("Object product differs from its required nominal output")

    def products(self, outputs):
        return (_K0FormOwnerRequest(self.family, outputs[self.initial_output]),)


def object_products(product, outputs):
    return () if product is None else product.products(outputs)


def bind_object_product(raw, kinds):
    if (
        type(raw) is not dict
        or set(raw) != {"kind", "initial_output"}
        or type(raw["kind"]) is not str
        or raw["kind"] not in kinds
        or type(raw["initial_output"]) is not str
        or not raw["initial_output"]
    ):
        raise C0LawError("Object product must bind one selected kind and required initial output")
    kind = kinds[raw["kind"]]
    product = C0ObjectProductIR(kind.symbol, kind.k0_kind.state_type, raw["initial_output"])
    product.check({product.initial_output: kind.k0_kind.state_type})
    return product
