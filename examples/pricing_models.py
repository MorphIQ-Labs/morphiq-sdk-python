"""Inspect public model capabilities with one unauthenticated request."""

from morphiq_sdk import MorphIQ


def main() -> None:
    with MorphIQ() as client:
        response = client.pricing_models()
    for model in response.models:
        print(model.id, model.operations, model.batch_operations)
        print("Constraints:", [item.model_dump(exclude_unset=True) for item in model.constraints])
    print("Engines:", [item.model_dump() for item in response.engines])
    print("Greek units:", response.greek_units)


if __name__ == "__main__":
    main()
