from pydantic import BaseModel, ConfigDict, field_serializer

class ChainAmounts(dict):
    @property
    def json(self):
        return {"converted": "string"}

class TestModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    balances: ChainAmounts

    @field_serializer('balances')
    def serialize_balances(self, balances: ChainAmounts):
        return balances.json

m = TestModel(balances=ChainAmounts({"a": 1}))
print(m.model_dump())
