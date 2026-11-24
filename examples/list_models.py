"""Inspect public model capabilities with one unauthenticated request (models.list)."""

from morphiq_sdk import MorphIQ


def main() -> None:
    with MorphIQ() as client:
        response = client.models.list()
    for model in response.models:
        # Operations are canonical ids such as options.price and options.batch_greeks.
        print(model.id, model.model_version, model.operations)
        print("Constraints:", [item.model_dump(exclude_unset=True) for item in model.constraints])
        for validity in model.validity:
            print(f"  {validity.quantity}: {validity.status}", validity.criterion or "")
    print("Engines:", [item.model_dump() for item in response.engines])
    print("Greek units:", response.greek_units)
    print("Validity symbols:", response.validity_symbols)


if __name__ == "__main__":
    main()
