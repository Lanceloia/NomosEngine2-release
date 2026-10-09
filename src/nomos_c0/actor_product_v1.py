"""One checked Actor product slot shared by every transition formation kind."""

from dataclasses import dataclass

from nomos_kernel._dynamic_actor_abi import _K0ActorProductSlot, _K0FormActorProduct

from .author_contract_v1 import C0LawError


@dataclass(frozen=True)
class C0ActorProductIR:
    family: str
    state_type: type
    initial_output: str
    required: bool

    def check(self, outputs):
        expected = self.state_type if self.required else self.state_type | None
        if (
            type(self.family) is not str
            or not self.family
            or not isinstance(self.state_type, type)
            or type(self.initial_output) is not str
            or not self.initial_output
            or type(self.required) is not bool
            or outputs.get(self.initial_output) != expected
        ):
            raise C0LawError("Actor product differs from its declared nominal output/cardinality")

    def products(self, outputs):
        return (_K0FormActorProduct(self.family, outputs[self.initial_output]),)

    def port(self):
        return _K0ActorProductSlot(self.family, self.required)


def product_outputs(product):
    return set() if product is None else {product.initial_output}


def actor_products(product, outputs):
    return () if product is None else product.products(outputs)


def bind_actor_product(raw, kinds):
    if (
        type(raw) is not dict
        or set(raw) != {"kind", "cardinality", "initial_output"}
        or type(raw["kind"]) is not str
        or raw["kind"] not in kinds
        or raw["cardinality"] not in ("one", "zero_or_one")
    ):
        raise C0LawError("Actor product must bind one selected kind and explicit cardinality")
    kind = kinds[raw["kind"]]
    return C0ActorProductIR(
        kind.symbol, kind.factory.state_type, raw["initial_output"], raw["cardinality"] == "one"
    )
