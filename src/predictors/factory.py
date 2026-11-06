from __future__ import annotations

from src.predictors.sequence import (
    KerasSequencePredictorAdapter,
)

from src.predictors.tabular import (
    TabularSklearnPredictorAdapter,
)

from src.registry.contracts import (
    ModelArtifactSpec,
)


def create_predictor(
    spec: ModelArtifactSpec,
    **kwargs,
):
    spec.validate()

    if (
        spec.inference_type
        == "TABULAR_28"
    ):
        return (
            TabularSklearnPredictorAdapter(
                spec,
                **kwargs,
            )
        )

    if (
        spec.inference_type
        == "SEQUENCE_3X12"
    ):
        return (
            KerasSequencePredictorAdapter(
                spec,
                **kwargs,
            )
        )

    raise ValueError(
        "Unsupported inference_type: "
        f"{spec.inference_type}"
    )