import pytest

from tempor.plugins import plugin_loader
from tempor.plugins.prediction.one_off.classification import BaseOneOffClassifier
from tempor.plugins.prediction.one_off.classification.plugin_laplace_classifier import (
    LaplaceODEClassifier as plugin,
)
from tempor.utils.serialization import load, save

train_kwargs = {"random_state": 123, "n_iter": 5}

TEST_ON_DATASETS = ["google_stocks_data_small"]


def from_api() -> BaseOneOffClassifier:
    return plugin_loader.get("prediction.one_off.classification.laplace_ode_classifier", **train_kwargs)


def from_module() -> BaseOneOffClassifier:
    return plugin(**train_kwargs)


@pytest.mark.parametrize("test_plugin", [from_api(), from_module()])
def test_sanity(test_plugin: BaseOneOffClassifier) -> None:
    assert test_plugin is not None
    assert test_plugin.name == "laplace_ode_classifier"
    assert test_plugin.fqn() == "prediction.one_off.classification.laplace_ode_classifier"
    assert len(test_plugin.hyperparameter_space()) == 7


@pytest.mark.parametrize(
    "test_plugin",
    [
        from_api(),
        pytest.param(from_module(), marks=pytest.mark.extra),
    ],
)
@pytest.mark.parametrize("data", TEST_ON_DATASETS)
def test_fit(test_plugin: BaseOneOffClassifier, data: str, request: pytest.FixtureRequest) -> None:
    dataset = request.getfixturevalue(data)
    test_plugin.fit(dataset)


@pytest.mark.parametrize(
    "test_plugin",
    [
        from_api(),
        pytest.param(from_module(), marks=pytest.mark.extra),
    ],
)
@pytest.mark.parametrize("data", TEST_ON_DATASETS)
@pytest.mark.parametrize(
    "no_targets",
    [
        False,
        pytest.param(True, marks=pytest.mark.extra),
    ],
)
def test_predict(
    test_plugin: BaseOneOffClassifier, no_targets: bool, data: str, request: pytest.FixtureRequest
) -> None:
    dataset = request.getfixturevalue(data)
    test_plugin.fit(dataset)
    if no_targets:
        dataset.predictive.targets = None
    output = test_plugin.predict(dataset)
    assert output.numpy().shape == (len(dataset.time_series), 1)


@pytest.mark.filterwarnings("ignore:RNN.*contiguous.*:UserWarning")  # Expected: problem with current serialization.
@pytest.mark.parametrize("data", TEST_ON_DATASETS)
def test_serde(data: str, request: pytest.FixtureRequest) -> None:
    test_plugin = from_api()

    dataset = request.getfixturevalue(data)

    dump = save(test_plugin)
    reloaded1 = load(dump)

    reloaded1.fit(dataset)

    dump = save(reloaded1)
    reloaded2 = load(dump)

    reloaded2.predict(dataset)